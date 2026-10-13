"""Candidate blueprints, sampled by code (PRD F4).

Asking a model for "100 CVs" gives a pool of look-alikes with unknown
quality. Here, code decides who each candidate is: a fictional name, years
of experience, a dated job timeline, the skills used in each job, and a
match category in a fixed distribution. The model later only writes prose
for a given blueprint. That gives variety, and it means the ground truth
is known: the lists can be measured against the planted categories.

Sampling is deterministic: the same seed and inputs give the same pool.
"""

import math
import random
import re
import unicodedata
from datetime import date

from faker import Faker

from app.candidates.schemas import (
    Blueprint,
    BlueprintPosition,
    Language,
    MatchCategory,
    VacancyProfile,
)
from app.candidates.timeline import add_months, month_of, total_years, years_per_skill

# The fixed distribution of match categories (PRD F4).
DISTRIBUTION: list[tuple[MatchCategory, float]] = [
    (MatchCategory.STRONG, 0.15),
    (MatchCategory.PARTIAL, 0.35),
    (MatchCategory.ADJACENT, 0.30),
    (MatchCategory.WEAK, 0.20),
]

LEVELS = ["junior", "medior", "senior", "lead"]
# Years of work experience that fit each level (lowest, highest).
YEARS_FOR_LEVEL = {
    "junior": (1, 2),
    "medior": (3, 5),
    "senior": (6, 10),
    "lead": (10, 16),
}

# Reserved so that they can never belong to a real person: example.com is
# reserved by RFC 2606, and 07700 900000-900999 is the UK range that Ofcom
# reserves for use in drama.
EMAIL_DOMAIN = "example.com"
PHONE_PREFIX = "+44 7700 900"


def category_counts(n: int) -> dict[MatchCategory, int]:
    """Split n candidates over the categories, as close to the distribution as possible.

    Largest-remainder rounding, so the counts always add up to n. There is
    always at least one strong match: without one, a short list could not be
    judged at all.
    """
    if n < 1:
        raise ValueError("n must be at least 1")
    exact = {category: n * share for category, share in DISTRIBUTION}
    counts = {category: math.floor(value) for category, value in exact.items()}
    by_remainder = sorted(
        exact, key=lambda category: exact[category] - counts[category], reverse=True
    )
    for category in by_remainder[: n - sum(counts.values())]:
        counts[category] += 1
    if counts[MatchCategory.STRONG] == 0:
        # Make room in the largest category; on a tie, in the weakest of them.
        largest = max(reversed(counts), key=lambda category: counts[category])
        counts[largest] -= 1
        counts[MatchCategory.STRONG] = 1
    return counts


def _email(first: str, last: str, index: int) -> str:
    """An address on a reserved domain. The index keeps addresses unique."""
    ascii_name = (
        unicodedata.normalize("NFKD", f"{first}.{last}")
        .encode("ascii", "ignore")
        .decode()
    )
    local = re.sub(r"[^a-z.]+", "", ascii_name.lower().replace(" ", "")).strip(".")
    return f"{local or 'candidate'}{index}@{EMAIL_DOMAIN}"


def _level_for(category: MatchCategory, target: str, rng: random.Random) -> str:
    """The candidate's seniority: sometimes above or below what the vacancy asks."""
    at = LEVELS.index(target)
    if category is MatchCategory.STRONG:
        shift = rng.choices([0, 1], weights=[70, 30])[0]
    elif category is MatchCategory.PARTIAL:
        shift = rng.choices([0, -1], weights=[60, 40])[0]
    elif category is MatchCategory.ADJACENT:
        shift = rng.choice([-1, 0, 1])
    else:
        return rng.choice(LEVELS)
    return LEVELS[min(max(at + shift, 0), len(LEVELS) - 1)]


