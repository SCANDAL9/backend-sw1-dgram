"""
redis_relay.py — Cross-replica WebSocket relay via Redis Pub/Sub.

Problem: ConnectionManager and _handlers live in a single Python process's RAM.
With N FastAPI replicas behind a load balancer, users on Replica A are invisible
to users on Replica B because broadcast() only reaches local WebSocket connections.

Solution: When a replica broadcasts to a board room it also PUBLISHes the message
to Redis channel ``board:{board_id}``.  Every replica that has at least one local
connection to that board subscribes to the same channel and relays incoming
messages to its own local connections — thus all replicas effectively share
a single logical room.

Architecture:

    Replica A                     Redis                     Replica B
    ─────────────────────         ────────────              ──────────────────────
    manager.broadcast()  ──pub──> board:xyz  ──sub──>  relay_board() task
    relay_board() task   <──sub── board:xyz  <──pub──  manager.broadcast()

Deduplication: the relay task checks the ``_replica_id`` field injected by
manager.broadcast().  If the field matches THIS replica's ID the message
originated locally and was already delivered — it is skipped silently.

Lifecycle: a relay task is started the first time a user joins a board on this
replica (via start_relay_if_needed()) and cancelled automatically when the local
room becomes empty (via stop_relay_if_empty()).
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING

from app.core import pubsub

if TYPE_CHECKING:
    from app.core.websocket.manager import ConnectionManager

logger = logging.getLogger(__name__)

# Unique identifier for this process / replica — used to deduplicate echoes.
REPLICA_ID: str = str(uuid.uuid4())

# board_id → running asyncio.Task
_relay_tasks: dict[str, asyncio.Task] = {}


async def _relay_loop(board_id: str, mgr: "ConnectionManager") -> None:
    """Subscribe to Redis, synchronize local replica memory state, and forward to local connections."""
    channel = f"board:{board_id}"
    logger.debug("Relay started for board %s (replica=%s)", board_id, REPLICA_ID)
    try:
        async for msg in pubsub.subscribe(channel):
            # Skip messages that originated on THIS replica (already sent locally)
            if msg.get("_replica_id") == REPLICA_ID:
                continue

            exclude = msg.pop("_exclude", None)
            msg.pop("_replica_id", None)

            # Sincronizar el estado en memoria de esta réplica receptora
            msg_type = msg.get("type")
            data_payload = msg.get("data", {})

            try:
                if msg_type == "command:executed":
                    from app.core.websocket.handlers import sync_remote_command_to_handler
                    sync_remote_command_to_handler(board_id, data_payload)

                elif msg_type == "yjs:update":
                    from app.core.websocket.yjs_handler import sync_remote_yjs_update
                    b64_update = data_payload.get("update")
                    if b64_update:
                        sync_remote_yjs_update(board_id, b64_update)

                elif msg_type in ("cursor:update", "presence:selection", "user:joined"):
                    uid = data_payload.get("user_id")
                    if uid:
                        mgr.update_remote_presence(board_id, uid, data_payload)

                elif msg_type == "user:left":
                    uid = data_payload.get("user_id")
                    if uid:
                        mgr.remove_remote_presence(board_id, uid)
            except Exception as sync_exc:
                logger.warning(
                    "Error al sincronizar estado en réplica local para mensaje %s en board %s: %s",
                    msg_type,
                    board_id,
                    sync_exc,
                )

            for uid, ws in list(mgr.rooms.get(board_id, {}).items()):
                if uid != exclude:
                    try:
                        await ws.send_json(msg)
                    except Exception as exc:
                        logger.debug("Fallo enviando relay a websocket de user %s: %s", uid, exc)

    except asyncio.CancelledError:
        logger.debug("Relay cancelled for board %s", board_id)
    except Exception as exc:
        logger.error("Relay error for board %s: %s", board_id, exc)


def start_relay_if_needed(board_id: str, mgr: "ConnectionManager") -> None:
    """Spawn a relay task for this board if one is not already running."""
    if board_id not in _relay_tasks or _relay_tasks[board_id].done():
        task = asyncio.create_task(
            _relay_loop(board_id, mgr),
            name=f"relay:{board_id}",
        )
        _relay_tasks[board_id] = task


def stop_relay_if_empty(board_id: str, mgr: "ConnectionManager") -> None:
    """Cancel the relay task when the local room is empty."""
    if board_id not in mgr.rooms or not mgr.rooms[board_id]:
        task = _relay_tasks.pop(board_id, None)
        if task and not task.done():
            task.cancel()
            logger.debug("Relay stopped for board %s (room empty)", board_id)
