import logging
from fastapi import APIRouter, WebSocket, Query, WebSocketDisconnect
from app.core.websocket.manager import manager
from app.modeling.diagram.dto.command_dto import Command
from app.modeling.diagram.service.command_handler_service import CommandHandler
from app.workspace.history.service.command_history_service import CommandHistory
from app.core.database import async_session_factory
from app.modeling.diagram.service import board_service
from app.modeling.diagram.service.relational_mutator_service import apply_command_to_relational_db
from app.workspace.history.service.state_reconstructor_service import get_normalized_board_state
from app.core.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()

# Board_id → CommandHandler (in-memory, per board)
_handlers: dict[str, CommandHandler] = {}


async def _load_board_snapshot(board_id: str, handler: CommandHandler) -> None:
    """Carga el estado del board desde las tablas normalizadas o board_snapshots."""
    try:
        async with async_session_factory() as session:
            state = await get_normalized_board_state(session, board_id)
            if state:
                handler.load_snapshot(state)
    except Exception as exc:
        logger.warning(
            "No se pudo cargar el snapshot normalizado para el board %s: %s",
            board_id,
            exc,
            exc_info=True,
        )


async def _persist_snapshot_atomic(
    handler: CommandHandler,
    command: Command | None = None,
    actor_id: str | None = None,
) -> bool:
    """
    Persistencia atómica en PostgreSQL:
    1. INSERT board_history (command_id UNIQUE).
    2. Mutación de tablas normalizadas (class_element, attribute, association, board_element).
    3. Optimistic locking en boards.diagram_version.
    4. Guardado de checkpoint en board_snapshots.
    """
    if command is None:
        # Checkpoint de snapshot general
        try:
            async with async_session_factory() as session:
                await board_service.save_snapshot(
                    session, handler.board_id, handler.get_state()
                )
            return True
        except Exception as exc:
            logger.error(
                "Error al guardar snapshot general para board %s: %s",
                handler.board_id,
                exc,
                exc_info=True,
            )
            return False

    try:
        async with async_session_factory() as session:
            async with session.begin():
                # 1. Mutar las tablas relacionales normalizadas
                await apply_command_to_relational_db(
                    session,
                    board_id=handler.board_id,
                    command=command,
                    actor_id=actor_id,
                )

                # 2. Guardar snapshot y log de historia con optimistic locking
                cmd_type_str = (
                    command.command_type.value
                    if hasattr(command.command_type, "value")
                    else str(command.command_type)
                )
                payload_dict = (
                    command.payload.model_dump()
                    if hasattr(command.payload, "model_dump")
                    else dict(command.payload)
                )

                ok = await board_service.save_snapshot_normalized(
                    session,
                    board_id=handler.board_id,
                    state=handler.get_state(),
                    command_id=command.command_id,
                    command_type=cmd_type_str,
                    payload=payload_dict,
                    actor_id=actor_id,
                    model_version=handler.version,
                    expected_version=handler.version - 1,
                    actor=command.actor,
                )
                return ok
    except Exception as exc:
        cmd_id = getattr(command, "command_id", "unknown")
        logger.exception(
            "Fallo en persistencia atómica para board %s y comando %s: %s",
            handler.board_id,
            cmd_id,
            exc,
        )
        return False



def _get_handler(board_id: str) -> CommandHandler:
    if board_id not in _handlers:
        history = CommandHistory(board_id)
        _handlers[board_id] = CommandHandler(board_id, history)
    return _handlers[board_id]


def sync_remote_command_to_handler(board_id: str, command_input: dict | Command) -> bool:
    """
    Sincroniza un comando ejecutado en otra réplica en el CommandHandler local
    si el tablero está cargado en memoria, sin re-persistir en PostgreSQL.
    """
    handler = _handlers.get(board_id)
    if not handler:
        return False
    try:
        if isinstance(command_input, Command):
            command = command_input
        else:
            command = Command(
                command_id=command_input.get("command_id", ""),
                command_type=command_input.get("command_type", ""),
                payload=command_input.get("payload", {}),
                actor=command_input.get("actor", "remote_replica"),
                timestamp=command_input.get("timestamp", ""),
                model_version=command_input.get("model_version", 0),
            )
        handler.apply_remote_command(command)
        return True
    except Exception as exc:
        logger.warning(
            "Fallo al sincronizar comando remoto en handler para board %s: %s",
            board_id,
            exc,
            exc_info=True,
        )
        return False


