"""
WebSocket Rate Limiter para dgram usando Token Bucket.
Protege el event loop de asyncio, PostgreSQL y Redis Pub/Sub contra
ráfagas abusivas de mensajes y ataques de denegación de servicio (DoS).
"""
import time
from typing import NamedTuple


class BucketConfig(NamedTuple):
    capacity: float
    refill_rate: float  # Tokens por segundo


class TokenBucket:
    __slots__ = ("capacity", "refill_rate", "tokens", "last_update")

    def __init__(self, capacity: float, refill_rate: float):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = capacity
        self.last_update = time.monotonic()

    def consume(self, cost: float = 1.0) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_update
        self.last_update = now

        # Reponer tokens proporcionales al tiempo transcurrido
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)

        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False


# Configuraciones por categoría de mensaje
CATEGORY_CONFIGS: dict[str, BucketConfig] = {
    "ephemeral": BucketConfig(capacity=60.0, refill_rate=40.0),  # cursor, drag preview
    "mutation": BucketConfig(capacity=30.0, refill_rate=15.0),   # commands, CRDT updates
    "chat": BucketConfig(capacity=5.0, refill_rate=2.0),         # mensajes de chat
    "sync": BucketConfig(capacity=4.0, refill_rate=1.0),         # snapshots y sync requests
}

MSG_TYPE_TO_CATEGORY: dict[str, str] = {
    "cursor:move": "ephemeral",
    "presence:drag": "ephemeral",
    "presence:selection": "ephemeral",
    "command:send": "mutation",
    "yjs:update": "mutation",
    "chat:message": "chat",
    "state:request": "sync",
    "yjs:sync_request": "sync",
}


class WebSocketRateLimiter:
    """
    Controlador de tasa por conexión (user_id) con buckets diferenciados por tipo de tráfico.
    """

    def __init__(self):
        # user_id -> category -> TokenBucket
        self._buckets: dict[str, dict[str, TokenBucket]] = {}

    def is_allowed(self, user_id: str, msg_type: str) -> tuple[bool, str | None]:
        """
        Evalúa si el mensaje está dentro de los límites de tasa permitidos.
        Retorna (is_allowed, category). Si el tipo de mensaje no está limitado, retorna (True, None).
        """
        category = MSG_TYPE_TO_CATEGORY.get(msg_type)
        if not category:
            return True, None

        user_buckets = self._buckets.setdefault(user_id, {})
        bucket = user_buckets.get(category)
        if bucket is None:
            config = CATEGORY_CONFIGS[category]
            bucket = TokenBucket(capacity=config.capacity, refill_rate=config.refill_rate)
            user_buckets[category] = bucket

        allowed = bucket.consume(1.0)
        return allowed, category

    def clear_user(self, user_id: str) -> None:
        """Libera la memoria de los buckets del usuario al desconectarse."""
        self._buckets.pop(user_id, None)


rate_limiter = WebSocketRateLimiter()
