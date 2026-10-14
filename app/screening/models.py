"""The assessment table (PRD section 9): one row per candidate per screening run."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Assessment(Base):
    __tablename__ = "assessment"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    vacancy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vacancy.id", ondelete="CASCADE"), index=True
    )
    # An assessment of a candidate who no longer exists means nothing.
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidate.id", ondelete="CASCADE"), index=True
    )
    # The screening job that made it.
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("job.id", ondelete="CASCADE"), index=True
    )

    # --- Step 1, by code: facts and requirements ---
    deterministic_score: Mapped[float]
    # Position in the ranking on facts alone, best first, starting at 1.
    deterministic_rank: Mapped[int]
    meets_hard: Mapped[bool]
    # May be listed: meets every hard requirement, or was admitted with a
    # flag because too few candidates do.
    listable: Mapped[bool]
    # Per script item: met or not, the keyword that counted, years, years asked.
    requirements: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    # Per keyword: found or not, computed years, and where in the CV.
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB)

    # --- Step 2, by the model, after the evidence check ---
    # Empty for candidates who were not among the strongest: not assessed.
    llm_score: Mapped[int | None]
    strengths: Mapped[list[str]] = mapped_column(JSONB, default=list)
    concerns: Mapped[list[str]] = mapped_column(JSONB, default=list)
    reasoning: Mapped[str | None] = mapped_column(Text)
    # Claims the check removed or corrected, and missed hard requirements.
    flags: Mapped[list[dict[str, str]]] = mapped_column(JSONB, default=list)
    claims_made: Mapped[int] = mapped_column(default=0)
    claims_supported: Mapped[int] = mapped_column(default=0)

    # --- The result ---
    final_score: Mapped[float | None]
    # The paragraph shown to the recruiter: computed facts, then the reasoning.
    rationale: Mapped[str | None] = mapped_column(Text)
    in_long_list: Mapped[bool] = mapped_column(default=False)
    in_short_list: Mapped[bool] = mapped_column(default=False)
    # Position in the long list, starting at 1.
    list_position: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
