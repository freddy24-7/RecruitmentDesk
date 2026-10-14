"""The evaluation: how good are the lists, measured against the planted truth (PRD 10).

Because every candidate is built from a blueprint with a known match
category, the quality of the lists can be measured. This module runs whole
vacancies through the application (the same code paths as a user), then
measures. It is used by `scripts/evaluate_lists.py`, which writes a report.

Nothing here may change the ground truth to improve a score.
"""

import json
import statistics
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.codes import hash_code
from app.access.models import AccessCode
from app.candidates.models import Candidate
from app.candidates.schemas import Cv
from app.config import get_settings
from app.db import get_sessionmaker
from app.jobs.runner import JobRunner
from app.llm.prompts import load_prompt
from app.llm.service import LlmService
from app.llm.usage import UsageRecord
from app.screening import service as screening
from app.screening.blind import blind_text
from app.screening.models import Assessment
from app.screening.ranking import Scored, build_lists
from app.screening.schemas import ModelAssessment
from app.screening.sizes import list_sizes
from app.script.models import SelectionScript
from app.script.schemas import ScriptItem
from app.vacancy.guardrails import find_flags
from app.vacancy.models import Vacancy
from app.vacancy.schemas import VacancySections

# An obviously fake code, for the evaluation's own database only.
EVAL_CODE = "EVALQ"

# The vacancies the evaluation runs, in this order. Different sectors on
# purpose: the earlier real runs were all cloud engineers.
SCENARIOS: list[dict[str, Any]] = [
    {
        "sector": "IT and software",
        "title": "Cloud Engineer",
        "seniority": ["senior"],
        "work_mode": ["hybrid"],
    },
    {
        "sector": "Finance",
        "title": "Financial Controller",
        "seniority": ["medior"],
        "work_mode": ["office-based"],
    },
    {
        "sector": "Healthcare",
        "title": "District Nurse",
        "seniority": ["medior"],
        "work_mode": ["office-based"],
    },
    {
        "sector": "Logistics",
        "title": "Supply Chain Planner",
        "seniority": ["senior"],
        "work_mode": ["hybrid"],
    },
]

STRONG = "strong"


@dataclass
class ListQuality:
    short_precision: float  # share of the short list that are planted strong matches
    long_recall: float  # share of the planted strong matches that reached the long list
    short: list[str] = field(default_factory=list)  # categories, in order
    long: list[str] = field(default_factory=list)


@dataclass
class VacancyResult:
    scenario: dict[str, Any]
    candidates: int
    categories: dict[str, int]
    long_size: int
    short_size: int
    combined: ListQuality
    facts_only: ListQuality
    model_only: ListQuality
    # Listed with a missed hard requirement and no flag. Must be 0.
    unflagged_hard_misses: int
    # Listed with a flag for a missed hard requirement (allowed, but telling).
    flagged_entries: int
    claims_made: int
    claims_supported: int
    # Overlap of the lists over repeated runs on the same input (Jaccard).
    long_overlap: list[float]
    short_overlap: list[float]
    name_swap: list[dict[str, Any]]
    vacancy_rubric: dict[str, bool]
    script_items: list[str]
    errors: list[str] = field(default_factory=list)


def _quality(ordered: list[str], truth: dict[str, str], short_size: int) -> ListQuality:
    short = ordered[:short_size]
    strong_total = sum(1 for category in truth.values() if category == STRONG)
    return ListQuality(
        short_precision=_share(sum(truth[c] == STRONG for c in short), len(short)),
        long_recall=_share(sum(truth[c] == STRONG for c in ordered), strong_total),
        short=[truth[c] for c in short],
        long=[truth[c] for c in ordered],
    )


def _share(part: int, whole: int) -> float:
    return round(part / whole, 3) if whole else 0.0


def _jaccard(first: set[str], second: set[str]) -> float:
    union = first | second
    return round(len(first & second) / len(union), 3) if union else 1.0


