"""Centralized logging setup for ContextPilot."""
import logging
import json
import os


class JSONFormatter(logging.Formatter):
    """JSON log formatter for structured logging."""

    def format(self, record):
        log_data = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "extra_data"):
            log_data.update(record.extra_data)
        if record.exc_info and record.exc_info[0]:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data)


def get_logger(name: str) -> logging.Logger:
    """Get a named logger with consistent config."""
    logger = logging.getLogger(f"contextpilot.{name}")
    return logger


def setup_logging():
    """Initialize logging. Call once at startup."""
    level = os.environ.get("CONTEXTPILOT_LOG_LEVEL", "INFO").upper()
    fmt = os.environ.get("CONTEXTPILOT_LOG_FORMAT", "text")  # "text" or "json"

    root = logging.getLogger("contextpilot")
    root.setLevel(getattr(logging, level, logging.INFO))

    if not root.handlers:
        handler = logging.StreamHandler()
        if fmt == "json":
            handler.setFormatter(JSONFormatter())
        else:
            handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            ))
        root.addHandler(handler)
