"""Finding a skill name in text."""

import re


def mentions(text: str, term: str) -> bool:
    """True if `term` occurs in `text` as a whole word or phrase, ignoring case.

    "Java" is not found in "JavaScript", but "AWS" is found in "AWS CDK".
    """
    pattern = r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])"
    return re.search(pattern, text, re.IGNORECASE) is not None


def overlap(first: str, second: str) -> bool:
    """True if one name contains the other, so naming one also names the other."""
    return mentions(first, second) or mentions(second, first)
