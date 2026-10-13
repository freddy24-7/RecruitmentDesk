"""Hard and soft requirements are applied in one function (CLAUDE.md rule 5)."""

import ast
from pathlib import Path

from app.script.requirements import apply_requirements, check
from app.script.schemas import Kind, ScriptItem

REPO_ROOT = Path(__file__).resolve().parents[2]


def item(
    *keywords: str, years: int = 0, hard: bool = True, enabled: bool = True
) -> ScriptItem:
    return ScriptItem(
        any_of=list(keywords),
        min_years=years,
        kind=Kind.HARD if hard else Kind.SOFT,
        enabled=enabled,
    )


SCRIPT = [
    item("AWS", "Azure", "GCP", years=5),
    item("Terraform", years=3),
    item("Kubernetes", hard=False),
    item("Python", hard=False),
]


# --- One candidate against the script ----------------------------------------


def test_a_candidate_who_meets_everything_scores_one() -> None:
    outcome = check(SCRIPT, {"Azure": 6, "Terraform": 3, "Kubernetes": 1, "Python": 2})

    assert outcome.meets_hard
    assert outcome.missed_hard == []
    assert outcome.score == 1.0


def test_any_one_alternative_meets_an_item() -> None:
    for cloud in ("AWS", "Azure", "GCP"):
        outcome = check(SCRIPT, {cloud: 5, "Terraform": 3})

        assert outcome.meets_hard
        assert outcome.results[0].keyword == cloud


def test_years_are_not_added_up_across_alternatives() -> None:
    """Three years of AWS and three of Azure are not six years of one of them."""
    outcome = check(SCRIPT, {"AWS": 3, "Azure": 3, "Terraform": 3})

    cloud = outcome.results[0]
    assert not cloud.met
    assert cloud.years == 3
    assert not outcome.meets_hard


def test_the_alternative_with_the_most_years_counts() -> None:
    outcome = check(SCRIPT, {"AWS": 2, "GCP": 7, "Terraform": 3})

    assert (outcome.results[0].keyword, outcome.results[0].years) == ("GCP", 7)
    assert outcome.results[0].met


def test_too_few_years_fails_a_hard_requirement() -> None:
    outcome = check(SCRIPT, {"Azure": 6, "Terraform": 2.9})

    assert [r.item for r in outcome.missed_hard] == [1]
    missed = outcome.missed_hard[0]
    assert (missed.keyword, missed.years, missed.min_years) == ("Terraform", 2.9, 3)


def test_exactly_the_years_asked_is_enough() -> None:
    assert check(SCRIPT, {"Azure": 5, "Terraform": 3}).meets_hard


def test_a_keyword_that_was_not_found_fails_the_item() -> None:
    outcome = check(SCRIPT, {"Azure": 6})

    terraform = outcome.results[1]
    assert (terraform.met, terraform.keyword, terraform.years) == (False, None, 0.0)


def test_without_a_number_of_years_being_there_is_enough() -> None:
    outcome = check([item("Kubernetes")], {"Kubernetes": 0.1})

    assert outcome.meets_hard


def test_keywords_are_compared_without_regard_to_case() -> None:
    outcome = check(SCRIPT, {"azure": 6, "TERRAFORM": 3})

    assert outcome.meets_hard


def test_a_soft_requirement_only_changes_the_score() -> None:
    hard_only = check(SCRIPT, {"Azure": 6, "Terraform": 3})
    with_soft = check(SCRIPT, {"Azure": 6, "Terraform": 3, "Python": 1})

    assert hard_only.meets_hard
    assert with_soft.meets_hard
    assert hard_only.missed_hard == with_soft.missed_hard == []
    assert with_soft.score > hard_only.score
    # Two hard items (weight 2 each) and two soft ones (weight 1 each).
    assert hard_only.score == 4 / 6
    assert with_soft.score == 5 / 6


def test_a_missed_soft_requirement_never_blocks_a_candidate() -> None:
    outcome = check(SCRIPT, {"Azure": 6, "Terraform": 3})

    assert [r.met for r in outcome.results] == [True, True, False, False]
    assert outcome.meets_hard


def test_being_short_of_years_earns_part_of_the_score() -> None:
    none = check(SCRIPT, {"Terraform": 3})
    some = check(SCRIPT, {"Azure": 2.5, "Terraform": 3})
    full = check(SCRIPT, {"Azure": 5, "Terraform": 3})

    assert none.score < some.score < full.score
    # Half of the five years gives a quarter of the item's weight of 2.
    assert some.score == (2 + 0.5) / 6


