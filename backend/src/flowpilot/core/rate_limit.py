"""Rate limiting utility backed by Redis with in-memory fallback."""

import asyncio
import time
from collections import defaultdict

import redis.asyncio as aioredis

from flowpilot.core.config import get_settings
from flowpilot.core.logging import get_logger

logger = get_logger("core.rate_limit")

# In-memory fallback: key -> list of timestamp floats
_memory_cache: dict[str, list[float]] = defaultdict(list)
_memory_lock = asyncio.Lock()


async def check_rate_limit(
    key: str,
    max_requests: int = 5,
    window_seconds: int = 60,
) -> bool:
    """Check if the given key has exceeded the rate limit.

    Returns:
        True if the request is permitted.
        False if the limit has been exceeded.
    """
    settings = get_settings()

    if (settings.is_testing or ":testclient" in key) and not key.startswith("test_ratelimit:"):
        return True

    # Attempt Redis-based rate limiting first
    try:
        r = aioredis.from_url(settings.REDIS_URL, socket_timeout=1.0)
        async with r:
            redis_key = f"flowpilot:ratelimit:{key}"
            current = await r.incr(redis_key)
            if current == 1:
                await r.expire(redis_key, window_seconds)
            return current <= max_requests
    except Exception as exc:
        logger.debug("Redis rate limit unavailable, using in-memory fallback: %s", exc)

    # In-memory sliding window fallback
    async with _memory_lock:
        now = time.time()
        window_start = now - window_seconds

        # Clean timestamps older than window
        timestamps = [ts for ts in _memory_cache[key] if ts > window_start]
        if len(timestamps) >= max_requests:
            _memory_cache[key] = timestamps
            return False

        timestamps.append(now)
        _memory_cache[key] = timestamps
        return True