@router.websocket("/ws/{board_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    board_id: str,
    user_id: str | None = Query(None),
    token: str | None = Query(None),
):
    from app.workspace.authentication.service import auth_service

    if not token:
        await websocket.accept()
        await websocket.send_json(
            {"type": "error", "message": "Autenticación requerida para conectar al WebSocket"}
        )
        await websocket.close(code=4001)
        return

    payload = auth_service.decode_jwt_token(token)
    if not payload or "sub" not in payload:
        await websocket.accept()
        await websocket.send_json(
            {"type": "error", "message": "Token inválido o expirado"}
        )
        await websocket.close(code=4001)
        return

    actual_user_id = payload["sub"]

    # Verificar acceso y rol en el proyecto/board
    async with async_session_factory() as session:
        has_access, role = await auth_service.check_board_access(
            session, board_id, actual_user_id
        )

    if not has_access or role == "none":
        await websocket.accept()
        await websocket.send_json(
            {"type": "error", "message": "Acceso denegado al board"}
        )
        await websocket.close(code=4003)
        return

    await manager.connect(websocket, board_id, actual_user_id)
    handler = _get_handler(board_id)
    await _load_board_snapshot(board_id, handler)

    await manager.send_personal(
        websocket,
        {
            "type": "state:sync",
            "data": handler.get_state(),
            "role": role,
        },
    )
    await manager.send_personal(
        websocket,
        {
            "type": "presence:list",
            "data": manager.get_room_users(board_id),
        },
    )

    from app.core.websocket.yjs_handler import handle_yjs_sync_request, handle_yjs_update
    await handle_yjs_sync_request(websocket, board_id)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            # Viewers cannot send mutations
            if role == "viewer" and msg_type in ("command:send", "yjs:update"):
                await manager.send_personal(
                    websocket,
                    {
                        "type": "error",
                        "message": "Permission denied: read-only role (viewer)",
                    },
                )
                continue

            if msg_type == "command:send":
                await _handle_command(handler, data, websocket, actor_id=actual_user_id)

            elif msg_type == "cursor:move":
                await _handle_cursor(board_id, actual_user_id, data)

            elif msg_type == "chat:message":
                await _handle_chat(board_id, actual_user_id, data)

            elif msg_type == "state:request":
                await manager.send_personal(
                    websocket,
                    {
                        "type": "state:sync",
                        "data": handler.get_state(),
                    },
                )
                await handle_yjs_sync_request(websocket, board_id)

            elif msg_type == "presence:drag":
                # Ephemeral live-drag preview — never written to PostgreSQL.
                # Broadcast raw canvas position to all peers except the sender.
                await _handle_presence_drag(board_id, actual_user_id, data)

            elif msg_type == "presence:selection":
                # Ephemeral selection / editing awareness — never written to PostgreSQL.
                await _handle_presence_selection(board_id, actual_user_id, data)

            elif msg_type == "agent:sync_session":
                # Sincronización explícita del Session State del usuario para los agentes
                from app.modeling.ai.agent.agent_session import session_manager
                session_manager.update_state(board_id, actual_user_id, data.get("data", {}))

            elif msg_type == "yjs:update":
                await handle_yjs_update(board_id, actual_user_id, data)

            elif msg_type == "yjs:sync_request":
                await handle_yjs_sync_request(websocket, board_id)

    except WebSocketDisconnect:
        logger.debug(
            "Cliente desconectado de board %s (user_id=%s)", board_id, actual_user_id
        )
    except Exception as exc:
        logger.error(
            "Error inesperado en loop WebSocket para board %s (user_id=%s): %s",
            board_id,
            actual_user_id,
            exc,
            exc_info=True,
        )
    finally:
        await manager.disconnect(board_id, actual_user_id)



