"""Application logging configuration built on the standard library."""

import logging
import sys

from core.config.settings import LoggingSettings

_CONFIGURED = False


def configure_logging(settings: LoggingSettings) -> None:
    """Configure the root `vaos` logger according to `settings`.

    This is idempotent: calling it multiple times reconfigures the
    existing handler rather than attaching duplicate handlers.

    Args:
        settings: Logging configuration specifying level and format.
    """
    global _CONFIGURED
    root = logging.getLogger("vaos")
    root.setLevel(settings.level)

    if not _CONFIGURED:
        handler = logging.StreamHandler(stream=sys.stdout)
        handler.setFormatter(_build_formatter(settings))
        root.addHandler(handler)
        root.propagate = False
        _CONFIGURED = True
    else:
        formatter = _build_formatter(settings)
        for handler in root.handlers:
            handler.setFormatter(formatter)


def _build_formatter(settings: LoggingSettings) -> logging.Formatter:
    """Build a log formatter matching the requested output format.

    Args:
        settings: Logging configuration specifying the desired format.

    Returns:
        A configured `logging.Formatter` instance.
    """
    if settings.json_format:
        fmt = (
            '{"time": "%(asctime)s", "level": "%(levelname)s", '
            '"logger": "%(name)s", "message": "%(message)s"}'
        )
    else:
        fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    return logging.Formatter(fmt)


def get_logger(name: str) -> logging.Logger:
    """Retrieve a namespaced logger nested under the `vaos` root logger.

    Args:
        name: Logical name of the component requesting a logger, e.g.
            the dotted module path.

    Returns:
        A `logging.Logger` instance nested under `vaos`.
    """
    return logging.getLogger(f"vaos.{name}")
