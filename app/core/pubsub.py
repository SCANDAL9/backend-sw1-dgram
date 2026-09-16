"""
pubsub.py — Redis Pub/Sub client for cross-replica WebSocket message routing.

Each FastAPI replica subscribes to the channels for the boards it hosts locally.
When a message arrives via broadcast(), it is published here so other replicas
can relay it to their own local WebSocket connections.

Channel naming:
  board:{board_id}   — broadcast messages for a specific board room
  presence:{board_id} — heartbeat / join / leave presence events (future use)
"""
from __future__ import annotations

import json
import asyncio
import logging
from typing import AsyncGenerator

import redis.asyncio as aioredis
from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Module-level singleton — initialised once in lifespan, shared across workers.
_redis_client: aioredis.Redis | None = None


async def init_redis() -> None:
    """Connect the module-level Redis client. Call once from app lifespan."""
    global _redis_client
    settings = get_settings()
    _redis_client = aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
    )
    # Verify connectivity
    await _redis_client.ping()
    logger.info("Redis Pub/Sub connected: %s", settings.redis_url)


async def close_redis() -> None:
    """Gracefully close the Redis connection. Call once from app lifespan."""
    global _redis_client
    if _redis_client:
        await _redis_client.aclose()
        _redis_client = None
        logger.info("Redis Pub/Sub connection closed.")


def _get_client() -> aioredis.Redis:
    if _redis_client is None:
        raise RuntimeError("Redis client not initialised — call pubsub.init_redis() first.")
    return _redis_client


def get_redis() -> aioredis.Redis | None:
    """Return the active Redis client if initialized, or None."""
    return _redis_client


async def publish(channel: str, message: dict) -> None:
    """
    Publish a message to a Redis channel.

    The message dict is JSON-serialised. The ``_source`` field is NOT added here
    so callers control the envelope; replicas rely on ConnectionManager to avoid
    re-broadcasting messages that originated locally.
    """
    client = _get_client()
    await client.publish(channel, json.dumps(message, ensure_ascii=False))


async def subscribe(channel: str) -> AsyncGenerator[dict, None]:
    """
    Async generator that yields parsed messages from a Redis channel.

    Each iteration yields one decoded dict. The generator runs until the caller
    breaks out or the task is cancelled.

    Usage::
        async for msg in pubsub.subscribe("board:abc"):
            await relay_to_local_connections(msg)
    """
    client = _get_client()
    ps = client.pubsub()
    await ps.subscribe(channel)
    try:
        async for raw in ps.listen():
            if raw["type"] == "message" and raw.get("data"):
                try:
                    yield json.loads(raw["data"])
                except (json.JSONDecodeError, TypeError):
                    logger.warning("Malformed pubsub message on %s: %r", channel, raw["data"])
    finally:
        await ps.unsubscribe(channel)
        await ps.aclose()
