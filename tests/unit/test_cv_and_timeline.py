"""Years from dated jobs, and CVs assembled from a blueprint and the model's prose."""

from datetime import date
from typing import Any

import pytest
from pydantic import ValidationError

from app.candidates.cv import assemble, mentions, problems_in, render_text
from app.candidates.schemas import (
    Blueprint,
    BlueprintPosition,
    CvText,
    VacancyProfile,
)
from app.candidates.timeline import (
    add_months,
    month_index,
    total_years,
    years_per_skill,
)

AS_OF = date(2026, 10, 13)


def job(start: str, end: str | None, *skills: str) -> BlueprintPosition:
    return BlueprintPosition(
        role="Cloud Engineer",
        seniority="senior",
        start=start,
        end=end,
        skills=list(skills),
    )


# --- Timeline -----------------------------------------------------------------


def test_a_job_counts_both_its_first_and_its_last_month() -> None:
    assert total_years([job("2025-01", "2025-12")], AS_OF) == 1.0
    assert total_years([job("2026-10", None)], AS_OF) == 0.1


def test_a_current_job_runs_until_today() -> None:
    assert total_years([job("2023-11", None)], AS_OF) == 3.0


def test_overlapping_jobs_are_not_counted_twice() -> None:
    jobs = [job("2024-01", "2025-12", "Azure"), job("2025-01", "2026-06", "Azure")]

    assert total_years(jobs, AS_OF) == 2.5
    assert years_per_skill(jobs, AS_OF) == {"Azure": 2.5}


def test_a_gap_between_jobs_does_not_count() -> None:
    jobs = [job("2025-01", "2025-12"), job("2022-01", "2022-12")]

    assert total_years(jobs, AS_OF) == 2.0


def test_years_per_skill_only_count_the_jobs_that_used_it() -> None:
    jobs = [
        job("2024-01", None, "Azure", "Terraform"),
        job("2020-01", "2023-12", "Azure"),
        job("2018-01", "2019-12", "Java"),
    ]

    years = years_per_skill(jobs, AS_OF)

    assert years == {"Azure": 6.8, "Terraform": 2.8, "Java": 2.0}


def test_months_can_be_added_and_subtracted() -> None:
    assert add_months("2026-10", -10) == "2025-12"
    assert add_months("2025-12", 1) == "2026-01"
    assert month_index("2026-01") - month_index("2025-12") == 1


@pytest.mark.parametrize("month", ["2026", "2026-13", "2026-00", "26-10", "2026/10"])
def test_a_malformed_month_is_refused(month: str) -> None:
    with pytest.raises(ValueError, match="not a YYYY-MM month"):
        month_index(month)


# --- CV -------------------------------------------------------------------------

BLUEPRINT = Blueprint.model_validate(
    {
        "index": 7,
        "name": "Saar Brands",
        "email": "saar.brands7@example.com",
        "phone": "+44 7700 900007",
        "match_category": "partial",
        "seniority": "senior",
        "years_experience": 6.8,
        "positions": [
            job("2024-01", None, "Microsoft Azure", "Terraform").model_dump(),
            job("2020-01", "2023-12", "Microsoft Azure").model_dump(),
        ],
        "skill_years": {"Microsoft Azure": 6.8, "Terraform": 2.8},
        "avoid_skills": ["Kubernetes", "CI/CD"],
        "education_level": "Bachelor",
        "languages": [{"language": "Dutch", "level": "fluent"}],
    }
)


def written(**changes: Any) -> CvText:
    base: dict[str, Any] = {
        "profile": "Engineer with a focus on Microsoft Azure platforms.",
        "positions": [
            {
                "title": "Senior Cloud Engineer",
                "company": "Tulip Systems",
                "highlights": [
                    "Built landing zones on Microsoft Azure with Terraform."
                ],
            },
            {
                "title": "Cloud Engineer",
                "company": "Delta Works",
                "highlights": ["Ran workloads on Microsoft Azure."],
            },
        ],
        "education": [
            {"degree": "BSc Computer Science", "institution": "Hogeschool X"}
        ],
    }
    return CvText.model_validate(base | changes)


def test_usable_text_has_no_problems() -> None:
    assert problems_in(written(), BLUEPRINT) == []


def test_dates_skills_and_languages_come_from_the_blueprint() -> None:
    cv = assemble(written(), BLUEPRINT)

    assert [(p.start, p.end) for p in cv.positions] == [
        ("2024-01", None),
        ("2020-01", "2023-12"),
    ]
    assert cv.positions[0].skills == ["Microsoft Azure", "Terraform"]
    assert cv.skills == ["Microsoft Azure", "Terraform"]
    assert cv.languages == BLUEPRINT.languages
    assert cv.education[0].year == 2020
    # The prose is the model's.
    assert cv.positions[0].company == "Tulip Systems"
    # Computing from the CV gives back the planted years.
    assert years_per_skill(cv.positions, AS_OF) == BLUEPRINT.skill_years


