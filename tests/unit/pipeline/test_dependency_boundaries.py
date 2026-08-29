"""Dependency-boundary tests for `src.pipeline`.

These tests statically inspect every `src.pipeline` module's import *statements* (via `ast`,
without executing them -- see `test_imports.py` for execution-based import verification) to
verify Phase 13's dependency rules hold: no forbidden layer is imported, every `src.*` import
resolves to one of Pipeline's explicitly allowed layers, no other layer imports `src.pipeline`
back, and Pipeline's own four modules form a DAG rather than a cycle. Mirrors
`tests/unit/memory/test_dependency_boundaries.py`'s own structure exactly.

`src.repository` is deliberately absent from `_ALLOWED_PREFIXES`: this phase's own brief lists
exactly nine layers Pipeline "may coordinate" (collectors, parsers, extractors, analyzers, graph,
foundation, storage, vector, memory) and does not name repository among them, even though
repository is listed among the layers that must never import pipeline back. `core` and `domain`
are included alongside those nine because every other already-frozen layer treats them as
universally available foundational layers, not because this phase's brief names them specifically.

Boundary-test correction (Phase 14): `test_no_other_layer_imports_pipeline` below now also
exempts `src/application` from its scan, alongside `src/pipeline` itself. This module's own
docstring, above, already named "a future, not-yet-built `application`/`cli`/`bootstrap` layer" as
pipeline's intended assembler -- Phase 14's own instruction makes `application` that layer, and
explicitly authorizes `Application -> Pipeline`. The original, Phase-13-era form of this test
predated `src/application`'s existence and so had no way to distinguish a genuinely lower layer
from a not-yet-built, already-anticipated outer one; without the exemption it produces a false
positive against a dependency this phase's own architecture requires. This is a correction to what
this test checks, not to Phase 13's own dependency rule or any Phase 13 production code -- neither
was ever touched. See `test_only_lower_layers_are_barred_from_importing_pipeline` and
`test_application_is_the_authorized_outer_consumer_of_pipeline`, further down, for the explicit,
per-layer re-statement of this same rule the correction is paired with.

Boundary-test correction (Phase 15): the same exemption now also covers `src/bootstrap`, for the
identical reason -- see `test_no_other_layer_imports_pipeline`'s own docstring, below, for detail.

Boundary-test correction (Phase 16): the same exemption now also covers `src/cli`, for the
identical reason -- `cli` is the third and final of the three layers this module's own docstring
named as sharing pipeline's "assemble a flow" gap, and Phase 16's own instruction explicitly
authorizes `CLI -> Bootstrap -> Application -> Pipeline`. See `test_no_other_layer_imports_
pipeline`'s own docstring, below, for detail.
"""

import ast
from pathlib import Path

import pytest

_SRC_ROOT = Path(__file__).resolve().parents[3] / "src"
_PIPELINE_ROOT = _SRC_ROOT / "pipeline"

_FORBIDDEN_PREFIXES = (
    "src.repository",
    "src.plugins",
    "src.api",
    "src.cli",
    "src.application",
    "src.bootstrap",
)

