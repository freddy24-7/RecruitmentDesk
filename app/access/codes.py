"""Access codes: format, generation and keyed hashing (PRD F0).

A code is never stored or logged. Only its HMAC-SHA256 hash, keyed with a
pepper from the environment, is kept in the database.
"""

import hashlib
import hmac
import secrets

# Uppercase A to Z without I and O, which are easily confused with 1 and 0.
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ"
CODE_LENGTH = 5


def generate_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def normalize(raw: str) -> str:
    """Input is case-insensitive and ignores surrounding spaces."""
    return raw.strip().upper()


def is_well_formed(code: str) -> bool:
    return len(code) == CODE_LENGTH and all(letter in ALPHABET for letter in code)


def _keyed_hash(value: str, pepper: str) -> str:
    return hmac.new(pepper.encode(), value.encode(), hashlib.sha256).hexdigest()


def hash_code(code: str, pepper: str) -> str:
    return _keyed_hash("code:" + code, pepper)


def hash_ip(ip: str, pepper: str) -> str:
    """IP addresses are personal data, so only a keyed hash is stored."""
    return _keyed_hash("ip:" + ip, pepper)
