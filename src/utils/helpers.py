"""Shared helper utilities — retry, formatting, string sanitisation."""

import asyncio
import logging
import time
from functools import wraps
from typing import Any, Callable, Optional, Tuple, Type

logger = logging.getLogger(__name__)


# ── Retry helpers ─────────────────────────────────────────────────────────────


def retry_with_backoff(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
):
    """Decorator — retry a sync function with exponential back-off."""

    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = base_delay
            last_exc: Optional[Exception] = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt < max_attempts:
                        logger.warning(
                            "%s failed (attempt %d/%d), retrying in %.1fs: %s",
                            func.__name__,
                            attempt,
                            max_attempts,
                            delay,
                            exc,
                        )
                        time.sleep(delay)
                        delay *= backoff_factor
            raise last_exc

        return wrapper

    return decorator


def async_retry_with_backoff(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
):
    """Decorator — retry an async function with exponential back-off."""

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            delay = base_delay
            last_exc: Optional[Exception] = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt < max_attempts:
                        logger.warning(
                            "%s failed (attempt %d/%d), retrying in %.1fs: %s",
                            func.__name__,
                            attempt,
                            max_attempts,
                            delay,
                            exc,
                        )
                        await asyncio.sleep(delay)
                        delay *= backoff_factor
            raise last_exc

        return wrapper

    return decorator


# ── String helpers ────────────────────────────────────────────────────────────


def truncate_string(s: str, max_len: int, suffix: str = "…") -> str:
    """Truncate string to *max_len* characters, appending *suffix* if cut."""
    if len(s) <= max_len:
        return s
    return s[: max_len - len(suffix)] + suffix


def sanitise_filename(name: str, max_len: int = 100) -> str:
    """Replace filesystem-unsafe characters and enforce length limit."""
    import re

    safe = re.sub(r'[\\/:*?"<>|]', "_", name)
    safe = re.sub(r"\s+", "_", safe).strip("_. ")
    return safe[:max_len] or "unnamed"


def slugify(text: str) -> str:
    """Convert text to URL-safe slug."""
    import re
    import unicodedata

    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text).lower()
    return re.sub(r"[-\s]+", "-", text).strip("-")


# ── Number / size helpers ─────────────────────────────────────────────────────


def format_duration(seconds: float) -> str:
    """Convert seconds to HH:MM:SS string."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def clamp(value: float, min_val: float, max_val: float) -> float:
    return max(min_val, min(max_val, value))


# ── Dict helpers ──────────────────────────────────────────────────────────────


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base* (non-destructive)."""
    result = base.copy()
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def flatten_dict(d: dict, parent_key: str = "", sep: str = ".") -> dict:
    """Flatten nested dict to dot-notation keys."""
    items: list = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep).items())
        else:
            items.append((new_key, v))
    return dict(items)
