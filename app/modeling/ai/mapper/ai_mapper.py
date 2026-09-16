"""
AI Mapper — Object mapping between AI domain entities, DTOs, and dictionaries.
"""
from typing import Any
from app.modeling.ai.entity.guide_entity import GuideSession
from app.modeling.ai.entity.chat_entity import ChatMessage, ChatConversation


class AIMapper:
    @staticmethod
    def guide_session_to_dict(session: GuideSession) -> dict[str, Any]:
        return {
            "board_id": session.board_id,
            "session_token": session.session_token,
            "completed_steps": session.completed_steps or [],
            "dismissed_at": str(session.dismissed_at) if session.dismissed_at else None,
        }

    @staticmethod
    def chat_message_to_dict(msg: ChatMessage) -> dict[str, Any]:
        return {
            "id": msg.id,
            "conversation_id": msg.conversation_id,
            "sender_type": str(msg.sender_type.value) if hasattr(msg.sender_type, "value") else str(msg.sender_type),
            "user_id": msg.user_id,
            "content_text": msg.content_text,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
        }
