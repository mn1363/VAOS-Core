"""Dependency-boundary tests for `src.health`.

These tests statically inspect every `src.health` module's import *statements* (via `ast`,
without executing them -- see `test_imports.py` for execution-based import verification) to
verify Phase 20's dependency rules hold: only `core` may be imported, every other layer is
forbidden, and no layer anywhere in `src/` imports `src.health` back. Mirrors
`tests/unit/runtime/test_dependency_boundaries.py`'s own structure: no second allowed layer
exists here either -- `health`'s accepted Phase 20 responsibility (orchestrating an already
constructor-injected `Sequence[SupportsHealthCheck]`) is fully satisfiable importing `core`
alone, so `runtime`, `bootstrap`, and `pipeline` are all forbidden below despite `health` and
`runtime` sharing the same "orchestrates a `Sequence` of a `core.protocols` shape" family
resemblance -- see `docs/phase20_summary.md` for why that resemblance was not treated as
evidence of an import dependency.

`test_no_layer_imports_health_yet` grants no exemption to any layer, exactly like
`tests/unit/runtime/test_dependency_boundaries.py::test_no_layer_imports_runtime_yet`: this
phase does not wire itself into `bootstrap`, `cli`, or `api`, so no outer consumer is authorized
yet.
"""

import ast
from pathlib import Path

import pytest

_SRC_ROOT = Path(__file__).resolve().parents[3] / "src"
_HEALTH_ROOT = _SRC_ROOT / "health"

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
    "src.runtime",
)

_ALLOWED_PREFIXES = ("src.core", "src.health")


def _health_source_files() -> list[Path]:
    """Every `.py` file under `src/health`, sorted for deterministic test IDs."""
    return sorted(_HEALTH_ROOT.rglob("*.py"))


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
    """Render `path` relative to `_HEALTH_ROOT`, for readable parametrized test ids."""
    return str(path.relative_to(_HEALTH_ROOT))


@pytest.mark.parametrize("path", _health_source_files(), ids=_relative_id)
def test_health_module_imports_no_forbidden_layer(path: Path) -> None:
    """No `src.health` module may import from a layer Phase 20 forbids."""
    for module_name in _imported_module_names(path):
        for forbidden in _FORBIDDEN_PREFIXES:
            is_forbidden = module_name == forbidden or module_name.startswith(f"{forbidden}.")
            assert not is_forbidden, f"{path} imports forbidden module '{module_name}'"


@pytest.mark.parametrize("path", _health_source_files(), ids=_relative_id)
def test_health_module_imports_only_allowed_layers(path: Path) -> None:
    """Every `src.*` import in `src.health` must resolve to an explicitly allowed layer."""
    for module_name in _imported_module_names(path):
        if module_name == "src" or module_name.startswith("src."):
            is_allowed = any(
                module_name == allowed or module_name.startswith(f"{allowed}.")
                for allowed in _ALLOWED_PREFIXES
            )
            assert is_allowed, f"{path} imports '{module_name}', not an allowed dependency"


def test_no_layer_imports_health_yet() -> None:
    """No layer anywhere in `src/` may import `src.health` -- this phase does not wire itself
    into `bootstrap`, `cli`, or `api`, so no exemption is authorized here."""
    for path in sorted(_SRC_ROOT.rglob("*.py")):
        if _HEALTH_ROOT in path.parents or path.parent == _HEALTH_ROOT:
            continue
        for module_name in _imported_module_names(path):
            assert not (
                module_name == "src.health" or module_name.startswith("src.health.")
            ), f"{path} imports 'src.health' -- no exemption is authorized for Phase 20"
