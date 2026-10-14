"""List sizes, blind CVs, computed facts, the evidence check and the ranking."""

from datetime import date
from typing import Any

import pytest

from app.candidates.cv import render_text
from app.candidates.schemas import Cv
from app.screening.blind import REMOVED, anonymise, blind_cv, blind_text
from app.screening.evidence import (
    CONCERN_CONTRADICTED,
    KEYWORD_NOT_IN_CV,
    SENTENCE_UNSUPPORTED,
    STRENGTH_UNSUPPORTED,
    YEARS_CORRECTED,
    check_assessment,
)
from app.screening.facts import candidate_facts, keyword_fact, script_keywords
from app.screening.ranking import Scored, build_lists, final_score
from app.screening.schemas import ModelAssessment
from app.screening.sizes import ListSizes, list_sizes
from app.script.schemas import Kind, ScriptItem

AS_OF = date(2026, 10, 13)

# --- List sizes (CLAUDE.md rule 6) -------------------------------------------


@pytest.mark.parametrize(
    ("candidates", "long", "short"),
    [
        (1, 1, 1),
        (2, 1, 1),
        (5, 2, 1),
        (10, 3, 1),
        (15, 5, 2),  # 4.5 rounds up to 5; Python's round() would give 4
        (20, 6, 2),
        (25, 8, 3),  # 2.5 rounds up to 3; Python's round() would give 2
        (100, 10, 4),
    ],
)
def test_list_sizes_at_the_edges(candidates: int, long: int, short: int) -> None:
    assert list_sizes(candidates) == ListSizes(long=long, short=short)


@pytest.mark.parametrize("candidates", range(1, 101))
def test_list_sizes_hold_for_every_pool(candidates: int) -> None:
    sizes = list_sizes(candidates)

    assert 1 <= sizes.short <= sizes.long <= candidates
    assert sizes.long <= 10
    assert sizes.short <= 4


def test_no_candidates_means_no_lists() -> None:
    with pytest.raises(ValueError, match="at least one candidate"):
        list_sizes(0)


# --- A CV to work with -------------------------------------------------------


def make_cv(**changes: Any) -> Cv:
    base: dict[str, Any] = {
        "profile": "Cloud engineer with a focus on Azure platforms.",
        "positions": [
            {
                "title": "Senior Cloud Engineer",
                "company": "Tulip Systems",
                "start": "2024-01",
                "end": None,
                "highlights": ["Built landing zones on Azure with Terraform."],
                "skills": ["Azure", "Terraform"],
            },
            {
                "title": "Cloud Engineer",
                "company": "Delta Works",
                "start": "2020-01",
                "end": "2023-12",
                "highlights": ["Ran workloads on Azure."],
                "skills": ["Azure"],
            },
        ],
        "education": [
            {"degree": "BSc Computer Science", "institution": "X", "year": 2020}
        ],
        "skills": ["Azure", "Terraform"],
        "languages": [{"language": "English", "level": "fluent"}],
    }
    return Cv.model_validate(base | changes)


CV = make_cv()
WHO = {
    "name": "Saar van der Veen",
    "email": "saar.veen7@example.com",
    "phone": "+44 7700 900007",
}

# --- Blind screening (CLAUDE.md rule 3) --------------------------------------


def test_a_cv_with_identifiable_details_is_cleaned() -> None:
    """Broken on purpose: a CV that does contain the name and contact details."""
    identifiable = make_cv(
        profile=(
            "Saar van der Veen is a cloud engineer. Reach Saar at "
            "saar.veen7@example.com or +44 7700 900007, or see "
            "https://www.linkedin.com/in/saarvanderveen."
        ),
        positions=[
            CV.positions[0].model_dump()
            | {"highlights": ["Veen led the Azure migration. Call 06 12345678."]}
        ],
    )

    text = blind_text(identifiable, **WHO)

    for personal in (
        "Saar",
        "Veen",
        "van der Veen",
        "example.com",
        "7700",
        "linkedin",
        "12345678",
    ):
        assert personal not in text
    assert REMOVED in text
    # The professional content is still there.
    assert "led the Azure migration" in text
    assert "2024-01 to present" in text


