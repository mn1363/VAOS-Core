"""Unit tests for `src.core.utils`."""

from pathlib import Path

import pytest
from src.core.exceptions import ConfigurationError, NotFoundError
from src.core.utils import deep_merge, ensure_directory, read_yaml_file


def test_read_yaml_file_parses_existing_file(tmp_path: Path) -> None:
    """A valid YAML file should be parsed into a matching dictionary."""
    config_file = tmp_path / "sample.yaml"
    config_file.write_text("a: 1\nb:\n  c: 2\n", encoding="utf-8")

    result = read_yaml_file(config_file)

    assert result == {"a": 1, "b": {"c": 2}}


def test_read_yaml_file_missing_and_required_raises(tmp_path: Path) -> None:
    """A missing, required file should raise `NotFoundError`."""
    missing = tmp_path / "missing.yaml"

    with pytest.raises(NotFoundError):
        read_yaml_file(missing, required=True)


def test_read_yaml_file_missing_and_optional_returns_empty(tmp_path: Path) -> None:
    """A missing, optional file should return an empty dictionary."""
    missing = tmp_path / "missing.yaml"

    assert read_yaml_file(missing, required=False) == {}


def test_read_yaml_file_empty_file_returns_empty(tmp_path: Path) -> None:
    """An existing but empty file should return an empty dictionary."""
    empty = tmp_path / "empty.yaml"
    empty.write_text("", encoding="utf-8")

    assert read_yaml_file(empty) == {}


def test_read_yaml_file_malformed_raises_configuration_error(tmp_path: Path) -> None:
    """Malformed YAML content should raise `ConfigurationError`."""
    bad = tmp_path / "bad.yaml"
    bad.write_text("a: [1, 2\n", encoding="utf-8")

    with pytest.raises(ConfigurationError):
        read_yaml_file(bad)


def test_read_yaml_file_non_mapping_top_level_raises(tmp_path: Path) -> None:
    """A YAML file whose top level is not a mapping should raise `ConfigurationError`."""
    listy = tmp_path / "list.yaml"
    listy.write_text("- 1\n- 2\n", encoding="utf-8")

    with pytest.raises(ConfigurationError):
        read_yaml_file(listy)


def test_read_yaml_file_directory_in_place_of_file_raises_configuration_error(
    tmp_path: Path,
) -> None:
    """A path that is a directory, not a file, should raise `ConfigurationError`.

    This must not leak the underlying `IsADirectoryError`.
    """
    directory = tmp_path / "config.yaml"
    directory.mkdir()

    with pytest.raises(ConfigurationError):
        read_yaml_file(directory)


def test_read_yaml_file_invalid_encoding_raises_configuration_error(tmp_path: Path) -> None:
    """A file that is not valid UTF-8 should raise `ConfigurationError`.

    This must not leak the underlying `UnicodeDecodeError`.
    """
    bad_encoding = tmp_path / "bad_encoding.yaml"
    bad_encoding.write_bytes(b"\xff\xfe key: value")

    with pytest.raises(ConfigurationError):
        read_yaml_file(bad_encoding)


def test_deep_merge_combines_nested_dictionaries() -> None:
    """Nested mappings should be merged key by key, not replaced wholesale."""
    base = {"a": 1, "nested": {"x": 1, "y": 2}}
    override = {"nested": {"y": 20, "z": 3}}

    result = deep_merge(base, override)

    assert result == {"a": 1, "nested": {"x": 1, "y": 20, "z": 3}}


def test_deep_merge_does_not_mutate_inputs() -> None:
    """`deep_merge` should return a new dictionary, leaving both inputs untouched."""
    base = {"nested": {"x": 1}}
    override = {"nested": {"y": 2}}

    deep_merge(base, override)

    assert base == {"nested": {"x": 1}}
    assert override == {"nested": {"y": 2}}


def test_deep_merge_non_mapping_override_replaces_value() -> None:
    """A non-mapping override value should replace the base value outright."""
    base = {"a": {"x": 1}}
    override = {"a": "replaced"}

    result = deep_merge(base, override)

    assert result == {"a": "replaced"}


def test_ensure_directory_creates_nested_path(tmp_path: Path) -> None:
    """`ensure_directory` should create missing parent directories."""
    target = tmp_path / "a" / "b" / "c"

    result = ensure_directory(target)

    assert result == target
    assert target.is_dir()


def test_ensure_directory_is_idempotent(tmp_path: Path) -> None:
    """Calling `ensure_directory` on an already-existing directory should not raise."""
    target = tmp_path / "already-there"
    target.mkdir()

    ensure_directory(target)

    assert target.is_dir()
