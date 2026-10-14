"""
chat_repository.py — Data Access Layer for Chat AI conversations, messages, and attachments.
Encapsulates all SQLAlchemy queries and transactional operations for chat entities.
"""
import uuid
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from app.modeling.ai.entity.chat_entity import (
    ChatConversation, ChatMessage, ChatAttachment, AiAction
)


class ChatRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_conversations_with_stats(
        self, board_id: str
    ) -> List[Tuple[ChatConversation, int, Optional[datetime]]]:
        """
        Recupera todas las conversaciones de un tablero junto con el conteo de mensajes
        y la fecha de última actividad ordenada descendentemente.
        """
        stmt = (
            select(
                ChatConversation,
                func.count(ChatMessage.id).label("message_count"),
                func.max(ChatMessage.created_at).label("last_activity"),
            )
            .outerjoin(ChatMessage, ChatMessage.conversation_id == ChatConversation.id)
            .where(ChatConversation.board_id == board_id)
            .group_by(ChatConversation.id)
            .order_by(
                func.coalesce(func.max(ChatMessage.created_at), ChatConversation.created_at).desc()
            )
        )
        result = await self.db.execute(stmt)
        return list(result.all())

    async def get_first_messages_for_conversations(
        self, conv_ids: List[str]
    ) -> Dict[str, str]:
        """
        Recupera el primer mensaje de cada conversación para generar el título de previsualización.
        """
        if not conv_ids:
            return {}

        first_msgs_stmt = (
            select(ChatMessage.conversation_id, ChatMessage.content_text)
            .where(ChatMessage.conversation_id.in_(conv_ids))
            .order_by(ChatMessage.created_at.asc())
        )
        first_msgs_res = await self.db.execute(first_msgs_stmt)
        first_msg_map: Dict[str, str] = {}
        for cid, content in first_msgs_res.all():
            if cid not in first_msg_map and content:
                first_msg_map[cid] = content.strip()
        return first_msg_map

    async def delete_conversation(self, board_id: str, conversation_id: str) -> bool:
        """
        Elimina una conversación específica de un tablero. Retorna True si se eliminó, False si no existía.
        """
        stmt = (
            delete(ChatConversation)
            .where(
                ChatConversation.id == conversation_id,
                ChatConversation.board_id == board_id,
            )
        )
        res = await self.db.execute(stmt)
        await self.db.commit()
        return res.rowcount > 0

    async def get_messages_for_conversation(self, conversation_id: str) -> List[ChatMessage]:
        """
        Recupera todos los mensajes cronológicos pertenecientes a una conversación.
        """
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
            .order_by(ChatMessage.created_at.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_attachments_for_messages(
        self, message_ids: List[str]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Recupera y agrupa todos los archivos adjuntos vinculados a una lista de IDs de mensajes.
        """
        if not message_ids:
            return {}

        att_stmt = select(ChatAttachment).where(ChatAttachment.chat_message_id.in_(message_ids))
        att_res = await self.db.execute(att_stmt)
        attachments_by_msg: Dict[str, List[Dict[str, Any]]] = {}
        for att in att_res.scalars().all():
            attachments_by_msg.setdefault(att.chat_message_id, []).append({
                "id": att.id,
                "type": att.type.value if hasattr(att.type, "value") else str(att.type),
                "storage_url": att.storage_url,
                "mime_type": att.mime_type,
                "duration_seconds": att.duration_seconds,
                "order_index": att.order_index,
                "created_at": str(att.created_at),
            })
        return attachments_by_msg

    async def get_attachment_by_board_and_id(
        self, board_id: str, attachment_id: str
    ) -> Optional[ChatAttachment]:
        """
        Recupera un archivo adjunto asegurando que pertenezca al tablero indicado.
        """
        stmt = (
            select(ChatAttachment)
            .join(ChatMessage, ChatAttachment.chat_message_id == ChatMessage.id)
            .join(ChatConversation, ChatMessage.conversation_id == ChatConversation.id)
            .where(
                ChatAttachment.id == attachment_id,
                ChatConversation.board_id == board_id,
            )
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_or_create_conversation(
        self,
        board_id: str,
        user_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        force_new: bool = False,
    ) -> ChatConversation:
        """
        Recupera una conversación existente o crea una nueva garantizando persistencia atómica.
        """
        clean_uid = None
        if user_id:
            raw = str(user_id)
            if not (raw.startswith("guest") or raw.startswith("user-") or raw in {"system", "demo", "public", "user-test"}):
                clean_uid = raw

        if not force_new and conversation_id:
            stmt = select(ChatConversation).where(
                ChatConversation.board_id == board_id,
                ChatConversation.id == conversation_id,
            )
            res = await self.db.execute(stmt)
            conv = res.scalar_one_or_none()
            if conv:
                return conv

        if not force_new:
            stmt = (
                select(ChatConversation)
                .where(ChatConversation.board_id == board_id)
                .order_by(ChatConversation.created_at.desc())
            )
            res = await self.db.execute(stmt)
            conv = res.scalar_one_or_none()
            if conv:
                return conv

        conv = ChatConversation(
            id=str(uuid.uuid4()),
            board_id=board_id,
            started_by=clean_uid,
        )
        self.db.add(conv)
        await self.db.commit()
        await self.db.refresh(conv)
        return conv

    async def save_message(self, message: ChatMessage) -> None:
        self.db.add(message)
        await self.db.flush()

    async def save_attachment(self, attachment: ChatAttachment) -> None:
        self.db.add(attachment)
        await self.db.flush()

    async def save_actions(self, actions: List[AiAction]) -> None:
        for action in actions:
            self.db.add(action)

    async def flush(self) -> None:
        await self.db.flush()

    async def commit(self) -> None:
        await self.db.commit()