async def _handle_command(
    handler: CommandHandler,
    data: dict,
    websocket: WebSocket,
    actor_id: str | None = None,
) -> None:
    cmd_data = data.get("data", {})
    command = Command(
        command_id=cmd_data.get("command_id", ""),
        command_type=cmd_data.get("command_type", ""),
        payload=cmd_data.get("payload", {}),
        actor=cmd_data.get("actor", f"user:{actor_id or 'anonymous'}"),
        timestamp=cmd_data.get("timestamp", ""),
        model_version=cmd_data.get("model_version", 0),
    )
    result = await handler.execute(command)

    if not result.success:
        await manager.send_personal(
            websocket,
            {
                "type": "command:result",
                "data": result.model_dump(),
            },
        )
        return

    persist_ok = await _persist_snapshot_atomic(
        handler, command=command, actor_id=actor_id
    )

    if not persist_ok:
        # Conflicto de versión optimista en PostgreSQL:
        # 1. Revertir el comando en memoria para no desincronizar con la BD
        await handler.rollback_last_command()

        # 2. Notificar explícitamente el rechazo al cliente emisor
        await manager.send_personal(
            websocket,
            {
                "type": "command:result",
                "data": {
                    "success": False,
                    "command_id": command.command_id,
                    "error": "Conflict: El diagrama fue modificado concurrentemente por otro usuario. Sincronizando estado más reciente.",
                },
            },
        )

        # 3. Sincronizar el estado canónico actualizado hacia el cliente
        await manager.send_personal(
            websocket,
            {
                "type": "state:sync",
                "data": handler.get_state(),
            },
        )
        # NUNCA hacer broadcast a otros peers de un comando cuya persistencia falló
        return

    # Si persistió exitosamente en PostgreSQL:
    await manager.send_personal(
        websocket,
        {
            "type": "command:result",
            "data": result.model_dump(),
        },
    )

    await manager.broadcast(
        handler.board_id,
        {
            "type": "command:executed",
            "data": command.model_dump(),
        },
    )


async def _handle_chat(board_id: str, user_id: str, data: dict) -> None:
    text_msg = (data.get("data", {}).get("text") or "").strip()
    if not text_msg:
        return
    name = (
        manager.presence.get(board_id, {})
        .get(user_id, {})
        .get("name", f"User-{user_id[:6]}")
    )
    color = (
        manager.presence.get(board_id, {})
        .get(user_id, {})
        .get("color", "#cdd6f4")
    )
    await manager.broadcast(
        board_id,
        {
            "type": "chat:message",
            "data": {
                "user_id": user_id,
                "name": name,
                "color": color,
                "text": text_msg,
                "ts": data.get("data", {}).get("ts"),
            },
        },
    )


async def _handle_cursor(board_id: str, user_id: str, data: dict) -> None:
    position = data.get("data", {}).get("position", {"x": 0, "y": 0})

    if board_id in manager.presence and user_id in manager.presence[board_id]:
        manager.presence[board_id][user_id]["cursor"] = position

    await manager.broadcast(
        board_id,
        {
            "type": "cursor:update",
            "data": {"user_id": user_id, "position": position},
        },
        exclude_user=user_id,
    )


async def _handle_presence_drag(
    board_id: str, user_id: str, data: dict
) -> None:
    """
    Ephemeral live-drag broadcast.
    Peers receive a visual hint that an entity is being moved,
    but no command is created and nothing touches PostgreSQL.
    """
    drag_data = data.get("data", {})
    entity_id = drag_data.get("entity_id", "")
    position = drag_data.get("position", {"x": 0, "y": 0})
    await manager.broadcast(
        board_id,
        {
            "type": "presence:drag",
            "data": {
                "user_id": user_id,
                "entity_id": entity_id,
                "position": position,
            },
        },
        exclude_user=user_id,
    )


async def _handle_presence_selection(
    board_id: str, user_id: str, data: dict
) -> None:
    """
    Ephemeral selection / editing awareness broadcast.
    Peers render colored selection borders and editing overlays.
    No command is created and nothing touches PostgreSQL.
    """
    sel_data = data.get("data", {})
    selected_ids = sel_data.get("selected_ids", [])
    editing_id = sel_data.get("editing_id")  # may be None

    # Mirror into in-memory presence for late-joining peers (state:sync)
    if board_id in manager.presence and user_id in manager.presence[board_id]:
        manager.presence[board_id][user_id]["selection"] = selected_ids
        manager.presence[board_id][user_id]["editing"] = editing_id

    await manager.broadcast(
        board_id,
        {
            "type": "presence:selection",
            "data": {
                "user_id": user_id,
                "selected_ids": selected_ids,
                "editing_id": editing_id,
            },
        },
        exclude_user=user_id,
    )
