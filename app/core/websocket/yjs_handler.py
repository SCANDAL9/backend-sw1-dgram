"""
Handler de mensajes Yjs (CRDT) sobre WebSocket para dgram.
Gestiona el intercambio de diffs binarios con fusión determinista en memoria
usando pycrdt y persistencia diferida de snapshots en PostgreSQL.
"""
import base64
import asyncio
import logging
import pycrdt
from fastapi import WebSocket
from app.core.database import async_session_factory
from app.modeling.diagram.service.yjs_persistence_service import load_ydoc_state, save_ydoc_state
from app.core.websocket.manager import manager

logger = logging.getLogger(__name__)

# Debounce tasks per board: board_id -> asyncio.Task
_persist_tasks: dict[str, asyncio.Task] = {}
# Active in-memory pycrdt.Doc per board: board_id -> pycrdt.Doc
_active_docs: dict[str, pycrdt.Doc] = {}
# Buffered latest state per board (for compatibility/inspection)
_state_buffers: dict[str, bytes] = {}


async def get_or_create_board_doc(board_id: str) -> pycrdt.Doc:
    """Obtiene o carga el documento CRDT en memoria para el tablero."""
    doc = _active_docs.get(board_id)
    if doc is None:
        doc = pycrdt.Doc()
        try:
            async with async_session_factory() as db:
                state_bytes = await load_ydoc_state(db, board_id)
                if state_bytes:
                    doc.apply_update(state_bytes)
        except Exception as exc:
            logger.warning("No se pudo cargar snapshot inicial de base de datos para board %s: %s", board_id, exc)
        _active_docs[board_id] = doc
        _state_buffers[board_id] = doc.get_update()
    return doc


async def handle_yjs_sync_request(websocket: WebSocket, board_id: str) -> None:
    """Envía el estado CRDT Yjs completo consolidado al cliente que se conecta."""
    doc = await get_or_create_board_doc(board_id)
    state_bytes = doc.get_update()

    if state_bytes:
        b64_state = base64.b64encode(state_bytes).decode("ascii")
        await manager.send_personal(
            websocket,
            {
                "type": "yjs:sync",
                "data": {"board_id": board_id, "state": b64_state},
            },
        )


async def handle_yjs_update(board_id: str, user_id: str, data: dict) -> None:
    """
    Aplica una actualización CRDT incremental al documento del tablero con fusión real,
    la retransmite a los peers y programa su persistencia en PostgreSQL con debounce.
    """
    update_data = data.get("data", {})
    b64_update = update_data.get("update")
    if not b64_update:
        return

    # 1. Retransmitir a los otros peers conectados
    await manager.broadcast(
        board_id,
        {
            "type": "yjs:update",
            "data": {
                "board_id": board_id,
                "user_id": user_id,
                "update": b64_update,
            },
        },
        exclude_user=user_id,
    )

    # 2. Decodificar delta y fusionarlo en el pycrdt.Doc en memoria
    try:
        raw_bytes = base64.b64decode(b64_update)
        doc = await get_or_create_board_doc(board_id)
        doc.apply_update(raw_bytes)
        _state_buffers[board_id] = doc.get_update()

        # Debounced persistence a PostgreSQL (espera 2s de inactividad)
        if board_id in _persist_tasks and not _persist_tasks[board_id].done():
            _persist_tasks[board_id].cancel()

        async def _debounced_save(bid: str, ydoc: pycrdt.Doc):
            try:
                await asyncio.sleep(2.0)
                snapshot_bytes = ydoc.get_update()
                async with async_session_factory() as db:
                    await save_ydoc_state(db, bid, snapshot_bytes)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error("[YjsHandler] Error persisting ydoc state: %s", e)

        _persist_tasks[board_id] = asyncio.create_task(_debounced_save(board_id, doc))
    except Exception as err:
        logger.error("[YjsHandler] Failed to process Yjs update: %s", err)


def sync_remote_yjs_update(board_id: str, b64_update: str) -> bool:
    """
    Aplica una actualización CRDT proveniente de otra réplica en el doc local
    sin reprogramar debounce a PostgreSQL (la réplica originaria ya lo gestiona).
    """
    doc = _active_docs.get(board_id)
    if not doc or not b64_update:
        return False
    try:
        raw_bytes = base64.b64decode(b64_update)
        doc.apply_update(raw_bytes)
        _state_buffers[board_id] = doc.get_update()
        return True
    except Exception as exc:
        logger.error("[YjsHandler] Failed to apply remote Yjs update for board %s: %s", board_id, exc)
        return False
