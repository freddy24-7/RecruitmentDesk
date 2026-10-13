"""One row per model call: what it was for, how long it took, what it cost."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

OUTCOME_OK = "ok"
OUTCOME_INVALID_OUTPUT = "invalid_output"


class UsageRecord(Base):
    __tablename__ = "usage_record"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Kept when the workspace or job is deleted: the cost was still made.
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspace.id", ondelete="SET NULL"), index=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL")
    )
    call_type: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(32))
    input_tokens: Mapped[int]
    output_tokens: Mapped[int]
    latency_ms: Mapped[int]
    estimated_cost: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
