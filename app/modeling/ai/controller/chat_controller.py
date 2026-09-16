"""
chat_controller.py — Router API para Chat IA multimodal y Vision OCR.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.modeling.ai.entity.chat_entity import ChatMessage
from app.modeling.ai.service.ai_service import process_vision_image, get_or_create_conversation
from app.workspace.history.service.state_reconstructor_service import get_normalized_board_state
from app.modeling.diagram.entity.board_entity import Board

router = APIRouter()


class ChatInput(BaseModel):
    text: str
    user_id: str | None = None


@router.get("/boards/{board_id}/messages")
async def list_chat_messages(board_id: str, db: AsyncSession = Depends(get_db)):
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
async def send_chat_message(board_id: str, data: ChatInput, db: AsyncSession = Depends(get_db)):
    board = await db.get(Board, board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    from app.modeling.ai.agent.agent_orchestrator import agent_orchestrator

    result = await agent_orchestrator.route_and_execute(
        db=db,
        board_id=board_id,
        user_prompt=data.text,
        user_id=data.user_id,
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
    db: AsyncSession = Depends(get_db),
):
    """
    Endpoint para análisis de bocetos o pizarras con Vertex AI Vision OCR.
    Extrae entidades y genera comandos para el lienzo.
    """
    board = await db.get(Board, board_id)
    if not board:
        raise HTTPException(status_code=404, detail="Board not found")

    content_bytes = await file.read()
    if not content_bytes:
        raise HTTPException(status_code=400, detail="El archivo está vacío")

    mime_type = file.content_type or "image/png"
    state = await get_normalized_board_state(db, board_id) or {}

    result = await process_vision_image(
        db,
        board_id=board_id,
        user_id=user_id,
        image_bytes=content_bytes,
        mime_type=mime_type,
        current_state=state,
        prompt=prompt,
    )
    return result
