"""Unit tests for `src.core.constants`."""

from pathlib import Path

from src.core import constants


def test_app_identity_constants_are_nonempty_strings() -> None:
    """APP_NAME and APP_VERSION should be non-empty strings."""
    assert isinstance(constants.APP_NAME, str) and constants.APP_NAME
    assert isinstance(constants.APP_VERSION, str) and constants.APP_VERSION


def test_env_prefix_is_uppercase_and_ends_with_underscore() -> None:
    """ENV_PREFIX should look like a shell-safe environment variable prefix."""
    assert constants.ENV_PREFIX == constants.ENV_PREFIX.upper()
    assert constants.ENV_PREFIX.endswith("_")


def test_default_config_paths_are_relative_yaml_files() -> None:
    """The default config directory should be relative; filenames should be YAML."""
    assert isinstance(constants.DEFAULT_CONFIG_DIR, Path)
    assert not constants.DEFAULT_CONFIG_DIR.is_absolute()
    assert constants.DEFAULT_CONFIG_FILENAME.endswith(".yaml")
    assert constants.DEFAULT_LOGGING_CONFIG_FILENAME.endswith(".yaml")


def test_allowed_environments_include_development_and_production() -> None:
    """The allowed-environments tuple should cover the standard deployment stages."""
    assert "development" in constants.ALLOWED_ENVIRONMENTS
    assert "production" in constants.ALLOWED_ENVIRONMENTS


def test_default_log_level_is_a_standard_logging_level_name() -> None:
    """DEFAULT_LOG_LEVEL should be a name the stdlib logging module understands."""
    assert constants.DEFAULT_LOG_LEVEL in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def test_encoding_constant_is_utf8() -> None:
    """ENCODING_UTF8 should be the standard UTF-8 codec name used for file I/O."""
    assert constants.ENCODING_UTF8 == "utf-8"
