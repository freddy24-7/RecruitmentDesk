import pytest

from app.access.codes import (
    ALPHABET,
    CODE_LENGTH,
    generate_code,
    hash_code,
    hash_ip,
    is_well_formed,
    normalize,
)

PEPPER = "fake-pepper-for-tests-only-0123456789abcdef"


def test_alphabet_is_a_to_z_without_i_and_o() -> None:
    assert len(ALPHABET) == 24
    assert "I" not in ALPHABET
    assert "O" not in ALPHABET
    assert "".join(sorted(set(ALPHABET))) == ALPHABET


def test_generated_codes_are_five_letters_from_the_alphabet() -> None:
    codes = {generate_code() for _ in range(500)}

    assert all(len(code) == CODE_LENGTH for code in codes)
    assert all(set(code) <= set(ALPHABET) for code in codes)
    # Random: 500 draws from about 8 million possibilities hardly ever repeat.
    assert len(codes) > 490


@pytest.mark.parametrize(
    ("typed", "expected"),
    [("testa", "TESTA"), ("  TESTA ", "TESTA"), ("\tTeStA\n", "TESTA")],
)
def test_normalize_ignores_case_and_surrounding_spaces(
    typed: str, expected: str
) -> None:
    assert normalize(typed) == expected


@pytest.mark.parametrize(
    "code", ["", "TEST", "TESTAA", "TEST1", "TESTI", "TESTO", "TE TA", "testa"]
)
def test_malformed_codes_are_recognised(code: str) -> None:
    assert not is_well_formed(code)


def test_hash_is_keyed_and_does_not_contain_the_code() -> None:
    digest = hash_code("TESTA", PEPPER)

    assert digest == hash_code("TESTA", PEPPER)
    assert digest != hash_code("TESTA", "another-pepper-for-tests-0123456789abcdef")
    assert digest != hash_code("FAKEB", PEPPER)
    assert len(digest) == 64
    assert "TESTA" not in digest


def test_code_and_ip_hashes_cannot_be_confused() -> None:
    assert hash_code("TESTA", PEPPER) != hash_ip("TESTA", PEPPER)
