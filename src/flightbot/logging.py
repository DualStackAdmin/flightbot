"""Structured logging (structlog) with secret redaction.

Secrets (bot token, provider token, webhook secret) and anything shaped like a Telegram bot token are replaced
with "***" in every log line and in Sentry events, including formatted exception tracebacks. Telegram API URLs
contain the bot token (`/bot<TOKEN>/method`), so network errors would otherwise leak it.
"""

import logging
import re
import sys
from collections.abc import Iterable
from typing import Any

import structlog

TELEGRAM_TOKEN_RE = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b")
REDACTED = "***"
_secrets: list[str] = []


def set_secrets(secrets: Iterable[str | None]) -> None:
    """Register secret values to redact. Short values are ignored to avoid mangling ordinary text."""
    _secrets[:] = sorted({s for s in secrets if s and len(s) >= 8}, key=len, reverse=True)


def redact_text(text: str) -> str:
    for s in _secrets:
        if s in text:
            text = text.replace(s, REDACTED)
    return TELEGRAM_TOKEN_RE.sub(REDACTED, text)


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: _redact_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return type(value)(_redact_value(v) for v in value)
    return value


def redact_processor(_logger, _method, event_dict: dict) -> dict:
    for key, value in list(event_dict.items()):
        if not key.startswith("_"):
            event_dict[key] = _redact_value(value)
    return event_dict


def sentry_before_send(event: dict, _hint: dict) -> dict:
    """Sentry hook: scrub secrets from the whole event (messages, exception values, breadcrumbs, request URLs)."""
    return _redact_value(event)


def setup_logging(level: str = "INFO", json_logs: bool = False, secrets: Iterable[str | None] = ()) -> None:
    set_secrets(secrets)
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        timestamper,
    ]
    renderer = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                # Render tracebacks to text first, so the redactor also sees exception messages and URLs
                structlog.processors.format_exc_info,
                redact_processor,
                renderer,
            ],
        )
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "aiogram.event"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