def test_a_disabled_item_is_ignored() -> None:
    script = [item("Azure", years=5), item("COBOL", years=10, enabled=False)]

    outcome = check(script, {"Azure": 5})

    assert outcome.meets_hard
    assert outcome.score == 1.0
    assert [r.item for r in outcome.results] == [0]


def test_a_script_with_only_soft_items_blocks_nobody() -> None:
    outcome = check([item("Python", hard=False)], {})

    assert outcome.meets_hard
    assert outcome.score == 0.0


# --- All candidates: who may be listed ---------------------------------------

FACTS = {
    "strong": {"Azure": 8, "Terraform": 4, "Kubernetes": 2, "Python": 3},
    "good": {"AWS": 5, "Terraform": 3},
    "no-terraform": {"GCP": 9, "Kubernetes": 4, "Python": 5},
    "short-on-cloud": {"Azure": 2, "Terraform": 5, "Python": 1},
    "unrelated": {"SEO": 6},
}


def test_candidates_who_miss_a_hard_requirement_are_not_listed() -> None:
    ranked = apply_requirements(SCRIPT, FACTS, needed=2)

    listable = [r.candidate for r in ranked if r.listable]
    assert listable == ["strong", "good"]
    assert not any(r.flagged for r in ranked)
    # Everyone is ranked, also those who cannot be listed.
    assert len(ranked) == len(FACTS)


def test_a_higher_soft_score_does_not_beat_a_missed_hard_requirement() -> None:
    """Both soft skills but no Terraform does not beat a candidate who qualifies."""
    ranked = [r.candidate for r in apply_requirements(SCRIPT, FACTS, needed=2)]

    assert ranked.index("good") < ranked.index("no-terraform")


def test_too_few_qualified_candidates_lists_others_with_a_flag() -> None:
    ranked = apply_requirements(SCRIPT, FACTS, needed=4)

    listable = [r for r in ranked if r.listable]
    assert [r.candidate for r in listable] == [
        "strong",
        "good",
        "no-terraform",
        "short-on-cloud",
    ]
    # The two who qualify carry no flag.
    assert [r.flagged for r in listable] == [False, False, True, True]
    # The flag says exactly which hard requirement is missed.
    flagged = {r.candidate: r.missed_hard for r in listable if r.flagged}
    assert [m.item for m in flagged["no-terraform"]] == [1]
    assert [(m.item, m.keyword, m.years) for m in flagged["short-on-cloud"]] == [
        (0, "Azure", 2)
    ]
    # Whoever is not needed stays unlisted and unflagged.
    last = ranked[-1]
    assert (last.candidate, last.listable, last.flagged) == ("unrelated", False, False)


def test_nobody_is_listed_with_a_missed_hard_requirement_and_no_flag() -> None:
    """The guarantee itself, for every list size."""
    for needed in range(0, len(FACTS) + 2):
        for ranked in apply_requirements(SCRIPT, FACTS, needed=needed):
            if ranked.listable and not ranked.outcome.meets_hard:
                assert ranked.flagged
            if not ranked.listable:
                assert not ranked.flagged


def test_among_the_others_fewer_missed_requirements_come_first() -> None:
    facts = {
        "misses-two": {"Kubernetes": 3, "Python": 3},
        "misses-one": {"Azure": 6},
    }

    ranked = apply_requirements(SCRIPT, facts, needed=1)

    assert [(r.candidate, r.listable) for r in ranked] == [
        ("misses-one", True),
        ("misses-two", False),
    ]


def test_ties_keep_the_given_order() -> None:
    facts = {"b": {"Azure": 5, "Terraform": 3}, "a": {"Azure": 5, "Terraform": 3}}

    assert [r.candidate for r in apply_requirements(SCRIPT, facts, needed=2)] == [
        "b",
        "a",
    ]


def test_with_no_candidates_there_is_nothing_to_rank() -> None:
    assert apply_requirements(SCRIPT, {}, needed=3) == []


# --- The rule itself: one place ----------------------------------------------


def test_hard_and_soft_are_only_told_apart_in_the_requirements_module() -> None:
    """No other module may decide what a hard or soft requirement means."""
    offenders = []
    for path in sorted((REPO_ROOT / "app").rglob("*.py")):
        relative = path.relative_to(REPO_ROOT)
        if str(relative) == "app/script/requirements.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            # A comparison with Kind.HARD or Kind.SOFT is a decision on kind.
            if isinstance(node, ast.Compare):
                names = [node.left, *node.comparators]
                if any(
                    isinstance(n, ast.Attribute)
                    and isinstance(n.value, ast.Name)
                    and n.value.id == "Kind"
                    for n in names
                ):
                    offenders.append(str(relative))
    assert offenders == []