def vacancy_rubric(
    sections: VacancySections, scenario: dict[str, Any]
) -> dict[str, bool]:
    """A simple rubric for the generated vacancy, checked in code (PRD 10)."""
    text = json.dumps(sections.model_dump()).lower()
    return {
        "all_sections_filled": all(
            bool(getattr(sections, name))
            for name in (
                "title",
                "company_intro",
                "role_summary",
                "responsibilities",
                "required_qualifications",
                "what_we_offer",
                "location_and_work_mode",
            )
        ),
        "no_flagged_wording": not find_flags(sections),
        "title_matches": all(
            word.lower() in sections.title.lower() for word in scenario["title"].split()
        ),
        "work_mode_mentioned": any(
            mode.split("-")[0] in sections.location_and_work_mode.lower()
            for mode in scenario["work_mode"]
        ),
        "seniority_mentioned": any(level in text for level in scenario["seniority"]),
    }


class Evaluation:
    """Runs scenarios through the app, in process, as one signed-in visitor."""

    def __init__(self, app: FastAPI, client: httpx.AsyncClient) -> None:
        self.app = app
        self.client = client
        self.runner: JobRunner = app.state.job_runner
        self.llm: LlmService = app.state.llm

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        response = await self.client.post(path, json=body)
        if response.status_code >= 400:
            raise RuntimeError(f"{path}: {response.status_code} {response.text[:200]}")
        await self.runner.wait_idle()
        result: dict[str, Any] = response.json() if response.content else {}
        return result

    async def _get(self, path: str) -> dict[str, Any]:
        response = await self.client.get(path)
        if response.status_code >= 400:
            raise RuntimeError(f"{path}: {response.status_code} {response.text[:200]}")
        body: dict[str, Any] = response.json()
        return body

    async def run_scenario(
        self, scenario: dict[str, Any], candidates: int, repeats: int, name_swaps: int
    ) -> VacancyResult:
        started = await self._post("/api/vacancies", scenario)
        vacancy_id = started["vacancy_id"]
        vacancy = await self._get(f"/api/vacancies/{vacancy_id}")
        if vacancy["status"] != "draft":
            raise RuntimeError(
                f"vacancy generation failed: {vacancy['job']['error_kind']}"
            )
        await self._post(f"/api/vacancies/{vacancy_id}/submit", {})
        await self._post(
            f"/api/vacancies/{vacancy_id}/candidates", {"count": candidates}
        )
        state = await self._get(f"/api/vacancies/{vacancy_id}")
        errors = []
        if state["candidate_job"]["status"] != "done":
            # Some CVs may fail; the evaluation goes on with those that exist.
            errors.append(f"candidates: {state['candidate_job']['error_kind']}")
        # The script as the model proposed it, unedited: this measures the
        # automatic pipeline, without a recruiter's corrections.
        await self._post(f"/api/vacancies/{vacancy_id}/script/proposal", {})
        proposal = (await self._get(f"/api/vacancies/{vacancy_id}/script"))["proposal"]
        await self.client.put(
            f"/api/vacancies/{vacancy_id}/script", json={"items": proposal["items"]}
        )

        runs: list[list[Assessment]] = []
        for repeat in range(repeats):
            await self._post(
                f"/api/vacancies/{vacancy_id}/screening", {"replace": repeat > 0}
            )
            runs.append(await self._assessments(uuid.UUID(vacancy_id)))

        async with get_sessionmaker()() as session:
            people = (
                await session.scalars(
                    select(Candidate).where(
                        Candidate.vacancy_id == uuid.UUID(vacancy_id)
                    )
                )
            ).all()
            script = await session.scalar(
                select(SelectionScript).where(
                    SelectionScript.vacancy_id == uuid.UUID(vacancy_id)
                )
            )
        truth = {str(p.id): p.blueprint["match_category"] for p in people if p.cv}
        sizes = list_sizes(len(truth))
        first = runs[0]

        def ordered(rows: list[Assessment], weight: float, everyone: bool) -> list[str]:
            scored = [
                Scored(
                    candidate=str(row.candidate_id),
                    deterministic_score=row.deterministic_score,
                    llm_score=row.llm_score if not everyone else (row.llm_score or 0),
                    meets_hard=row.meets_hard,
                    listable=row.listable,
                    missed_hard=sum(
                        1 for f in row.flags if f["kind"] == screening.MISSED_HARD
                    ),
                )
                for row in rows
            ]
            return build_lists(scored, sizes, weight).long

        combined = sorted(
            (r for r in first if r.in_long_list), key=lambda r: r.list_position or 0
        )
        listed = [str(r.candidate_id) for r in combined]
        sets = [{str(r.candidate_id) for r in run if r.in_long_list} for run in runs]
        shorts = [{str(r.candidate_id) for r in run if r.in_short_list} for run in runs]
        assessed = [r for r in first if r.llm_score is not None]
        sections = VacancySections.model_validate(vacancy["sections"])
        items = [ScriptItem.model_validate(i) for i in (script.items if script else [])]

        return VacancyResult(
            scenario=scenario,
            candidates=len(truth),
            categories=dict(
                sorted(
                    {
                        c: list(truth.values()).count(c) for c in set(truth.values())
                    }.items()
                )
            ),
            long_size=sizes.long,
            short_size=sizes.short,
            combined=_quality(listed, truth, sizes.short),
            facts_only=_quality(ordered(first, 1.0, everyone=True), truth, sizes.short),
            model_only=_quality(
                ordered(first, 0.0, everyone=False), truth, sizes.short
            ),
            unflagged_hard_misses=sum(
                1
                for r in combined
                if not r.meets_hard
                and not any(f["kind"] == screening.MISSED_HARD for f in r.flags)
            ),
            flagged_entries=sum(1 for r in combined if not r.meets_hard),
            claims_made=sum(r.claims_made for r in assessed),
            claims_supported=sum(r.claims_supported for r in assessed),
            long_overlap=[_jaccard(sets[0], other) for other in sets[1:]],
            short_overlap=[_jaccard(shorts[0], other) for other in shorts[1:]],
            name_swap=await self._name_swaps(
                uuid.UUID(vacancy_id), combined[:name_swaps], items
            ),
            vacancy_rubric=vacancy_rubric(sections, scenario),
            script_items=[
                f"{i.kind.value}: {' | '.join(i.any_of)} ({i.min_years}y)"
                for i in items
            ],
            errors=errors,
        )

    async def _assessments(self, vacancy_id: uuid.UUID) -> list[Assessment]:
        async with get_sessionmaker()() as session:
            run = await screening.latest_run(session, vacancy_id)
            if run is None:
                return []
            return list(
                (
                    await session.scalars(
                        select(Assessment)
                        .where(Assessment.run_id == run.job_id)
                        .order_by(Assessment.deterministic_rank)
                    )
                ).all()
            )

    async def _name_swaps(
        self, vacancy_id: uuid.UUID, rows: list[Assessment], items: list[ScriptItem]
    ) -> list[dict[str, Any]]:
        """The same CV under two different names must get the same assessment.

        The name is written into the CV on purpose, as a real CV would have it.
        Blind screening should remove it, so the model's input is identical;
        any difference left is the model's own variation at temperature 0.
        """
        results = []
        settings = get_settings()
        async with get_sessionmaker()() as session:
            vacancy = await session.get(Vacancy, vacancy_id)
            if vacancy is None:
                raise RuntimeError("the vacancy disappeared during the evaluation")
            screener = screening.Screener(self.llm, settings, get_sessionmaker())
            variables = screener.vacancy_variables(vacancy, items)
            for row in rows:
                person = await session.get(Candidate, row.candidate_id)
                if person is None:
                    continue
                cv = Cv.model_validate(person.cv)
                texts = []
                scores = []
                for name in (person.name, "Jordan Vermeulen"):
                    named = cv.model_copy(update={"profile": f"{name}. {cv.profile}"})
                    text = blind_text(
                        named, name=name, email=person.email, phone=person.phone
                    )
                    texts.append(text)
                    answer: ModelAssessment = await self.llm.generate(
                        call_type="evaluation_name_swap",
                        model=settings.mistral_model_assessment,
                        prompt=load_prompt(screening.PROMPT),
                        variables=variables
                        | {
                            "cv_text": text,
                            "fake_facts_json": json.dumps(row.evidence),
                            "fake_score": str(round(row.deterministic_score * 100)),
                        },
                        schema=ModelAssessment,
                        temperature=screening.TEMPERATURE,
                        max_tokens=screening.MAX_TOKENS,
                        workspace_id=None,
                        job_id=None,
                    )
                    scores.append(answer.fit_score)
                results.append(
                    {
                        "input_identical": texts[0] == texts[1],
                        "names_in_input": any(
                            part in t
                            for t in texts
                            for part in (person.name, "Vermeulen")
                        ),
                        "scores": scores,
                        "difference": abs(scores[0] - scores[1]),
                    }
                )
        return results


