"""
chat_controller.py — Router API para Chat IA multimodal, Vision OCR y Audio transcription.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from app.core.database import get_db
from app.core.dependencies import require_board_access, BoardAuthContext, DEMO_OWNERS
from app.workspace.projects.entity.project_entity import ProjectRole
from app.modeling.ai.entity.chat_entity import ChatMessage, ChatConversation, ChatAttachment
from app.modeling.ai.service.ai_service import process_vision_image, get_or_create_conversation
from app.modeling.ai.service.audio_service import process_audio_file
from app.modeling.ai.service.attachment_storage_service import get_attachment_file_path
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


@router.get("/boards/{board_id}/conversations")
async def list_conversations(
    board_id: str,
    auth: BoardAuthContext = Depends(require_board_access(min_role=ProjectRole.viewer)),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(
            ChatConversation,
            func.count(ChatMessage.id).label("message_count"),
            func.max(ChatMessage.created_at).label("last_activity"),
        )
        .outerjoin(ChatMessage, ChatMessage.conversation_id == ChatConversation.id)
        .where(ChatConversation.board_id == board_id)
        .group_by(ChatConversation.id)
        .order_by(func.coalesce(func.max(ChatMessage.created_at), ChatConversation.created_at).desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    # If no conversations exist yet, ensure a default one is created
    if not rows:
        conv = await get_or_create_conversation(db, board_id=board_id)
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
    first_msgs_stmt = (
        select(ChatMessage.conversation_id, ChatMessage.content_text)
        .where(ChatMessage.conversation_id.in_(conv_ids))
        .order_by(ChatMessage.created_at.asc())
    )
    first_msgs_res = await db.execute(first_msgs_stmt)
    first_msg_map: dict[str, str] = {}
    for cid, content in first_msgs_res.all():
        if cid not in first_msg_map and content:
            first_msg_map[cid] = content.strip()

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


@router.post("/boards/{board_id}/conversations")
async def create_conversation(
    board_id: str,
    data: CreateConversationInput | None = None,
    auth: BoardAuthContext = Depends(require_board_access(min_role=ProjectRole.editor)),
    db: AsyncSession = Depends(get_db),
):
    caller_user_id = _sanitize_user_id(auth)
    conv = await get_or_create_conversation(
        db,
        board_id=board_id,
        user_id=caller_user_id,
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


@router.delete("/boards/{board_id}/conversations/{conversation_id}")
async def delete_conversation(
    board_id: str,
    conversation_id: str,
    auth: BoardAuthContext = Depends(require_board_access(min_role=ProjectRole.editor)),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        delete(ChatConversation)
        .where(
            ChatConversation.id == conversation_id,
            ChatConversation.board_id == board_id,
        )
    )
    res = await db.execute(stmt)
    await db.commit()
    if res.rowcount == 0:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    return {"status": "deleted", "id": conversation_id}


@router.get("/boards/{board_id}/messages")
async def list_chat_messages(
    board_id: str,
    conversation_id: str | None = Query(None),
    auth: BoardAuthContext = Depends(require_board_access(min_role=ProjectRole.viewer)),
    db: AsyncSession = Depends(get_db),
):
    conv = await get_or_create_conversation(db, board_id, conversation_id=conversation_id)
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conv.id)
        .order_by(ChatMessage.created_at.asc())
    )
    result = await db.execute(stmt)
    messages = result.scalars().all()

    attachments_by_msg: dict[str, list[dict]] = {}
    if messages:
        msg_ids = [m.id for m in messages]
        att_stmt = select(ChatAttachment).where(ChatAttachment.chat_message_id.in_(msg_ids))
        att_res = await db.execute(att_stmt)
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
    prompt: str | None = Form(None),
    user_id: str | None = Form(None),
    conversation_id: str | None = Form(None),
    auth: BoardAuthContext = Depends(require_board_access(min_role=ProjectRole.editor)),
    db: AsyncSession = Depends(get_db),
):
    """
    Endpoint para análisis de bocetos o pizarras con OCR y visión artificial.
    Extrae entidades y genera comandos para el lienzo.
    """
    content_bytes = await file.read()
    if not content_bytes:
        raise HTTPException(status_code=400, detail="El archivo está vacío")

    mime_type = file.content_type or "image/png"
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
    caller_user_id = _sanitize_user_id(auth)

    result = await process_audio_file(
        db,
        board_id=board_id,
        user_id=caller_user_id,
        audio_bytes=content_bytes,
        mime_type=mime_type,
        prompt=prompt,
    )
    return result


@router.get("/boards/{board_id}/attachments/{attachment_id}")
async def get_attachment_file(
    board_id: str,
    attachment_id: str,
    auth: BoardAuthContext = Depends(require_board_access(min_role=ProjectRole.viewer)),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(ChatAttachment)
        .join(ChatMessage, ChatAttachment.chat_message_id == ChatMessage.id)
        .join(ChatConversation, ChatMessage.conversation_id == ChatConversation.id)
        .where(
            ChatAttachment.id == attachment_id,
            ChatConversation.board_id == board_id,
        )
    )
    res = await db.execute(stmt)
    attachment = res.scalar_one_or_none()
    if not attachment:
        raise HTTPException(status_code=404, detail="Archivo adjunto no encontrado")

    file_path = get_attachment_file_path(board_id, attachment_id)
    if not file_path or not file_path.exists():
        raise HTTPException(status_code=404, detail="Archivo en disco no encontrado")

    return FileResponse(
        path=str(file_path),
        media_type=attachment.mime_type or "application/octet-stream",
        filename=file_path.name,
    )

