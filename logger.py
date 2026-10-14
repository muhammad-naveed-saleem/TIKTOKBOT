"""
logger.py
─────────
Centralised logging configuration for the entire pipeline.
Every module imports `get_logger(__name__)` to get a named logger
that writes both to the console (colour-coded) and a rotating log file.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path("./logs")
LOG_FILE = LOG_DIR / "tiktok_bot.log"
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# ANSI colour codes for console output
COLOURS = {
    logging.DEBUG: "\033[36m",     # Cyan
    logging.INFO: "\033[32m",      # Green
    logging.WARNING: "\033[33m",   # Yellow
    logging.ERROR: "\033[31m",     # Red
    logging.CRITICAL: "\033[35m",  # Magenta
}
RESET = "\033[0m"


class ColourFormatter(logging.Formatter):
    """Apply ANSI colour codes based on log level (console only)."""

    def format(self, record: logging.LogRecord) -> str:
        colour = COLOURS.get(record.levelno, "")
        message = super().format(record)
        return f"{colour}{message}{RESET}"


def _setup_root_logger() -> None:
    """Configure root logger once at import time."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    if root.handlers:
        return  # Already configured; avoid duplicate handlers

    root.setLevel(logging.DEBUG)

    # ── Console handler ───────────────────────────────────────────────────────
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(
        ColourFormatter(fmt=LOG_FORMAT, datefmt=DATE_FORMAT)
    )

    # ── Rotating file handler (max 5 MB × 3 backups) ─────────────────────────
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(fmt=LOG_FORMAT, datefmt=DATE_FORMAT)
    )

    root.addHandler(console_handler)
    root.addHandler(file_handler)


_setup_root_logger()


def get_logger(name: str) -> logging.Logger:
    """Return a named logger; call with `get_logger(__name__)`."""
    return logging.getLogger(name)
