"""Structured logging configuration."""

import logging
import sys


class _FlushingStreamHandler(logging.StreamHandler):
    """Write each record immediately so Cursor/PowerShell terminals stay current."""

    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        self.flush()


def setup_logging(level: str = "INFO") -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except (AttributeError, OSError, ValueError):
        pass

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler = _FlushingStreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    for existing in list(root.handlers):
        if isinstance(existing, logging.StreamHandler):
            root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(log_level)

    # Keep request access lines next to uvicorn startup logs (stderr), not stdout.
    access = logging.getLogger("uvicorn.access")
    for access_handler in access.handlers:
        if isinstance(access_handler, logging.StreamHandler):
            access_handler.stream = sys.stderr
