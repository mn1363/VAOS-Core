"""Dependency-boundary tests for `src.api`.

These tests statically inspect every `src.api` module's import *statements* (via `ast`, without
executing them -- see `test_imports.py` for execution-based import verification) to verify Phase
17's dependency rules hold: no forbidden layer is imported, no `src.*` import appears at all
(Phase 17's confirmed initial scope needs none), and no other layer imports `src.api` back.
Mirrors `tests/unit/cli/test_dependency_boundaries.py`'s own structure, with one deliberate
difference explained below.

**`_ALLOWED_PREFIXES` is empty.** Every prior outer layer's own dependency-boundary test grants a
real, non-empty allowed set, because each one's confirmed scope genuinely needed inner-layer
access (`cli` needs `bootstrap` to run the default flow a process invocation triggers). Phase 17's
confirmed initial scope is exactly one operation, `GET /health`, and `src.api.__init__`'s own
docstring explains why that operation calls nothing in any other layer: reaching the liveness
handler's body at all *is* the liveness signal, so no `bootstrap`, `application`, `pipeline`,
`storage`, `vector`, or `memory` call is needed, and none appears. `_FORBIDDEN_PREFIXES` below is
therefore every one of the sixteen other named VAOS packages plus `src.plugins` -- the same
not-yet-built name every other phase's own dependency-boundary test already forbids -- rather than
a smaller forbidden set alongside a large allowed one. A later phase that adds an operation genuinely
requiring an inner-layer call would widen `_ALLOWED_PREFIXES` then, following the same "widen
only when a specific, evidenced need appears" precedent every earlier phase's own boundary-test
correction already used (see e.g. `tests/unit/bootstrap/test_dependency_boundaries.py`'s own
Phase-16 correction note).
"""

import ast
from pathlib import Path

import pytest

_SRC_ROOT = Path(__file__).resolve().parents[3] / "src"
_API_ROOT = _SRC_ROOT / "api"

_FORBIDDEN_PREFIXES = (
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
    "src.bootstrap",
    "src.cli",
    "src.plugins",
)

#: Phase 17's confirmed initial `GET /health` scope needs no `src.*` import at all; see this
#: module's own docstring.
_ALLOWED_PREFIXES: tuple[str, ...] = ()


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
    """Render `path` relative to `_API_ROOT`, for readable parametrized test ids."""
    return str(path.relative_to(_API_ROOT))


@pytest.mark.parametrize("path", _source_files(_API_ROOT), ids=_relative_id)
def test_api_module_imports_no_forbidden_layer(path: Path) -> None:
    """No `src.api` module may import from a layer Phase 17 forbids."""
    for module_name in _imported_module_names(path):
        for forbidden in _FORBIDDEN_PREFIXES:
            is_forbidden = module_name == forbidden or module_name.startswith(f"{forbidden}.")
            assert not is_forbidden, f"{path} imports forbidden module '{module_name}'"


@pytest.mark.parametrize("path", _source_files(_API_ROOT), ids=_relative_id)
def test_api_module_imports_only_allowed_layers(path: Path) -> None:
    """Every `src.*` import in `src.api` must resolve to an explicitly allowed layer.

    `_ALLOWED_PREFIXES` is empty for Phase 17's confirmed scope, so this asserts no `src.*`
    import appears in `src.api` at all -- see this module's own docstring.
    """
    for module_name in _imported_module_names(path):
        if module_name == "src" or module_name.startswith("src."):
            is_allowed = any(
                module_name == allowed or module_name.startswith(f"{allowed}.")
                for allowed in _ALLOWED_PREFIXES
            )
            assert is_allowed, f"{path} imports '{module_name}', not an allowed dependency"


def test_no_other_layer_imports_api() -> None:
    """No module outside `src/api` may import `src.api` -- the dependency direction must remain
    one-way, exactly as every earlier phase's own instruction required for itself. Scans the
    whole `src/` tree rather than relying only on each already-frozen phase's own
    dependency-boundary test."""
    for path in _source_files(_SRC_ROOT):
        if _API_ROOT in path.parents or path.parent == _API_ROOT:
            continue
        for module_name in _imported_module_names(path):
            is_api = module_name == "src.api" or module_name.startswith("src.api.")
            assert not is_api, f"{path} imports 'src.api' -- no other layer may depend on api"
