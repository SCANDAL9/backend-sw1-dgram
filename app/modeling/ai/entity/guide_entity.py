"""
Guide Entity — Spatial AI Guide and contextual onboarding persistence model.
"""
import uuid
from datetime import datetime
from sqlalchemy import (
    String, DateTime, ForeignKey, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class GuideSession(Base):
    """
    Sesión y progreso del agente espacial de guía y onboarding en un board.
    """
    __tablename__ = "guide_session"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    board_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("boards.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    session_token: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    completed_steps: Mapped[list] = mapped_column(
        JSONB, default=list, nullable=False
    )
    dismissed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
