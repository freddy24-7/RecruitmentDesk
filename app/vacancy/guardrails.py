"""A simple check for obviously discriminatory wording in a vacancy (PRD F1).

The prompt already forbids such requirements. This is the check in code:
a short list of terms that are flagged for a person to review. It does not
block anything, and it is not a complete test for discrimination.
"""

import re

from pydantic import BaseModel

from app.vacancy.schemas import VacancySections

# (pattern, the protected attribute it may point at)
TERMS: list[tuple[str, str]] = [
    (r"\byoung\b", "age"),
    (r"\byouthful\b", "age"),
    (r"\bdigital native\b", "age"),
    (r"\brecent graduates? only\b", "age"),
    (r"\b(under|below|younger than|max(imum)?( age)?( of)?) \d{2}\b", "age"),
    (r"\b\d{2}\s*(-|to)\s*\d{2} years old\b", "age"),
    (r"\bage (limit|range|between)\b", "age"),
    (r"\b(male|female|man|woman|men|women)\b", "gender"),
    (r"\b(salesman|chairman|waitress|handyman)\b", "gender"),
    (r"\bnative (english |dutch )?speaker\b", "origin"),
    (r"\bmother tongue\b", "origin"),
    (r"\bnationality\b", "nationality"),
    (r"\b(dutch|eu|european) (citizens?|nationals?|passport)\b", "nationality"),
    (r"\b(married|unmarried|no children|without children)\b", "family status"),
    (r"\b(christian|muslim|jewish|hindu|religious)\b", "religion"),
    (r"\b(able-bodied|physically fit|in good health)\b", "health"),
]

_COMPILED = [(re.compile(pattern, re.IGNORECASE), kind) for pattern, kind in TERMS]


class Flag(BaseModel):
    section: str
    term: str
    attribute: str


def find_flags(sections: VacancySections) -> list[Flag]:
    """Return every flagged term, with the section it was found in."""
    flags: list[Flag] = []
    for section, value in sections.model_dump().items():
        text = " \n ".join(value) if isinstance(value, list) else str(value)
        for pattern, attribute in _COMPILED:
            for match in pattern.finditer(text):
                flag = Flag(
                    section=section, term=match.group(0).lower(), attribute=attribute
                )
                if flag not in flags:
                    flags.append(flag)
    return flags
