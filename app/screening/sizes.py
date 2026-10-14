"""How long the lists are. The only place that decides this (CLAUDE.md rule 6)."""

from dataclasses import dataclass

LONG_SHARE_PERCENT = 30
SHORT_SHARE_PERCENT = 10
LONG_MAX = 10
SHORT_MAX = 4


@dataclass(frozen=True)
class ListSizes:
    long: int
    short: int


def _share(candidates: int, percent: int) -> int:
    """`percent` of `candidates`, rounded half up, in whole numbers only.

    Not Python's `round`, which rounds half to even (2.5 becomes 2), and not
    floating point, where 0.30 x 15 is not exactly 4.5.
    """
    return (candidates * percent + 50) // 100


def list_sizes(candidates: int) -> ListSizes:
    """Long list: about 30%, at most 10. Short list: about 10%, at most 4.

    Both have at least one entry, and neither is longer than the pool. The
    short list is never longer than the long list, of which it is the top.
    """
    if candidates < 1:
        raise ValueError("there must be at least one candidate")
    long = min(LONG_MAX, max(1, _share(candidates, LONG_SHARE_PERCENT)), candidates)
    short = min(SHORT_MAX, max(1, _share(candidates, SHORT_SHARE_PERCENT)), long)
    return ListSizes(long=long, short=short)
