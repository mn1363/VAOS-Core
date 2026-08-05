"""Generic, dependency-light helpers shared across VAOS layers.

Every function here is a pure, general-purpose utility with no awareness
of domain, application, or infrastructure concerns -- if a helper needs to
know about a specific layer's data, it does not belong in `core`.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from .constants import ENCODING_UTF8
from .exceptions import ConfigurationError, NotFoundError


def read_yaml_file(path: Path, *, required: bool = True) -> dict[str, Any]:
    """Read and parse a YAML file into a plain dictionary.

    Args:
        path: Path of the YAML file to read.
        required: If True, raise `NotFoundError` when `path` does not
            exist. If False, a missing file yields an empty dictionary.

    Returns:
        The parsed YAML content as a dictionary. An empty dictionary is
        returned if the file is missing and `required` is False, or if
        the file exists but is empty.

    Raises:
        NotFoundError: If `required` is True and `path` does not exist.
        ConfigurationError: If `path` exists but cannot be read (e.g. it is
            a directory, or is not readable, or is not valid UTF-8), is
            not valid YAML, or its top-level structure is not a mapping.
    """
    if not path.exists():
        if required:
            raise NotFoundError(f"required file not found: '{path}'", details={"path": str(path)})
        return {}

    try:
        content = path.read_text(encoding=ENCODING_UTF8)
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigurationError(
            f"could not read '{path}': {exc}", details={"path": str(path)}
        ) from exc

    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ConfigurationError(
            f"invalid YAML in '{path}': {exc}", details={"path": str(path)}
        ) from exc

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigurationError(
            f"expected a mapping at the top level of '{path}', got {type(data).__name__}",
            details={"path": str(path), "actual_type": type(data).__name__},
        )
    return data


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively merge `override` into `base`, without mutating either.

    Nested dictionaries are merged key by key; any other value in
    `override` replaces the corresponding value in `base` outright.

    Args:
        base: The starting mapping.
        override: The mapping whose values take precedence.

    Returns:
        A new dictionary containing the merged result.
    """
    result: dict[str, Any] = dict(base)
    for key, value in override.items():
        existing = result.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            result[key] = deep_merge(existing, value)
        else:
            result[key] = value
    return result


def ensure_directory(path: Path) -> Path:
    """Ensure `path` exists as a directory, creating parents as needed.

    Args:
        path: Directory path to create if it does not already exist.

    Returns:
        The same path, for convenient chaining.
    """
    path.mkdir(parents=True, exist_ok=True)
    return path
