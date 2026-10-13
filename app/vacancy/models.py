"""The vacancy table (PRD section 9)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

GENERATING = "generating"
DRAFT = "draft"
SUBMITTED = "submitted"
FAILED = "failed"


class Vacancy(Base):
    __tablename__ = "vacancy"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), default=GENERATING)
    # The choices from the dialog (VacancyParameters).
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # The current text (VacancySections), and the text as the model wrote it,
    # kept for "Reset to generated".
    sections: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    generated_sections: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Terms flagged by the guardrail check, for a person to review.
    flags: Mapped[list[dict[str, str]]] = mapped_column(JSONB, default=list)
    version: Mapped[int] = mapped_column(default=0)
    # Which prompt file and model produced the text.
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
