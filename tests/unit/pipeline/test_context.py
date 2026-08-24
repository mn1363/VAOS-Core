"""Tests for `src.pipeline.context.PipelineContext`."""

import pytest
from src.core.exceptions import NotFoundError, ValidationError
from src.pipeline.context import PipelineContext


def test_get_returns_default_when_key_absent() -> None:
    """`get` returns the given default, not an exception, when `key` is unset."""
    context = PipelineContext()
    assert context.get("missing") is None
    assert context.get("missing", "fallback") == "fallback"


def test_get_returns_stored_value() -> None:
    """`get` returns whatever was previously `set` under the same key."""
    context = PipelineContext()
    context.set("repo", "value")
    assert context.get("repo") == "value"


def test_has_reflects_presence() -> None:
    """`has` is False before `set` and True after."""
    context = PipelineContext()
    assert context.has("repo") is False
    context.set("repo", object())
    assert context.has("repo") is True


def test_require_returns_stored_value() -> None:
    """`require` returns the stored value when present, exactly like `get`."""
    context = PipelineContext()
    context.set("repo", 42)
    assert context.require("repo") == 42


def test_require_raises_not_found_when_key_absent() -> None:
    """`require` raises `NotFoundError`, not `KeyError`, so callers can catch a VAOS-wide type."""
    context = PipelineContext()
    with pytest.raises(NotFoundError) as excinfo:
        context.require("missing")
    assert "missing" in str(excinfo.value)
    assert excinfo.value.details["key"] == "missing"


def test_set_overwrites_existing_value() -> None:
    """A second `set` under the same key replaces the first value, not append/merge it."""
    context = PipelineContext()
    context.set("repo", "first")
    context.set("repo", "second")
    assert context.get("repo") == "second"


@pytest.mark.parametrize("blank_key", ["", "   ", "\t"])
def test_set_rejects_blank_key(blank_key: str) -> None:
    """`set` refuses a blank key rather than silently storing under an unusable one."""
    context = PipelineContext()
    with pytest.raises(ValidationError):
        context.set(blank_key, "value")


def test_to_mapping_returns_independent_copy() -> None:
    """Mutating the dict `to_mapping` returns must not affect the context's own storage."""
    context = PipelineContext()
    context.set("repo", "value")
    snapshot = context.to_mapping()
    snapshot["repo"] = "mutated"
    snapshot["extra"] = "new"
    assert context.get("repo") == "value"
    assert context.has("extra") is False


def test_context_can_be_constructed_with_initial_values() -> None:
    """A context can be seeded directly via `values=`, without going through `set` per key."""
    context = PipelineContext(values={"repo": "seeded"})
    assert context.get("repo") == "seeded"
