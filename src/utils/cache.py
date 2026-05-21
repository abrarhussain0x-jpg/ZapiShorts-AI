"""Redis-backed async cache with typed helpers and a decorator."""

import json
import logging
from functools import wraps
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_redis_client: Optional[Any] = None


def _get_client():
    """Lazy singleton Redis client (async)."""
    global _redis_client
    if _redis_client is None:
        try:
            import redis.asyncio as aioredis

            from src.config.settings import settings

            _redis_client = aioredis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=3,
            )
        except Exception as exc:
            logger.warning("Redis unavailable — caching disabled: %s", exc)
    return _redis_client


class RedisCache:
    """Typed async Redis cache wrapper."""

    async def get(self, key: str) -> Optional[Any]:
        client = _get_client()
        if client is None:
            return None
        try:
            raw = await client.get(key)
            return json.loads(raw) if raw else None
        except Exception as exc:
            logger.debug("Cache GET error [%s]: %s", key, exc)
            return None

    async def set(self, key: str, value: Any, ttl: int = 300) -> bool:
        client = _get_client()
        if client is None:
            return False
        try:
            await client.setex(key, ttl, json.dumps(value, default=str))
            return True
        except Exception as exc:
            logger.debug("Cache SET error [%s]: %s", key, exc)
            return False

    async def delete(self, key: str) -> bool:
        client = _get_client()
        if client is None:
            return False
        try:
            await client.delete(key)
            return True
        except Exception as exc:
            logger.debug("Cache DEL error [%s]: %s", key, exc)
            return False

    async def exists(self, key: str) -> bool:
        client = _get_client()
        if client is None:
            return False
        try:
            return bool(await client.exists(key))
        except Exception:
            return False

    async def invalidate_pattern(self, pattern: str) -> int:
        """Delete all keys matching glob pattern. Returns count deleted."""
        client = _get_client()
        if client is None:
            return 0
        try:
            keys = await client.keys(pattern)
            if keys:
                return await client.delete(*keys)
            return 0
        except Exception as exc:
            logger.debug("Cache INVALIDATE error [%s]: %s", pattern, exc)
            return 0

    async def publish(self, channel: str, message: Any) -> None:
        """Publish message to a Redis pub/sub channel."""
        client = _get_client()
        if client is None:
            return
        try:
            await client.publish(channel, json.dumps(message, default=str))
        except Exception as exc:
            logger.debug("Cache PUBLISH error [%s]: %s", channel, exc)


# Global cache instance
cache = RedisCache()


def cached(ttl: int = 300, key_prefix: str = ""):
    """Decorator to cache async function results in Redis."""

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Build cache key from function name + args
            parts = [key_prefix or func.__qualname__]
            parts += [str(a) for a in args if not hasattr(a, "__dict__")]
            parts += [f"{k}={v}" for k, v in sorted(kwargs.items())]
            key = "zapi:" + ":".join(parts)

            cached_val = await cache.get(key)
            if cached_val is not None:
                return cached_val

            result = await func(*args, **kwargs)
            if result is not None:
                await cache.set(key, result, ttl=ttl)
            return result

        return wrapper

    return decorator
