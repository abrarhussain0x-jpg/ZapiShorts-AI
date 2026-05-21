"""Job queue configuration — Celery with fallback capability."""

import logging
import os
import sys

from src.config.settings import settings

logger = logging.getLogger(__name__)

_CELERY_ENABLED = True
try:
    from celery import Celery
except ImportError:
    _CELERY_ENABLED = False
    logger.warning("Celery not installed — running in fallback (inline) mode")


def make_celery(app_name=__name__):
    if not _CELERY_ENABLED:

        class FakeCelery:
            def task(self, *args, **kwargs):
                def decorator(fn):
                    fn.delay = lambda *a, **k: fn(*a, **k)
                    fn.apply_async = lambda args=(), kwargs=None, **opts: fn(
                        *args, **(kwargs or {})
                    )
                    return fn

                return decorator

            class control:
                class inspect:
                    def active(self):
                        return None

        return FakeCelery()

    c_app = Celery(
        app_name,
        broker=settings.redis_url,
        backend=settings.redis_url,
    )

    c_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
        task_time_limit=settings.job_timeout_minutes * 60,
        worker_prefetch_multiplier=1,
        worker_max_tasks_per_child=50,
        broker_connection_retry_on_startup=True,
    )
    return c_app


celery_app = make_celery("zapi_celery")


def is_celery_available() -> bool:
    """Check if the broker is actually reachable."""
    if not _CELERY_ENABLED:
        return False
    try:
        with celery_app.connection() as conn:
            conn.heartbeat_check()
        return True
    except Exception:
        return False


def get_worker_stats() -> dict:
    """Return a stats dict with keys: status, workers, tasks (int).

    Always present regardless of Celery availability or broker connectivity.
    """
    if not _CELERY_ENABLED:
        return {"status": "fallback", "workers": 0, "tasks": 0}
    try:
        i = celery_app.control.inspect()
        active = i.active() or {}
        return {
            "status": "connected",
            "workers": len(active),
            "tasks": sum(len(v) for v in active.values()),
        }
    except Exception:
        return {"status": "disconnected", "workers": 0, "tasks": 0}


if __name__ == "__main__":
    if _CELERY_ENABLED:
        celery_app.worker_main(
            [
                "worker",
                "--loglevel=info",
                "-P",
                "solo" if sys.platform == "win32" else "prefork",
            ]
        )
