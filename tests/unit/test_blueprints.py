"""Candidate blueprints are sampled by code, with known ground truth (PRD F4)."""

import json
from collections import Counter
from datetime import date

import pytest

from app.candidates.blueprints import category_counts, sample_blueprints
from app.candidates.schemas import (
    Blueprint,
    MatchCategory,
    SkillNeed,
    VacancyProfile,
)
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
NEEDS = PROFILE.required_skills
REQUIRED = {name for need in NEEDS for name in need.any_of}
NICE = set(PROFILE.nice_skills)


def has(blueprint: Blueprint, need: SkillNeed) -> bool:
    return any(name in blueprint.skill_years for name in need.any_of)


def meets(blueprint: Blueprint, need: SkillNeed) -> bool:
    """One of the alternatives, for at least the years the vacancy asks."""
    return any(
        blueprint.skill_years.get(name, 0) >= max(need.min_years, 1)
        for name in need.any_of
    )


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


def test_a_strong_match_meets_every_requirement_for_long_enough() -> None:
    strong = [b for b in sample(100) if b.match_category is MatchCategory.STRONG]

    assert strong
    for blueprint in strong:
        assert all(meets(blueprint, need) for need in NEEDS)
        assert all(
            position.role == "Cloud Engineer" for position in blueprint.positions
        )


def test_one_alternative_is_enough_for_a_strong_match() -> None:
    """The vacancy asks for Azure or AWS: a strong match need not have both."""
    strong = [b for b in sample(100) if b.match_category is MatchCategory.STRONG]
    clouds = [{"Microsoft Azure", "AWS"} & set(b.skill_years) for b in strong]

    assert all(len(held) >= 1 for held in clouds)
    assert any(len(held) == 1 for held in clouds)
    # The one they lack must not turn up in their CV.
    for blueprint, held in zip(strong, clouds, strict=True):
        assert {"Microsoft Azure", "AWS"} - held <= set(blueprint.avoid_skills)


def test_a_partial_match_misses_at_least_one_requirement() -> None:
    partial = [b for b in sample(100) if b.match_category is MatchCategory.PARTIAL]

    for blueprint in partial:
        covered = [has(blueprint, need) for need in NEEDS]
        assert 1 <= sum(covered) < len(NEEDS)
        assert not all(meets(blueprint, need) for need in NEEDS)


def test_an_adjacent_candidate_has_another_job_and_one_required_skill() -> None:
    adjacent = [b for b in sample(100) if b.match_category is MatchCategory.ADJACENT]
    adjacent_titles = {role.title for role in PROFILE.adjacent_roles}

    for blueprint in adjacent:
        assert {position.role for position in blueprint.positions} <= adjacent_titles
        assert len(set(blueprint.skill_years) & REQUIRED) == 1


def test_a_weak_match_has_none_of_the_vacancy_skills() -> None:
    weak = [b for b in sample(100) if b.match_category is MatchCategory.WEAK]
    unrelated_titles = {role.title for role in PROFILE.unrelated_roles}

    for blueprint in weak:
        assert not set(blueprint.skill_years) & (REQUIRED | NICE)
        assert {position.role for position in blueprint.positions} <= unrelated_titles
        assert set(blueprint.avoid_skills) == REQUIRED | NICE
        assert blueprint.tracked_skills == []


def test_vacancy_skills_are_either_tracked_or_to_be_avoided() -> None:
    for blueprint in sample(100):
        tracked, avoid = set(blueprint.tracked_skills), set(blueprint.avoid_skills)

        assert tracked | avoid == REQUIRED | NICE
        assert not tracked & avoid
        assert tracked == set(blueprint.skill_years) & (REQUIRED | NICE)


def test_someone_in_this_line_of_work_names_a_skill_in_every_job() -> None:
    """A cloud engineer's CV with a job that names no skill is hard to write."""
    for blueprint in sample(100):
        if blueprint.match_category in (MatchCategory.STRONG, MatchCategory.PARTIAL):
            assert all(position.skills for position in blueprint.positions)


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
