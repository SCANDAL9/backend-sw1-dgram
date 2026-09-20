"""
session_store.py — Almacén de sesiones y tokens de refresco con TTL.
Usa Redis si está disponible (vía app.core.pubsub.get_redis()), con fallback transparente a memoria.
Permite revocación en servidor y rotación de tokens sin modificar el esquema de base de datos.
"""
import time
import logging
from app.core.pubsub import get_redis

logger = logging.getLogger(__name__)

# Fallback en memoria: user_id -> {token_hash: expiration_timestamp}
_memory_store: dict[str, dict[str, float]] = {}


class SessionStore:
    KEY_PREFIX = "auth:refresh"

    @classmethod
    async def store_refresh_token(cls, user_id: str, token_hash: str, ttl_seconds: int = 604800) -> None:
        """Almacena un refresh token con tiempo de vida (por defecto 7 días)."""
        redis = get_redis()
        if redis:
            try:
                key = f"{cls.KEY_PREFIX}:{user_id}:{token_hash}"
                await redis.set(key, "1", ex=ttl_seconds)
                return
            except Exception as e:
                logger.warning("Error escribiendo en Redis, usando fallback en memoria: %s", e)

        # Fallback en memoria
        if user_id not in _memory_store:
            _memory_store[user_id] = {}
        _memory_store[user_id][token_hash] = time.time() + ttl_seconds

    @classmethod
    async def is_refresh_token_valid(cls, user_id: str, token_hash: str) -> bool:
        """Verifica si un refresh token existe y sigue vigente."""
        redis = get_redis()
        if redis:
            try:
                key = f"{cls.KEY_PREFIX}:{user_id}:{token_hash}"
                exists = await redis.exists(key)
                return bool(exists)
            except Exception as e:
                logger.warning("Error consultando Redis, consultando fallback en memoria: %s", e)

        # Fallback en memoria
        user_tokens = _memory_store.get(user_id, {})
        expires_at = user_tokens.get(token_hash)
        if not expires_at:
            return False
        if time.time() > expires_at:
            del user_tokens[token_hash]
            return False
        return True

    @classmethod
    async def revoke_refresh_token(cls, user_id: str, token_hash: str) -> None:
        """Revoca un refresh token específico (ej. en logout o tras rotación)."""
        redis = get_redis()
        if redis:
            try:
                key = f"{cls.KEY_PREFIX}:{user_id}:{token_hash}"
                await redis.delete(key)
            except Exception as e:
                logger.warning("Error eliminando clave de Redis: %s", e)

        # Fallback en memoria
        if user_id in _memory_store and token_hash in _memory_store[user_id]:
            del _memory_store[user_id][token_hash]

    @classmethod
    async def revoke_all_user_sessions(cls, user_id: str) -> None:
        """Revoca todas las sesiones activas de un usuario (ej. tras cambio de contraseña)."""
        redis = get_redis()
        if redis:
            try:
                pattern = f"{cls.KEY_PREFIX}:{user_id}:*"
                keys = []
                async for k in redis.scan_iter(match=pattern):
                    keys.append(k)
                if keys:
                    await redis.delete(*keys)
            except Exception as e:
                logger.warning("Error purgando sesiones de Redis para usuario %s: %s", user_id, e)

        # Fallback en memoria
        if user_id in _memory_store:
            del _memory_store[user_id]
