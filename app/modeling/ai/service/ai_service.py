"""
ai_service.py — Asistente IA con Google Cloud Vertex AI (Gemini 2.0 / 1.5 Flash).
Persiste conversaciones en chat_conversation, chat_message y auditoría en ai_action.
Soporta Function Calling en tiempo real y Vision OCR multimodal.
"""
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.modeling.ai.entity.chat_entity import (
    ChatConversation, ChatMessage, ChatAttachment, AttachmentType,
    AiAction, ActionStatus, ActorTypeEnum,
)
from app.modeling.diagram.dto.command_dto import Command, CommandType, CommandPayload
from app.modeling.diagram.dto.command_payload_dto import ColumnData
from app.modeling.ai.agent.vertex_client import vertex_ai_client
from app.modeling.ai.service.attachment_storage_service import save_attachment_file


def parse_intent_and_generate_commands(user_prompt: str, current_state: dict) -> tuple[str, list[dict]]:
    """Función de compatibilidad para análisis síncrono/offline de intención."""
    reply_text, tool_calls = vertex_ai_client._heuristic_fallback(user_prompt, current_state)
    mapped = _tool_calls_to_commands(tool_calls, current_state)
    result_cmds = []
    for item in mapped:
        tool_name, tool_args, cmd = item[0], item[1], item[2]
        if cmd:
            result_cmds.append({
                "tool": tool_name,
                "function_args": tool_args,
                "command": cmd,
            })
    return reply_text, result_cmds


def _clean_user_id(uid: str | None) -> str | None:
    if not uid:
        return None
    raw = str(uid)
    if raw.startswith("guest") or raw.startswith("user-") or raw in {"system", "demo", "public", "user-test"}:
        return None
    return raw


