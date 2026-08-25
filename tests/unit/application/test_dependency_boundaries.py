"""Dependency-boundary tests for `src.application`.

These tests statically inspect every `src.application` module's import *statements* (via `ast`,
without executing them -- see `test_imports.py` for execution-based import verification) to
verify Phase 14's dependency rules hold: no forbidden layer is imported, every `src.*` import
resolves to one of Application's explicitly allowed layers, and no other layer imports
`src.application` back. Mirrors `tests/unit/pipeline/test_dependency_boundaries.py`'s own
structure exactly.

Unlike Pipeline's own boundary test, `src.repository` is *included* in `_ALLOWED_PREFIXES`: this
phase's own instruction is that "Phase 14/application may depend on the existing frozen layers
from Phase 1-13, where required by the actual architecture," with no layer excluded the way
Pipeline's own brief deliberately excluded `repository`. `_ALLOWED_PREFIXES` below is therefore
every one of the thirteen Phase 1-13 packages -- `core`, `domain`, `repository`, `collectors`,
`parsers`, `extractors`, `analyzers`, `graph`, `foundation`, `storage`, `vector`, `memory`, and
`pipeline` -- rather than the narrower nine-layer list Pipeline's own test uses.
"""

import ast
from pathlib import Path

import pytest

_SRC_ROOT = Path(__file__).resolve().parents[3] / "src"
_APPLICATION_ROOT = _SRC_ROOT / "application"

_FORBIDDEN_PREFIXES = (
    "src.plugins",
    "src.api",
    "src.cli",
    "src.bootstrap",
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
    """Render `path` relative to `_APPLICATION_ROOT`, for readable parametrized test ids."""
    return str(path.relative_to(_APPLICATION_ROOT))


@pytest.mark.parametrize("path", _source_files(_APPLICATION_ROOT), ids=_relative_id)
def test_application_module_imports_no_forbidden_layer(path: Path) -> None:
    """No `src.application` module may import from a layer Phase 14 forbids."""
    for module_name in _imported_module_names(path):
        for forbidden in _FORBIDDEN_PREFIXES:
            is_forbidden = module_name == forbidden or module_name.startswith(f"{forbidden}.")
            assert not is_forbidden, f"{path} imports forbidden module '{module_name}'"


@pytest.mark.parametrize("path", _source_files(_APPLICATION_ROOT), ids=_relative_id)
def test_application_module_imports_only_allowed_layers(path: Path) -> None:
    """Every `src.*` import in `src.application` must resolve to an explicitly allowed layer."""
    for module_name in _imported_module_names(path):
        if module_name == "src" or module_name.startswith("src."):
            is_allowed = any(
                module_name == allowed or module_name.startswith(f"{allowed}.")
                for allowed in _ALLOWED_PREFIXES
            )
            assert is_allowed, f"{path} imports '{module_name}', not an allowed dependency"


def test_no_other_layer_imports_application() -> None:
    """No module outside `src/application` may import `src.application` -- the dependency
    direction must remain one-way, exactly as this phase's own instruction requires ("No Phase
    1-13 layer may import src.application"). Scans the whole `src/` tree rather than relying only
    on each already-frozen phase's own dependency-boundary test."""
    for path in _source_files(_SRC_ROOT):
        if _APPLICATION_ROOT in path.parents or path.parent == _APPLICATION_ROOT:
            continue
        for module_name in _imported_module_names(path):
            is_application = module_name == "src.application" or module_name.startswith(
                "src.application."
            )
            assert not is_application, (
                f"{path} imports 'src.application' -- no Phase 1-13 layer may depend on "
                "application"
            )
