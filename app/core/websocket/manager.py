import random
import logging
from fastapi import WebSocket
from app.core import pubsub
from app.core.websocket.redis_relay import REPLICA_ID, start_relay_if_needed, stop_relay_if_empty

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Manages WebSocket connections per board room with presence tracking.

    Broadcast strategy (horizontal scaling):
      1. Send to all local WebSocket connections on this replica.
      2. Publish to Redis channel ``board:{board_id}`` so other replicas
         relay the message to their own local connections.

    The ``_replica_id`` field is injected into each published message so relay
    tasks on this same replica can identify and skip their own echoes.
    """

    def __init__(self):
        self.rooms: dict[str, dict[str, WebSocket]] = {}
        self.presence: dict[str, dict[str, dict]] = {}

    async def connect(self, websocket: WebSocket, board_id: str, user_id: str) -> None:
        await websocket.accept()

        if board_id not in self.rooms:
            self.rooms[board_id] = {}
            self.presence[board_id] = {}

        self.rooms[board_id][user_id] = websocket
        color = f"#{random.randint(0x333333, 0xDDDDDD):06x}"
        self.presence[board_id][user_id] = {
            "cursor": {"x": 0, "y": 0},
            "color": color,
            "name": f"User-{user_id[:6]}",
            "selection": [],
            "editing": None,
        }

        # Start cross-replica relay task for this board (idempotent)
        start_relay_if_needed(board_id, self)

        await self.broadcast(
            board_id,
            {"type": "user:joined", "data": {"user_id": user_id, "color": color}},
            exclude_user=user_id,
        )

    async def disconnect(self, board_id: str, user_id: str) -> None:
        if board_id in self.rooms:
            self.rooms[board_id].pop(user_id, None)
            self.presence[board_id].pop(user_id, None)

            if not self.rooms[board_id]:
                del self.rooms[board_id]
                del self.presence[board_id]
                # Cancel relay — room is empty on this replica
                stop_relay_if_empty(board_id, self)
            else:
                await self.broadcast(
                    board_id,
                    {"type": "user:left", "data": {"user_id": user_id}},
                )

    async def kick_local(self, board_id: str, user_id: str, reason: str = "Acceso revocado") -> None:
        """Desconecta a un usuario expulsado en esta réplica local cerrando su WebSocket con 4003."""
        ws = self.rooms.get(board_id, {}).get(user_id)
        if ws:
            try:
                await ws.send_json({"type": "error", "message": reason})
                await ws.close(code=4003)
            except Exception as exc:
                logger.debug("Error cerrando socket de usuario expulsado %s: %s", user_id, exc)
            await self.disconnect(board_id, user_id)

    async def kick_user(self, board_id: str, user_id: str, reason: str = "Acceso revocado") -> None:
        """Expulsa a un usuario tanto localmente como difundiendo la orden por Redis a las demás réplicas."""
        await self.kick_local(board_id, user_id, reason)
        try:
            redis_msg = {
                "type": "member:kicked",
                "board_id": board_id,
                "user_id": user_id,
                "reason": reason,
                "_replica_id": REPLICA_ID,
            }
            await pubsub.publish(f"board:{board_id}", redis_msg)
        except Exception as exc:
            logger.warning("Fallo al publicar member:kicked en Redis para board %s: %s", board_id, exc)

    async def broadcast(
        self, board_id: str, message: dict, exclude_user: str | None = None
    ) -> None:
        # 1. Deliver to local connections on this replica
        for uid, ws in list(self.rooms.get(board_id, {}).items()):
            if uid != exclude_user:
                try:
                    await ws.send_json(message)
                except Exception as exc:
                    logger.debug(
                        "Fallo al enviar mensaje local a user %s en board %s: %s",
                        uid,
                        board_id,
                        exc,
                    )


        # 2. Publish to Redis so other replicas can relay
        try:
            redis_msg = {**message, "_replica_id": REPLICA_ID, "_exclude": exclude_user}
            await pubsub.publish(f"board:{board_id}", redis_msg)
        except Exception as exc:
            # Non-fatal: Redis unavailable degrades to single-replica mode
            logger.warning("Redis publish failed for board %s: %s", board_id, exc)

    async def send_personal(self, websocket: WebSocket, message: dict) -> None:
        await websocket.send_json(message)

    def get_room_users(self, board_id: str) -> list[dict]:
        return list(self.presence.get(board_id, {}).values())

    def update_remote_presence(self, board_id: str, user_id: str, data: dict) -> None:
        """Actualiza la presencia local con datos provenientes de otra réplica."""
        if not board_id or not user_id:
            return
        if board_id not in self.presence:
            self.presence[board_id] = {}
        if user_id not in self.presence[board_id]:
            self.presence[board_id][user_id] = {
                "cursor": {"x": 0, "y": 0},
                "color": data.get("color", "#999999"),
                "name": data.get("name", f"User-{user_id[:6]}"),
                "selection": [],
                "editing": None,
            }

        user_pres = self.presence[board_id][user_id]
        if "position" in data:
            user_pres["cursor"] = data["position"]
        elif "cursor" in data:
            user_pres["cursor"] = data["cursor"]
        if "selected_ids" in data:
            user_pres["selection"] = data["selected_ids"]
        if "editing_id" in data:
            user_pres["editing"] = data["editing_id"]
        if "color" in data:
            user_pres["color"] = data["color"]
        if "name" in data:
            user_pres["name"] = data["name"]

    def remove_remote_presence(self, board_id: str, user_id: str) -> None:
        """Elimina la presencia de un usuario cuando se desconecta en otra réplica."""
        if board_id in self.presence:
            self.presence[board_id].pop(user_id, None)


manager = ConnectionManager()