def test_other_peoples_contact_details_are_removed_too() -> None:
    text = anonymise(
        "Reference: j.jansen@werk.nl, tel. 020-555 01 23, www.jansen.nl",
        **WHO,
    )

    assert text == f"Reference: {REMOVED}, tel. {REMOVED}, {REMOVED}"


def test_a_clean_cv_passes_through_unchanged() -> None:
    assert blind_cv(CV, **WHO) == CV
    assert blind_text(CV, **WHO) == render_text(CV)


def test_dates_and_years_are_not_mistaken_for_phone_numbers() -> None:
    text = "Worked 2020-01 to 2023-12, saved 25% and 1,200,000 euros in 2024."

    assert anonymise(text, **WHO) == text


# --- Facts, computed by code (CLAUDE.md rule 4) ------------------------------


def test_years_come_from_the_dated_jobs_that_mention_the_keyword() -> None:
    azure = keyword_fact(CV, "Azure", AS_OF)
    terraform = keyword_fact(CV, "Terraform", AS_OF)

    assert (azure.found, azure.years) == (True, 6.8)
    assert (terraform.found, terraform.years) == (True, 2.8)
    # The evidence says where.
    assert [s.where for s in terraform.snippets] == [
        "Job 1: Senior Cloud Engineer, Tulip Systems",
        "Job 1: Senior Cloud Engineer, Tulip Systems",
    ]
    assert terraform.snippets[0].text == "Built landing zones on Azure with Terraform."


def test_a_keyword_that_is_not_in_the_cv_is_not_found() -> None:
    fact = keyword_fact(CV, "Kubernetes", AS_OF)

    assert (fact.found, fact.years, fact.snippets) == (False, 0.0, [])


def test_a_keyword_named_outside_a_job_is_found_with_no_years() -> None:
    english = keyword_fact(CV, "English", AS_OF)

    assert (english.found, english.years) == (True, 0.0)
    assert english.snippets[0].where == "Languages"


def test_a_company_name_is_not_evidence_of_a_skill() -> None:
    cv = make_cv(
        positions=[
            CV.positions[0].model_dump() | {"company": "Kubernetes Consulting BV"}
        ]
    )

    assert keyword_fact(cv, "Kubernetes", AS_OF).found is False


def test_keywords_match_whole_words() -> None:
    cv = make_cv(
        positions=[
            CV.positions[0].model_dump()
            | {"highlights": ["Wrote JavaScript."], "skills": []}
        ]
    )

    assert keyword_fact(cv, "Java", AS_OF).found is False
    assert keyword_fact(cv, "javascript", AS_OF).found is True


def item(
    *keywords: str, years: int = 0, hard: bool = True, enabled: bool = True
) -> ScriptItem:
    return ScriptItem(
        any_of=list(keywords),
        min_years=years,
        kind=Kind.HARD if hard else Kind.SOFT,
        enabled=enabled,
    )


def test_facts_cover_every_keyword_of_the_enabled_items() -> None:
    script = [
        item("AWS", "Azure", years=5),
        item("Terraform"),
        item("COBOL", enabled=False),
        item("Azure", hard=False),
    ]

    facts = candidate_facts(CV, script, AS_OF)

    assert script_keywords(script) == ["AWS", "Azure", "Terraform"]
    assert facts.total_years == 6.8
    assert facts.found_years == {"Azure": 6.8, "Terraform": 2.8}
    assert facts.keywords["AWS"].found is False


# --- The evidence check (CLAUDE.md rule 4) -----------------------------------

KEYWORDS = ["Azure", "Terraform", "Kubernetes"]


