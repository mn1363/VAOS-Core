"""Unit tests for `src.core.config`."""

import dataclasses
from pathlib import Path

import pytest
from src.core.config import AppConfig, load_config
from src.core.constants import ALLOWED_ENVIRONMENTS, APP_NAME, APP_VERSION
from src.core.exceptions import ValidationError


def test_appconfig_is_directly_constructible_and_immutable() -> None:
    """`AppConfig` should be directly constructible with sensible defaults, and frozen."""
    config = AppConfig()

    assert isinstance(config, AppConfig)
    assert config.app_name == APP_NAME
    assert config.app_version == APP_VERSION
    assert config.environment == "development"
    assert config.debug is False
    assert config.config_path is None
    assert config.raw == {}

    with pytest.raises(dataclasses.FrozenInstanceError):
        config.debug = True  # type: ignore[misc]


def test_load_config_without_a_file_uses_defaults(tmp_path: Path) -> None:
    """Loading from a path that does not exist should fall back to defaults."""
    config = load_config(tmp_path / "missing.yaml", env={})

    assert config.environment == "development"
    assert config.debug is False
    assert config.config_path is None


def test_load_config_reads_values_from_yaml(tmp_path: Path) -> None:
    """Values present in the YAML file should populate the resulting config."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "app_name: my-app\napp_version: '9.9.9'\nenvironment: staging\ndebug: true\n",
        encoding="utf-8",
    )

    config = load_config(config_file, env={})

    assert config.app_name == "my-app"
    assert config.app_version == "9.9.9"
    assert config.environment == "staging"
    assert config.debug is True
    assert config.config_path == config_file


def test_environment_variable_overrides_yaml_value(tmp_path: Path) -> None:
    """A `VAOS_*` environment variable should take precedence over the YAML file."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("environment: development\n", encoding="utf-8")

    config = load_config(config_file, env={"VAOS_ENVIRONMENT": "production"})

    assert config.environment == "production"


def test_debug_flag_is_coerced_from_string_env_var(tmp_path: Path) -> None:
    """A string 'true'-like `VAOS_DEBUG` value should coerce to a real boolean."""
    config = load_config(tmp_path / "missing.yaml", env={"VAOS_DEBUG": "yes"})

    assert config.debug is True


def test_invalid_environment_raises_validation_error(tmp_path: Path) -> None:
    """An `environment` value outside the allowed set should raise `ValidationError`."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("environment: not-a-real-environment\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        load_config(config_file, env={})


def test_explicit_null_yaml_values_fall_back_to_defaults(tmp_path: Path) -> None:
    """An explicit YAML `null` (not just a missing key) should fall back to the default.

    `app_name:` with no value parses to `None`; this must not become the
    literal string `"None"`.
    """
    config_file = tmp_path / "config.yaml"
    config_file.write_text("app_name:\napp_version:\nenvironment:\n", encoding="utf-8")

    config = load_config(config_file, env={})

    assert config.app_name == APP_NAME
    assert config.app_version == APP_VERSION
    assert config.environment == "development"


def test_allowed_environments_are_all_accepted(tmp_path: Path) -> None:
    """Every value in ALLOWED_ENVIRONMENTS should be accepted without error."""
    for environment in ALLOWED_ENVIRONMENTS:
        config_file = tmp_path / "config.yaml"
        config_file.write_text(f"environment: {environment}\n", encoding="utf-8")

        config = load_config(config_file, env={})

        assert config.environment == environment


def test_raw_and_get_expose_the_full_merged_configuration(tmp_path: Path) -> None:
    """`get()` should expose sections owned by layers other than `core`."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "environment: staging\nstorage:\n  sqlite:\n    path: data.db\n", encoding="utf-8"
    )

    config = load_config(config_file, env={})

    assert config.get("storage.sqlite.path") == "data.db"
    assert config.get("storage.sqlite.missing", "fallback") == "fallback"
    assert config.get("nonexistent.deeply.nested", "fallback") == "fallback"


def test_load_config_reads_the_shipped_default_file() -> None:
    """With no path argument, `load_config` should load the project's real config.yaml."""
    config = load_config(env={})

    assert config.app_name == "vaos"
    assert config.environment in ALLOWED_ENVIRONMENTS
    assert config.config_path is not None
