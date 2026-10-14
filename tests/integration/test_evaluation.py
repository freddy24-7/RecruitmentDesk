"""The evaluation code itself, checked with fakes (CLAUDE.md, Testing).

A fake that answers from the ground truth must score perfectly. A fake that
answers badly on purpose must be caught: if the evaluation reports good
numbers for a bad model, the numbers mean nothing.
"""

import json

from fastapi import FastAPI

from app.evaluation.run import (
    SCENARIOS,
    VacancyResult,
    _jaccard,
    _quality,
    evaluate,
    interview_quality,
    to_markdown,
)
from app.llm.base import TIMEOUT, LlmError, LlmRequest
from app.llm.fake import FakeLlm, fake_assessment, fake_vacancy
from scripts.evaluate_lists import expected_calls


async def run(
    app: FastAPI, vacancies: int = 1, candidates: int = 10
) -> list[VacancyResult]:
    report = await evaluate(
        app, "fake", vacancies=vacancies, candidates=candidates, repeats=2, name_swaps=1
    )
    assert "Evaluation report (fake)" in to_markdown(report)
    json.loads(report.to_json())
    return report.results


async def test_a_fake_that_answers_from_the_ground_truth_scores_perfectly(
    app: FastAPI, llm: FakeLlm
) -> None:
    results = await run(app, vacancies=2)

    assert [r.scenario["title"] for r in results] == [s["title"] for s in SCENARIOS[:2]]
    for result in results:
        assert not result.errors
        assert result.combined.short_precision == 1.0
        assert result.combined.long_recall == 1.0
        assert result.unflagged_hard_misses == 0
        assert result.claims_made > 0
        assert result.claims_supported == result.claims_made
        assert result.short_overlap == [1.0]
        assert result.long_overlap == [1.0]
        assert result.name_swap
        for swap in result.name_swap:
            assert swap["input_identical"]
            assert not swap["names_in_input"]
            assert swap["difference"] == 0
        assert result.interview is not None
        assert result.interview.sets == 1 + result.short_size
        assert result.interview.questions > 0
        assert result.interview.dropped == 0
        assert result.interview.flagged == 0
        assert result.interview.reference_codes == 0
    # The run makes as many model calls as the script announces before
    # asking for confirmation.
    assert len(llm.requests) == expected_calls(2, 10, 2, 1)


async def test_a_model_that_ranks_badly_and_invents_claims_is_caught(
    app: FastAPI, llm: FakeLlm
) -> None:
    def bad_assessment(request: LlmRequest) -> str:
        answer = json.loads(fake_assessment(request))
        # The best candidates get the lowest scores, and every answer claims
        # a keyword that no CV contains.
        answer["fit_score"] = 100 - answer["fit_score"]
        answer["found"].append({"keyword": "Invented Skill", "years": 5})
        return json.dumps(answer)

    llm.responders["assessment"] = bad_assessment

    # With 20 candidates more people meet the hard requirements than fit on
    # the long list, so the scores decide the order. (With 10, only the
    # strong matches meet them, and the hard requirements alone keep them
    # on top, whatever the model says.)
    [result] = await run(app, candidates=20)

    assert result.model_only.short_precision < 1.0
    assert result.claims_supported < result.claims_made
    # The facts computed by code are unaffected by the model.
    assert result.facts_only.short_precision == 1.0
    # Hard requirements are applied by code, whatever the model says.
    assert result.unflagged_hard_misses == 0


def test_list_quality_against_the_planted_matches() -> None:
    truth = {"a": "strong", "b": "strong", "c": "partial", "d": "weak"}

    good = _quality(["a", "b", "c"], truth, short_size=2)
    bad = _quality(["c", "a", "d"], truth, short_size=2)

    assert (good.short_precision, good.long_recall) == (1.0, 1.0)
    assert (bad.short_precision, bad.long_recall) == (0.5, 0.5)
    assert bad.short == ["partial", "strong"]


