"""Redeeming an access code: one redemption is one new workspace (PRD F0)."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.codes import hash_code, is_well_formed, normalize
from app.access.models import AccessCode, Workspace


class RedeemFailure(StrEnum):
    INVALID = "invalid"
    EXHAUSTED = "exhausted"


@dataclass(frozen=True)
class Redeemed:
    workspace: Workspace
    code_label: str


async def redeem_code(
    session: AsyncSession,
    raw_code: str,
    pepper: str,
    now: datetime,
    ip_hash: str | None = None,
) -> Redeemed | RedeemFailure:
    """Count one use of the code and create a workspace. The caller commits."""
    code = normalize(raw_code)
    if not is_well_formed(code):
        return RedeemFailure.INVALID
    code_hash = hash_code(code, pepper)

    # A single conditional update. PostgreSQL locks the row, so simultaneous
    # requests are counted one after another and can never pass max_uses.
    result = await session.execute(
        update(AccessCode)
        .where(
            AccessCode.code_hash == code_hash,
            AccessCode.disabled.is_(False),
            AccessCode.uses < AccessCode.max_uses,
        )
        .values(uses=AccessCode.uses + 1, last_used_at=now)
        .returning(AccessCode.id, AccessCode.label)
    )
    row = result.first()

    if row is None:
        # A disabled code is reported as invalid: it reveals nothing.
        known = await session.scalar(
            select(AccessCode.id).where(
                AccessCode.code_hash == code_hash, AccessCode.disabled.is_(False)
            )
        )
        return RedeemFailure.EXHAUSTED if known is not None else RedeemFailure.INVALID

    workspace = Workspace(
        access_code_id=row.id, created_at=now, last_seen_at=now, ip_hash=ip_hash
    )
    session.add(workspace)
    await session.flush()
    return Redeemed(workspace=workspace, code_label=row.label)
