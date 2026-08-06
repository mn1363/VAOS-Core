"""Application configuration: typed settings loaded from YAML with
environment-variable overrides.

Configuration is assembled in three layers, each overriding the last:
built-in defaults, the YAML file at `configs/config.yaml`, and matching
`VAOS_*` environment variables. `config` does not import `core.logging`
(and vice versa): each independently reads its own YAML file, which keeps
the two Core modules decoupled and lets config load before logging is
configured, matching the intended bootstrap order.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from .constants import (
    ALLOWED_ENVIRONMENTS,
    APP_NAME,
    APP_VERSION,
    DEFAULT_CONFIG_DIR,
    DEFAULT_CONFIG_FILENAME,
    ENV_PREFIX,
)
from .exceptions import ValidationError
from .utils import deep_merge, read_yaml_file

#: Maps each typed `AppConfig` field to the environment variable that may
#: override it.
_ENV_OVERRIDES: Final[dict[str, str]] = {
    "app_name": f"{ENV_PREFIX}APP_NAME",
    "app_version": f"{ENV_PREFIX}APP_VERSION",
    "environment": f"{ENV_PREFIX}ENVIRONMENT",
    "debug": f"{ENV_PREFIX}DEBUG",
}


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Fully resolved, validated application configuration.

    Attributes:
        app_name: Human-readable application name.
        app_version: Application version string.
        environment: Deployment environment; one of `ALLOWED_ENVIRONMENTS`.
        debug: Whether the application is running in debug mode.
        config_path: Path the configuration was actually loaded from, or
            None if no configuration file was found and built-in defaults
            were used instead.
        raw: The complete, merged configuration mapping (YAML file plus
            environment overrides), for sections owned by layers other
            than `core` (for example a future `storage` section) that the
            typed fields above intentionally do not model.
    """

    app_name: str = APP_NAME
    app_version: str = APP_VERSION
    environment: str = "development"
    debug: bool = False
    config_path: Path | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """Look up a dotted-path value from the raw, merged configuration.

        Args:
            key: Dotted path into the raw configuration, e.g.
                `"storage.sqlite.path"`.
            default: Value returned if any segment of `key` is missing.

        Returns:
            The resolved value, or `default` if `key` cannot be fully
            resolved.
        """
        node: Any = self.raw
        for part in key.split("."):
            if not isinstance(node, Mapping) or part not in node:
                return default
            node = node[part]
        return node


def _apply_env_overrides(data: Mapping[str, Any], env: Mapping[str, str]) -> dict[str, Any]:
    """Build an overrides mapping from `env` and merge it onto `data`.

    Args:
        data: The configuration mapping loaded from YAML.
        env: The environment mapping to read `VAOS_*` overrides from.

    Returns:
        A new mapping with any present environment overrides applied.
    """
    overrides: dict[str, Any] = {
        field_name: env[env_var] for field_name, env_var in _ENV_OVERRIDES.items() if env_var in env
    }
    return deep_merge(data, overrides)


def _get_str(data: Mapping[str, Any], key: str, default: str) -> str:
    """Look up a string field, falling back to `default` if absent or null.

    Using `Mapping.get(key, default)` directly only falls back when `key`
    is absent; a YAML file with an explicit `key:` (which parses to
    `None`) would otherwise become the literal string `"None"`. This
    treats "absent" and "present but null" the same way.

    Args:
        data: The merged configuration mapping.
        key: Top-level key to look up.
        default: Value to use if `key` is absent or explicitly null.

    Returns:
        The resolved string value.
    """
    value = data.get(key)
    return str(value) if value is not None else default


def _coerce_bool(value: Any) -> bool:
    """Coerce a YAML- or environment-sourced value into a real boolean.

    Args:
        value: The raw value, typically a `bool` (from YAML) or a `str`
            (from an environment variable).

    Returns:
        True if `value` represents an affirmative flag, False otherwise.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def load_config(path: Path | None = None, *, env: Mapping[str, str] | None = None) -> AppConfig:
    """Load and validate the application configuration.

    Args:
        path: Path to the YAML configuration file. Defaults to
            `configs/config.yaml`, resolved relative to the current
            working directory. A missing file is not an error; built-in
            defaults apply instead.
        env: Mapping to read `VAOS_*` overrides from. Defaults to
            `os.environ`.

    Returns:
        A fully resolved, validated `AppConfig`.

    Raises:
        ConfigurationError: If the YAML file exists but cannot be parsed.
        ValidationError: If a resolved value fails validation.
    """
    resolved_path = path if path is not None else DEFAULT_CONFIG_DIR / DEFAULT_CONFIG_FILENAME
    source_env = env if env is not None else os.environ

    data = read_yaml_file(resolved_path, required=False)
    merged = _apply_env_overrides(data, source_env)

    environment = _get_str(merged, "environment", "development")
    if environment not in ALLOWED_ENVIRONMENTS:
        raise ValidationError(
            f"'environment' must be one of {ALLOWED_ENVIRONMENTS}, got '{environment}'",
            details={"value": environment, "allowed": ALLOWED_ENVIRONMENTS},
        )

    return AppConfig(
        app_name=_get_str(merged, "app_name", APP_NAME),
        app_version=_get_str(merged, "app_version", APP_VERSION),
        environment=environment,
        debug=_coerce_bool(merged.get("debug", False)),
        config_path=resolved_path if resolved_path.exists() else None,
        raw=merged,
    )
