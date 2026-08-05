"""Structured logging setup for VAOS, configured from a YAML dictConfig file.

Bootstrap order expects `configure_logging()` to run after configuration
is loaded (see `core.config.load_config`) but before any other component
starts logging. `config` and `logging` do not import each other: each
independently reads its own YAML file, keeping the two Core modules
decoupled.
"""

import logging
import logging.config
from pathlib import Path
from typing import Any

from .constants import (
    APP_NAME,
    DEFAULT_CONFIG_DIR,
    DEFAULT_LOG_LEVEL,
    DEFAULT_LOGGING_CONFIG_FILENAME,
)
from .exceptions import ConfigurationError
from .utils import ensure_directory, read_yaml_file


def configure_logging(config_path: Path | None = None, *, level_override: str | None = None) -> None:
    """Configure Python logging for the whole application.

    Args:
        config_path: Path to a `logging.config.dictConfig`-compatible YAML
            file. Defaults to `configs/logging.yaml`, resolved relative to
            the current working directory. A missing file is not an
            error; a sane console-only default is applied instead.
        level_override: If given, forces this level on the `vaos` root
            logger after the configuration file (or the default) has been
            applied. Intended for a `VAOS_LOG_LEVEL` environment override.

    Note:
        If the loaded schema does not explicitly set
        `disable_existing_loggers`, it defaults to False here (the
        stdlib's own default is True), so a schema that omits it does not
        silently disable every logger created before this function runs.

    Raises:
        ConfigurationError: If `config_path` exists but cannot be read or
            is not valid YAML, if its content is not a valid `dictConfig`
            schema, or if `level_override` is not a recognized level name.
    """
    resolved_path = (
        config_path if config_path is not None else DEFAULT_CONFIG_DIR / DEFAULT_LOGGING_CONFIG_FILENAME
    )
    schema = read_yaml_file(resolved_path, required=False)

    if schema:
        schema.setdefault("disable_existing_loggers", False)
        _ensure_file_handler_directories(schema)
        try:
            logging.config.dictConfig(schema)
        except (ValueError, TypeError, AttributeError, ImportError) as exc:
            raise ConfigurationError(
                f"invalid logging configuration at '{resolved_path}': {exc}",
                details={"path": str(resolved_path)},
            ) from exc
    else:
        _apply_default_configuration()

    if level_override:
        try:
            logging.getLogger(APP_NAME).setLevel(level_override)
        except ValueError as exc:
            raise ConfigurationError(
                f"invalid level_override '{level_override}': {exc}",
                details={"level_override": level_override},
            ) from exc

    get_logger(__name__).debug(
        "Logging configured from %s", resolved_path if schema else "built-in default"
    )


def _apply_default_configuration() -> None:
    """Apply a sane console-only logging configuration.

    Used when no logging configuration file is found, so the application
    still has usable logging without requiring `configs/logging.yaml`.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"))

    root = logging.getLogger(APP_NAME)
    root.setLevel(DEFAULT_LOG_LEVEL)
    root.handlers = [handler]
    root.propagate = False


def _ensure_file_handler_directories(schema: dict[str, Any]) -> None:
    """Create the parent directory of every file-based handler in `schema`.

    `logging.config.dictConfig` fails if a file handler's target directory
    does not exist; this creates it first.

    Args:
        schema: A `dictConfig`-compatible configuration mapping.
    """
    for handler_config in schema.get("handlers", {}).values():
        filename = handler_config.get("filename")
        if filename:
            ensure_directory(Path(filename).parent)


def get_logger(name: str) -> logging.Logger:
    """Retrieve a logger namespaced under the application's root logger.

    Args:
        name: Logical name of the component requesting a logger, typically
            `__name__` of the calling module.

    Returns:
        A `logging.Logger` nested under the `vaos` root logger.
    """
    return logging.getLogger(f"{APP_NAME}.{name}")
