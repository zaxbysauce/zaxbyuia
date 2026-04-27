"""Structlog configuration.

Stdio MCP servers must NEVER write to stdout (the MCP framing channel). All
logs go to stderr. We provide:

- JSON output when transport is HTTP (machine-parsable for log aggregators).
- Pretty/console output when transport is stdio (human-debuggable in terminals).
"""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(level: str = "INFO", *, transport: str = "stdio") -> None:
    """Initialize structlog and stdlib logging.

    Args:
        level: Standard log level name ("DEBUG", "INFO", "WARNING", ...).
        transport: ``"stdio"`` for pretty console output, anything else for JSON.

    Example:
        >>> configure_logging("DEBUG", transport="stdio")
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(level=log_level, stream=sys.stderr, format="%(message)s", force=True)

    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if transport == "stdio":
        processors.append(structlog.dev.ConsoleRenderer(colors=False))
    else:
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger for the given module/component name."""
    return structlog.get_logger(name)
