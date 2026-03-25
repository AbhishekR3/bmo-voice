"""
BMO Voice — Centralized Logging Configuration

All components use Python `logging` under the `bmo` namespace.
Each component gets its own child logger (e.g., bmo.rag, bmo.stt).

Usage:
    from server.logging_config import setup_logging, get_logger

    # Call once at startup (in main.py)
    setup_logging()

    # In each component module
    logger = get_logger("rag")      # returns logging.getLogger("bmo.rag")
    logger.info("Indexed: %s → %d chunks", path, count)
"""

import logging
import logging.handlers
import os
import sys
from pathlib import Path

LOG_DIR = Path.home() / ".bmo-voice" / "logs"
LOG_FILE = LOG_DIR / "bmo.log"
MAX_BYTES = 10 * 1024 * 1024  # 10 MB per log file
BACKUP_COUNT = 5               # keep 5 rotated files (50 MB total max)
DEFAULT_LEVEL = logging.INFO

# Format: [2026-03-25 14:30:05.123] [bmo.stt] [INFO] message
LOG_FORMAT = "[%(asctime)s.%(msecs)03d] [%(name)s] [%(levelname)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: int = DEFAULT_LEVEL) -> None:
    """Configure the root `bmo` logger with console and file handlers.

    Should be called once at application startup before any component
    initializes its logger.

    Args:
        level: Logging level for the bmo logger. Defaults to INFO.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # Console handler — stderr so stdout stays clean for any structured output
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)

    # File handler — rotating to prevent unbounded disk usage
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)  # file captures everything

    # Configure the bmo root logger
    bmo_logger = logging.getLogger("bmo")
    bmo_logger.setLevel(logging.DEBUG)  # let handlers decide filtering
    bmo_logger.handlers.clear()         # prevent duplicate handlers on re-call
    bmo_logger.addHandler(console_handler)
    bmo_logger.addHandler(file_handler)

    # Don't propagate to the root logger
    bmo_logger.propagate = False

    bmo_logger.info("Logging initialized (console=%s, file=%s)", logging.getLevelName(level), LOG_FILE)


def get_logger(component: str) -> logging.Logger:
    """Get a namespaced logger for a BMO component.

    Args:
        component: Component name (e.g., "rag", "stt", "llm").
                   Will be prefixed with "bmo." automatically.

    Returns:
        A logger instance named "bmo.{component}".
    """
    return logging.getLogger(f"bmo.{component}")
