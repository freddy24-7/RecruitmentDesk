"""The evidence check: the model's claims are checked by code (CLAUDE.md rule 4).

The model reads the blind CV and says what it found. Nothing it says is
shown to the recruiter on trust:

- a keyword it says it found must appear in the CV;
- a number of years it states is compared with the years computed from the
  dated employment history;
- a strength must rest on keywords that are in the CV, a concern on keywords
  that are not;
- a sentence of its reasoning that names a keyword the CV does not contain,
  or a number of years that matches nothing computed, is removed.

What fails is removed or corrected, and flagged. It is the same principle
as resolving citations in code.
"""

import re
from dataclasses import dataclass, field
from datetime import date

from app.candidates.schemas import Cv
from app.candidates.text import mentions
from app.screening.facts import keyword_fact
from app.screening.schemas import ModelAssessment

# Flag kinds. They are stored and shown; the details name keywords and
# numbers, never CV text.
KEYWORD_NOT_IN_CV = "keyword_not_in_cv"
YEARS_CORRECTED = "years_corrected"
STRENGTH_UNSUPPORTED = "strength_unsupported"
CONCERN_CONTRADICTED = "concern_contradicted"
SENTENCE_UNSUPPORTED = "sentence_unsupported"

# A stated number of years may differ this much from the computed one.
YEARS_TOLERANCE = 1.0

_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_YEARS = re.compile(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Flag:
    kind: str
    detail: str


@dataclass(frozen=True)
class CheckedClaim:
    keyword: str
    years: float  # the computed years, whatever the model said


@dataclass(frozen=True)
class CheckedAssessment:
    """What is left of the model's assessment after the check."""

    fit_score: int
    found: list[CheckedClaim]
    strengths: list[str]
    concerns: list[str]
    reasoning: str
    flags: list[Flag] = field(default_factory=list)
    # How many of the model's keyword and years claims were made, and how many
    # held. Kept for the evaluation of evidence accuracy.
    claims_made: int = 0
    claims_supported: int = 0


def _close(stated: float, computed: float) -> bool:
    return abs(stated - computed) <= YEARS_TOLERANCE


def check_assessment(
    assessment: ModelAssessment,
    cv: Cv,
    cv_text: str,
    script_keywords: list[str],
    as_of: date,
    total_years: float,
) -> CheckedAssessment:
    """Check every claim against the blind CV. `cv_text` is that CV as text."""
    flags: list[Flag] = []
    made = supported = 0

    # 1. Keywords the model says it found, and the years it states for them.
    found: list[CheckedClaim] = []
    for claim in assessment.found:
        made += 1
        if not mentions(cv_text, claim.keyword):
            flags.append(Flag(KEYWORD_NOT_IN_CV, claim.keyword))
            continue
        supported += 1
        computed = keyword_fact(cv, claim.keyword, as_of).years
        made += 1
        if _close(claim.years, computed):
            supported += 1
        else:
            flags.append(
                Flag(
                    YEARS_CORRECTED,
                    f"{claim.keyword}: stated {claim.years:g}, computed {computed:g}",
                )
            )
        if not any(c.keyword.lower() == claim.keyword.lower() for c in found):
            found.append(CheckedClaim(keyword=claim.keyword, years=computed))

    # 2. Strengths rest on keywords the candidate has.
    strengths = []
    for point in assessment.strengths:
        missing = [k for k in point.keywords if not mentions(cv_text, k)]
        if missing:
            flags.append(Flag(STRENGTH_UNSUPPORTED, ", ".join(missing)))
        else:
            strengths.append(point.text)

    # 3. Concerns rest on keywords the candidate lacks.
    concerns = []
    for point in assessment.concerns:
        present = [k for k in point.keywords if mentions(cv_text, k)]
        if present:
            flags.append(Flag(CONCERN_CONTRADICTED, ", ".join(present)))
        else:
            concerns.append(point.text)

    # 4. The reasoning, sentence by sentence.
    absent = [k for k in script_keywords if not mentions(cv_text, k)]
    known_years = [total_years, *(claim.years for claim in found)]
    kept = []
    for sentence in _SENTENCE.split(assessment.reasoning):
        named_absent = [k for k in absent if mentions(sentence, k)]
        stated = [float(number) for number in _YEARS.findall(sentence)]
        unmatched = [
            years
            for years in stated
            if not any(_close(years, known) for known in known_years)
        ]
        if named_absent:
            flags.append(Flag(SENTENCE_UNSUPPORTED, ", ".join(named_absent)))
        elif unmatched:
            detail = ", ".join(f"{years:g} years" for years in unmatched)
            flags.append(Flag(SENTENCE_UNSUPPORTED, detail))
        elif sentence.strip():
            kept.append(sentence.strip())

    return CheckedAssessment(
        fit_score=assessment.fit_score,
        found=found,
        strengths=strengths,
        concerns=concerns,
        reasoning=" ".join(kept),
        flags=flags,
        claims_made=made,
        claims_supported=supported,
    )
