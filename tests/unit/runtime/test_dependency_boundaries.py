"""Dependency-boundary tests for `src.runtime`.

These tests statically inspect every `src.runtime` module's import *statements* (via `ast`,
without executing them -- see `test_imports.py` for execution-based import verification) to
verify Phase 19's dependency rules hold: only `core` may be imported, every other layer is
forbidden, and no layer anywhere in `src/` imports `src.runtime` back. Mirrors
`tests/unit/plugins/test_dependency_boundaries.py`'s own structure, with one difference: unlike
`plugins -> pipeline`, no second allowed layer exists here -- `runtime`'s accepted Phase 19
responsibility (orchestrating an already constructor-injected `Sequence[SupportsLifecycle]`) is
fully satisfiable importing `core` alone, so `bootstrap` and `pipeline` are both forbidden below
despite each being named alongside `runtime` in prior phases' own documentation -- see
`docs/phase19_summary.md` for why that documentation-only pairing was not treated as evidence of
an import dependency.

`test_no_layer_imports_runtime_yet` grants no exemption to any layer, exactly like
`tests/unit/plugins/test_dependency_boundaries.py::test_no_layer_imports_plugins_yet`: this phase
does not wire itself into `bootstrap`, `cli`, or `api`, so no outer consumer is authorized yet.
"""

import ast
from pathlib import Path

import pytest

_SRC_ROOT = Path(__file__).resolve().parents[3] / "src"
_RUNTIME_ROOT = _SRC_ROOT / "runtime"

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
    "src.pipeline",
    "src.application",
    "src.bootstrap",
    "src.cli",
    "src.api",
    "src.plugins",
)

_ALLOWED_PREFIXES = ("src.core", "src.runtime")


def _runtime_source_files() -> list[Path]:
    """Every `.py` file under `src/runtime`, sorted for deterministic test IDs."""
    return sorted(_RUNTIME_ROOT.rglob("*.py"))


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
    """Render `path` relative to `_RUNTIME_ROOT`, for readable parametrized test ids."""
    return str(path.relative_to(_RUNTIME_ROOT))


@pytest.mark.parametrize("path", _runtime_source_files(), ids=_relative_id)
def test_runtime_module_imports_no_forbidden_layer(path: Path) -> None:
    """No `src.runtime` module may import from a layer Phase 19 forbids."""
    for module_name in _imported_module_names(path):
        for forbidden in _FORBIDDEN_PREFIXES:
            is_forbidden = module_name == forbidden or module_name.startswith(f"{forbidden}.")
            assert not is_forbidden, f"{path} imports forbidden module '{module_name}'"


@pytest.mark.parametrize("path", _runtime_source_files(), ids=_relative_id)
def test_runtime_module_imports_only_allowed_layers(path: Path) -> None:
    """Every `src.*` import in `src.runtime` must resolve to an explicitly allowed layer."""
    for module_name in _imported_module_names(path):
        if module_name == "src" or module_name.startswith("src."):
            is_allowed = any(
                module_name == allowed or module_name.startswith(f"{allowed}.")
                for allowed in _ALLOWED_PREFIXES
            )
            assert is_allowed, f"{path} imports '{module_name}', not an allowed dependency"


def test_no_layer_imports_runtime_yet() -> None:
    """No layer anywhere in `src/` may import `src.runtime` -- this phase does not wire itself
    into `bootstrap`, `cli`, or `api`, so no exemption is authorized here."""
    for path in sorted(_SRC_ROOT.rglob("*.py")):
        if _RUNTIME_ROOT in path.parents or path.parent == _RUNTIME_ROOT:
            continue
        for module_name in _imported_module_names(path):
            assert not (
                module_name == "src.runtime" or module_name.startswith("src.runtime.")
            ), f"{path} imports 'src.runtime' -- no exemption is authorized for Phase 19"
