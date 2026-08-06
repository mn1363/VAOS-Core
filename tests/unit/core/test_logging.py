"""Unit tests for `src.core.logging`."""

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from src.core.exceptions import ConfigurationError
from src.core.logging import configure_logging, get_logger


@pytest.fixture(autouse=True)
def _reset_vaos_logger() -> Iterator[None]:
    """Reset the `vaos` logger's handlers and level before and after every test."""
    logger = logging.getLogger("vaos")
    original_handlers = list(logger.handlers)
    original_level = logger.level
    yield
    logger.handlers = original_handlers
    logger.setLevel(original_level)


def test_get_logger_is_namespaced_under_vaos() -> None:
    """`get_logger` should return a logger nested under the `vaos` root."""
    logger = get_logger("some.module")

    assert logger.name == "vaos.some.module"


def test_configure_logging_without_a_file_applies_default(tmp_path: Path) -> None:
    """With no logging.yaml present, a working console handler should still attach."""
    configure_logging(tmp_path / "missing.yaml")

    root = logging.getLogger("vaos")

    assert root.handlers
    assert root.level == logging.INFO


def test_configure_logging_applies_a_valid_dictconfig_file(tmp_path: Path) -> None:
    """A valid dictConfig YAML file should be applied via `logging.config.dictConfig`."""
    config_file = tmp_path / "logging.yaml"
    config_file.write_text(
        "version: 1\n"
        "disable_existing_loggers: false\n"
        "handlers:\n"
        "  console:\n"
        "    class: logging.StreamHandler\n"
        "    level: DEBUG\n"
        "loggers:\n"
        "  vaos:\n"
        "    level: DEBUG\n"
        "    handlers: [console]\n"
        "    propagate: false\n",
        encoding="utf-8",
    )

    configure_logging(config_file)

    root = logging.getLogger("vaos")
    assert root.level == logging.DEBUG
    assert len(root.handlers) == 1


def test_configure_logging_creates_file_handler_directory(tmp_path: Path) -> None:
    """A file handler's target directory should be created before dictConfig runs."""
    log_dir = tmp_path / "nested" / "logs"
    log_file = log_dir / "vaos.log"
    config_file = tmp_path / "logging.yaml"
    config_file.write_text(
        "version: 1\n"
        "disable_existing_loggers: false\n"
        "handlers:\n"
        "  file:\n"
        "    class: logging.FileHandler\n"
        f"    filename: {log_file}\n"
        "    level: INFO\n"
        "loggers:\n"
        "  vaos:\n"
        "    level: INFO\n"
        "    handlers: [file]\n"
        "    propagate: false\n",
        encoding="utf-8",
    )
    assert not log_dir.exists()

    configure_logging(config_file)

    assert log_dir.is_dir()


def test_configure_logging_invalid_schema_raises_configuration_error(tmp_path: Path) -> None:
    """A structurally invalid dictConfig schema should raise `ConfigurationError`."""
    config_file = tmp_path / "logging.yaml"
    config_file.write_text(
        "version: 1\nhandlers:\n  console:\n    class: not.a.real.Class\n", encoding="utf-8"
    )

    with pytest.raises(ConfigurationError):
        configure_logging(config_file)


def test_configure_logging_applies_level_override(tmp_path: Path) -> None:
    """`level_override` should be applied after the file (or default) configuration."""
    configure_logging(tmp_path / "missing.yaml", level_override="ERROR")

    assert logging.getLogger("vaos").level == logging.ERROR


def test_configure_logging_invalid_level_override_raises_configuration_error(
    tmp_path: Path,
) -> None:
    """An unrecognized `level_override` name should raise `ConfigurationError`.

    This must not leak the underlying `ValueError` from `Logger.setLevel`.
    """
    with pytest.raises(ConfigurationError):
        configure_logging(tmp_path / "missing.yaml", level_override="NOT_A_REAL_LEVEL")


def test_configure_logging_does_not_silently_disable_other_loggers(tmp_path: Path) -> None:
    """A schema that omits `disable_existing_loggers` must not disable other loggers.

    The stdlib's own `dictConfig` default for this key is True, which
    silently disables every logger created before `configure_logging`
    runs -- a well-known footgun `configure_logging` must guard against.
    """
    other_logger = logging.getLogger("some_other_module_under_test")
    other_logger.disabled = False
    try:
        config_file = tmp_path / "logging.yaml"
        config_file.write_text(
            "version: 1\n"
            "handlers:\n"
            "  console:\n"
            "    class: logging.StreamHandler\n"
            "loggers:\n"
            "  vaos:\n"
            "    handlers: [console]\n",
            encoding="utf-8",
        )

        configure_logging(config_file)

        assert other_logger.disabled is False
    finally:
        logging.getLogger().manager.loggerDict.pop("some_other_module_under_test", None)
