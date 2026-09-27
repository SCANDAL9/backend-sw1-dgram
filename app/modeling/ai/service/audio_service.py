"""
audio_service.py — Servicio de procesamiento y transcripción de audio para IA multimodal.
"""
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException
from app.modeling.ai.entity.chat_entity import ChatMessage, ChatAttachment, AttachmentType, AiAction, ActorTypeEnum
from app.modeling.ai.service.ai_service import get_or_create_conversation, _tool_calls_to_commands
from app.modeling.ai.agent.vertex_client import vertex_ai_client
from app.modeling.ai.service.attachment_storage_service import save_attachment_file
from app.workspace.history.service.state_reconstructor_service import get_normalized_board_state

ALLOWED_AUDIO_TYPES = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/ogg": ".ogg",
    "audio/webm": ".webm",
    "audio/x-m4a": ".m4a",
    "audio/m4a": ".m4a",
    "audio/aac": ".aac",
}

MAX_AUDIO_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB


async def process_audio_file(
    db: AsyncSession,
    board_id: str,
    user_id: str | None,
    audio_bytes: bytes,
    mime_type: str,
    prompt: str | None = None,
    conversation_id: str | None = None,
) -> dict:
    """
    Procesa un archivo de audio pregrabado, lo transcribe y genera comandos para el diagrama.
    """
    if len(audio_bytes) > MAX_AUDIO_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="El archivo de audio supera el límite de 15 MB.")

    normalized_mime = mime_type.lower().split(";")[0].strip()
    if normalized_mime not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Formato de audio no soportado: '{mime_type}'. Permitidos: wav, mp3, ogg, webm, m4a.",
        )

    conv = await get_or_create_conversation(db, board_id, user_id, conversation_id=conversation_id)
    current_state = await get_normalized_board_state(db, board_id) or {}

    # 1. Transcripción y análisis con Vertex AI o fallback
    transcript, reply_text, tool_calls = await vertex_ai_client.transcribe_and_process_audio(
        audio_bytes=audio_bytes,
        mime_type=normalized_mime,
        user_prompt=prompt,
        current_state=current_state,
    )

    # 2. Registrar el mensaje del usuario con la transcripción
    user_msg = ChatMessage(
        id=str(uuid.uuid4()),
        conversation_id=conv.id,
        sender_type=ActorTypeEnum.user,
        user_id=user_id,
        content_text=f'[Nota de voz transcrita]: "{transcript}"',
    )
    db.add(user_msg)
    await db.flush()

    # 2.b Guardar adjunto de audio en ChatAttachment y disco
    attachment_id = str(uuid.uuid4())
    storage_url = save_attachment_file(board_id, attachment_id, audio_bytes, normalized_mime)
    attachment = ChatAttachment(
        id=attachment_id,
        chat_message_id=user_msg.id,
        type=AttachmentType.audio,
        storage_url=storage_url,
        mime_type=normalized_mime,
        order_index=0,
    )
    db.add(attachment)
    await db.flush()

    # 3. Mapear tool calls a comandos del dominio
    mapped_actions = _tool_calls_to_commands(tool_calls, current_state)

    # 4. Registrar mensaje de la IA
    ai_msg = ChatMessage(
        id=str(uuid.uuid4()),
        conversation_id=conv.id,
        sender_type=ActorTypeEnum.ai,
        user_id=None,
        content_text=reply_text,
    )
    db.add(ai_msg)
    await db.flush()

    # 5. Registrar acciones en ai_action
    generated_commands = []
    for item in mapped_actions:
        tool_name, tool_args, cmd, status = item[0], item[1], item[2], item[3]
        action = AiAction(
            id=str(uuid.uuid4()),
            chat_message_id=ai_msg.id,
            function_name=tool_name,
            function_arguments=tool_args,
            status=status,
            board_history_id=None,
        )
        db.add(action)
        if cmd:
            generated_commands.append(cmd.model_dump())

    await db.commit()

    return {
        "transcript": transcript,
        "reply": reply_text,
        "commands": generated_commands,
        "conversation_id": conv.id,
        "attachment": {
            "id": attachment.id,
            "storage_url": attachment.storage_url,
            "mime_type": attachment.mime_type,
        },
    }
