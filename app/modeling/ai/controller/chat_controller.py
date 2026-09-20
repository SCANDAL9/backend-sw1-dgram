"""
chat_controller.py — Router API para Chat IA multimodal, Vision OCR y Audio transcription.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.dependencies import require_board_access, BoardAuthContext
from app.workspace.projects.entity.project_entity import ProjectRole
from app.modeling.ai.entity.chat_entity import ChatMessage
from app.modeling.ai.service.ai_service import process_vision_image, get_or_create_conversation
from app.modeling.ai.service.audio_service import process_audio_file
from app.workspace.history.service.state_reconstructor_service import get_normalized_board_state

router = APIRouter()


class ChatInput(BaseModel):
    text: str
    user_id: str | None = None


@router.get("/boards/{board_id}/messages")
async def list_chat_messages(
    board_id: str,
    auth: BoardAuthContext = Depends(require_board_access(min_role=ProjectRole.viewer)),
    db: AsyncSession = Depends(get_db),
):
    conv = await get_or_create_conversation(db, board_id)
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conv.id)
        .order_by(ChatMessage.created_at.asc())
    )
    result = await db.execute(stmt)
    messages = result.scalars().all()
    return [
        {
            "id": m.id,
            "sender_type": m.sender_type.value if hasattr(m.sender_type, "value") else str(m.sender_type),
            "user_id": m.user_id,
            "content": m.content_text,
            "created_at": str(m.created_at),
        }
        for m in messages
    ]


@router.post("/boards/{board_id}/message")
async def send_chat_message(
    board_id: str,
    data: ChatInput,
    auth: BoardAuthContext = Depends(require_board_access(min_role=ProjectRole.editor)),
    db: AsyncSession = Depends(get_db),
):
    from app.modeling.ai.agent.agent_orchestrator import agent_orchestrator

    caller_user_id = str(auth.user.id)

    result = await agent_orchestrator.route_and_execute(
        db=db,
        board_id=board_id,
        user_prompt=data.text,
        user_id=caller_user_id,
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
    prompt: str | None = Form(None),
    user_id: str | None = Form(None),
    auth: BoardAuthContext = Depends(require_board_access(min_role=ProjectRole.editor)),
    db: AsyncSession = Depends(get_db),
):
    """
    Endpoint para análisis de bocetos o pizarras con Vertex AI Vision OCR.
    Extrae entidades y genera comandos para el lienzo.
    """
    content_bytes = await file.read()
    if not content_bytes:
        raise HTTPException(status_code=400, detail="El archivo está vacío")

    mime_type = file.content_type or "image/png"
    state = await get_normalized_board_state(db, board_id) or {}
    caller_user_id = str(auth.user.id)

    result = await process_vision_image(
        db,
        board_id=board_id,
        user_id=caller_user_id,
        image_bytes=content_bytes,
        mime_type=mime_type,
        current_state=state,
        prompt=prompt,
    )
    return result


@router.post("/boards/{board_id}/audio")
async def upload_diagram_audio_transcription(
    board_id: str,
    file: UploadFile = File(...),
    prompt: str | None = Form(None),
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
    caller_user_id = str(auth.user.id)

    result = await process_audio_file(
        db,
        board_id=board_id,
        user_id=caller_user_id,
        audio_bytes=content_bytes,
        mime_type=mime_type,
        prompt=prompt,
    )
    return result

