"""Structured JSON logging configuration."""

import logging
import sys
from typing import Any, cast

import structlog
from structlog.typing import EventDict, WrappedLogger

SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "cookie",
        "credentials",
        "database_url",
        "nobitex_api",
        "nobitex_token",
        "password",
        "postgres_password",
        "proxy_authorization",
        "refresh_token",
        "secret",
        "set_cookie",
        "telegram_bot_token",
        "token",
    }
)
SENSITIVE_SUFFIXES = ("_api_key", "_authorization", "_password", "_secret", "_token")


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).strip().lower().replace("-", "_")
    return normalized in SENSITIVE_KEYS or normalized.endswith(SENSITIVE_SUFFIXES)


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if _is_sensitive_key(key) else _redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item) for item in value)
    return value


def _redact_secrets(
    _logger: WrappedLogger | None, _method_name: str, event_dict: EventDict
) -> EventDict:
    return cast(EventDict, _redact_value(event_dict))


def configure_logging(log_level: str = "INFO") -> None:
    """Configure standard-library and structlog output as one JSON stream."""
    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level, force=True)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
            _redact_secrets,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger() -> Any:
    return structlog.get_logger()