_ALLOWED_PREFIXES = (
    "src.core",
    "src.domain",
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
    """Render `path` relative to `_PIPELINE_ROOT`, for readable parametrized test ids."""
    return str(path.relative_to(_PIPELINE_ROOT))


@pytest.mark.parametrize("path", _source_files(_PIPELINE_ROOT), ids=_relative_id)
def test_pipeline_module_imports_no_forbidden_layer(path: Path) -> None:
    """No `src.pipeline` module may import from a layer Phase 13 forbids."""
    for module_name in _imported_module_names(path):
        for forbidden in _FORBIDDEN_PREFIXES:
            is_forbidden = module_name == forbidden or module_name.startswith(f"{forbidden}.")
            assert not is_forbidden, f"{path} imports forbidden module '{module_name}'"


@pytest.mark.parametrize("path", _source_files(_PIPELINE_ROOT), ids=_relative_id)
def test_pipeline_module_imports_only_allowed_layers(path: Path) -> None:
    """Every `src.*` import in `src.pipeline` must resolve to an explicitly allowed layer."""
    for module_name in _imported_module_names(path):
        if module_name == "src" or module_name.startswith("src."):
            is_allowed = any(
                module_name == allowed or module_name.startswith(f"{allowed}.")
                for allowed in _ALLOWED_PREFIXES
            )
            assert is_allowed, f"{path} imports '{module_name}', not an allowed dependency"


def test_pipeline_does_not_import_repository_anywhere() -> None:
    """Explicit, single-purpose guard for the one exclusion `_ALLOWED_PREFIXES` deliberately
    leaves out: `pipeline` must never import `repository`, even indirectly through a helper
    import list -- see this module's own docstring for why."""
    for path in _source_files(_PIPELINE_ROOT):
        for module_name in _imported_module_names(path):
            assert not module_name.startswith("src.repository"), (
                f"{path} imports 'src.repository' -- this phase's brief does not list "
                "repository among the layers Pipeline coordinates"
            )


def test_no_other_layer_imports_pipeline() -> None:
    """No *lower* layer may import `src.pipeline` -- the dependency direction from every layer
    Phase 13 was built on top of (`core` through `memory`) into `pipeline` must remain one-way,
    exactly as this phase's own brief requires. Scans the whole `src/` tree rather than relying
    only on each already-frozen phase's own dependency-boundary test.

    `src/application` is exempted from this scan, alongside `src/pipeline` itself: see this
    module's own docstring, above, for why -- it is the one, explicitly authorized outer layer,
    not a lower layer this rule was ever meant to guard against.

    Boundary-test correction (Phase 15): `src/bootstrap` is exempted for the identical reason.
    This module's own docstring already named `bootstrap` as one of the three layers sharing
    pipeline's own "assemble a flow" gap, alongside `application` and `cli`; Phase 15's own
    instruction makes `bootstrap` the second of those three to exist, and its approved contract
    explicitly authorizes `Bootstrap -> Pipeline` (via `Bootstrap -> Application -> Pipeline`).
    The original, Phase-14-era form of this exemption predated `src/bootstrap`'s existence and so
    had no way to distinguish it from a genuinely lower layer either; without widening the
    exemption it produces the same false positive against `bootstrap` that it once did against
    `application`. This is a correction to what this test checks, not to Phase 13's own
    dependency rule or any Phase 1-14 production code -- neither was touched.

    Boundary-test correction (Phase 16): `src/cli` is exempted for the identical reason. It is
    the third and final of the three layers this module's own docstring named as sharing
    pipeline's "assemble a flow" gap; Phase 16's own instruction requires `PipelineResult` as
    `src.cli.main`'s own return-type annotation, an import the original, pre-Phase-16 form of
    this test had no way to distinguish from a genuinely lower layer's. This is a correction to
    what this test checks, not to Phase 13's own dependency rule or any Phase 1-15 production
    code -- neither was touched.
    """
    _application_root = _SRC_ROOT / "application"
    _bootstrap_root = _SRC_ROOT / "bootstrap"
    _cli_root = _SRC_ROOT / "cli"
    for path in _source_files(_SRC_ROOT):
        if _PIPELINE_ROOT in path.parents or path.parent == _PIPELINE_ROOT:
            continue
        if _application_root in path.parents or path.parent == _application_root:
            continue
        if _bootstrap_root in path.parents or path.parent == _bootstrap_root:
            continue
        if _cli_root in path.parents or path.parent == _cli_root:
            continue
        for module_name in _imported_module_names(path):
            assert not (module_name == "src.pipeline" or module_name.startswith("src.pipeline.")), (
                f"{path} imports 'src.pipeline' -- no lower layer may depend on pipeline"
            )


_LOWER_LAYER_NAMES = (
    "core",
    "domain",
    "repository",
    "collectors",
    "parsers",
    "extractors",
    "analyzers",
    "graph",
    "foundation",
    "storage",
    "vector",
    "memory",
)


@pytest.mark.parametrize("layer_name", _LOWER_LAYER_NAMES)
def test_only_lower_layers_are_barred_from_importing_pipeline(layer_name: str) -> None:
    """Explicit, per-layer re-statement of `test_no_other_layer_imports_pipeline`'s rule, one
    lower layer at a time, so a regression names the exact offending layer rather than only the
    offending file. Covers every one of the twelve layers barred from importing pipeline --
    `core`, `domain`, `repository`, `collectors`, `parsers`, `extractors`, `analyzers`, `graph`,
    `foundation`, `storage`, `vector`, `memory` -- deliberately excluding `application`, the one
    layer this correction authorizes.
    """
    layer_root = _SRC_ROOT / layer_name
    for path in _source_files(layer_root):
        for module_name in _imported_module_names(path):
            assert not (module_name == "src.pipeline" or module_name.startswith("src.pipeline.")), (
                f"{path} imports 'src.pipeline' -- '{layer_name}' is a lower layer and must not "
                "depend on pipeline"
            )


def test_application_is_the_authorized_outer_consumer_of_pipeline() -> None:
    """Positive counterpart to `test_only_lower_layers_are_barred_from_importing_pipeline`: proves
    `src.application` genuinely does import `src.pipeline` -- the one direction Phase 14 explicitly
    authorizes ("Application -> Pipeline") and this module's own docstring already anticipated
    pipeline needing. A `src/application` that stopped importing `src.pipeline` would silently
    make this whole correction moot, so this asserts the dependency is real and exercised, not
    merely unforbidden.
    """
    application_root = _SRC_ROOT / "application"
    imports_pipeline = any(
        module_name == "src.pipeline" or module_name.startswith("src.pipeline.")
        for path in _source_files(application_root)
        for module_name in _imported_module_names(path)
    )
    assert imports_pipeline, "src.application does not import src.pipeline anywhere"


def _internal_relative_imports(path: Path) -> list[str]:
    """Every sibling module a single `src.pipeline` file imports via a relative import.

    `_imported_module_names` deliberately skips relative imports (`node.level > 0`), matching
    `test_memory_does_not_import_storage_anywhere`'s own upstream convention -- fine for
    cross-layer checks, since a relative import inside `src/pipeline/*.py` can only ever resolve
    to another module already inside `src.pipeline` itself. That is exactly what this DAG check
    needs to inspect, so it resolves them explicitly instead of skipping them: `src/pipeline/
    base.py`'s `from .context import PipelineContext` resolves to `src.pipeline.context`.
    """
    dotted_path = "src.pipeline." + path.stem
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    resolved: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level > 0:
            package_parts = dotted_path.split(".")[: -node.level]
            resolved.append(".".join(package_parts + ([node.module] if node.module else [])))
    return resolved


class TestInternalDependencyGraph:
    """Confirms Pipeline's own four modules form a DAG, not a cycle.

    `context.py` depends on nothing else in this package; `base.py` depends only on `context.py`;
    `pipeline.py` and `steps.py` each depend on `base.py` and `context.py`, never on each other.
    """

    def test_context_module_has_no_internal_pipeline_imports(self) -> None:
        assert _internal_relative_imports(_PIPELINE_ROOT / "context.py") == []

    def test_base_module_only_depends_on_context(self) -> None:
        internal = _internal_relative_imports(_PIPELINE_ROOT / "base.py")
        assert set(internal) <= {"src.pipeline.context"}

    def test_pipeline_module_does_not_depend_on_steps(self) -> None:
        internal = _internal_relative_imports(_PIPELINE_ROOT / "pipeline.py")
        assert "src.pipeline.steps" not in internal

    def test_steps_module_does_not_depend_on_pipeline_module(self) -> None:
        internal = _internal_relative_imports(_PIPELINE_ROOT / "steps.py")
        assert "src.pipeline.pipeline" not in internal

    def test_pipeline_and_steps_only_depend_on_base_and_context(self) -> None:
        for filename in ("pipeline.py", "steps.py"):
            internal = _internal_relative_imports(_PIPELINE_ROOT / filename)
            assert set(internal) <= {"src.pipeline.base", "src.pipeline.context"}
