"""The interview_question_set table (PRD section 9)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class QuestionSet(Base):
    """The core questions of a vacancy, or the follow-ups for one candidate."""

    __tablename__ = "interview_question_set"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    vacancy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vacancy.id", ondelete="CASCADE"), index=True
    )
    # Empty for the core set. Follow-ups go with their candidate.
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("candidate.id", ondelete="CASCADE"), index=True
    )
    # The interview-questions job that made the set.
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("job.id", ondelete="CASCADE"))
    # What the questions were made from. If any of it changed since, the
    # questions are out of date.
    vacancy_version: Mapped[int]
    script_revision: Mapped[int]
    screening_run_id: Mapped[uuid.UUID]
    # Reference ("S1", "P2", "C1") to {"kind": ..., "text": ...}: everything a
    # question in this set may be based on.
    sources: Mapped[dict[str, Any]] = mapped_column(JSONB)
    questions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    # As the model wrote them (after the checks), for "Reset to generated".
    generated_questions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    # Questions dropped because their source did not exist.
    dropped: Mapped[list[dict[str, str]]] = mapped_column(JSONB, default=list)
    prompt_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
