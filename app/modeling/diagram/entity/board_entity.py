"""
Board — tablero colaborativo normalizado.

Columnas relacionales:
  - project_id: FK nullable a project
  - created_by: FK nullable a users
  - diagram_version: contador de optimistic locking para concurrencia segura
"""
import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, Text, ForeignKey, LargeBinary, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class Board(Base):
    __tablename__ = "boards"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False)

    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("project.id", ondelete="SET NULL"), nullable=True
    )
    # Optimistic locking: UPDATE ... WHERE id=:id AND diagram_version=:expected
    diagram_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # CRDT Yjs binary state snapshot (BYTEA)
    yjs_state: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
