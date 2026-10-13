"""Years of experience, computed from dated employment history (CLAUDE.md rule 4).

Facts are computed by code, not claimed by the model. This module is used
when blueprints are sampled, and again when CVs are scored: the same
arithmetic on both sides.
"""

from collections.abc import Iterable
from datetime import date
from typing import Protocol

MONTH_FORMAT_LENGTH = 7  # "YYYY-MM"


class DatedPosition(Protocol):
    """Anything with a start month, an optional end month, and skills."""

    @property
    def start(self) -> str: ...
    @property
    def end(self) -> str | None: ...
    @property
    def skills(self) -> list[str]: ...


def month_index(month: str) -> int:
    """A "YYYY-MM" month as a count of months, so months can be subtracted."""
    if len(month) != MONTH_FORMAT_LENGTH or month[4] != "-":
        raise ValueError(f"not a YYYY-MM month: {month!r}")
    year, number = int(month[:4]), int(month[5:])
    if not 1 <= number <= 12:
        raise ValueError(f"not a YYYY-MM month: {month!r}")
    return year * 12 + (number - 1)


def month_of(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def add_months(month: str, months: int) -> str:
    index = month_index(month) + months
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _months_covered(spans: Iterable[tuple[int, int]]) -> int:
    """Months covered by a set of spans. Overlapping jobs are not counted twice."""
    covered: set[int] = set()
    for first, last in spans:
        covered.update(range(first, last + 1))
    return len(covered)


def _span(position: DatedPosition, as_of: date) -> tuple[int, int]:
    """First and last month of a position, both included. No end means "now"."""
    first = month_index(position.start)
    last = month_index(position.end or month_of(as_of))
    return first, max(first, last)


def _years(months: int) -> float:
    return round(months / 12, 1)


def total_years(positions: Iterable[DatedPosition], as_of: date) -> float:
    """Years of work experience over all positions."""
    return _years(_months_covered(_span(position, as_of) for position in positions))


def years_per_skill(
    positions: Iterable[DatedPosition], as_of: date
) -> dict[str, float]:
    """For each skill, the years in which a position used it."""
    spans: dict[str, list[tuple[int, int]]] = {}
    for position in positions:
        for skill in position.skills:
            spans.setdefault(skill, []).append(_span(position, as_of))
    return {skill: _years(_months_covered(found)) for skill, found in spans.items()}