async def get_or_create_conversation(
    db: AsyncSession,
    board_id: str,
    user_id: str | None = None,
    conversation_id: str | None = None,
    force_new: bool = False,
) -> ChatConversation:
    clean_uid = _clean_user_id(user_id)
    if not force_new and conversation_id:
        stmt = (
            select(ChatConversation)
            .where(
                ChatConversation.board_id == board_id,
                ChatConversation.id == conversation_id,
            )
        )
        res = await db.execute(stmt)
        conv = res.scalar_one_or_none()
        if conv:
            return conv

    if not force_new:
        stmt = (
            select(ChatConversation)
            .where(ChatConversation.board_id == board_id)
            .order_by(ChatConversation.created_at.desc())
        )
        res = await db.execute(stmt)
        conv = res.scalar_one_or_none()
        if conv:
            return conv

    conv = ChatConversation(
        id=str(uuid.uuid4()),
        board_id=board_id,
        started_by=clean_uid,
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv


def _tool_calls_to_commands(
    tool_calls: list[dict], current_state: dict, source: str = "manual"
) -> list[tuple[str, dict, Command | None, ActionStatus]]:
    """Convierte las llamadas de herramientas de Vertex AI a objetos Command del dominio."""
    results = []
    entities_count = len(current_state.get("entities", []))
    created_entities_map: dict[str, str] = {}

    for idx, tc in enumerate(tool_calls):
        name = tc.get("name")
        args = tc.get("args", {})

        if name == "create_class":
            class_name = args.get("name", f"Entity_{idx+1}")
            eid = str(uuid.uuid4())
            created_entities_map[class_name.lower()] = eid

            attrs = args.get("attributes", [{"name": "id", "type": "INTEGER", "pk": True, "fk": False}])
            # Normalizar atributos
            normalized_attrs = []
            for a in attrs:
                vis_val = a.get("visibility") or a.get("vis") or "public"
                normalized_attrs.append({
                    "name": a.get("name", "attr"),
                    "type": a.get("type", "VARCHAR(255)"),
                    "pk": a.get("pk", False),
                    "fk": a.get("fk", False),
                    "visibility": vis_val,
                })

            cmd_id = str(uuid.uuid4())
            args["_command_id"] = cmd_id

            cmd = Command(
                command_id=cmd_id,
                command_type=CommandType.CREATE_ENTITY,
                payload=CommandPayload(
                    entity_id=eid,
                    entity_name=class_name,
                    source=source,
                    columns=normalized_attrs,
                    position={
                        "x": args.get("x", 200 + ((entities_count + idx) * 80)),
                        "y": args.get("y", 150 + ((idx % 3) * 60)),
                    },
                ),
                actor="ai:copilot",
            )
            results.append(("create_class", args, cmd, ActionStatus.success))

        elif name == "add_attribute":
            class_name = args.get("class_name") or args.get("class_id")
            attr_name = args.get("attribute_name", "campo")
            attr_type = args.get("attribute_type", "VARCHAR(255)")
            pk = args.get("pk", False)
            vis_val = args.get("visibility") or args.get("vis") or "public"

            # Buscar entity_id: primero en las creadas en este turno, luego en current_state
            target_id = None
            if class_name:
                class_name_lower = str(class_name).lower()
                target_id = created_entities_map.get(class_name_lower)
                if not target_id:
                    for e in current_state.get("entities", []):
                        if e.get("name", "").lower() == class_name_lower or str(e.get("id")) == str(class_name):
                            target_id = e.get("id")
                            break

            if not target_id:
                results.append(("add_attribute", args, None, ActionStatus.failed))
                continue

            cmd_id = str(uuid.uuid4())
            args["_command_id"] = cmd_id

            cmd = Command(
                command_id=cmd_id,
                command_type=CommandType.ADD_COLUMN,
                payload=CommandPayload(
                    entity_id=target_id,
                    column_changes={
                        "name": attr_name,
                        "type": attr_type,
                        "pk": pk,
                        "fk": False,
                        "visibility": vis_val,
                    },
                ),
                actor="ai:copilot",
            )
            results.append(("add_attribute", args, cmd, ActionStatus.success))

        elif name == "create_association":
            source = args.get("source_class") or args.get("source_class_id")
            target = args.get("target_class") or args.get("target_class_id")
            rel_type = args.get("type", "1:N")

            # Resolver IDs: buscar primero en creadas en este turno, luego en current_state
            source_id = None
            target_id = None

            if source:
                source_lower = str(source).lower()
                source_id = created_entities_map.get(source_lower)
                if not source_id:
                    for e in current_state.get("entities", []):
                        if e.get("name", "").lower() == source_lower or str(e.get("id")) == str(source):
                            source_id = e.get("id")
                            break

            if target:
                target_lower = str(target).lower()
                target_id = created_entities_map.get(target_lower)
                if not target_id:
                    for e in current_state.get("entities", []):
                        if e.get("name", "").lower() == target_lower or str(e.get("id")) == str(target):
                            target_id = e.get("id")
                            break

            # Salvaguarda backend (#4): si alguna clase no existe, marcar fallo
            if not source_id or not target_id:
                results.append(("create_association", args, None, ActionStatus.failed))
                continue

            cmd_id = str(uuid.uuid4())
            args["_command_id"] = cmd_id

            cmd = Command(
                command_id=cmd_id,
                command_type=CommandType.CREATE_RELATION,
                payload=CommandPayload(
                    relation_id=str(uuid.uuid4()),
                    source_entity_id=source_id,
                    target_entity_id=target_id,
                    relation_type=rel_type,
                    source_column="id",
                    target_column=f"{str(source).lower()}_id",
                ),
                actor="ai:vertex-gemini",
            )
            results.append(("create_association", args, cmd, ActionStatus.success))

        elif name == "update_class":
            class_name = args.get("class_name")
            new_name = args.get("new_name")
            is_abstract = args.get("is_abstract")

            target_id = None
            if class_name:
                class_name_lower = str(class_name).lower()
                target_id = created_entities_map.get(class_name_lower)
                if not target_id:
                    for e in current_state.get("entities", []):
                        if e.get("name", "").lower() == class_name_lower or str(e.get("id")) == str(class_name):
                            target_id = e.get("id")
                            break

            if not target_id:
                results.append(("update_class", args, None, ActionStatus.failed))
                continue

            cmd_id = str(uuid.uuid4())
            args["_command_id"] = cmd_id

            cmd = Command(
                command_id=cmd_id,
                command_type=CommandType.UPDATE_ENTITY,
                payload=CommandPayload(
                    entity_id=target_id,
                    entity_name=new_name,
                ),
                actor="ai:vertex-gemini",
            )
            results.append(("update_class", args, cmd, ActionStatus.success))

        elif name == "delete_class":
            class_name = args.get("class_name")

            target_id = None
            if class_name:
                class_name_lower = str(class_name).lower()
                target_id = created_entities_map.get(class_name_lower)
                if not target_id:
                    for e in current_state.get("entities", []):
                        if e.get("name", "").lower() == class_name_lower or str(e.get("id")) == str(class_name):
                            target_id = e.get("id")
                            break

            if not target_id:
                results.append(("delete_class", args, None, ActionStatus.failed))
                continue

            cmd_id = str(uuid.uuid4())
            args["_command_id"] = cmd_id

            cmd = Command(
                command_id=cmd_id,
                command_type=CommandType.DELETE_ENTITY,
                payload=CommandPayload(
                    entity_id=target_id,
                ),
                actor="ai:vertex-gemini",
            )
            results.append(("delete_class", args, cmd, ActionStatus.success))

        elif name == "update_attribute":
            class_name = args.get("class_name")
            attr_name = args.get("attribute_name")
            new_type = args.get("new_type")
            new_name = args.get("new_name")
            pk = args.get("pk")

            target_id = None
            if class_name:
                class_name_lower = str(class_name).lower()
                target_id = created_entities_map.get(class_name_lower)
                if not target_id:
                    for e in current_state.get("entities", []):
                        if e.get("name", "").lower() == class_name_lower or str(e.get("id")) == str(class_name):
                            target_id = e.get("id")
                            break

            if not target_id or not attr_name:
                results.append(("update_attribute", args, None, ActionStatus.failed))
                continue

            cmd_id = str(uuid.uuid4())
            args["_command_id"] = cmd_id

            changes = {}
            if new_type:
                changes["type"] = new_type
            if new_name:
                changes["name"] = new_name
            if pk is not None:
                changes["pk"] = pk

            cmd = Command(
                command_id=cmd_id,
                command_type=CommandType.UPDATE_COLUMN,
                payload=CommandPayload(
                    entity_id=target_id,
                    column_name=attr_name,
                    column_changes=changes,
                ),
                actor="ai:vertex-gemini",
            )
            results.append(("update_attribute", args, cmd, ActionStatus.success))

        elif name == "delete_attribute":
            class_name = args.get("class_name")
            attr_name = args.get("attribute_name")

            target_id = None
            if class_name:
                class_name_lower = str(class_name).lower()
                target_id = created_entities_map.get(class_name_lower)
                if not target_id:
                    for e in current_state.get("entities", []):
                        if e.get("name", "").lower() == class_name_lower or str(e.get("id")) == str(class_name):
                            target_id = e.get("id")
                            break

            if not target_id or not attr_name:
                results.append(("delete_attribute", args, None, ActionStatus.failed))
                continue

            cmd_id = str(uuid.uuid4())
            args["_command_id"] = cmd_id

            cmd = Command(
                command_id=cmd_id,
                command_type=CommandType.DELETE_COLUMN,
                payload=CommandPayload(
                    entity_id=target_id,
                    column_name=attr_name,
                ),
                actor="ai:vertex-gemini",
            )
            results.append(("delete_attribute", args, cmd, ActionStatus.success))

        elif name == "delete_association":
            source = args.get("source_class")
            target = args.get("target_class")

            # Buscar relation_id que una source y target
            target_rel_id = None
            source_lower = str(source).lower() if source else ""
            target_lower = str(target).lower() if target else ""

            # Resolver IDs
            s_id = None
            t_id = None
            for e in current_state.get("entities", []):
                if e.get("name", "").lower() == source_lower or str(e.get("id")) == str(source):
                    s_id = e.get("id")
                if e.get("name", "").lower() == target_lower or str(e.get("id")) == str(target):
                    t_id = e.get("id")

            for r in current_state.get("relations", []):
                r_src = r.get("sourceId") or r.get("source_id")
                r_tgt = r.get("targetId") or r.get("target_id")
                if (r_src == s_id and r_tgt == t_id) or (r_src == t_id and r_tgt == s_id):
                    target_rel_id = r.get("id")
                    break

            if not target_rel_id:
                results.append(("delete_association", args, None, ActionStatus.failed))
                continue

            cmd_id = str(uuid.uuid4())
            args["_command_id"] = cmd_id

            cmd = Command(
                command_id=cmd_id,
                command_type=CommandType.DELETE_RELATION,
                payload=CommandPayload(
                    relation_id=target_rel_id,
                ),
                actor="ai:vertex-gemini",
            )
            results.append(("delete_association", args, cmd, ActionStatus.success))

    return results


async def process_chat_message(
    db: AsyncSession,
    board_id: str,
    user_id: str | None,
    content: str,
    current_state: dict,
) -> dict:
    """
    Procesa un mensaje de chat mediante Vertex AI, persiste en BD y ejecuta acciones.
    """
    clean_uid = _clean_user_id(user_id)
    conv = await get_or_create_conversation(db, board_id, clean_uid)

    # 1. Guardar mensaje del usuario
    user_msg = ChatMessage(
        id=str(uuid.uuid4()),
        conversation_id=conv.id,
        sender_type=ActorTypeEnum.user,
        user_id=clean_uid,
        content_text=content,
    )
    db.add(user_msg)
    await db.flush()

    # 2. Generar respuesta con Vertex AI (o fallback)
    reply_text, tool_calls = await vertex_ai_client.generate_chat_response(
        user_prompt=content,
        current_state=current_state,
    )

    # 3. Mapear tool calls a comandos
    mapped_actions = _tool_calls_to_commands(tool_calls, current_state)

    # 4. Guardar mensaje de la IA
    ai_msg = ChatMessage(
        id=str(uuid.uuid4()),
        conversation_id=conv.id,
        sender_type=ActorTypeEnum.ai,
        user_id=None,
        content_text=reply_text,
    )
    db.add(ai_msg)
    await db.flush()

    # 5. Registrar cada ai_action
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
        "reply": reply_text,
        "commands": generated_commands,
        "conversation_id": conv.id,
    }


