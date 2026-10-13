"""Candidate blueprints are sampled by code, with known ground truth (PRD F4)."""

import json
from collections import Counter
from datetime import date

import pytest

from app.candidates.blueprints import category_counts, sample_blueprints
from app.candidates.schemas import Blueprint, MatchCategory, VacancyProfile
from app.candidates.timeline import total_years, years_per_skill
from app.llm.base import LlmRequest
from app.llm.fake import fake_vacancy_profile

AS_OF = date(2026, 10, 13)
SEED = 20261013

PROFILE = VacancyProfile.model_validate_json(
    fake_vacancy_profile(
        LlmRequest(
            call_type="vacancy_profile",
            model="fake",
            system="",
            user="",
            schema=VacancyProfile,
            temperature=0,
            max_tokens=1,
        )
    )
)
REQUIRED = {need.name: need.min_years for need in PROFILE.required_skills}
NICE = set(PROFILE.nice_skills)


def sample(
    n: int, seed: int = SEED, seniority: list[str] | None = None
) -> list[Blueprint]:
    return sample_blueprints(
        n=n,
        seed=seed,
        title="Cloud Engineer",
        seniority=seniority or ["senior"],
        profile=PROFILE,
        as_of=AS_OF,
    )


def as_json(blueprints: list[Blueprint]) -> str:
    return json.dumps([b.model_dump(mode="json") for b in blueprints])


def test_the_same_seed_gives_the_same_pool() -> None:
    assert as_json(sample(40)) == as_json(sample(40))


def test_another_seed_gives_other_people() -> None:
    first, second = sample(40), sample(40, seed=SEED + 1)

    assert {b.name for b in first} != {b.name for b in second}
    assert as_json(first) != as_json(second)


@pytest.mark.parametrize(
    ("n", "strong", "partial", "adjacent", "weak"),
    [
        (100, 15, 35, 30, 20),
        (20, 3, 7, 6, 4),
        (10, 2, 3, 3, 2),
        (5, 1, 2, 1, 1),
        (2, 1, 1, 0, 0),
        (1, 1, 0, 0, 0),
    ],
)
def test_match_categories_follow_the_fixed_distribution(
    n: int, strong: int, partial: int, adjacent: int, weak: int
) -> None:
    counts = category_counts(n)

    assert sum(counts.values()) == n
    assert (
        counts[MatchCategory.STRONG],
        counts[MatchCategory.PARTIAL],
        counts[MatchCategory.ADJACENT],
        counts[MatchCategory.WEAK],
    ) == (strong, partial, adjacent, weak)
    # The sampled pool has exactly these counts.
    assert Counter(b.match_category for b in sample(n)) == Counter(
        {category: count for category, count in counts.items() if count}
    )


@pytest.mark.parametrize("n", range(1, 101))
def test_every_pool_size_adds_up_and_has_a_strong_match(n: int) -> None:
    counts = category_counts(n)

    assert sum(counts.values()) == n
    assert counts[MatchCategory.STRONG] >= 1
    assert all(count >= 0 for count in counts.values())


def test_zero_candidates_is_refused() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        category_counts(0)


def test_categories_are_not_in_a_recognisable_order() -> None:
    order = [b.match_category for b in sample(100)]

    assert order != sorted(order)


def test_contact_details_are_clearly_fictional_and_unique() -> None:
    pool = sample(100)

    assert all(b.email.endswith("@example.com") for b in pool)
    assert all(b.email.isascii() and " " not in b.email for b in pool)
    assert all(b.phone.startswith("+44 7700 900") for b in pool)
    assert len({b.email for b in pool}) == 100
    assert len({b.phone for b in pool}) == 100
    assert len({b.name for b in pool}) == 100
    assert [b.index for b in pool] == list(range(1, 101))


def test_a_strong_match_has_every_required_skill_for_long_enough() -> None:
    strong = [b for b in sample(100) if b.match_category is MatchCategory.STRONG]

    assert strong
    for blueprint in strong:
        for skill, min_years in REQUIRED.items():
            assert blueprint.skill_years.get(skill, 0) >= max(min_years, 1)
        assert not set(blueprint.avoid_skills) & set(REQUIRED)
        assert all(
            position.role == "Cloud Engineer" for position in blueprint.positions
        )


def test_a_partial_match_misses_at_least_one_required_skill() -> None:
    partial = [b for b in sample(100) if b.match_category is MatchCategory.PARTIAL]

    for blueprint in partial:
        held = set(blueprint.skill_years) & set(REQUIRED)
        assert 1 <= len(held) < len(REQUIRED)
        assert set(REQUIRED) - held <= set(blueprint.avoid_skills)


def test_an_adjacent_candidate_has_another_job_and_at_most_one_required_skill() -> None:
    adjacent = [b for b in sample(100) if b.match_category is MatchCategory.ADJACENT]
    adjacent_titles = {role.title for role in PROFILE.adjacent_roles}

    for blueprint in adjacent:
        assert {position.role for position in blueprint.positions} <= adjacent_titles
        assert len(set(blueprint.skill_years) & set(REQUIRED)) == 1


def test_a_weak_match_has_none_of_the_vacancy_skills() -> None:
    weak = [b for b in sample(100) if b.match_category is MatchCategory.WEAK]
    unrelated_titles = {role.title for role in PROFILE.unrelated_roles}

    for blueprint in weak:
        assert not set(blueprint.skill_years) & (set(REQUIRED) | NICE)
        assert {position.role for position in blueprint.positions} <= unrelated_titles
        assert set(blueprint.avoid_skills) == set(REQUIRED) | NICE


def test_ground_truth_years_are_what_the_timeline_says() -> None:
    """Planted years come from the same arithmetic the scoring step will use."""
    for blueprint in sample(100):
        assert blueprint.skill_years == years_per_skill(blueprint.positions, AS_OF)
        assert blueprint.years_experience == total_years(blueprint.positions, AS_OF)
        assert all(
            years <= blueprint.years_experience
            for years in blueprint.skill_years.values()
        )


def test_timelines_are_plausible() -> None:
    for blueprint in sample(100):
        positions = blueprint.positions
        assert 1 <= len(positions) <= 4
        # Most recent first, no overlap, nothing in the future.
        for newer, older in zip(positions, positions[1:], strict=False):
            assert older.end is not None
            assert older.end < newer.start
        for position in positions:
            assert position.start <= (position.end or "2026-10")
            assert (position.end or "2026-10") <= "2026-10"
        assert 1 <= blueprint.years_experience <= 18


def test_seniority_is_sometimes_above_or_below_the_vacancy() -> None:
    levels = Counter(b.seniority for b in sample(100, seniority=["medior"]))

    assert levels["medior"] > 0
    assert levels["junior"] > 0
    assert levels["senior"] > 0


def test_a_blueprint_holds_no_protected_attributes() -> None:
    fields = set(Blueprint.model_fields)

    assert not fields & {
        "birth_date",
        "age",
        "gender",
        "nationality",
        "marital_status",
        "photo",
    }
