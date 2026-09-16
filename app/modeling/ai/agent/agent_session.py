"""
agent_session.py — Administrador explícito de Session State para el sistema de agentes.
Almacena el estado visual y temporal de cada usuario (elemento seleccionado, herramienta activa, viewport)
para que las tools del agente lean contexto en tiempo real sin adivinanzas.
Soporta sincronización distribuida vía Redis con fallback local en memoria.
"""
import asyncio
import json
import logging
import time
from typing import Any
from pydantic import BaseModel, Field
from app.core import pubsub

logger = logging.getLogger(__name__)


class AgentSessionState(BaseModel):
    board_id: str
    user_id: str
    selected_element_id: str | None = None
    selected_element_type: str | None = None  # 'class' | 'relation'
    active_tool: str = "select"  # 'select' | 'hand' | 'relation'
    viewport: dict[str, Any] = Field(default_factory=lambda: {"x": 0, "y": 0, "zoom": 1.0})
    recent_action: str | None = None
    updated_at: float = 0.0


class SessionStateManager:
    """Almacén con soporte distribuido en Redis y caché local en RAM."""
    def __init__(self):
        # Clave: f"{board_id}:{user_id}"
        self._store: dict[str, AgentSessionState] = {}

    def update_state(self, board_id: str, user_id: str, state_dict: dict[str, Any]) -> AgentSessionState:
        key = f"{board_id}:{user_id}"
        payload = {
            "board_id": board_id,
            "user_id": user_id,
            "selected_element_id": state_dict.get("selected_element_id"),
            "selected_element_type": state_dict.get("selected_element_type"),
            "active_tool": state_dict.get("active_tool", "select"),
            "viewport": state_dict.get("viewport", {"x": 0, "y": 0, "zoom": 1.0}),
            "recent_action": state_dict.get("recent_action"),
            "updated_at": time.time(),
        }

        session_state = AgentSessionState(**payload)
        self._store[key] = session_state

        # Persistir de forma asíncrona en Redis si hay bucle activo
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._persist_to_redis(key, session_state))
        except RuntimeError:
            pass

        return session_state

    async def _persist_to_redis(self, key: str, state: AgentSessionState) -> None:
        try:
            client = pubsub.get_redis()
            if client:
                await client.set(f"agent_session:{key}", state.model_dump_json(), ex=3600)
        except Exception as exc:
            logger.debug("Failed to cache agent session in Redis: %s", exc)

    def get_state(self, board_id: str, user_id: str) -> AgentSessionState | None:
        return self._store.get(f"{board_id}:{user_id}")

    async def get_state_async(self, board_id: str, user_id: str) -> AgentSessionState | None:
        """Intenta leer de la caché en RAM; si no está, consulta Redis."""
        key = f"{board_id}:{user_id}"
        state = self._store.get(key)
        if state is not None:
            return state

        try:
            client = pubsub.get_redis()
            if client:
                raw = await client.get(f"agent_session:{key}")
                if raw:
                    data = json.loads(raw)
                    state = AgentSessionState(**data)
                    self._store[key] = state
                    return state
        except Exception as exc:
            logger.debug("Failed to fetch agent session from Redis: %s", exc)

        return None

    def get_session(self, board_id: str, user_id: str | None = None) -> AgentSessionState | None:
        if not user_id:
            return None
        return self.get_state(board_id, user_id)


session_manager = SessionStateManager()
session_state_manager = session_manager