def test_overlap_of_repeated_lists() -> None:
    assert _jaccard({"a", "b"}, {"a", "b"}) == 1.0
    assert _jaccard({"a", "b"}, {"c", "d"}) == 0.0
    assert _jaccard({"a", "b"}, {"b", "c"}) == 0.333
    assert _jaccard(set(), set()) == 1.0


def test_expected_calls_for_the_full_run() -> None:
    # Per vacancy: vacancy, profile, 20 CVs, script, 3 runs of 12
    # assessments, 2 name swaps of 2 calls, and interview questions for a
    # short list of 2 (one core set, two follow-up sets).
    assert expected_calls(4, 20, 3, 2) == 4 * (1 + 1 + 20 + 1 + 36 + 4 + 3)
    # 5 candidates give a long list of 2, so 4 are assessed per run, and a
    # short list of 1.
    assert expected_calls(1, 5, 1, 0) == 1 + 1 + 5 + 1 + 4 + 2


async def test_interview_questions_that_break_the_rules_are_counted(
    app: FastAPI, llm: FakeLlm
) -> None:
    def bad_questions(request: LlmRequest) -> str:
        return json.dumps(
            {
                "questions": [
                    {
                        "question": "How old are you?",
                        "purpose": "Checks S1.",
                        "source": "S1",
                    },
                    {
                        "question": "Tell me about X.",
                        "purpose": "Probes X.",
                        "source": "Z9",
                    },
                ]
            }
        )

    llm.responders["interview"] = bad_questions

    [result] = await run(app)

    assert result.interview is not None
    assert result.interview.dropped >= 1
    assert result.interview.flagged >= 1
    assert result.interview.reference_codes >= 1


def test_interview_quality_counts_per_question() -> None:
    def question(
        text: str, purpose: str = "", flags: list[str] | None = None
    ) -> dict[str, object]:
        return {"question": text, "purpose": purpose, "flags": flags or []}

    body = {
        "core": {
            "questions": [question("Describe a deployment."), question("As in P2?")],
            "dropped": [{"kind": "source_not_found", "detail": "S9"}],
        },
        "follow_ups": [
            {
                "questions": [question("Do you have children?", flags=["children"])],
                "dropped": [],
            }
        ],
    }

    quality = interview_quality(body)

    assert (quality.sets, quality.questions, quality.dropped) == (2, 3, 1)
    assert (quality.flagged, quality.reference_codes) == (1, 1)
    assert interview_quality({"core": None, "follow_ups": []}).sets == 0


async def test_a_failed_name_swap_call_is_reported_and_the_run_goes_on(
    app: FastAPI, llm: FakeLlm
) -> None:
    llm.responders["evaluation_name_swap"] = timing_out

    [result] = await run(app)

    assert result.name_swap
    assert all(swap["error"] == "llm_timeout" for swap in result.name_swap)
    assert all(swap["difference"] is None for swap in result.name_swap)
    # Whether the input was identical is computed by code, without the model.
    assert all(swap["input_identical"] for swap in result.name_swap)
    assert result.interview is not None


async def test_a_scenario_that_fails_is_reported_and_the_others_still_run(
    app: FastAPI, llm: FakeLlm
) -> None:
    def vacancy_for_one_scenario(request: LlmRequest) -> str:
        if "Financial Controller" in json.dumps(request.variables):
            return "not json"
        return fake_vacancy(request)

    llm.responders["vacancy"] = vacancy_for_one_scenario

    report = await evaluate(
        app, "fake", vacancies=2, candidates=10, repeats=1, name_swaps=0
    )

    assert [r.scenario["title"] for r in report.results] == ["Cloud Engineer"]
    assert [f["scenario"] for f in report.failed] == ["Financial Controller"]
    assert "Not completed:" in to_markdown(report)


def timing_out(request: LlmRequest) -> str:
    raise LlmError(TIMEOUT)
