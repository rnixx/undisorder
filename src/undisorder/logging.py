"""Logging configuration for undisorder."""

from __future__ import annotations

import logging


def configure_logging(verbose: bool = False, quiet: bool = False) -> None:
    """Configure the undisorder root logger."""
    if verbose:
        level = logging.DEBUG
        fmt = "%(levelname)s: %(message)s"
    elif quiet:
        level = logging.WARNING
        fmt = "%(levelname)s: %(message)s"
    else:
        level = logging.INFO
        fmt = "%(message)s"

    root_logger = logging.getLogger("undisorder")
    root_logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(fmt))
    root_logger.setLevel(level)
    root_logger.addHandler(handler)
