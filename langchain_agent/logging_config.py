"""
Structured logging configuration using structlog.

Provides:
- configure_logging(): Setup structlog with JSON/console output
- get_logger(name): Get a bound logger for a module
"""

import logging
import sys

import structlog
from structlog.types import Processor

from config import LOG_FORMAT, LOG_INCLUDE_TIMESTAMP, LOG_LEVEL


def configure_logging() -> None:
    """
    Configure structlog for the application.

    Uses LOG_FORMAT from config to determine output format:
    - "json": JSON output for production (machine-readable)
    - "console": Human-readable console output for development

    Uses LOG_LEVEL from config to set logging verbosity.
    """
    # Shared processors for all output formats
    # NOTE: Removed filter_by_level as it fails in thread pool contexts with None logger
    # Filtering is handled by root logger level instead
    shared_processors: list[Processor] = [
        # structlog.stdlib.filter_by_level,  # DISABLED: fails in thread pools
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.contextvars.merge_contextvars,
        structlog.processors.CallsiteParameterAdder(
            {
                structlog.processors.CallsiteParameter.FILENAME,
                structlog.processors.CallsiteParameter.LINENO,
            }
        ),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if LOG_INCLUDE_TIMESTAMP:
        shared_processors.insert(0, structlog.processors.TimeStamper(fmt="iso"))

    # Format-specific renderer
    if LOG_FORMAT == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        # Console format with colors for development
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    # Configure structlog
    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure standard library logging to use structlog
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    # Setup root handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

    # Set levels for noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """
    Get a structured logger for a module.

    Args:
        name: Logger name (typically __name__)

    Returns:
        BoundLogger instance with structured logging capabilities
    """
    return structlog.get_logger(name)
