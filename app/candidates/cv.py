"""From a blueprint and the model's prose to a CV (PRD F4).

The model writes the profile, job titles, company names, highlights and
education. Dates, the skills per job, languages and contact details come
from the blueprint, so the facts in a CV are exactly the planted ones.
"""

import re

from app.candidates.schemas import (
    Blueprint,
    Cv,
    CvEducation,
    CvPosition,
    CvText,
)
from app.candidates.text import mentions

# Personal details a CV must not contain (PRD F4). Checked in the model's
# text; an answer that contains one is treated as invalid output.
FORBIDDEN_PERSONAL = [
    r"\bdate of birth\b",
    r"\bborn (in|on)\b",
    r"\b\d{1,2} years old\b",
    r"\bage:?\s*\d",
    r"\bgender\b",
    r"\b(male|female)\b",
    r"\bmarital status\b",
    r"\b(married|unmarried|divorced)\b",
    r"\bnationality\b",
    r"\bphoto(graph)?\b",
]
_FORBIDDEN = [re.compile(pattern, re.IGNORECASE) for pattern in FORBIDDEN_PERSONAL]


def _all_text(written: CvText) -> str:
    parts = [written.profile]
    for position in written.positions:
        parts += [position.title, position.company, *position.highlights]
    for education in written.education:
        parts += [education.degree, education.institution]
    return "\n".join(parts)


def problems_in(written: CvText, blueprint: Blueprint) -> list[str]:
    """Why the model's text cannot be used for this blueprint. Empty if it can.

    Returns kinds, never the text itself, so the result is safe to log.
    """
    found = []
    if len(written.positions) != len(blueprint.positions):
        found.append("wrong_number_of_positions")
    text = _all_text(written)
    if any(pattern.search(text) for pattern in _FORBIDDEN):
        found.append("personal_details")
    # A skill the candidate does not have must not appear: it would make the
    # planted match category wrong.
    if any(mentions(text, skill) for skill in blueprint.avoid_skills):
        found.append("mentions_missing_skill")
    # A skill must only be named in the jobs where it was used. Years of
    # experience are later computed from the dated jobs that mention it.
    # Only the vacancy's skills are tracked this way. The everyday skills of
    # another job ("monitoring") may turn up anywhere.
    held = set(blueprint.tracked_skills)
    for text_part, planned in zip(written.positions, blueprint.positions, strict=False):
        # Highlights only: a job title may legitimately contain a skill name.
        job_text = "\n".join(text_part.highlights)
        elsewhere = held - set(planned.skills)
        if any(mentions(job_text, skill) for skill in elsewhere):
            found.append("skill_in_wrong_position")
            break
    return found


def assemble(written: CvText, blueprint: Blueprint) -> Cv:
    """Join the model's prose with the facts from the blueprint."""
    positions = [
        CvPosition(
            title=text.title,
            company=text.company,
            start=planned.start,
            end=planned.end,
            highlights=text.highlights,
            skills=planned.skills,
        )
        for text, planned in zip(written.positions, blueprint.positions, strict=True)
    ]
    # Graduated in the year the first job started.
    graduation = int(blueprint.positions[-1].start[:4])
    skills: list[str] = []
    for position in positions:
        skills += [skill for skill in position.skills if skill not in skills]
    return Cv(
        profile=written.profile,
        positions=positions,
        education=[
            CvEducation(
                degree=education.degree,
                institution=education.institution,
                year=graduation - 3 * number,
            )
            for number, education in enumerate(written.education)
        ],
        skills=skills,
        languages=blueprint.languages,
    )


def _period(start: str, end: str | None) -> str:
    return f"{start} to {end or 'present'}"


def render_text(cv: Cv) -> str:
    """The CV as plain text. No name and no contact details: it is blind."""
    lines = ["PROFILE", cv.profile, "", "EMPLOYMENT"]
    for position in cv.positions:
        lines.append(
            f"{position.title}, {position.company} "
            f"({_period(position.start, position.end)})"
        )
        lines += [f"- {highlight}" for highlight in position.highlights]
        if position.skills:
            lines.append("Skills used: " + ", ".join(position.skills))
        lines.append("")
    lines.append("EDUCATION")
    lines += [
        f"{education.degree}, {education.institution} ({education.year})"
        for education in cv.education
    ]
    lines += ["", "SKILLS", ", ".join(cv.skills), "", "LANGUAGES"]
    lines += [f"{language.language}: {language.level}" for language in cv.languages]
    return "\n".join(lines)
