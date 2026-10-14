"""From scores to lists: the final ranking, and who is on which list (PRD F6).

Pure functions on plain values, so the rules can be tested without a
database or a model.
"""

from dataclasses import dataclass

from app.screening.sizes import ListSizes


@dataclass(frozen=True)
class Scored[CandidateId]:
    candidate: CandidateId
    deterministic_score: float  # 0 to 1
    llm_score: int | None  # 0 to 100, None if the model did not assess
    meets_hard: bool
    # Decided by app.script.requirements.apply_requirements, nowhere else.
    listable: bool
    missed_hard: int


def final_score(
    deterministic_score: float, llm_score: int, weight_deterministic: float
) -> float:
    """Combine the two stages into one score from 0 to 1.

    `weight_deterministic` is the share of the facts computed by code. The
    model's fit score gets the rest. Both weights are configuration.
    """
    if not 0 <= weight_deterministic <= 1:
        raise ValueError("weight_deterministic must be between 0 and 1")
    combined = (
        weight_deterministic * deterministic_score
        + (1 - weight_deterministic) * llm_score / 100
    )
    return round(combined, 4)


@dataclass(frozen=True)
class Lists[CandidateId]:
    long: list[CandidateId]  # best first
    short: list[CandidateId]  # the top of the long list
    scores: dict[CandidateId, float]


def build_lists[CandidateId](
    scored: list[Scored[CandidateId]], sizes: ListSizes, weight_deterministic: float
) -> Lists[CandidateId]:
    """Rank the assessed candidates and cut the two lists.

    Only candidates the model assessed, and who are listable, can be on a
    list. Those who meet every hard requirement come first, by final score.
    Those admitted with a flag come after them, fewest missed requirements
    first. The short list is the top of the long list, so it is always a
    subset of it.
    """
    scores = {
        entry.candidate: final_score(
            entry.deterministic_score, entry.llm_score, weight_deterministic
        )
        for entry in scored
        if entry.llm_score is not None
    }
    eligible = [e for e in scored if e.candidate in scores and e.listable]
    qualified = sorted(
        (e for e in eligible if e.meets_hard), key=lambda e: -scores[e.candidate]
    )
    flagged = sorted(
        (e for e in eligible if not e.meets_hard),
        key=lambda e: (e.missed_hard, -scores[e.candidate]),
    )
    long = [e.candidate for e in (qualified + flagged)[: sizes.long]]
    return Lists(long=long, short=long[: sizes.short], scores=scores)
