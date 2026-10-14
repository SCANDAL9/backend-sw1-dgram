"""
chat_service.py — Business logic and orchestration for Chat conversations, messages, and attachments.
"""
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from app.modeling.ai.repository.chat_repository import ChatRepository
from app.modeling.ai.service.attachment_storage_service import get_attachment_file_path
from app.modeling.ai.exception.ai_exceptions import (
    AISessionNotFoundError, AttachmentNotFoundError
)


class ChatService:
    def __init__(self, repo: ChatRepository):
        self.repo = repo

    async def list_conversations(
        self, db: AsyncSession, board_id: str
    ) -> List[Dict[str, Any]]:
        """
        Lista todas las conversaciones del tablero con su título previsualizado y conteos.
        """
        rows = await self.repo.get_conversations_with_stats(board_id)

        # Si no existe ninguna conversación aún, asegurar una por defecto
        if not rows:
            conv = await self.repo.get_or_create_conversation(board_id=board_id)
            return [
                {
                    "id": conv.id,
                    "board_id": conv.board_id,
                    "title": "Chat Principal",
                    "created_at": str(conv.created_at),
                    "updated_at": str(conv.created_at),
                    "message_count": 0,
                }
            ]

        conv_ids = [conv.id for conv, _, _ in rows]
        first_msg_map = await self.repo.get_first_messages_for_conversations(conv_ids)

        items = []
        for conv, count, last_act in rows:
            preview = first_msg_map.get(conv.id)
            if preview:
                title = preview[:35] + ("..." if len(preview) > 35 else "")
            else:
                title = f"Chat {conv.created_at.strftime('%d/%m %H:%M')}"

            activity = last_act or conv.created_at
            items.append({
                "id": conv.id,
                "board_id": conv.board_id,
                "title": title,
                "created_at": str(conv.created_at),
                "updated_at": str(activity),
                "message_count": count,
            })
        return items

    async def create_conversation(
        self, db: AsyncSession, board_id: str, user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Crea una nueva conversación explícita para el tablero.
        """
        conv = await self.repo.get_or_create_conversation(
            board_id=board_id,
            user_id=user_id,
            force_new=True,
        )
        return {
            "id": conv.id,
            "board_id": conv.board_id,
            "title": "Nuevo Chat",
            "created_at": str(conv.created_at),
            "updated_at": str(conv.created_at),
            "message_count": 0,
        }

    async def delete_conversation(self, board_id: str, conversation_id: str) -> None:
        """
        Elimina la conversación indicada comprobando su existencia previa.
        """
        deleted = await self.repo.delete_conversation(board_id, conversation_id)
        if not deleted:
            raise AISessionNotFoundError("Conversación no encontrada")

    async def list_messages(
        self, db: AsyncSession, board_id: str, conversation_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Lista los mensajes cronológicos de una conversación junto con sus archivos adjuntos.
        """
        conv = await self.repo.get_or_create_conversation(board_id=board_id, conversation_id=conversation_id)
        messages = await self.repo.get_messages_for_conversation(conv.id)

        msg_ids = [m.id for m in messages]
        attachments_by_msg = await self.repo.get_attachments_for_messages(msg_ids)

        return [
            {
                "id": m.id,
                "sender_type": m.sender_type.value if hasattr(m.sender_type, "value") else str(m.sender_type),
                "user_id": m.user_id,
                "content": m.content_text,
                "created_at": str(m.created_at),
                "attachments": attachments_by_msg.get(m.id, []),
            }
            for m in messages
        ]

    async def get_attachment_file(
        self, board_id: str, attachment_id: str
    ) -> Tuple[Path, str]:
        """
        Obtiene la ruta física y el tipo MIME de un archivo adjunto tras validar pertenencia.
        """
        attachment = await self.repo.get_attachment_by_board_and_id(board_id, attachment_id)
        if not attachment:
            raise AttachmentNotFoundError("Archivo adjunto no encontrado")

        file_path = get_attachment_file_path(board_id, attachment_id)
        if not file_path or not file_path.exists():
            raise AttachmentNotFoundError("Archivo en disco no encontrado")

        return file_path, attachment.mime_type or "application/octet-stream"