def assessment(**changes: Any) -> ModelAssessment:
    base: dict[str, Any] = {
        "fit_score": 80,
        "found": [
            {"keyword": "Azure", "years": 7},
            {"keyword": "Terraform", "years": 3},
        ],
        "strengths": [{"text": "Long Azure experience.", "keywords": ["Azure"]}],
        "concerns": [{"text": "No Kubernetes.", "keywords": ["Kubernetes"]}],
        "reasoning": "Relevant roles in the same field. The career shows progression.",
    }
    return ModelAssessment.model_validate(base | changes)


def check(given: ModelAssessment) -> Any:
    return check_assessment(
        given, CV, render_text(CV), KEYWORDS, AS_OF, total_years=6.8
    )


def test_a_truthful_assessment_passes_unchanged() -> None:
    checked = check(assessment())

    assert checked.flags == []
    assert checked.fit_score == 80
    assert checked.strengths == ["Long Azure experience."]
    assert checked.concerns == ["No Kubernetes."]
    assert checked.reasoning == (
        "Relevant roles in the same field. The career shows progression."
    )
    # Two keywords and two numbers of years were claimed; all four held.
    assert (checked.claims_made, checked.claims_supported) == (4, 4)


def test_computed_years_replace_the_models_years() -> None:
    checked = check(assessment())

    assert [(c.keyword, c.years) for c in checked.found] == [
        ("Azure", 6.8),
        ("Terraform", 2.8),
    ]


def test_a_claimed_keyword_that_is_not_in_the_cv_is_removed_and_flagged() -> None:
    """Broken on purpose: the model says it found Kubernetes."""
    lying = assessment(
        found=[{"keyword": "Azure", "years": 7}, {"keyword": "Kubernetes", "years": 4}]
    )

    checked = check(lying)

    assert [c.keyword for c in checked.found] == ["Azure"]
    assert [(f.kind, f.detail) for f in checked.flags] == [
        (KEYWORD_NOT_IN_CV, "Kubernetes")
    ]
    assert (checked.claims_made, checked.claims_supported) == (3, 2)


def test_overstated_years_are_corrected_and_flagged() -> None:
    checked = check(assessment(found=[{"keyword": "Terraform", "years": 8}]))

    assert [(c.keyword, c.years) for c in checked.found] == [("Terraform", 2.8)]
    assert [(f.kind, f.detail) for f in checked.flags] == [
        (YEARS_CORRECTED, "Terraform: stated 8, computed 2.8")
    ]


def test_years_within_a_year_of_the_computed_value_are_accepted() -> None:
    checked = check(assessment(found=[{"keyword": "Azure", "years": 6}]))

    assert checked.flags == []


def test_a_strength_built_on_a_missing_keyword_is_removed() -> None:
    checked = check(
        assessment(
            strengths=[
                {"text": "Deep Kubernetes knowledge.", "keywords": ["Kubernetes"]},
                {"text": "Solid infrastructure as code.", "keywords": ["Terraform"]},
            ]
        )
    )

    assert checked.strengths == ["Solid infrastructure as code."]
    assert [(f.kind, f.detail) for f in checked.flags] == [
        (STRENGTH_UNSUPPORTED, "Kubernetes")
    ]


def test_a_concern_about_something_the_cv_does_contain_is_removed() -> None:
    checked = check(
        assessment(
            concerns=[{"text": "No Terraform experience.", "keywords": ["Terraform"]}]
        )
    )

    assert checked.concerns == []
    assert [(f.kind, f.detail) for f in checked.flags] == [
        (CONCERN_CONTRADICTED, "Terraform")
    ]


def test_a_sentence_that_names_a_missing_keyword_is_removed_from_the_reasoning() -> (
    None
):
    checked = check(
        assessment(
            reasoning=(
                "Relevant roles in the same field. Their Kubernetes work stands out. "
                "The career shows progression."
            )
        )
    )

    assert checked.reasoning == (
        "Relevant roles in the same field. The career shows progression."
    )
    assert [(f.kind, f.detail) for f in checked.flags] == [
        (SENTENCE_UNSUPPORTED, "Kubernetes")
    ]


