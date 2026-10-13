"""Developer operations on access codes, used by scripts/manage_codes.py."""

import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.codes import generate_code, hash_code
from app.access.models import AccessCode

LABEL = re.compile(r"^c(\d+)$")
MAX_CODES_PER_RUN = 50


class UnknownLabelError(Exception):
    pass


@dataclass(frozen=True)
class NewCode:
    label: str
    code: str


@dataclass(frozen=True)
class CodeStatus:
    label: str
    uses: int
    max_uses: int
    disabled: bool
    last_used_at: datetime | None

    @property
    def remaining(self) -> int:
        return 0 if self.disabled else self.max_uses - self.uses


async def create_codes(
    session: AsyncSession, count: int, pepper: str, now: datetime, max_uses: int = 20
) -> list[NewCode]:
    """Register new codes and return them. This is the only time they are known."""
    if not 1 <= count <= MAX_CODES_PER_RUN:
        raise ValueError(f"count must be between 1 and {MAX_CODES_PER_RUN}")
    if max_uses < 1:
        raise ValueError("max_uses must be at least 1")

    rows = (await session.execute(select(AccessCode.label, AccessCode.code_hash))).all()
    taken_hashes = {row.code_hash for row in rows}
    numbers = [int(m.group(1)) for row in rows if (m := LABEL.match(row.label))]
    next_number = max(numbers, default=0) + 1

    created: list[NewCode] = []
    while len(created) < count:
        code = generate_code()
        code_hash = hash_code(code, pepper)
        if code_hash in taken_hashes:
            continue
        taken_hashes.add(code_hash)
        label = f"c{next_number + len(created):02d}"
        session.add(
            AccessCode(
                label=label, code_hash=code_hash, max_uses=max_uses, created_at=now
            )
        )
        created.append(NewCode(label=label, code=code))
    await session.flush()
    return created


async def list_status(session: AsyncSession) -> list[CodeStatus]:
    codes = (await session.scalars(select(AccessCode).order_by(AccessCode.label))).all()
    return [
        CodeStatus(
            label=code.label,
            uses=code.uses,
            max_uses=code.max_uses,
            disabled=code.disabled,
            last_used_at=code.last_used_at,
        )
        for code in codes
    ]


async def _by_label(session: AsyncSession, label: str) -> AccessCode:
    code = await session.scalar(select(AccessCode).where(AccessCode.label == label))
    if code is None:
        raise UnknownLabelError(label)
    return code


async def extend_code(session: AsyncSession, label: str, uses: int) -> CodeStatus:
    """Add redemptions to a code."""
    if uses < 1:
        raise ValueError("uses must be at least 1")
    code = await _by_label(session, label)
    code.max_uses += uses
    await session.flush()
    return CodeStatus(
        code.label, code.uses, code.max_uses, code.disabled, code.last_used_at
    )


async def disable_code(session: AsyncSession, label: str) -> None:
    """Block a code immediately. Existing sessions keep working until they expire."""
    code = await _by_label(session, label)
    code.disabled = True
    await session.flush()
