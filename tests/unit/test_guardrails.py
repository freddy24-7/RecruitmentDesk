import pytest

from app.vacancy.guardrails import find_flags
from app.vacancy.schemas import VacancySections


def sections(**changes: object) -> VacancySections:
    base: dict[str, object] = {
        "title": "Cloud Engineer",
        "company_intro": "A fictional company in Utrecht.",
        "role_summary": "You build and run cloud platforms with a small team.",
        "responsibilities": ["Design cloud infrastructure", "Review code"],
        "required_qualifications": [
            "3 years of experience with Microsoft Azure",
            "Fluent in English",
        ],
        "nice_to_haves": ["Experience with Terraform"],
        "what_we_offer": ["A healthy work-life balance", "A single point of contact"],
        "location_and_work_mode": "Utrecht, hybrid.",
    }
    return VacancySections.model_validate(base | changes)


def test_a_normal_vacancy_has_no_flags() -> None:
    assert find_flags(sections()) == []


@pytest.mark.parametrize(
    ("text", "term", "attribute"),
    [
        ("We are looking for a young professional", "young", "age"),
        ("You are a digital native", "digital native", "age"),
        ("Candidates under 35 preferred", "under 35", "age"),
        ("Between 25-35 years old", "25-35 years old", "age"),
        ("Native speaker of Dutch", "native speaker", "origin"),
        ("Native English speaker", "native english speaker", "origin"),
        ("Dutch nationality required", "nationality", "nationality"),
        ("EU citizens only", "eu citizens", "nationality"),
        ("We prefer a female colleague", "female", "gender"),
        ("An experienced salesman", "salesman", "gender"),
        ("Unmarried and flexible", "unmarried", "family status"),
        ("Physically fit", "physically fit", "health"),
    ],
)
def test_obvious_discriminatory_terms_are_flagged(
    text: str, term: str, attribute: str
) -> None:
    flags = find_flags(sections(required_qualifications=[text]))

    assert [(f.section, f.term, f.attribute) for f in flags] == [
        ("required_qualifications", term, attribute)
    ]


def test_flags_name_the_section_and_are_not_repeated() -> None:
    flags = find_flags(
        sections(
            role_summary="A young team. Young at heart.",
            required_qualifications=["Native speaker"],
        )
    )

    assert [(f.section, f.term) for f in flags] == [
        ("role_summary", "young"),
        ("required_qualifications", "native speaker"),
    ]


def test_similar_but_harmless_words_are_not_flagged() -> None:
    harmless = sections(
        required_qualifications=[
            "Experience with change management",
            "Knowledge of human resources systems",
            "Experience managing a team of ten",
        ]
    )

    assert find_flags(harmless) == []
