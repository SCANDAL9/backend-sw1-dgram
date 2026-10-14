"""
chat_controller.py — Router API para Chat IA multimodal, Vision OCR y Audio transcription.
Controlador delgado (Thin Controller) que delega la orquestación a ChatService
y la persistencia a ChatRepository, eliminando consultas ORM directas.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.dependencies import require_board_access, BoardAuthContext, DEMO_OWNERS
from app.workspace.projects.entity.project_entity import ProjectRole
from app.modeling.ai.repository.chat_repository import ChatRepository
from app.modeling.ai.service.chat_service import ChatService
from app.modeling.ai.service.ai_service import process_vision_image
from app.modeling.ai.service.audio_service import process_audio_file
from app.modeling.ai.exception.ai_exceptions import (
    AISessionNotFoundError, AttachmentNotFoundError
)
from app.workspace.history.service.state_reconstructor_service import get_normalized_board_state

router = APIRouter()


class ChatInput(BaseModel):
    text: str
    user_id: str | None = None
    conversation_id: str | None = None


class CreateConversationInput(BaseModel):
    pass


def _sanitize_user_id(auth: BoardAuthContext) -> str | None:
    if not auth.user or not auth.user.id:
        return None
    raw = str(auth.user.id)
    if raw.startswith("guest") or raw.startswith("user-") or raw in DEMO_OWNERS:
        return None
    return raw


def _get_chat_service(db: AsyncSession) -> ChatService:
    repo = ChatRepository(db)
    return ChatService(repo)


@router.get("/boards/{board_id}/conversations")
async def list_conversations(
    board_id: str,
    auth: BoardAuthContext = Depends(require_board_access(min_role=ProjectRole.viewer)),
    db: AsyncSession = Depends(get_db),
):
    service = _get_chat_service(db)
    return await service.list_conversations(db, board_id=board_id)


@router.post("/boards/{board_id}/conversations")
async def create_conversation(
    board_id: str,
    data: CreateConversationInput | None = None,
    auth: BoardAuthContext = Depends(require_board_access(min_role=ProjectRole.editor)),
    db: AsyncSession = Depends(get_db),
):
    caller_user_id = _sanitize_user_id(auth)
    service = _get_chat_service(db)
    return await service.create_conversation(db, board_id=board_id, user_id=caller_user_id)


@router.delete("/boards/{board_id}/conversations/{conversation_id}")
async def delete_conversation(
    board_id: str,
    conversation_id: str,
    auth: BoardAuthContext = Depends(require_board_access(min_role=ProjectRole.editor)),
    db: AsyncSession = Depends(get_db),
):
    service = _get_chat_service(db)
    try:
        await service.delete_conversation(board_id=board_id, conversation_id=conversation_id)
    except AISessionNotFoundError:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    return {"status": "deleted", "id": conversation_id}


@router.get("/boards/{board_id}/messages")
async def list_chat_messages(
    board_id: str,
    conversation_id: str | None = Query(None),
    auth: BoardAuthContext = Depends(require_board_access(min_role=ProjectRole.viewer)),
    db: AsyncSession = Depends(get_db),
):
    service = _get_chat_service(db)
    return await service.list_messages(db, board_id=board_id, conversation_id=conversation_id)


@router.post("/boards/{board_id}/message")
async def send_chat_message(
    board_id: str,
    data: ChatInput,
    auth: BoardAuthContext = Depends(require_board_access(min_role=ProjectRole.editor)),
    db: AsyncSession = Depends(get_db),
):
    from app.modeling.ai.agent.agent_orchestrator import agent_orchestrator

    caller_user_id = _sanitize_user_id(auth)

    result = await agent_orchestrator.route_and_execute(
        db=db,
        board_id=board_id,
        user_prompt=data.text,
        user_id=caller_user_id,
        conversation_id=data.conversation_id,
    )

    return {
        "reply": result.reply,
        "commands": result.commands_executed,
        "conversation_id": result.conversation_id,
        "agent": result.agent,
        "traces": [t.model_dump() for t in result.traces],
    }


@router.post("/boards/{board_id}/vision")
async def upload_diagram_image_for_ocr(
    board_id: str,
    file: UploadFile = File(...),
    audio_file: UploadFile | None = File(None),
    prompt: str | None = Form(None),
    user_id: str | None = Form(None),
    conversation_id: str | None = Form(None),
    auth: BoardAuthContext = Depends(require_board_access(min_role=ProjectRole.editor)),
    db: AsyncSession = Depends(get_db),
):
    """
    Endpoint para análisis de bocetos o pizarras con OCR y visión artificial.
    Soporta audio adicional para instrucciones de voz sobre la imagen.
    Extrae entidades y genera comandos para el lienzo.
    """
    content_bytes = await file.read()
    if not content_bytes:
        raise HTTPException(status_code=400, detail="El archivo está vacío")

    mime_type = file.content_type or "image/png"
    audio_bytes = None
    audio_mime = None
    if audio_file is not None:
        raw_audio = await audio_file.read()
        if raw_audio:
            audio_bytes = raw_audio
            audio_mime = audio_file.content_type or "audio/wav"

    state = await get_normalized_board_state(db, board_id) or {}
    caller_user_id = _sanitize_user_id(auth)

    result = await process_vision_image(
        db,
        board_id=board_id,
        user_id=caller_user_id,
        image_bytes=content_bytes,
        mime_type=mime_type,
        current_state=state,
        prompt=prompt,
        conversation_id=conversation_id,
        audio_bytes=audio_bytes,
        audio_mime_type=audio_mime,
    )
    return result


@router.post("/boards/{board_id}/audio")
async def upload_diagram_audio_transcription(
    board_id: str,
    file: UploadFile = File(...),
    prompt: str | None = Form(None),
    conversation_id: str | None = Form(None),
    auth: BoardAuthContext = Depends(require_board_access(min_role=ProjectRole.editor)),
    db: AsyncSession = Depends(get_db),
):
    """
    Endpoint para análisis y transcripción de notas de voz o audio pregrabado.
    Transcribe el audio y aplica o sugiere comandos para el diagrama.
    """
    content_bytes = await file.read()
    if not content_bytes:
        raise HTTPException(status_code=400, detail="El archivo de audio está vacío")

    mime_type = file.content_type or "audio/wav"
    caller_user_id = _sanitize_user_id(auth)

    result = await process_audio_file(
        db,
        board_id=board_id,
        user_id=caller_user_id,
        audio_bytes=content_bytes,
        mime_type=mime_type,
        prompt=prompt,
        conversation_id=conversation_id,
    )
    return result


@router.get("/boards/{board_id}/attachments/{attachment_id}")
async def get_attachment_file(
    board_id: str,
    attachment_id: str,
    auth: BoardAuthContext = Depends(require_board_access(min_role=ProjectRole.viewer)),
    db: AsyncSession = Depends(get_db),
):
    service = _get_chat_service(db)
    try:
        file_path, mime_type = await service.get_attachment_file(
            board_id=board_id, attachment_id=attachment_id
        )
    except AttachmentNotFoundError:
        raise HTTPException(status_code=404, detail="Archivo adjunto no encontrado")

    return FileResponse(
        path=str(file_path),
        media_type=mime_type,
        filename=file_path.name,
    )