def test_the_cv_holds_no_name_and_no_contact_details() -> None:
    cv = assemble(written(), BLUEPRINT)
    text = render_text(cv)
    as_json = cv.model_dump_json()

    for personal in ("Saar", "Brands", "example.com", "7700"):
        assert personal not in text
        assert personal not in as_json
    assert "Senior Cloud Engineer, Tulip Systems (2024-01 to present)" in text
    assert "Skills used: Microsoft Azure, Terraform" in text
    assert "Dutch: fluent" in text


def test_a_wrong_number_of_jobs_is_a_problem() -> None:
    one_job = written(positions=written().model_dump()["positions"][:1])

    assert "wrong_number_of_positions" in problems_in(one_job, BLUEPRINT)


@pytest.mark.parametrize(
    "profile",
    [
        "Born in 1990 in Utrecht.",
        "Date of birth: 1 May 1990.",
        "A 34 years old engineer.",
        "Age: 34.",
        "Married, two children.",
        "Dutch nationality.",
        "Gender: female.",
        "See the photo above.",
    ],
)
def test_personal_details_in_the_text_are_a_problem(profile: str) -> None:
    assert "personal_details" in problems_in(written(profile=profile), BLUEPRINT)


def test_a_skill_the_candidate_does_not_have_is_a_problem() -> None:
    boasting = written(profile="Experienced with Microsoft Azure and kubernetes.")

    assert "mentions_missing_skill" in problems_in(boasting, BLUEPRINT)


def test_a_skill_named_in_a_job_where_it_was_not_used_is_a_problem() -> None:
    """Otherwise the years computed from the CV would exceed the planted years."""
    positions = written().model_dump()["positions"]
    positions[1]["highlights"] = ["Managed infrastructure with Terraform."]

    assert "skill_in_wrong_position" in problems_in(
        written(positions=positions), BLUEPRINT
    )


def test_mentions_matches_whole_words_only() -> None:
    assert mentions("Worked with Java daily", "java")
    assert not mentions("Wrote JavaScript daily", "Java")
    assert mentions("Set up CI/CD pipelines", "CI/CD")
    assert mentions("C++ and C# experience", "C++")
    assert not mentions("Scrummaster", "Scrum")


# --- Vacancy profile --------------------------------------------------------------


def profile(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "required_skills": [
            {"name": "Microsoft Azure", "min_years": 3},
            {"name": "Terraform", "min_years": 0},
        ],
        "nice_skills": ["Scrum"],
        "adjacent_roles": [{"title": "Data Engineer", "skills": ["Spark", "dbt"]}],
        "unrelated_roles": [{"title": "Nurse", "skills": ["Patient care"]}],
    }
    return base | changes


def test_a_profile_is_tidied() -> None:
    parsed = VacancyProfile.model_validate(
        profile(
            required_skills=[
                {"name": " Microsoft Azure ", "min_years": 3},
                {"name": "microsoft azure", "min_years": 5},
                {"name": "Terraform", "min_years": 0},
            ],
            nice_skills=["Scrum", "terraform", "", "scrum"],
            adjacent_roles=[
                {
                    "title": "Data Engineer",
                    "skills": ["Spark", "Microsoft Azure", "Scrum"],
                }
            ],
        )
    )

    assert [(n.name, n.min_years) for n in parsed.required_skills] == [
        ("Microsoft Azure", 3),
        ("Terraform", 0),
    ]
    assert parsed.nice_skills == ["Scrum"]
    # A neighbouring job does not bring the vacancy's own skills along.
    assert parsed.adjacent_roles[0].skills == ["Spark"]


@pytest.mark.parametrize(
    "change",
    [
        {"required_skills": [{"name": "Azure", "min_years": 1}]},
        {
            "required_skills": [
                {"name": "", "min_years": 1},
                {"name": "X", "min_years": 1},
            ]
        },
        {
            "required_skills": [
                {"name": "A", "min_years": 40},
                {"name": "B", "min_years": 1},
            ]
        },
        {"adjacent_roles": []},
        {"unrelated_roles": [{"title": "Nurse", "skills": []}]},
        {"adjacent_roles": [{"title": "Data Engineer", "skills": ["Terraform"]}]},
    ],
)
def test_an_unusable_profile_is_refused(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        VacancyProfile.model_validate(profile(**change))
