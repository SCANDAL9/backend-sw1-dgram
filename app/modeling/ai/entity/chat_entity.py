"""
Chat Entity — Multimodal AI Chat, Attachments, and AI Action persistence models.
"""
import enum
import uuid
from datetime import datetime
from sqlalchemy import (
    String, Text, Float, Integer, DateTime,
    Enum as SAEnum, ForeignKey, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
from app.modeling.diagram.entity.board_normalized_entity import ActorTypeEnum


class AttachmentType(str, enum.Enum):
    image = "image"
    audio = "audio"
    video = "video"
    document = "document"


class ActionStatus(str, enum.Enum):
    success = "success"
    failed = "failed"


class ChatConversation(Base):
    """
    Conversación atada a un board específico.
    La IA solo puede invocar herramientas sobre ESE board — no hay chat global.
    """
    __tablename__ = "chat_conversation"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    board_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("boards.id", ondelete="CASCADE"), nullable=False
    )
    started_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ChatMessage(Base):
    __tablename__ = "chat_message"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_conversation.id", ondelete="CASCADE"), nullable=False
    )
    sender_type: Mapped[ActorTypeEnum] = mapped_column(
        SAEnum(ActorTypeEnum, name="actor_type_enum"), nullable=False
    )
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ChatAttachment(Base):
    """
    Un mensaje puede traer varios adjuntos (ej. varias fotos del pizarrón).
    El binario vive en S3/MinIO; acá solo queda la referencia storage_url.
    """
    __tablename__ = "chat_attachment"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    chat_message_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_message.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[AttachmentType] = mapped_column(
        SAEnum(AttachmentType, name="attachment_type"), nullable=False
    )
    storage_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=True
    )


class AiAction(Base):
    """
    Puente chat_message → board_history.
    """
    __tablename__ = "ai_action"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    chat_message_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_message.id", ondelete="CASCADE"), nullable=False
    )
    board_history_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("board_history.id", ondelete="SET NULL"), nullable=True
    )
    function_name: Mapped[str] = mapped_column(String(100), nullable=False)
    function_arguments: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[ActionStatus] = mapped_column(
        SAEnum(ActionStatus, name="action_status"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