@dataclass
class Report:
    services: str
    started_at: str
    models: dict[str, str]
    prompts: dict[str, str]
    seed: int
    results: list[VacancyResult]
    cost: dict[str, dict[str, float]]

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=1, default=str)


async def usage_summary(
    session: AsyncSession, since: datetime
) -> dict[str, dict[str, float]]:
    rows = (
        await session.scalars(
            select(UsageRecord).where(UsageRecord.created_at >= since)
        )
    ).all()
    summary: dict[str, dict[str, float]] = {}
    for row in rows:
        entry = summary.setdefault(
            row.call_type, {"calls": 0, "invalid": 0, "cost": 0.0, "latencies": 0.0}
        )
        entry["calls"] += 1
        entry["invalid"] += row.outcome != "ok"
        entry["cost"] += float(row.estimated_cost)
        entry["latencies"] += row.latency_ms
    for entry in summary.values():
        entry["avg_latency_ms"] = round(entry.pop("latencies") / entry["calls"])
        entry["cost"] = round(entry["cost"], 5)
    return summary


async def evaluate(
    app: FastAPI,
    services: str,
    vacancies: int,
    candidates: int,
    repeats: int,
    name_swaps: int,
) -> Report:
    """Run the scenarios and measure. The caller decides which database is used."""
    settings = get_settings()
    started = datetime.now(UTC)
    async with get_sessionmaker()() as session:
        if not await session.scalar(
            select(AccessCode).where(AccessCode.label == "eval")
        ):
            session.add(
                AccessCode(
                    label="eval",
                    code_hash=hash_code(
                        EVAL_CODE, settings.access_code_pepper.get_secret_value()
                    ),
                    max_uses=1_000_000,
                    created_at=started,
                )
            )
            await session.commit()
    transport = httpx.ASGITransport(app=app)
    results = []
    async with httpx.AsyncClient(
        transport=transport, base_url="https://eval", timeout=600
    ) as client:
        evaluation = Evaluation(app, client)
        for scenario in SCENARIOS[:vacancies]:
            # One workspace per vacancy, as a visitor would have: the
            # per-workspace limits apply unchanged.
            client.cookies.clear()
            signed = await client.post("/api/session", json={"code": EVAL_CODE})
            if signed.status_code != 200:
                raise RuntimeError("the evaluation could not start a session")
            results.append(
                await evaluation.run_scenario(scenario, candidates, repeats, name_swaps)
            )
    async with get_sessionmaker()() as session:
        cost = await usage_summary(session, started)
    return Report(
        services=services,
        started_at=started.isoformat(timespec="seconds"),
        models={
            "vacancy": settings.mistral_model_vacancy,
            "profile": settings.mistral_model_profile,
            "cv": settings.mistral_model_cv,
            "script": settings.mistral_model_script,
            "assessment": settings.mistral_model_assessment,
        },
        prompts={
            "assessment": screening.PROMPT,
        },
        seed=settings.blueprint_seed,
        results=results,
        cost=cost,
    )


