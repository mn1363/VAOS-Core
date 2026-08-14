"""Dependency-boundary and circular-dependency tests for `src.foundation`.

These tests statically inspect every `src.foundation` module's import *statements* (via `ast`,
without executing them -- see `test_imports.py` for execution-based import verification) to
verify Phase 9's dependency rules hold: no forbidden layer is imported, every `src.*` import
resolves to one of Foundation's explicitly allowed layers, and the five subpackages' intra-
package imports form a DAG rather than a cycle.
"""

import ast
from pathlib import Path

import pytest

_FOUNDATION_ROOT = Path(__file__).resolve().parents[3] / "src" / "foundation"

_FORBIDDEN_PREFIXES = (
    "src.collectors",
    "src.parsers",
    "src.repository",
    "src.storage",
    "src.memory",
    "src.vector",
    "src.pipeline",
    "src.plugins",
    "src.api",
    "src.cli",
    "src.application",
    "src.bootstrap",
)

_ALLOWED_PREFIXES = (
    "src.core",
    "src.domain",
    "src.extractors",
    "src.analyzers",
    "src.graph",
    "src.foundation",
)

_SUBPACKAGES = ("comparer", "ranking", "selector", "merger", "exporter")


def _foundation_source_files() -> list[Path]:
    """Every `.py` file under `src/foundation`, sorted for deterministic test IDs."""
    return sorted(_FOUNDATION_ROOT.rglob("*.py"))


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
    """Render `path` relative to `_FOUNDATION_ROOT`, for readable parametrized test ids."""
    return str(path.relative_to(_FOUNDATION_ROOT))


@pytest.mark.parametrize("path", _foundation_source_files(), ids=_relative_id)
def test_foundation_module_imports_no_forbidden_layer(path: Path) -> None:
    """No `src.foundation` module may import from a layer Phase 9 forbids."""
    for module_name in _imported_module_names(path):
        for forbidden in _FORBIDDEN_PREFIXES:
            is_forbidden = module_name == forbidden or module_name.startswith(f"{forbidden}.")
            assert not is_forbidden, f"{path} imports forbidden module '{module_name}'"


@pytest.mark.parametrize("path", _foundation_source_files(), ids=_relative_id)
def test_foundation_module_imports_only_allowed_layers(path: Path) -> None:
    """Every `src.*` import in `src.foundation` must resolve to an explicitly allowed layer."""
    for module_name in _imported_module_names(path):
        if module_name == "src" or module_name.startswith("src."):
            is_allowed = any(
                module_name == allowed or module_name.startswith(f"{allowed}.")
                for allowed in _ALLOWED_PREFIXES
            )
            assert is_allowed, f"{path} imports '{module_name}', not an allowed dependency"


def test_foundation_subpackages_have_no_import_cycle() -> None:
    """The five `foundation` subpackages must form a DAG, not a cycle.

    Built from each subpackage's own `base.py` imports of its sibling subpackages, then
    confirmed acyclic via depth-first traversal.
    """
    edges: dict[str, set[str]] = {name: set() for name in _SUBPACKAGES}
    for name in _SUBPACKAGES:
        for module_name in _imported_module_names(_FOUNDATION_ROOT / name / "base.py"):
            if not module_name.startswith("src.foundation."):
                continue
            sibling = module_name.split(".")[2]
            if sibling in _SUBPACKAGES and sibling != name:
                edges[name].add(sibling)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visited:
            return
        if node in visiting:
            pytest.fail(f"circular dependency detected among foundation subpackages at '{node}'")
        visiting.add(node)
        for neighbor in edges[node]:
            visit(neighbor)
        visiting.discard(node)
        visited.add(node)

    for name in _SUBPACKAGES:
        visit(name)
