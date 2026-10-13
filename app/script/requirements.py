"""Hard and soft requirements, applied in one place (CLAUDE.md rule 5).

Every step that decides who may be listed goes through `apply_requirements`.

- A **hard** requirement must be met for a candidate to be listed. If too few
  candidates meet all hard requirements, the best of the others are listed
  too, with a visible flag that says which requirement they miss.
- A **soft** requirement only adds to the score.

The input is facts, not claims: for each candidate, the keywords that were
found in the CV and the years of experience computed for each from the dated
employment history. This module does no text matching itself.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

from app.script.schemas import Kind, ScriptItem

# A hard requirement counts double in the score.
HARD_WEIGHT = 2.0
SOFT_WEIGHT = 1.0
# A keyword that is there, but for too few years, earns at most this share.
SHORT_OF_YEARS_SHARE = 0.5


@dataclass(frozen=True)
class ItemResult:
    """How one candidate does on one script item."""

    item: int  # position of the item in the script
    kind: Kind
    met: bool
    # The alternative that counted: the one with the most years. None if no
    # alternative was found in the CV.
    keyword: str | None
    years: float
    min_years: int


@dataclass(frozen=True)
class Outcome:
    """How one candidate does on the whole script."""

    results: list[ItemResult]
    score: float  # 0 to 1

    @property
    def missed_hard(self) -> list[ItemResult]:
        return [r for r in self.results if r.kind is Kind.HARD and not r.met]

    @property
    def meets_hard(self) -> bool:
        return not self.missed_hard


@dataclass(frozen=True)
class Ranked[CandidateId]:
    candidate: CandidateId
    outcome: Outcome
    # True if the candidate may be listed.
    listable: bool
    # Set when the candidate is listable although a hard requirement is not
    # met, because too few candidates meet them all. Shown to the recruiter.
    missed_hard: list[ItemResult] = field(default_factory=list)

    @property
    def flagged(self) -> bool:
        return bool(self.missed_hard)


def check(items: list[ScriptItem], found_years: Mapping[str, float]) -> Outcome:
    """Compare one candidate's facts with the script.

    `found_years` maps a keyword to the years of experience computed for it.
    A keyword that is not in the mapping was not found in the CV. Keywords are
    compared without regard to case.
    """
    found = {keyword.lower(): years for keyword, years in found_years.items()}
    results = []
    earned = 0.0
    possible = 0.0
    for position, item in enumerate(items):
        if not item.enabled:
            continue
        # Any one alternative is enough. Years are not added up across
        # alternatives: the best single one counts.
        keyword: str | None = None
        years = 0.0
        for alternative in item.any_of:
            if alternative.lower() in found and (
                keyword is None or found[alternative.lower()] > years
            ):
                keyword, years = alternative, found[alternative.lower()]
        met = keyword is not None and years >= item.min_years
        results.append(
            ItemResult(
                item=position,
                kind=item.kind,
                met=met,
                keyword=keyword,
                years=years,
                min_years=item.min_years,
            )
        )
        weight = HARD_WEIGHT if item.kind is Kind.HARD else SOFT_WEIGHT
        possible += weight
        if met:
            earned += weight
        elif keyword is not None and item.min_years > 0:
            earned += weight * SHORT_OF_YEARS_SHARE * min(years / item.min_years, 1.0)
    return Outcome(results=results, score=earned / possible if possible else 0.0)


def apply_requirements[CandidateId](
    items: list[ScriptItem],
    facts: Mapping[CandidateId, Mapping[str, float]],
    needed: int,
) -> list[Ranked[CandidateId]]:
    """Rank all candidates and decide who may be listed.

    `needed` is how many candidates the list wants. The result is ordered,
    best first: candidates who meet every hard requirement by score, then the
    others by how few hard requirements they miss and then by score. Ties keep
    the order of `facts`.

    Candidates who meet every hard requirement are listable. Only if there
    are fewer of them than `needed` do the best of the others become
    listable too, each with the requirements they miss as a flag.
    """
    outcomes = {candidate: check(items, found) for candidate, found in facts.items()}
    order = list(facts)
    qualified = sorted(
        (c for c in order if outcomes[c].meets_hard),
        key=lambda c: -outcomes[c].score,
    )
    others = sorted(
        (c for c in order if not outcomes[c].meets_hard),
        key=lambda c: (len(outcomes[c].missed_hard), -outcomes[c].score),
    )
    shortfall = max(needed - len(qualified), 0)

    ranked = [
        Ranked(candidate=c, outcome=outcomes[c], listable=True) for c in qualified
    ]
    for position, candidate in enumerate(others):
        admitted = position < shortfall
        ranked.append(
            Ranked(
                candidate=candidate,
                outcome=outcomes[candidate],
                listable=admitted,
                missed_hard=outcomes[candidate].missed_hard if admitted else [],
            )
        )
    return ranked
