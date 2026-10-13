"""The selection_script table (PRD section 9)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SelectionScript(Base):
    """The saved screening criteria of a vacancy. One per vacancy."""

    __tablename__ = "selection_script"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    vacancy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vacancy.id", ondelete="CASCADE"), unique=True
    )
    # The version of the vacancy the script was made from. If the vacancy has
    # moved on, the script is out of date.
    vacancy_version: Mapped[int]
    # Raised on every save, so lists can tell which script they were made with.
    revision: Mapped[int] = mapped_column(default=1)
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
