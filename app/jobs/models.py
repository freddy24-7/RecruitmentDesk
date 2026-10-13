"""Background jobs are stored in the database, so their state survives a reload."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
INTERRUPTED = "interrupted"

ACTIVE = (QUEUED, RUNNING)
RETRYABLE = (FAILED, INTERRUPTED)

# Error kinds that do not come from the model (those are in app/llm/base.py).
ERROR_INTERRUPTED = "interrupted"
ERROR_INTERNAL = "internal"


class Job(Base):
    __tablename__ = "job"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(32))
    vacancy_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("vacancy.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), default=QUEUED)
    # How often the job was started. Each start can cost model calls, so the
    # workspace limits count starts, not jobs.
    attempts: Mapped[int] = mapped_column(default=1)
    # What the job was asked to do (for example how many candidates).
    params: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    progress_done: Mapped[int] = mapped_column(default=0)
    progress_total: Mapped[int] = mapped_column(default=1)
    error_kind: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
