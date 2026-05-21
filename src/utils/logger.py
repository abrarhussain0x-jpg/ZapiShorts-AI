"""Production-grade structured logging with request-ID injection and Sentry support."""

import logging
import logging.handlers
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from pythonjsonlogger.json import JsonFormatter as _BaseJsonFormatter

# ── Request-ID context variable (set by middleware) ───────────────────────────
_request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def set_request_id(request_id: str) -> None:
    _request_id_var.set(request_id)


def get_request_id() -> str:
    return _request_id_var.get()


# ── ANSI colour codes for console ─────────────────────────────────────────────
_LEVEL_COLOURS = {
    "DEBUG": "\033[36m",  # cyan
    "INFO": "\033[32m",  # green
    "WARNING": "\033[33m",  # yellow
    "ERROR": "\033[31m",  # red
    "CRITICAL": "\033[35m",  # magenta
}
_RESET = "\033[0m"


class JSONFormatter(_BaseJsonFormatter):
    """JSON log formatter with request ID, level, and exception support."""

    def add_fields(
        self,
        log_record: Dict[str, Any],
        record: logging.LogRecord,
        message_dict: Dict[str, Any],
    ) -> None:
        super().add_fields(log_record, record, message_dict)
        log_record["timestamp"] = datetime.utcnow().isoformat() + "Z"
        log_record["level"] = record.levelname
        log_record["logger"] = record.name
        log_record["module"] = record.module
        log_record["function"] = record.funcName
        log_record["line"] = record.lineno
        log_record["request_id"] = get_request_id()
        log_record["process_id"] = record.process
        log_record["thread_id"] = record.thread
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)


class ColourTextFormatter(logging.Formatter):
    """Coloured text formatter for console output."""

    def format(self, record: logging.LogRecord) -> str:
        colour = _LEVEL_COLOURS.get(record.levelname, "")
        ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S.%f")[:-3]
        level = f"{colour}{record.levelname:<8}{_RESET}"
        rid = get_request_id()
        msg = record.getMessage()
        if record.exc_info:
            msg += "\n" + self.formatException(record.exc_info)
        return f"{ts} | {level} | {record.name}:{record.lineno} | [{rid}] {msg}"


def setup_logging(
    name: str = "zapi",
    log_level: Optional[str] = None,
    logs_dir: Optional[str] = None,
) -> logging.Logger:
    """Configure a production logger with file (JSON) + console (coloured) handlers."""
    from src.config.settings import settings

    effective_level_str = (log_level or settings.log_level).upper()
    effective_level = getattr(logging, effective_level_str, logging.INFO)

    logger = logging.getLogger(name)
    logger.setLevel(effective_level)
    logger.handlers.clear()
    logger.propagate = False

    logs_path = Path(logs_dir or settings.logs_dir)
    logs_path.mkdir(parents=True, exist_ok=True)

    use_json = settings.log_format.lower() == "json"

    # ── Rotating file handler (JSON) ──────────────────────────────────────
    file_handler = logging.handlers.RotatingFileHandler(
        filename=logs_path / f"{name}.log",
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(JSONFormatter() if use_json else ColourTextFormatter())
    file_handler.setLevel(effective_level)
    logger.addHandler(file_handler)

    # ── Error-only file handler ───────────────────────────────────────────
    error_handler = logging.handlers.RotatingFileHandler(
        filename=logs_path / f"{name}_errors.log",
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    error_handler.setFormatter(JSONFormatter())
    error_handler.setLevel(logging.ERROR)
    logger.addHandler(error_handler)

    # ── Console handler (coloured text) ──────────────────────────────────
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(ColourTextFormatter())
    console_handler.setLevel(effective_level)
    logger.addHandler(console_handler)

    # ── Sentry handler (optional) ─────────────────────────────────────────
    if settings.sentry_dsn:
        try:
            import sentry_sdk
            from sentry_sdk.integrations.logging import SentryHandler

            sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.environment)
            sentry_handler = SentryHandler(level=logging.ERROR)
            logger.addHandler(sentry_handler)
        except ImportError:
            logger.warning("sentry-sdk not installed — Sentry integration disabled")

    return logger


class LoggerFactory:
    """Cached logger factory."""

    _cache: Dict[str, logging.Logger] = {}

    @classmethod
    def get_logger(cls, name: str, log_level: Optional[str] = None) -> logging.Logger:
        if name not in cls._cache:
            cls._cache[name] = setup_logging(name, log_level)
        return cls._cache[name]

    @classmethod
    def get_service_logger(cls, service_name: str) -> logging.Logger:
        return cls.get_logger(f"zapi.services.{service_name}")

    @classmethod
    def get_api_logger(cls) -> logging.Logger:
        return cls.get_logger("zapi.api")

    @classmethod
    def get_job_logger(cls, job_id: str) -> logging.Logger:
        return cls.get_logger(f"zapi.jobs.{job_id[:8]}")


def get_logger(name: str, log_level: Optional[str] = None) -> logging.Logger:
    return LoggerFactory.get_logger(name, log_level)
