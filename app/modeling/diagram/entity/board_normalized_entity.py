"""
board_element / board_history / board_snapshots

BoardElement   — posición visual de cada clase en un board específico.
                 La misma clase puede tener coordenadas distintas en cada board.
BoardHistory   — log durable de comandos (reemplaza Redis board:{id}:commands).
                 command_id UNIQUE garantiza idempotencia en retries.
BoardSnapshot  — caché JSONB regenerable; no es la fuente de verdad.
                 Se puede borrar y reconstruir reproduciendo board_history.
"""
import enum
import uuid
from datetime import datetime
from sqlalchemy import (
    String, Integer, Float, DateTime, Text,
    Enum as SAEnum, ForeignKey, func, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class ActorTypeEnum(str, enum.Enum):
    user = "user"
    ai = "ai"


# ─── BoardElement ─────────────────────────────────────────────────────────────

class BoardElement(Base):
    """
    Posición visual de una clase en un board concreto.
    UNIQUE(board_id, class_id): la misma clase solo aparece una vez por board.
    """
    __tablename__ = "board_element"
    __table_args__ = (
        UniqueConstraint("board_id", "class_id", name="uq_board_element_board_class"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    board_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("boards.id", ondelete="CASCADE"), nullable=False
    )
    class_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("class_element.id", ondelete="CASCADE"), nullable=False
    )
    x: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    y: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    # Nullable: el frontend calcula tamaño por defecto si no hay valor guardado
    width: Mapped[float | None] = mapped_column(Float, nullable=True)
    height: Mapped[float | None] = mapped_column(Float, nullable=True)


# ─── BoardHistory ─────────────────────────────────────────────────────────────

class BoardHistory(Base):
    """
    Log durable de cada comando aplicado al board.
    Reemplaza Redis board:{id}:commands LIST.

    command_id UNIQUE: el cliente genera el id ANTES de enviar por WS.
    Si la conexión falla y reintenta, ON CONFLICT DO NOTHING evita duplicados.
    """
    __tablename__ = "board_history"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    board_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("boards.id", ondelete="CASCADE"), nullable=False
    )
    # Idempotencia de retry: cliente genera este id antes de enviar
    command_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    # Varchar (no enum PG): catálogo validado en código, ~25 tipos
    command_type: Mapped[str] = mapped_column(String(100), nullable=False)
    # JSONB: cada command_type tiene shape distinta
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    actor_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_type: Mapped[ActorTypeEnum] = mapped_column(
        SAEnum(ActorTypeEnum, name="actor_type_enum"), nullable=False,
        default=ActorTypeEnum.user
    )
    # Versión del board en el momento de aplicar ESTE comando (no la versión actual)
    model_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ─── BoardSnapshot ────────────────────────────────────────────────────────────

class BoardSnapshot(Base):
    """
    Caché JSONB del estado normalizado — regenerable desde board_history.
    UNIQUE(board_id, version): un checkpoint por versión de board.
    """
    __tablename__ = "board_snapshots"
    __table_args__ = (
        UniqueConstraint("board_id", "version", name="uq_board_snapshot_version"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    board_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("boards.id", ondelete="CASCADE"), nullable=False
    )
    # Debe coincidir con model_version del último comando en board_history al crear el checkpoint
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    # JSONB: misma shape que el get_state() del CommandHandler
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