async def process_vision_image(
    db: AsyncSession,
    board_id: str,
    user_id: str | None,
    image_bytes: bytes,
    mime_type: str,
    current_state: dict,
    prompt: str | None = None,
    conversation_id: str | None = None,
    audio_bytes: bytes | None = None,
    audio_mime_type: str | None = None,
) -> dict:
    """
    Procesa una imagen de boceto o pizarra mediante análisis visual y genera entidades UML.
    Soporta opcionalmente audio complementario (nota de voz explicativa).
    """
    clean_uid = _clean_user_id(user_id)
    conv = await get_or_create_conversation(
        db, board_id, clean_uid, conversation_id=conversation_id
    )

    # 1. Mensaje de usuario indicando imagen subida
    default_text = (
        "[Imagen y nota de voz adjuntadas para análisis OCR]"
        if audio_bytes
        else "[Imagen de diagrama adjuntada para análisis OCR]"
    )
    user_msg = ChatMessage(
        id=str(uuid.uuid4()),
        conversation_id=conv.id,
        sender_type=ActorTypeEnum.user,
        user_id=clean_uid,
        content_text=prompt or default_text,
    )
    db.add(user_msg)
    await db.flush()

    # 1.b Guardar adjunto de imagen en ChatAttachment y disco
    attachment_id = str(uuid.uuid4())
    storage_url = save_attachment_file(board_id, attachment_id, image_bytes, mime_type)
    attachment = ChatAttachment(
        id=attachment_id,
        chat_message_id=user_msg.id,
        type=AttachmentType.image,
        storage_url=storage_url,
        mime_type=mime_type,
        order_index=0,
    )
    db.add(attachment)

    # 1.c Guardar adjunto de audio si existe
    if audio_bytes:
        audio_att_id = str(uuid.uuid4())
        audio_storage_url = save_attachment_file(
            board_id, audio_att_id, audio_bytes, audio_mime_type or "audio/wav"
        )
        audio_attachment = ChatAttachment(
            id=audio_att_id,
            chat_message_id=user_msg.id,
            type=AttachmentType.audio,
            storage_url=audio_storage_url,
            mime_type=audio_mime_type or "audio/wav",
            order_index=1,
        )
        db.add(audio_attachment)

    await db.flush()

    # 2. Análisis multimodal con Vertex AI
    reply_text, tool_calls = await vertex_ai_client.analyze_diagram_image(
        image_bytes=image_bytes,
        mime_type=mime_type,
        user_prompt=prompt,
        current_state=current_state,
        audio_bytes=audio_bytes,
        audio_mime_type=audio_mime_type,
    )

    mapped_actions = _tool_calls_to_commands(tool_calls, current_state, source="image_ocr")

    # 3. Guardar mensaje de IA
    ai_msg = ChatMessage(
        id=str(uuid.uuid4()),
        conversation_id=conv.id,
        sender_type=ActorTypeEnum.ai,
        user_id=None,
        content_text=reply_text,
    )
    db.add(ai_msg)
    await db.flush()

    # 4. Registrar acciones
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
        "reply": reply_text,
        "commands": generated_commands,
        "conversation_id": conv.id,
        "attachment": {
            "id": attachment.id,
            "storage_url": attachment.storage_url,
            "mime_type": attachment.mime_type,
        },
    }
