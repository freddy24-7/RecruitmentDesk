"""The candidate table (PRD section 9)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Candidate(Base):
    """A fictional person, generated for one vacancy."""

    __tablename__ = "candidate"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    vacancy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vacancy.id", ondelete="CASCADE"), index=True
    )
    # The generation run this candidate belongs to.
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), index=True
    )
    # The version of the vacancy the candidate was made for. If the vacancy
    # has moved on, the candidate is out of date.
    vacancy_version: Mapped[int]
    number: Mapped[int]
    # Ground truth, including the match category. Never sent to the scoring
    # step and never shown to the recruiter.
    blueprint: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # Contact details live apart from the CV, which holds none (blind screening).
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(40))
    # Empty until the model has written the CV for this blueprint.
    # none_as_null: Python None is stored as SQL NULL, not as JSON null, so
    # "no CV yet" can be found with IS NULL.
    cv: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    cv_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
