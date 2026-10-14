"""Facts about a candidate, computed by code from the blind CV (CLAUDE.md rule 4).

For each keyword of the selection script: is it in the CV, in which jobs,
and for how many years? Years come from the dated employment history, with
the same arithmetic that was used when the candidates were planted.
"""

from dataclasses import dataclass
from datetime import date

from app.candidates.schemas import Cv, CvPosition
from app.candidates.text import mentions
from app.candidates.timeline import months_covered, span, total_years
from app.script.schemas import ScriptItem


@dataclass(frozen=True)
class Snippet:
    """A place in the CV where a keyword was found: the evidence for a claim."""

    where: str  # for example "Job 1: Senior Cloud Engineer, Tulip Systems"
    text: str


@dataclass(frozen=True)
class KeywordFact:
    keyword: str
    found: bool
    # Years of the jobs that mention it. 0 if it is only named outside a job
    # (in the profile or the list of languages, for example).
    years: float
    snippets: list[Snippet]


def _job_lines(position: CvPosition) -> list[str]:
    """The text of one job, line by line. The company name is left out: a
    keyword in a company's name says nothing about what the person did."""
    lines = [position.title, *position.highlights]
    if position.skills:
        lines.append("Skills used: " + ", ".join(position.skills))
    return lines


def keyword_fact(cv: Cv, keyword: str, as_of: date) -> KeywordFact:
    """Find one keyword in the CV and compute its years of experience."""
    snippets: list[Snippet] = []
    spans = []
    for number, position in enumerate(cv.positions, start=1):
        hits = [line for line in _job_lines(position) if mentions(line, keyword)]
        if hits:
            spans.append(span(position, as_of))
            where = f"Job {number}: {position.title}, {position.company}"
            snippets += [Snippet(where=where, text=line) for line in hits]

    elsewhere = [
        ("Profile", [cv.profile]),
        ("Education", [f"{e.degree}, {e.institution}" for e in cv.education]),
        ("Languages", [f"{lang.language}: {lang.level}" for lang in cv.languages]),
    ]
    for where, lines in elsewhere:
        snippets += [
            Snippet(where=where, text=line) for line in lines if mentions(line, keyword)
        ]

    return KeywordFact(
        keyword=keyword,
        found=bool(snippets),
        years=round(months_covered(spans) / 12, 1),
        snippets=snippets,
    )


@dataclass(frozen=True)
class CandidateFacts:
    total_years: float
    keywords: dict[str, KeywordFact]

    @property
    def found_years(self) -> dict[str, float]:
        """Keyword to years, for the keywords that are in the CV at all."""
        return {k: fact.years for k, fact in self.keywords.items() if fact.found}


def script_keywords(items: list[ScriptItem]) -> list[str]:
    """Every keyword of the enabled items, each once, in script order."""
    keywords: list[str] = []
    for item in items:
        if item.enabled:
            keywords += [k for k in item.any_of if k not in keywords]
    return keywords


def candidate_facts(cv: Cv, items: list[ScriptItem], as_of: date) -> CandidateFacts:
    """Everything the script asks about, looked up in one (blind) CV."""
    return CandidateFacts(
        total_years=total_years(cv.positions, as_of),
        keywords={
            keyword: keyword_fact(cv, keyword, as_of)
            for keyword in script_keywords(items)
        },
    )
