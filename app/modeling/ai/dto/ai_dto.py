"""
AI DTOs — Request and response schemas for AI Guide, Chat, and Actions.
"""
from typing import Any
from pydantic import BaseModel, Field


class ExplainInput(BaseModel):
    target_type: str = Field(..., description="Tipo de target inspeccionado (ej. entity, relation, attribute, toolbar:create-entity)")
    target_meta: dict[str, Any] = Field(default_factory=dict, description="Metadatos del target (nombre, atributos, tipos)")
    session_token: str = Field(..., description="Token de sesión persistente del agente en el cliente")
    user_id: str | None = None


class AskInput(BaseModel):
    question: str = Field(..., description="Pregunta del usuario")
    target_context: dict[str, Any] | None = Field(default=None, description="Contexto opcional del elemento enfocado")
    session_token: str = Field(..., description="Token de sesión persistente del agente en el cliente")
    user_id: str | None = None


class StepInput(BaseModel):
    step_id: str = Field(..., description="ID del paso completado del onboarding tour")
    session_token: str = Field(..., description="Token de sesión persistente")
    user_id: str | None = None


class AttachmentInput(BaseModel):
    type: str = Field(..., description="Tipo de adjunto: image, audio, video, document")
    storage_url: str = Field(..., description="URL o data URI del adjunto")
    mime_type: str | None = None
    duration_seconds: float | None = None


class ChatInput(BaseModel):
    prompt: str = Field(..., description="Prompt o mensaje del usuario")
    conversation_id: str | None = Field(default=None, description="ID de la conversación existente o None para crear nueva")
    attachments: list[AttachmentInput] = Field(default_factory=list, description="Lista de adjuntos multimedia")
    current_state: dict[str, Any] | None = Field(default=None, description="Estado del canvas (entities, relations, metadata)")