def test_a_sentence_with_years_that_match_nothing_is_removed() -> None:
    checked = check(
        assessment(
            reasoning=(
                "Almost 7 years in cloud roles. They have 15 years of experience. "
                "About 3 years of Terraform."
            )
        )
    )

    # 7 is the total, 3 is Terraform; 15 matches nothing that was computed.
    assert (
        checked.reasoning
        == "Almost 7 years in cloud roles. About 3 years of Terraform."
    )
    assert [(f.kind, f.detail) for f in checked.flags] == [
        (SENTENCE_UNSUPPORTED, "15 years")
    ]


def test_points_without_keywords_are_kept() -> None:
    checked = check(
        assessment(
            strengths=[{"text": "Clear career progression.", "keywords": []}],
            concerns=[{"text": "Short time in a senior role.", "keywords": []}],
        )
    )

    assert checked.strengths == ["Clear career progression."]
    assert checked.concerns == ["Short time in a senior role."]
    assert checked.flags == []


@pytest.mark.parametrize(
    "change",
    [
        {"fit_score": 101},
        {"fit_score": -1},
        {"fit_score": 7.5},
        {"reasoning": "  "},
        {"found": [{"keyword": "", "years": 1}]},
        {"found": [{"keyword": "Azure", "years": -1}]},
        {"strengths": [{"text": "", "keywords": []}]},
        {"extra": True},
    ],
)
def test_a_malformed_assessment_is_refused(change: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="validation error"):
        assessment(**change)


# --- Final ranking and the two lists -----------------------------------------


def scored(
    name: str,
    deterministic: float,
    llm: int | None,
    *,
    meets_hard: bool = True,
    listable: bool = True,
    missed: int = 0,
) -> Scored[str]:
    return Scored(
        candidate=name,
        deterministic_score=deterministic,
        llm_score=llm,
        meets_hard=meets_hard,
        listable=listable,
        missed_hard=missed,
    )


def test_the_final_score_combines_both_stages_with_a_configurable_weight() -> None:
    assert final_score(1.0, 60, 0.5) == 0.8
    assert final_score(1.0, 60, 1.0) == 1.0  # facts only
    assert final_score(1.0, 60, 0.0) == 0.6  # model only
    assert final_score(0.4, 90, 0.25) == 0.775
    with pytest.raises(ValueError, match="between 0 and 1"):
        final_score(1.0, 60, 1.5)


POOL = [
    scored("a", 1.0, 70),
    scored("b", 0.8, 95),
    scored("c", 0.9, 50),
    scored("d", 0.7, 60),
    scored("no-hard", 0.6, 99, meets_hard=False, listable=False, missed=1),
    scored("not-assessed", 0.5, None),
]


def test_lists_are_cut_from_the_final_ranking() -> None:
    lists = build_lists(POOL, ListSizes(long=3, short=1), 0.5)

    # b: 0.875, a: 0.85, c: 0.7, d: 0.65
    assert lists.long == ["b", "a", "c"]
    assert lists.short == ["b"]
    assert lists.scores["b"] == 0.875


def test_the_weighting_can_change_the_order() -> None:
    by_facts = build_lists(POOL, ListSizes(long=3, short=1), 1.0)

    assert by_facts.long == ["a", "c", "b"]


def test_the_short_list_is_always_a_subset_of_the_long_list() -> None:
    for long in range(1, 7):
        for short in range(1, long + 1):
            lists = build_lists(POOL, ListSizes(long=long, short=short), 0.5)

            assert lists.short == lists.long[:short]
            assert set(lists.short) <= set(lists.long)


def test_a_high_model_score_does_not_get_an_unlistable_candidate_on_a_list() -> None:
    """Broken on purpose: the model loves a candidate who misses a hard requirement."""
    lists = build_lists(POOL, ListSizes(long=6, short=4), 0.5)

    assert "no-hard" not in lists.long
    assert lists.long == ["b", "a", "c", "d"]


