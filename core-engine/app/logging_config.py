"""Structured JSON logging configuration."""

import json
import logging
import sys
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Outputs log records as JSON for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        log = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add extra fields (request_id, method, path, etc.)
        for key in ("request_id", "method", "path", "status", "duration_ms",
                     "error", "error_type", "stock_code", "order_id"):
            if hasattr(record, key):
                log[key] = getattr(record, key)

        if record.exc_info and record.exc_info[1]:
            log["exception"] = str(record.exc_info[1])

        return json.dumps(log, ensure_ascii=False)


def setup_logging(json_format: bool = True):
    """Configure logging for the application."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Remove existing handlers
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    if json_format:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s"
        ))

    root.addHandler(handler)

    # Quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
