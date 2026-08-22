"""Dependency-boundary and circular-dependency tests for `src.storage`.

These tests statically inspect every `src.storage` module's import *statements* (via `ast`,
without executing them -- see `test_imports.py` for execution-based import verification) to
verify Phase 10's dependency rules hold: no forbidden layer is imported, every `src.*` import
resolves to one of storage's explicitly allowed layers (`core`, `domain`, `vector`, and
`storage` itself), and -- since `storage` is meant to sit as an outer/leaf layer nothing else
depends on -- no other already-frozen `src` package imports anything from `src.storage`.

Both absolute (`from src.storage.base import X`) and relative (`from ..base import X`) imports
are resolved to their absolute dotted module name before checking -- `storage.filesystem` and
`storage.sqlite` each import their shared `storage.base` helpers via a relative `from ..base
import ...`, so a check that only looked at `node.level == 0` absolute imports (as
`tests.unit.foundation.test_dependency_boundaries` and `tests.unit.vector.
test_dependency_boundaries` do, since neither package's modules use relative imports) would
silently skip every cross-module import `storage` actually has.
"""

import ast
from pathlib import Path

import pytest

_SRC_ROOT = Path(__file__).resolve().parents[3] / "src"
_STORAGE_ROOT = _SRC_ROOT / "storage"

_FORBIDDEN_PREFIXES = (
    "src.collectors",
    "src.parsers",
    "src.extractors",
    "src.analyzers",
    "src.graph",
    "src.foundation",
    "src.repository",
    "src.memory",
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
    "src.vector",
    "src.storage",
)


def _storage_source_files() -> list[Path]:
    """Every `.py` file under `src/storage`, sorted for deterministic test IDs."""
    return sorted(_STORAGE_ROOT.rglob("*.py"))


def _module_dotted_name(path: Path) -> str:
    """Absolute dotted module name for a source file under `src/`.

    E.g. `src/storage/filesystem/driver.py` -> `"src.storage.filesystem.driver"`, and
    `src/storage/__init__.py` -> `"src.storage"`.
    """
    relative = path.relative_to(_SRC_ROOT.parent)
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _containing_package(path: Path) -> str:
    """The dotted package name a relative import inside `path` is resolved against."""
    own = _module_dotted_name(path)
    if path.name == "__init__.py":
        return own
    return own.rsplit(".", 1)[0]


def _resolve_relative_import(path: Path, level: int, module: str | None) -> str:
    """Resolve a relative `ImportFrom` (`level > 0`) to its absolute dotted module name.

    `level=1` resolves against the importing module's own containing package; each additional
    level climbs one more parent package, matching Python's own relative-import semantics.
    """
    package_parts = _containing_package(path).split(".")
    base_parts = package_parts[: len(package_parts) - (level - 1)] if level > 1 else package_parts
    base = ".".join(base_parts)
    return f"{base}.{module}" if module else base


def _imported_module_names(path: Path) -> list[str]:
    """Every module a single file imports, via `import x` or any `from x import y` (absolute or
    relative -- see module docstring for why relative imports must be resolved here)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module is not None:
                    names.append(node.module)
            else:
                names.append(_resolve_relative_import(path, node.level, node.module))
    return names


def _relative_id(path: Path) -> str:
    """Render `path` relative to `_STORAGE_ROOT`, for readable parametrized test ids."""
    return str(path.relative_to(_STORAGE_ROOT))


@pytest.mark.parametrize("path", _storage_source_files(), ids=_relative_id)
def test_storage_module_imports_no_forbidden_layer(path: Path) -> None:
    """No `src.storage` module may import from a layer Phase 10 forbids."""
    for module_name in _imported_module_names(path):
        for forbidden in _FORBIDDEN_PREFIXES:
            is_forbidden = module_name == forbidden or module_name.startswith(f"{forbidden}.")
            assert not is_forbidden, f"{path} imports forbidden module '{module_name}'"


@pytest.mark.parametrize("path", _storage_source_files(), ids=_relative_id)
def test_storage_module_imports_only_allowed_layers(path: Path) -> None:
    """Every `src.*` import in `src.storage` must resolve to an explicitly allowed layer."""
    for module_name in _imported_module_names(path):
        if module_name == "src" or module_name.startswith("src."):
            is_allowed = any(
                module_name == allowed or module_name.startswith(f"{allowed}.")
                for allowed in _ALLOWED_PREFIXES
            )
            assert is_allowed, f"{path} imports '{module_name}', not an allowed dependency"


def test_storage_does_not_import_itself_circularly_across_subpackages() -> None:
    """`storage`'s four backend subpackages (`filesystem`, `sqlite`, `postgres`, `qdrant`) must
    not import from one another -- each is independently self-contained, sharing only `base.py`
    (see `src/storage/__init__.py`'s own docstring)."""
    subpackages = ("filesystem", "sqlite", "postgres", "qdrant")
    for name in subpackages:
        driver_path = _STORAGE_ROOT / name / "driver.py"
        for module_name in _imported_module_names(driver_path):
            if not module_name.startswith("src.storage."):
                continue
            imported_subpackage = module_name.split(".")[2]
            assert imported_subpackage not in subpackages or imported_subpackage == name, (
                f"{driver_path} imports sibling backend '{imported_subpackage}'"
            )


def test_nothing_outside_storage_imports_from_storage() -> None:
    """No already-frozen `src` package may import anything from `src.storage` -- it is meant to
    sit as an outer/leaf layer nothing else in this codebase depends on, the same relationship
    `tests.unit.vector.test_dependency_boundaries.
    test_vector_does_not_import_storage_anywhere` establishes in the opposite direction."""
    for path in sorted(_SRC_ROOT.rglob("*.py")):
        if path.is_relative_to(_STORAGE_ROOT):
            continue
        for module_name in _imported_module_names(path):
            is_storage_import = module_name == "src.storage" or module_name.startswith(
                "src.storage."
            )
            assert not is_storage_import, f"{path} imports '{module_name}' from src.storage"
