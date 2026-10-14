"""Blind screening: what the scoring and assessment steps are allowed to see.

They get an anonymised CV: no name, email, phone or other personal details
(CLAUDE.md rule 3). Our generated CVs hold none by construction. This module
still removes them, so the guarantee does not rest on that alone: a CV from
any other source would be cleaned in the same way.
"""

import re

from app.candidates.cv import render_text
from app.candidates.schemas import Cv

REMOVED = "[removed]"

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
# A run of at least nine digits, with the usual separators in between.
_PHONE = re.compile(r"(?<![\w.])\+?\d(?:[\s().-]?\d){8,}(?!\w)")


def _name_parts(name: str) -> list[str]:
    """The whole name, and each part of it that is long enough to be a name."""
    parts = [part for part in re.split(r"\s+", name.strip()) if len(part) >= 3]
    # Longest first, so "van der Veen" goes before "van".
    return sorted({name.strip(), *parts} - {""}, key=len, reverse=True)


def anonymise(text: str, *, name: str, email: str, phone: str) -> str:
    """Remove this person's identifiers, and anything that looks like contact data."""
    for identifier in (email, phone, *_name_parts(name)):
        if identifier:
            pattern = r"(?<!\w)" + re.escape(identifier) + r"(?!\w)"
            text = re.sub(pattern, REMOVED, text, flags=re.IGNORECASE)
    for contact in (_EMAIL, _URL, _PHONE):
        text = contact.sub(REMOVED, text)
    return text


def blind_cv(cv: Cv, *, name: str, email: str, phone: str) -> Cv:
    """The CV with every free-text field anonymised. Dates and structure stay."""

    def clean(text: str) -> str:
        return anonymise(text, name=name, email=email, phone=phone)

    return cv.model_copy(
        update={
            "profile": clean(cv.profile),
            "positions": [
                position.model_copy(
                    update={
                        "title": clean(position.title),
                        "company": clean(position.company),
                        "highlights": [clean(h) for h in position.highlights],
                        "skills": [clean(s) for s in position.skills],
                    }
                )
                for position in cv.positions
            ],
            "education": [
                education.model_copy(
                    update={
                        "degree": clean(education.degree),
                        "institution": clean(education.institution),
                    }
                )
                for education in cv.education
            ],
            "skills": [clean(skill) for skill in cv.skills],
        }
    )


def blind_text(cv: Cv, *, name: str, email: str, phone: str) -> str:
    """The anonymised CV as text: the only form of a CV a model ever reads."""
    return render_text(blind_cv(cv, name=name, email=email, phone=phone))
