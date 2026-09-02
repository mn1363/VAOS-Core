"""Dependency-boundary tests for `src.plugins`.

These tests statically inspect every `src.plugins` module's import *statements* (via `ast`,
without executing them -- see `test_imports.py` for execution-based import verification) to
verify Phase 18's dependency rules hold: only `core` and `pipeline` may be imported, every other
layer is forbidden, and no layer anywhere in `src/` imports `src.plugins` back. Mirrors
`tests/unit/vector/test_dependency_boundaries.py`'s own structure.

Unlike `tests/unit/pipeline/test_dependency_boundaries.py::test_no_other_layer_imports_pipeline`,
`test_no_layer_imports_plugins_yet` below grants no exemption to any layer: this phase does not
wire itself into `bootstrap`, `cli`, or `api`, so no outer consumer is authorized yet. A future
phase that legitimately needs one adds it explicitly, the same way `application`/`bootstrap`/
`cli` each earned their own exemption from `pipeline`'s equivalent guard.
"""

import ast
from pathlib import Path

import pytest

_SRC_ROOT = Path(__file__).resolve().parents[3] / "src"
_PLUGINS_ROOT = _SRC_ROOT / "plugins"

_FORBIDDEN_PREFIXES = (
    "src.domain",
    "src.repository",
    "src.collectors",
    "src.parsers",
    "src.extractors",
    "src.analyzers",
    "src.graph",
    "src.foundation",
    "src.storage",
    "src.vector",
    "src.memory",
    "src.application",
    "src.bootstrap",
    "src.cli",
    "src.api",
)

_ALLOWED_PREFIXES = ("src.core", "src.pipeline", "src.plugins")


def _plugins_source_files() -> list[Path]:
    """Every `.py` file under `src/plugins`, sorted for deterministic test IDs."""
    return sorted(_PLUGINS_ROOT.rglob("*.py"))


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
    """Render `path` relative to `_PLUGINS_ROOT`, for readable parametrized test ids."""
    return str(path.relative_to(_PLUGINS_ROOT))


@pytest.mark.parametrize("path", _plugins_source_files(), ids=_relative_id)
def test_plugins_module_imports_no_forbidden_layer(path: Path) -> None:
    """No `src.plugins` module may import from a layer Phase 18 forbids."""
    for module_name in _imported_module_names(path):
        for forbidden in _FORBIDDEN_PREFIXES:
            is_forbidden = module_name == forbidden or module_name.startswith(f"{forbidden}.")
            assert not is_forbidden, f"{path} imports forbidden module '{module_name}'"


@pytest.mark.parametrize("path", _plugins_source_files(), ids=_relative_id)
def test_plugins_module_imports_only_allowed_layers(path: Path) -> None:
    """Every `src.*` import in `src.plugins` must resolve to an explicitly allowed layer."""
    for module_name in _imported_module_names(path):
        if module_name == "src" or module_name.startswith("src."):
            is_allowed = any(
                module_name == allowed or module_name.startswith(f"{allowed}.")
                for allowed in _ALLOWED_PREFIXES
            )
            assert is_allowed, f"{path} imports '{module_name}', not an allowed dependency"


def test_no_layer_imports_plugins_yet() -> None:
    """No layer anywhere in `src/` may import `src.plugins` -- this phase does not wire itself
    into `bootstrap`, `cli`, or `api`, so unlike `pipeline`'s own reverse-import guard, no
    exemption is authorized here."""
    for path in sorted(_SRC_ROOT.rglob("*.py")):
        if _PLUGINS_ROOT in path.parents or path.parent == _PLUGINS_ROOT:
            continue
        for module_name in _imported_module_names(path):
            assert not (
                module_name == "src.plugins" or module_name.startswith("src.plugins.")
            ), f"{path} imports 'src.plugins' -- no exemption is authorized for Phase 18"
