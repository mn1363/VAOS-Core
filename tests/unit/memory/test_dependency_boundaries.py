"""Dependency-boundary tests for `src.memory`.

These tests statically inspect every `src.memory` module's import *statements* (via `ast`,
without executing them -- see `test_imports.py` for execution-based import verification) to
verify Phase 12's dependency rules hold: no forbidden layer is imported (in particular
`src.storage` and `src.repository`, so `memory` never depends on a layer that could one day
depend on it), and every `src.*` import resolves to one of Memory's explicitly allowed layers.
Mirrors `tests/unit/vector/test_dependency_boundaries.py`'s own structure exactly.
"""

import ast
from pathlib import Path

import pytest

_MEMORY_ROOT = Path(__file__).resolve().parents[3] / "src" / "memory"

_FORBIDDEN_PREFIXES = (
    "src.storage",
    "src.repository",
    "src.collectors",
    "src.parsers",
    "src.extractors",
    "src.analyzers",
    "src.graph",
    "src.foundation",
    "src.pipeline",
    "src.plugins",
    "src.api",
    "src.cli",
    "src.application",
    "src.bootstrap",
)

_ALLOWED_PREFIXES = ("src.core", "src.domain", "src.vector", "src.memory")


def _memory_source_files() -> list[Path]:
    """Every `.py` file under `src/memory`, sorted for deterministic test IDs."""
    return sorted(_MEMORY_ROOT.rglob("*.py"))


def _imported_module_names(path: Path) -> list[str]:
    """Every module a single file imports, via `import x` or an absolute `from x import y`."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            names.append(node.module)
    return names


def _relative_id(path: Path) -> str:
    """Render `path` relative to `_MEMORY_ROOT`, for readable parametrized test ids."""
    return str(path.relative_to(_MEMORY_ROOT))


@pytest.mark.parametrize("path", _memory_source_files(), ids=_relative_id)
def test_memory_module_imports_no_forbidden_layer(path: Path) -> None:
    """No `src.memory` module may import from a layer Phase 12 forbids."""
    for module_name in _imported_module_names(path):
        for forbidden in _FORBIDDEN_PREFIXES:
            is_forbidden = module_name == forbidden or module_name.startswith(f"{forbidden}.")
            assert not is_forbidden, f"{path} imports forbidden module '{module_name}'"


@pytest.mark.parametrize("path", _memory_source_files(), ids=_relative_id)
def test_memory_module_imports_only_allowed_layers(path: Path) -> None:
    """Every `src.*` import in `src.memory` must resolve to an explicitly allowed layer."""
    for module_name in _imported_module_names(path):
        if module_name == "src" or module_name.startswith("src."):
            is_allowed = any(
                module_name == allowed or module_name.startswith(f"{allowed}.")
                for allowed in _ALLOWED_PREFIXES
            )
            assert is_allowed, f"{path} imports '{module_name}', not an allowed dependency"


def test_memory_does_not_import_storage_anywhere() -> None:
    """Explicit, single-purpose guard for one relationship Phase 12 must never invert: `memory`
    must never import `storage`, even indirectly through a helper import list."""
    for path in _memory_source_files():
        for module_name in _imported_module_names(path):
            assert not module_name.startswith("src.storage"), (
                f"{path} imports 'src.storage' -- Memory must depend on nothing from Storage; "
                "a future storage driver depends on Memory, never the reverse"
            )


def test_memory_does_not_import_repository_anywhere() -> None:
    """Explicit, single-purpose guard for the other relationship Phase 12 must never invert:
    `memory` must never import `repository`, even indirectly through a helper import list."""
    for path in _memory_source_files():
        for module_name in _imported_module_names(path):
            assert not module_name.startswith("src.repository"), (
                f"{path} imports 'src.repository' -- Memory has no dependency on the git-backed "
                "workspace/repository-client Port"
            )
