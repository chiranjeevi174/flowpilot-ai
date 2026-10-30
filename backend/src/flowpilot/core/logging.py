"""Centralized logging configuration for FlowPilot."""

import logging
import re
import sys

from flowpilot.core.config import get_settings

_REDACTION_PATTERNS = [
    (re.compile(r"gsk_[A-Za-z0-9_]{20,}"), "gsk_***[REDACTED]"),
    (re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}"), "sk-***[REDACTED]"),
    (re.compile(r"AIzaSy[A-Za-z0-9_-]{30,}"), "AIzaSy***[REDACTED]"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9_-]{10,}"), "xox*-***[REDACTED]"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9_\-\.]{20,}", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r'("password"\s*:\s*")[^"]+(")'), r"\1[REDACTED]\2"),
    (re.compile(r'("api_key"\s*:\s*")[^"]+(")'), r"\1[REDACTED]\2"),
]


class SensitiveDataFilter(logging.Filter):
    """Log filter that intercepts and masks credentials and API tokens."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            for pattern, repl in _REDACTION_PATTERNS:
                record.msg = pattern.sub(repl, record.msg)
        if record.args:
            if isinstance(record.args, dict):
                clean_args = {}
                for k, v in record.args.items():
                    if isinstance(v, str):
                        for pattern, repl in _REDACTION_PATTERNS:
                            v = pattern.sub(repl, v)
                    clean_args[k] = v
                record.args = clean_args
            elif isinstance(record.args, tuple):
                clean_list = []
                for v in record.args:
                    if isinstance(v, str):
                        for pattern, repl in _REDACTION_PATTERNS:
                            v = pattern.sub(repl, v)
                    clean_list.append(v)
                record.args = tuple(clean_list)
        return True


def setup_logging(log_level: str | None = None) -> logging.Logger:
    """Configure centralized application logging with consistent formatting and secret redaction."""
    settings = get_settings()
    level_name = (log_level or settings.LOG_LEVEL).upper()
    level = getattr(logging, level_name, logging.INFO)

    log_format = "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(SensitiveDataFilter())

    # Configure root logger
    logging.basicConfig(
        level=level,
        format=log_format,
        datefmt=date_format,
        handlers=[handler],
        force=True,
    )

    # Align external library log levels
    logging.getLogger("uvicorn").setLevel(level)
    logging.getLogger("uvicorn.error").setLevel(level)
    logging.getLogger("uvicorn.access").setLevel(level)

    logger = logging.getLogger("flowpilot")
    logger.setLevel(level)
    return logger


def get_logger(name: str) -> logging.Logger:
    """Return a logger instance within the flowpilot namespace."""
    prefix = "flowpilot"
    logger_name = f"{prefix}.{name}" if not name.startswith(prefix) else name
    return logging.getLogger(logger_name)
