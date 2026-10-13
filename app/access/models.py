"""Tables for the access gate (PRD section 9)."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AccessCode(Base):
    __tablename__ = "access_code"
    __table_args__ = (
        # A second line of defence behind the conditional update in service.py.
        CheckConstraint("uses >= 0 AND uses <= max_uses", name="uses_within_limit"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(16), unique=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    uses: Mapped[int] = mapped_column(default=0)
    max_uses: Mapped[int] = mapped_column(default=20)
    disabled: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FailedAttempt(Base):
    """One failed code entry. The submitted code is not stored."""

    __tablename__ = "failed_attempt"

    id: Mapped[int] = mapped_column(primary_key=True)
    ip_hash: Mapped[str] = mapped_column(String(64), index=True)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Workspace(Base):
    """A visitor's private workspace. Its id is what the session cookie holds."""

    __tablename__ = "workspace"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    access_code_id: Mapped[int] = mapped_column(ForeignKey("access_code.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
