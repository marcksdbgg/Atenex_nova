"""Atenex Nova — Structured logging setup."""

import logging
import sys
from typing import Any


def setup_logging(level: str = "INFO") -> None:
    """Configure structured logging for the application."""
    log_format = "%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s"

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=log_format,
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    # Reduce noise from third-party libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str, **context: Any) -> logging.Logger:
    """Get a logger with optional context fields.

    Args:
        name: Logger name, typically __name__ of the calling module.
        **context: Additional context fields for log messages.

    Returns:
        Configured logger instance.
    """
    logger = logging.getLogger(name)
    return logger
