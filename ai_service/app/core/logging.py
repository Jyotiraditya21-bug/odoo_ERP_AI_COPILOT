import logging
import re
from typing import Any

import structlog

SECRET_KEYS = re.compile(r"(action[_-]?id|api[_-]?key|service[_-]?key|token|password|secret)", re.I)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if SECRET_KEYS.search(str(key)) else redact(val)
            for key, val in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"(?i)bearer\s+[a-z0-9._-]+", "Bearer [REDACTED]", value)
        value = re.sub(r"\bsk-[a-zA-Z0-9_-]{12,}\b", "[REDACTED]", value)
        value = re.sub(
            r"(?i)(password|api[_ -]?key|secret)\s*[:=]\s*\S+",
            r"\1=[REDACTED]",
            value,
        )
    return value


def configure_logging(level: str) -> None:
    logging.basicConfig(level=level.upper(), format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
    )


logger = structlog.get_logger()
