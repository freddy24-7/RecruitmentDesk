"""A stand-in for the model, behind the same interface.

Used by every test, so the pipeline runs in seconds without the network, and
in development with LLM_PROVIDER=fake, so the UI can be built without cost.
"""

import asyncio
import json
from collections.abc import Callable

from app.llm.base import NOT_CONFIGURED, LlmError, LlmRequest, LlmResponse

Responder = Callable[[LlmRequest], str]

FAKE_NOTE = "[Fake model output]"


def fake_vacancy(request: LlmRequest) -> str:
    v = request.variables
    title = v.get("title", "Example role")
    company = v.get("company") or "Northwind Example BV"
    return json.dumps(
        {
            "title": title,
            "company_intro": (
                f"{FAKE_NOTE} {company} is a fictional organisation in the "
                f"{v.get('sector', 'example')} sector."
            ),
            "role_summary": (
                f"As {title} ({v.get('seniority', 'medior')}) you work on "
                "example projects together with a small team."
            ),
            "responsibilities": [
                "Deliver the example work that belongs to this role",
                "Work together with colleagues and stakeholders",
                "Improve the way the team works",
            ],
            "required_qualifications": [
                "3 years of experience in a comparable role",
                "Experience with Microsoft Azure",
                "Good written and spoken English",
            ],
            "nice_to_haves": ["Experience in a regulated sector"],
            "what_we_offer": [
                "A competitive salary",
                "Room to learn and to grow",
            ],
            "location_and_work_mode": (
                f"Utrecht, the Netherlands. Work mode: {v.get('work_mode', 'hybrid')}."
            ),
        }
    )


def fake_vacancy_profile(request: LlmRequest) -> str:
    """Skills that match the text of `fake_vacancy`, and some other jobs."""
    return json.dumps(
        {
            "required_skills": [
                # One requirement with alternatives: any one of them meets it.
                {"any_of": ["Microsoft Azure", "AWS"], "min_years": 3},
                {"any_of": ["Terraform"], "min_years": 2},
                {"any_of": ["Kubernetes"], "min_years": 0},
                {"any_of": ["CI/CD"], "min_years": 0},
            ],
            "nice_skills": ["Scrum", "Python"],
            "adjacent_roles": [
                {
                    "title": "Data Engineer",
                    "skills": ["Apache Spark", "Airflow", "dbt"],
                },
                {"title": "Software Developer", "skills": ["Java", "Spring Boot"]},
                {"title": "Network Engineer", "skills": ["Cisco", "BGP", "Firewalls"]},
            ],
            "unrelated_roles": [
                {"title": "Marketing Specialist", "skills": ["SEO", "Copywriting"]},
                {
                    "title": "Financial Controller",
                    "skills": ["IFRS", "SAP", "Budgeting"],
                },
                {"title": "Store Manager", "skills": ["Retail", "Staff planning"]},
            ],
        }
    )


def fake_cv(request: LlmRequest) -> str:
    """CV prose for the jobs in the blueprint, naming each job's own skills."""
    jobs = json.loads(request.variables["positions_json"])
    return json.dumps(
        {
            "profile": (
                f"{FAKE_NOTE} Professional with "
                f"{request.variables['years_experience']} years of experience."
            ),
            "positions": [
                {
                    "title": f"{job['seniority'].capitalize()} {job['role']}",
                    "company": f"Example Company {number} BV",
                    "highlights": [
                        "Worked on projects using " + ", ".join(job["skills"]) + "."
                        if job["skills"]
                        else "Supported the team in daily operations.",
                        "Delivered results together with colleagues.",
                    ],
                }
                for number, job in enumerate(jobs, start=1)
            ],
            "education": [
                {
                    "degree": request.variables["education_level"]
                    + " of Example Studies",
                    "institution": "Example University of Applied Sciences",
                }
            ],
        }
    )


def fake_script(request: LlmRequest) -> str:
    """Screening criteria that match `fake_vacancy` and `fake_vacancy_profile`."""
    return json.dumps(
        {
            "items": [
                {
                    "any_of": ["Microsoft Azure", "AWS"],
                    "min_years": 3,
                    "hard": True,
                    "reason": "Experience with Microsoft Azure",
                },
                {
                    "any_of": ["Terraform"],
                    "min_years": 2,
                    "hard": True,
                    "reason": "3 years of experience in a comparable role",
                },
                {
                    "any_of": ["Kubernetes"],
                    "min_years": 0,
                    "hard": False,
                    "reason": "Experience in a regulated sector",
                },
                {
                    "any_of": ["Scrum"],
                    "min_years": 0,
                    "hard": False,
                    # Not in the vacancy: the check in code will say so.
                    "reason": "Agile ways of working are a plus",
                },
            ]
        }
    )


def fake_assessment(request: LlmRequest) -> str:
    """An assessment that agrees with the facts code computed.

    The fake is handed those facts in a variable that is not part of the
    prompt. A real model has to read the CV for itself.
    """
    facts = json.loads(request.variables["fake_facts_json"])
    found = [fact for fact in facts["keywords"] if fact["found"]]
    missing = [fact["keyword"] for fact in facts["keywords"] if not fact["found"]]
    return json.dumps(
        {
            "fit_score": int(request.variables["fake_score"]),
            "found": [
                {"keyword": fact["keyword"], "years": fact["years"]} for fact in found
            ],
            "strengths": [
                {
                    "text": "Has hands-on experience with tools the vacancy asks for.",
                    "keywords": [fact["keyword"] for fact in found],
                }
            ]
            if found
            else [{"text": "Has steady work experience.", "keywords": []}],
            "concerns": [
                {
                    "text": "Some of the screening keywords are not in the CV.",
                    "keywords": missing,
                }
            ]
            if missing
            else [],
            "reasoning": (
                f"{FAKE_NOTE} The past roles are relevant to the vacancy. "
                "The career shows steady progression."
            ),
        }
    )


DEFAULT_RESPONDERS: dict[str, Responder] = {
    "vacancy": fake_vacancy,
    "vacancy_profile": fake_vacancy_profile,
    "cv": fake_cv,
    "script": fake_script,
    "assessment": fake_assessment,
}


class FakeLlm:
    """Answers from `responders`, per call type, and remembers every request.

    A responder may be replaced by a list of raw answers, returned in order,
    or by an exception to raise.
    """

    def __init__(self, delay_seconds: float = 0.0) -> None:
        self.responders: dict[str, Responder] = dict(DEFAULT_RESPONDERS)
        self.scripted: dict[str, list[str | Exception]] = {}
        self.requests: list[LlmRequest] = []
        self.delay_seconds = delay_seconds
        # Tests set this to hold a call open until they release it.
        self.gate: asyncio.Event | None = None

    def script(self, call_type: str, *answers: str | Exception) -> None:
        self.scripted.setdefault(call_type, []).extend(answers)

    async def complete(self, request: LlmRequest) -> LlmResponse:
        self.requests.append(request)
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.gate is not None:
            await self.gate.wait()

        queued = self.scripted.get(request.call_type)
        if queued:
            answer = queued.pop(0)
            if isinstance(answer, Exception):
                raise answer
            text = answer
        else:
            text = self.responders[request.call_type](request)

        return LlmResponse(
            text=text,
            input_tokens=(len(request.system) + len(request.user)) // 4,
            output_tokens=len(text) // 4,
        )


class UnconfiguredLlm:
    """Used when no API key is set: every call fails with a clear error kind."""

    async def complete(self, request: LlmRequest) -> LlmResponse:
        raise LlmError(NOT_CONFIGURED)
