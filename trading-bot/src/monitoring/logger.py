"""Structured logging setup, shared across the CLI, orchestrator, and API."""
from __future__ import annotations

import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    if root.handlers:
        return  # already configured (e.g. under a test runner)

    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    root.addHandler(handler)

    # Quiet noisy third-party loggers at INFO unless the user asked for DEBUG.
    if level.upper() != "DEBUG":
        for noisy in ("httpx", "urllib3", "asyncio"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