def _mean(values: list[float]) -> str:
    return f"{statistics.mean(values):.2f}" if values else "n/a"


def to_markdown(report: Report) -> str:
    """The report as text. It states plainly what ran on which service."""
    lines = [
        f"# Evaluation report ({report.services})",
        "",
        f"Started {report.started_at}. Services: **{report.services}**"
        + (
            " (fake model: this checks the evaluation code, not model quality)."
            if report.services == "fake"
            else " (real Mistral API)."
        ),
        f"Models: {', '.join(f'{k} {v}' for k, v in report.models.items())}. Blueprint seed {report.seed}.",
        "",
        "## Summary",
        "",
        "| Vacancy | Candidates | Short-list precision | Long-list recall | Unflagged hard misses | Flagged entries | Evidence accuracy | Long-list overlap | Name swap: identical input / max score difference |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in report.results:
        accuracy = _share(r.claims_supported, r.claims_made)
        swaps = r.name_swap
        lines.append(
            f"| {r.scenario['title']} ({r.scenario['sector']}) | {r.candidates} | "
            f"{r.combined.short_precision:.2f} | {r.combined.long_recall:.2f} | "
            f"{r.unflagged_hard_misses} | {r.flagged_entries} of {len(r.combined.long)} | "
            f"{accuracy:.2f} ({r.claims_supported}/{r.claims_made}) | {_mean(r.long_overlap)} | "
            f"{sum(s['input_identical'] for s in swaps)}/{len(swaps)} / "
            f"{max((s['difference'] for s in swaps), default=0)} |"
        )
    lines += [
        "",
        "## Facts only, model only, combined",
        "",
        "Short-list precision and long-list recall when the final ranking uses only the scores computed by code, only the model's fit score, or both (the setting in use).",
        "",
        "| Vacancy | Facts only | Model only | Combined |",
        "| --- | --- | --- | --- |",
    ]
    for r in report.results:
        lines.append(
            f"| {r.scenario['title']} | "
            + " | ".join(
                f"{q.short_precision:.2f} / {q.long_recall:.2f}"
                for q in (r.facts_only, r.model_only, r.combined)
            )
            + " |"
        )
    lines += ["", "## Per vacancy", ""]
    for r in report.results:
        lines += [
            f"### {r.scenario['title']} ({r.scenario['sector']})",
            "",
            f"- Planted categories: {r.categories}. List sizes: long {r.long_size}, short {r.short_size}.",
            f"- Long list (planted categories, in order): {', '.join(r.combined.long)}.",
            f"- Short list: {', '.join(r.combined.short)}.",
            f"- Short-list overlap over repeated runs: {r.short_overlap or 'n/a'}; long list: {r.long_overlap or 'n/a'}.",
            f"- Vacancy rubric: {', '.join(f'{k} {"yes" if v else "NO"}' for k, v in r.vacancy_rubric.items())}.",
            f"- Script as proposed: {'; '.join(r.script_items)}.",
        ]
        if r.errors:
            lines.append(f"- Problems during the run: {'; '.join(r.errors)}.")
        lines.append("")
    lines += [
        "## Cost and latency",
        "",
        "From the usage records of this run. Estimated cost in US dollars.",
        "",
        "| Call | Calls | Invalid answers | Estimated cost | Average latency |",
        "| --- | --- | --- | --- | --- |",
    ]
    total = Decimal(0)
    for call, entry in sorted(report.cost.items()):
        total += Decimal(str(entry["cost"]))
        lines.append(
            f"| {call} | {int(entry['calls'])} | {int(entry['invalid'])} | "
            f"${entry['cost']:.5f} | {int(entry['avg_latency_ms'])} ms |"
        )
    lines += ["", f"Total estimated cost: ${total:.4f}.", ""]
    lines += [
        "## How to read this",
        "",
        "- **Short-list precision**: the share of the short list that are planted strong matches.",
        "- **Long-list recall**: the share of the planted strong matches that reached the long list. With more strong matches than places on the long list, 1.0 is not reachable.",
        "- **Unflagged hard misses** must be 0: nobody may be listed with a missed hard requirement unless it is flagged.",
        "- **Evidence accuracy**: the share of the model's claims about keywords and years that the CV supports. The rest was removed or corrected before anyone saw it.",
        "- **Name swap**: the same CV with the candidate's name written into it, assessed under two different names. Blind screening should make the model's input identical; a score difference is then the model's own variation.",
        "- The candidates are synthetic and easier than real CVs: a CV never names a skill its owner lacks. These figures are an upper bound.",
        "",
    ]
    return "\n".join(lines)
