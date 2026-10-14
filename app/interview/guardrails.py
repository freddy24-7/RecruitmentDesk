"""A simple check for interview questions that touch a protected attribute (PRD F8).

The prompt forbids questions about age, gender, family or pregnancy plans,
health, religion, nationality or origin. This is the check in code: a short
list of terms that are flagged for a person to review, as for vacancies. It
does not block anything, and it is not a complete test.
"""

import re

from app.vacancy.guardrails import TERMS

# Phrases that are typical of a question, on top of the vacancy terms.
QUESTION_TERMS: list[tuple[str, str]] = [
    (r"\bhow old\b", "age"),
    (r"\b(date|year) of birth\b", "age"),
    (r"\bwhen were you born\b", "age"),
    (r"\bretire(ment)?\b", "age"),
    (r"\b(children|kids|pregnan\w*|family plans?|plan to have)\b", "family"),
    (r"\b(husband|wife|spouse|boyfriend|girlfriend)\b", "family status"),
    (r"\bwhere are you (originally )?from\b", "origin"),
    (r"\b(born in|country of origin|first language|mother tongue)\b", "origin"),
    (r"\b(citizenship|passport|nationality)\b", "nationality"),
    (r"\b(religio\w*|church|mosque|pray\w*)\b", "religion"),
    # Personal health only: a nurse may well be asked about health care.
    (
        r"\b(your health|health (problems|issues|condition)|sick leave|disabilit\w*)\b",
        "health",
    ),
    (r"\b(sexual orientation|gay|lesbian)\b", "sexual orientation"),
]

_COMPILED = [
    (re.compile(pattern, re.IGNORECASE), attribute)
    for pattern, attribute in [*TERMS, *QUESTION_TERMS]
]


def flags_for(text: str) -> list[str]:
    """Each flagged term, as "term (attribute)", once."""
    found: list[str] = []
    for pattern, attribute in _COMPILED:
        for match in pattern.finditer(text):
            flag = f"{match.group(0).lower()} ({attribute})"
            if flag not in found:
                found.append(flag)
    return found
