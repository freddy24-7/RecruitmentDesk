"""Brute-force protection for the code entry endpoint (PRD F0).

There are roughly 8 million possible codes and only 10 valid ones. Guessing
is impractical only because failed attempts are limited: per IP, and with a
global ceiling for an attacker who spreads guesses over many addresses.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.models import FailedAttempt
from app.config import Settings

GLOBAL_WINDOW = timedelta(hours=1)


@dataclass(frozen=True)
class AttemptLimits:
    per_ip: int
    per_ip_window: timedelta
    global_per_hour: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "AttemptLimits":
        return cls(
            per_ip=settings.failed_attempts_per_ip,
            per_ip_window=timedelta(minutes=settings.failed_attempts_window_minutes),
            global_per_hour=settings.failed_attempts_global_per_hour,
        )


async def _failures_since(
    session: AsyncSession, since: datetime, ip_hash: str | None = None
) -> int:
    query = (
        select(func.count())
        .select_from(FailedAttempt)
        .where(FailedAttempt.attempted_at > since)
    )
    if ip_hash is not None:
        query = query.where(FailedAttempt.ip_hash == ip_hash)
    return await session.scalar(query) or 0


async def is_locked_out(
    session: AsyncSession, ip_hash: str, limits: AttemptLimits, now: datetime
) -> bool:
    """True if this address, or everyone, has to wait before trying again."""
    per_ip = await _failures_since(session, now - limits.per_ip_window, ip_hash)
    if per_ip >= limits.per_ip:
        return True
    return await _failures_since(session, now - GLOBAL_WINDOW) >= limits.global_per_hour


async def record_failure(session: AsyncSession, ip_hash: str, now: datetime) -> None:
    """Store one failed attempt. The caller commits."""
    session.add(FailedAttempt(ip_hash=ip_hash, attempted_at=now))
    await session.flush()
