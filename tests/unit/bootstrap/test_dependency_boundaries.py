"""Dependency-boundary tests for `src.bootstrap`.

These tests statically inspect every `src.bootstrap` module's import *statements* (via `ast`,
without executing them -- see `test_imports.py` for execution-based import verification) to
verify Phase 15's dependency rules hold: no forbidden layer is imported, every `src.*` import
resolves to one of Bootstrap's explicitly allowed layers, and no other layer imports
`src.bootstrap` back. Mirrors `tests/unit/application/test_dependency_boundaries.py`'s own
structure exactly.

`_ALLOWED_PREFIXES` is every one of the fourteen Phase 1-14 packages -- the same set
`src.application`'s own dependency-boundary test grants Application, plus `src.application`
itself, since `bootstrap` is the one layer that calls into it. `_FORBIDDEN_PREFIXES` is the same
three not-yet-built packages every other phase's own dependency-boundary test already forbids:
`src.api`, `src.cli`, `src.plugins`. `src.bootstrap` does not forbid itself, and no evidence
anywhere connects `src.runtime`, `src.infrastructure`, or `src.scorers` to this layer as an
actual dependency -- see the Phase 15 contract discovery this phase was built from.
"""

import ast
from pathlib import Path

import pytest

_SRC_ROOT = Path(__file__).resolve().parents[3] / "src"
_BOOTSTRAP_ROOT = _SRC_ROOT / "bootstrap"

_FORBIDDEN_PREFIXES = (
    "src.api",
    "src.cli",
    "src.plugins",
)

_ALLOWED_PREFIXES = (
    "src.core",
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
)


def _source_files(root: Path) -> list[Path]:
    """Every `.py` file under `root`, sorted for deterministic test IDs."""
    return sorted(root.rglob("*.py"))


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
    """Render `path` relative to `_BOOTSTRAP_ROOT`, for readable parametrized test ids."""
    return str(path.relative_to(_BOOTSTRAP_ROOT))


@pytest.mark.parametrize("path", _source_files(_BOOTSTRAP_ROOT), ids=_relative_id)
def test_bootstrap_module_imports_no_forbidden_layer(path: Path) -> None:
    """No `src.bootstrap` module may import from a layer Phase 15 forbids."""
    for module_name in _imported_module_names(path):
        for forbidden in _FORBIDDEN_PREFIXES:
            is_forbidden = module_name == forbidden or module_name.startswith(f"{forbidden}.")
            assert not is_forbidden, f"{path} imports forbidden module '{module_name}'"


@pytest.mark.parametrize("path", _source_files(_BOOTSTRAP_ROOT), ids=_relative_id)
def test_bootstrap_module_imports_only_allowed_layers(path: Path) -> None:
    """Every `src.*` import in `src.bootstrap` must resolve to an explicitly allowed layer."""
    for module_name in _imported_module_names(path):
        if module_name == "src" or module_name.startswith("src."):
            is_allowed = any(
                module_name == allowed or module_name.startswith(f"{allowed}.")
                for allowed in _ALLOWED_PREFIXES
            )
            assert is_allowed, f"{path} imports '{module_name}', not an allowed dependency"


def test_no_other_layer_imports_bootstrap() -> None:
    """No module outside `src/bootstrap` may import `src.bootstrap` -- the dependency direction
    must remain one-way, exactly as this phase's own instruction requires ("No Phase 1-14
    package may import src.bootstrap"). Scans the whole `src/` tree rather than relying only on
    each already-frozen phase's own dependency-boundary test."""
    for path in _source_files(_SRC_ROOT):
        if _BOOTSTRAP_ROOT in path.parents or path.parent == _BOOTSTRAP_ROOT:
            continue
        for module_name in _imported_module_names(path):
            is_bootstrap = module_name == "src.bootstrap" or module_name.startswith(
                "src.bootstrap."
            )
            assert not is_bootstrap, (
                f"{path} imports 'src.bootstrap' -- no Phase 1-14 layer may depend on bootstrap"
            )