def test_a_candidate_the_model_did_not_assess_is_not_listed() -> None:
    lists = build_lists(POOL, ListSizes(long=6, short=4), 0.5)

    assert "not-assessed" not in lists.long
    assert "not-assessed" not in lists.scores


def test_flagged_candidates_come_after_those_who_qualify() -> None:
    pool = [
        scored("qualifies", 0.5, 40),
        scored("flagged-one", 0.9, 99, meets_hard=False, missed=1),
        scored("flagged-two", 0.9, 99, meets_hard=False, missed=2),
    ]

    lists = build_lists(pool, ListSizes(long=3, short=1), 0.5)

    assert lists.long == ["qualifies", "flagged-one", "flagged-two"]
    assert lists.short == ["qualifies"]


def test_a_strength_that_states_wrong_years_is_removed() -> None:
    """Seen with the real models: "4 years of Terraform" where the CV gives 2.8."""
    checked = check(
        assessment(
            strengths=[
                {"text": "Has 8 years of Terraform.", "keywords": ["Terraform"]},
                {"text": "Close to 7 years in cloud roles.", "keywords": ["Azure"]},
            ]
        )
    )

    assert checked.strengths == ["Close to 7 years in cloud roles."]
    assert [(f.kind, f.detail) for f in checked.flags] == [
        (STRENGTH_UNSUPPORTED, "8 years")
    ]


def test_a_concern_that_states_wrong_years_is_removed() -> None:
    checked = check(
        assessment(concerns=[{"text": "Only 1 year of Terraform.", "keywords": []}])
    )

    assert checked.concerns == []
    assert [(f.kind, f.detail) for f in checked.flags] == [
        (CONCERN_CONTRADICTED, "1 years")
    ]


def test_years_written_as_words_are_checked_too() -> None:
    checked = check(
        assessment(
            strengths=[{"text": "Over twelve years of Azure.", "keywords": ["Azure"]}],
            reasoning="Seven years of solid cloud work. Fifteen years in total.",
        )
    )

    assert checked.strengths == []
    assert checked.reasoning == "Seven years of solid cloud work."
    assert [(f.kind, f.detail) for f in checked.flags] == [
        (STRENGTH_UNSUPPORTED, "12 years"),
        (SENTENCE_UNSUPPORTED, "15 years"),
    ]


def test_a_concern_about_a_missing_alternative_is_removed() -> None:
    """Seen with the real model: "lacks Azure" for a candidate who meets
    "AWS or Azure" with AWS. The concern was true of the CV, but not of the
    vacancy, and it reached the interview questions."""
    checked = check_assessment(
        assessment(
            concerns=[
                {"text": "Lacks Azure, a required platform.", "keywords": ["AWS"]},
                {"text": "No container orchestration.", "keywords": ["Kubernetes"]},
            ]
        ),
        CV,
        render_text(CV),
        KEYWORDS,
        AS_OF,
        total_years=6.8,
        covered={"aws": "Azure", "azure": "Azure"},
    )

    assert checked.concerns == ["No container orchestration."]
    assert [(f.kind, f.detail) for f in checked.flags] == [
        (CONCERN_CONTRADICTED, "AWS: Azure meets the same requirement")
    ]


def test_covered_alternatives_come_from_met_items_only() -> None:
    from app.screening.service import covered_alternatives

    items = [
        item("AWS", "Azure", "GCP", years=5),
        item("Terraform", "Pulumi"),
    ]
    requirements = [
        {"item": 0, "met": True, "keyword": "Azure"},
        # Found, but not for long enough: nothing is covered.
        {"item": 1, "met": False, "keyword": "Terraform"},
    ]

    assert covered_alternatives(requirements, items) == {
        "aws": "Azure",
        "azure": "Azure",
        "gcp": "Azure",
    }