def _job_lengths(total_months: int, rng: random.Random) -> list[int]:
    """Split a career into one to four jobs, each at least a year where possible."""
    years = total_months // 12
    jobs = 1 if years <= 2 else rng.randint(2, min(4, 1 + years // 3))
    spare = total_months - 12 * jobs
    if spare < 0:
        return [total_months]
    cuts = sorted(rng.randint(0, spare) for _ in range(jobs - 1))
    parts = [b - a for a, b in zip([0, *cuts], [*cuts, spare], strict=True)]
    return [12 + part for part in parts]


def _timeline(
    years: int, role: str, level: str, as_of: date, rng: random.Random
) -> list[BlueprintPosition]:
    """Dated positions, most recent first, without skills yet."""
    lengths = _job_lengths(years * 12 + rng.randint(0, 11), rng)
    at = LEVELS.index(level)
    positions: list[BlueprintPosition] = []
    # Most people are still in their current job; some left a few months ago.
    end: str | None = (
        None if rng.random() < 0.85 else add_months(month_of(as_of), -rng.randint(1, 4))
    )
    cursor = end or month_of(as_of)
    for number, length in enumerate(lengths):
        start = add_months(cursor, -(length - 1))
        positions.append(
            BlueprintPosition(
                role=role,
                # Earlier jobs were more junior.
                seniority=LEVELS[max(at - number, 0)],
                start=start,
                end=end if number == 0 else cursor,
                skills=[],
            )
        )
        # The job before ended the month before this one started, sometimes
        # with a gap of a few months.
        gap = rng.randint(1, 3) if rng.random() < 0.2 else 0
        cursor = add_months(start, -1 - gap)
    return positions


def _months(position: BlueprintPosition, as_of: date) -> float:
    return total_years([position], as_of) * 12


def _give_recent(
    positions: list[BlueprintPosition], skill: str, years: float, as_of: date
) -> None:
    """Use a skill in the most recent jobs, far enough back to cover `years`."""
    covered = 0.0
    for position in positions:
        position.skills.append(skill)
        covered += _months(position, as_of)
        if covered >= years * 12:
            return


def _give_briefly(positions: list[BlueprintPosition], skill: str, as_of: date) -> None:
    """Use a skill in the shortest job only: some exposure, few years."""
    shortest = min(positions, key=lambda position: _months(position, as_of))
    shortest.skills.append(skill)


def _build(
    index: int,
    category: MatchCategory,
    title: str,
    target_level: str,
    profile: VacancyProfile,
    as_of: date,
    rng: random.Random,
    name: tuple[str, str],
) -> Blueprint:
    level = _level_for(category, target_level, rng)
    low, high = YEARS_FOR_LEVEL[level]
    years = rng.randint(low, high)
    required = profile.required_skills
    nice = list(profile.nice_skills)

    if category is MatchCategory.STRONG:
        # Meets every requirement, for at least the years the vacancy asks.
        # Where the vacancy offers alternatives ("AWS, Azure or GCP"), one is
        # enough; some candidates know a second one, for a shorter time.
        wanted = {}
        for need in required:
            chosen = rng.sample(need.any_of, k=min(len(need.any_of), 2))
            wanted[chosen[0]] = max(need.min_years, 1) + rng.randint(0, 3)
            if len(chosen) > 1 and rng.random() < 0.25:
                wanted[chosen[1]] = rng.randint(1, max(1, need.min_years))
        years = max(years, math.ceil(max(wanted.values())))
        brief: list[str] = []
        extras = rng.sample(nice, k=rng.randint(math.ceil(len(nice) / 2), len(nice)))
        role = title
    elif category is MatchCategory.PARTIAL:
        # Same kind of job, but at least one requirement is not met at all.
        keep = min(
            max(1, round(len(required) * rng.uniform(0.4, 0.7))), len(required) - 1
        )
        wanted = {
            rng.choice(need.any_of): max(1, need.min_years - rng.randint(0, 2))
            for need in rng.sample(required, k=keep)
        }
        brief = []
        extras = rng.sample(nice, k=rng.randint(0, len(nice) // 2))
        role = title
    elif category is MatchCategory.ADJACENT:
        # A neighbouring job: its own skills, and one required skill in passing.
        sketch = rng.choice(profile.adjacent_roles)
        wanted = {skill: rng.randint(1, max(1, years)) for skill in sketch.skills}
        brief = [rng.choice(rng.choice(required).any_of)]
        extras = []
        role = sketch.title
    else:
        # A different job altogether: none of the vacancy's skills.
        sketch = rng.choice(profile.unrelated_roles)
        wanted = {skill: rng.randint(1, max(1, years)) for skill in sketch.skills}
        brief = []
        extras = []
        role = sketch.title

    positions = _timeline(years, role, level, as_of, rng)
    for skill, target_years in wanted.items():
        _give_recent(positions, skill, target_years, as_of)
    for skill in [*brief, *extras]:
        _give_briefly(positions, skill, as_of)
    if role == title:
        # Someone in this line of work used their main skill in every job. A
        # cloud engineer's CV with a job that names no cloud skill at all would
        # be odd, and hard to write.
        main = max(wanted, key=lambda skill: wanted[skill])
        for position in positions:
            if not position.skills:
                position.skills.append(main)

    # The ground truth is computed from the timeline as it turned out, with
    # the same arithmetic the scoring step will use on the CV.
    skill_years = years_per_skill(positions, as_of)
    vacancy_skills = profile.vacancy_skills
    first, last = name
    return Blueprint(
        index=index,
        name=f"{first} {last}",
        email=_email(first, last, index),
        phone=f"{PHONE_PREFIX}{index:03d}",
        match_category=category,
        seniority=level,
        years_experience=total_years(positions, as_of),
        positions=positions,
        skill_years=skill_years,
        tracked_skills=[skill for skill in vacancy_skills if skill in skill_years],
        avoid_skills=[skill for skill in vacancy_skills if skill not in skill_years],
        education_level=rng.choice(["Bachelor", "Bachelor", "Master"]),
        languages=[
            Language(language="Dutch", level="fluent"),
            Language(language="English", level=rng.choice(["fluent", "professional"])),
            *(
                [Language(language="German", level="basic")]
                if rng.random() < 0.25
                else []
            ),
        ],
    )


def sample_blueprints(
    n: int,
    seed: int,
    title: str,
    seniority: list[str],
    profile: VacancyProfile,
    as_of: date,
) -> list[Blueprint]:
    """Sample n candidate blueprints. Deterministic for a given seed and input."""
    rng = random.Random(seed)  # noqa: S311 - reproducible sampling, not security
    fake = Faker(["nl_NL", "en_GB"])
    fake.seed_instance(seed)

    counts = category_counts(n)
    categories = [category for category, count in counts.items() for _ in range(count)]
    rng.shuffle(categories)

    names: list[tuple[str, str]] = []
    while len(names) < n:
        name = (fake.first_name(), fake.last_name())
        if name not in names:
            names.append(name)

    return [
        _build(
            index=number,
            category=category,
            title=title,
            target_level=rng.choice(seniority),
            profile=profile,
            as_of=as_of,
            rng=rng,
            name=names[number - 1],
        )
        for number, category in enumerate(categories, start=1)
    ]
