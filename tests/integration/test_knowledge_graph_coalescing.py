"""Integration test: duplicate identity policy over real parsers and real extraction results.

Exercises `StructuralKnowledgeGraphBuilder`'s coalescing and rejection policy with the real
`Parser` implementations, the real structural extractors, and -- end to end -- the real
repository-analysis composition (`bootstrap(config, extra_steps=build_analysis_steps(config))`).
Nothing here touches the network: fixtures are local strings and temporary local Git repositories.

Two layers are covered:

- **Parser level** (no `git` needed): small per-language sources are parsed and extracted with the
  real parsers/extractors and handed straight to the builder, covering Python accessors, overloads
  and repeated definitions; Go `init` declared twice; Rust same-named functions in two inline
  `mod`s; TypeScript overloads; C++ overloads; and the non-equivalent conflicts (Python class vs.
  function, TypeScript class vs. `const`, a redefined Python `ABC` as an INTERFACE collision).
- **Pipeline level** (needs the real `git` executable; skipped, not failed, without it): the same
  sources are committed to a temporary local repository, analyzed by the real composition, and the
  builder is invoked directly on the composition's `symbol_results`, `interface_results`, and
  `foundation_results`. One fixture repository is accepted (every duplicate coalesces); another
  holds non-equivalent conflicts and is rejected deterministically.

The builder is invoked directly; it is not a pipeline step, and the existing
`tests/integration/test_knowledge_graph.py` is deliberately left untouched.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from src.bootstrap.analysis_steps import build_analysis_steps
from src.bootstrap.wiring import bootstrap
from src.core.config import AppConfig
from src.core.exceptions import ValidationError
from src.extractors.foundation.base import FoundationExtractionResult
from src.extractors.foundation.structural import StructuralFoundationExtractor
from src.extractors.interfaces.base import InterfaceExtractionResult
from src.extractors.interfaces.structural import StructuralInterfaceExtractor
from src.extractors.symbols.base import SymbolExtractionResult
from src.extractors.symbols.structural import StructuralSymbolExtractor
from src.graph.knowledge.base import (
    KnowledgeGraph,
    KnowledgeNodeKind,
    KnowledgeRelationKind,
    capability_node_id,
    interface_node_id,
)
from src.graph.knowledge.structural import StructuralKnowledgeGraphBuilder
from src.parsers.base import Parser
from src.parsers.cpp.parser import CppParser
from src.parsers.go.parser import GoParser
from src.parsers.python.parser import PythonParser
from src.parsers.rust.parser import RustParser
from src.parsers.typescript.parser import TypeScriptParser

_LOGGER_NAME = "vaos.graph.knowledge.structural"
_DUPLICATE_PREFIX = "KnowledgeGraph: nodes must not contain duplicate identifiers"

_ACCESSORS_PY = '''\
from typing import overload


class A:
    @property
    def x(self):
        return 1

    @x.setter
    def x(self, value):
        pass


@overload
def f(a: int) -> int: ...
@overload
def f(a: str) -> str: ...
def f(a):
    """Documented only on the implementation."""
    return a


def g():
    return 1


def g():
    return 2
'''

_COALESCING_FILES: dict[str, str] = {
    "accessors.py": _ACCESSORS_PY,
    "init.go": "package main\n\nfunc init() {}\n\nfunc init() {}\n",
    "modules.rs": "mod a {\n    pub fn run() {}\n}\n\nmod b {\n    pub fn run() {}\n}\n",
    "overloads.ts": (
        "function f(a: string): string;\n"
        "function f(a: number): number;\n"
        "function f(a: any): any { return a; }\n"
    ),
    "overloads.cpp": (
        "int add(int a, int b) { return a + b; }\n"
        "double add(double a, double b) { return a + b; }\n"
    ),
}

# Every identifier the real extractors give more than one record for, with how many records.
_EXPECTED_BY_FILE: dict[str, dict[str, int]] = {
    "accessors.py": {
        "symbol:accessors.py::A.x": 2,
        "symbol:accessors.py::f": 3,
        "symbol:accessors.py::g": 2,
        "capability:accessors.py::f": 3,
        "capability:accessors.py::g": 2,
    },
    "init.go": {"symbol:init.go::init": 2, "capability:init.go::init": 2},
    "modules.rs": {"symbol:modules.rs::run": 2, "capability:modules.rs::run": 2},
    "overloads.ts": {"symbol:overloads.ts::f": 3, "capability:overloads.ts::f": 3},
    "overloads.cpp": {"symbol:overloads.cpp::add": 2, "capability:overloads.cpp::add": 2},
}

_ABSTRACT_PY = '''\
from abc import ABC, abstractmethod


class Shape(ABC):
    @abstractmethod
    def a(self): ...


class Shape(ABC):
    @abstractmethod
    def b(self): ...
'''

_CONFLICT_FILES: dict[str, str] = {
    "m.py": "class Foo:\n    pass\n\n\ndef Foo():\n    return 1\n",
    "c.ts": "export class Foo { size(): number { return 1; } }\nexport const Foo = 1;\n",
    "abstract.py": _ABSTRACT_PY,
    "helpers.py": "def h():\n    return 1\n\n\ndef h():\n    return 2\n",
}

# identifier -> (node_kind, reason, differing_fields), for every rejected group in the conflict
# fixture. `helpers.py` and the `Shape` symbols/capabilities are equivalent and are never listed.
_EXPECTED_CONFLICTS: dict[str, tuple[str, str, list[str]]] = {
    "capability:m.py::Foo": ("capability", "conflicting_records", ["declaration_kind"]),
    "interface:abstract.py::Shape": ("interface", "coalescing_not_permitted", []),
    "symbol:c.ts::Foo": ("symbol", "conflicting_records", ["declaration_kind"]),
    "symbol:m.py::Foo": ("symbol", "conflicting_records", ["declaration_kind"]),
}

_PARSERS: dict[str, Parser] = {
    ".py": PythonParser(),
    ".go": GoParser(),
    ".rs": RustParser(),
    ".ts": TypeScriptParser(),
    ".cpp": CppParser(),
}


@dataclass(frozen=True)
class _Extracted:
    """The three extraction-result families the builder consumes for these fixtures."""

    symbol_results: tuple[SymbolExtractionResult, ...]
    interface_results: tuple[InterfaceExtractionResult, ...]
    foundation_results: tuple[FoundationExtractionResult, ...]


def _extract_sources(sources: dict[str, str]) -> _Extracted:
    """Parse and extract every source with the real parsers and structural extractors."""
    symbol_results: list[SymbolExtractionResult] = []
    interface_results: list[InterfaceExtractionResult] = []
    foundation_results: list[FoundationExtractionResult] = []
    for relative_path, content in sources.items():
        parser = _PARSERS[Path(relative_path).suffix]
        parse_result = parser.parse(relative_path=relative_path, content=content)
        assert parse_result.succeeded, (relative_path, parse_result.error_message)
        symbol_results.append(StructuralSymbolExtractor().extract(parse_result))
        interface_results.append(StructuralInterfaceExtractor().extract(parse_result))
        foundation_results.append(StructuralFoundationExtractor().extract(parse_result))
    return _Extracted(tuple(symbol_results), tuple(interface_results), tuple(foundation_results))


def _record_counts(extracted: _Extracted) -> Counter[str]:
    """How many raw extraction records map onto each concept node identifier."""
    counts: Counter[str] = Counter()
    for symbol_result in extracted.symbol_results:
        counts.update(f"symbol:{symbol.qualified_name}" for symbol in symbol_result.symbols)
    for interface_result in extracted.interface_results:
        counts.update(
            interface_node_id(relative_path=i.relative_path, name=i.name)
            for i in interface_result.interfaces
        )
    for foundation_result in extracted.foundation_results:
        counts.update(
            capability_node_id(relative_path=c.relative_path, name=c.name)
            for c in foundation_result.candidates
        )
    return counts


def _multi_record_identities(extracted: _Extracted) -> dict[str, int]:
    """Identifiers that more than one raw record maps onto, with their record counts."""
    return {identifier: n for identifier, n in _record_counts(extracted).items() if n > 1}


def _build(extracted: _Extracted) -> KnowledgeGraph:
    """Invoke the builder directly on `extracted`."""
    return StructuralKnowledgeGraphBuilder().build(
        symbol_results=extracted.symbol_results,
        pattern_results=(),
        interface_results=extracted.interface_results,
        foundation_results=extracted.foundation_results,
    )


def _concept_node_ids(graph: KnowledgeGraph) -> list[str]:
    """Identifiers of every non-entity, non-package node, in graph order."""
    concept_kinds = {
        KnowledgeNodeKind.SYMBOL,
        KnowledgeNodeKind.PATTERN,
        KnowledgeNodeKind.INTERFACE,
        KnowledgeNodeKind.CAPABILITY,
    }
    return [node.identifier for node in graph.nodes if node.kind in concept_kinds]


def _assert_one_node_and_one_declares_per_identity(
    graph: KnowledgeGraph, extracted: _Extracted
) -> None:
    """Every distinct identifier is exactly one node with exactly one `DECLARES` relation."""
    identifiers = set(_record_counts(extracted))
    node_ids = _concept_node_ids(graph)
    assert sorted(node_ids) == sorted(identifiers)
    declares = [r for r in graph.relations if r.kind is KnowledgeRelationKind.DECLARES]
    assert sorted(r.target for r in declares) == sorted(identifiers)


def _warning_message(groups: dict[str, int]) -> str:
    """The exact aggregate WARNING the builder emits for the coalesced `groups`."""
    symbols = {i: n for i, n in groups.items() if i.startswith("symbol:")}
    capabilities = {i: n for i, n in groups.items() if i.startswith("capability:")}
    return (
        f"Coalesced {len(groups)} colliding node group(s) covering {sum(groups.values())} "
        f"declaration(s): symbol={len(symbols)} group(s)/{sum(symbols.values())} "
        f"declaration(s), capability={len(capabilities)} group(s)/{sum(capabilities.values())} "
        "declaration(s); declaration multiplicity and metadata outside the node projection "
        "are not preserved"
    )


class _Capture(logging.Handler):
    """Collects every record the structural logger emits."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        """Remember `record`."""
        self.records.append(record)

    def lines(self) -> list[tuple[int, str]]:
        """Every captured record as `(level, formatted message)`, in emission order."""
        return [(record.levelno, record.getMessage()) for record in self.records]


@pytest.fixture
def log_capture() -> Iterator[_Capture]:
    """Isolate the structural logger: DEBUG level, no propagation, one capturing handler."""
    logger = logging.getLogger(_LOGGER_NAME)
    saved = (logger.level, logger.disabled, logger.propagate)
    saved_handlers = list(logger.handlers)
    saved_filters = list(logger.filters)
    capture = _Capture()
    logger.handlers = [capture]
    logger.filters = []
    logger.setLevel(logging.DEBUG)
    logger.disabled = False
    logger.propagate = False
    try:
        yield capture
    finally:
        logger.handlers = saved_handlers
        logger.filters = saved_filters
        logger.setLevel(saved[0])
        logger.disabled = saved[1]
        logger.propagate = saved[2]


# -- Parser level: accepted coalescing -------------------------------------------------------------


@pytest.mark.parametrize("relative_path", list(_COALESCING_FILES))
def test_real_parser_duplicates_coalesce_into_one_node_per_identity(
    relative_path: str, log_capture: _Capture
) -> None:
    """Real duplicates (accessors, overloads, `init`, inline mods) become one node each."""
    extracted = _extract_sources({relative_path: _COALESCING_FILES[relative_path]})
    expected = _EXPECTED_BY_FILE[relative_path]
    # The duplicates are real extractor output, not constructed data.
    assert _multi_record_identities(extracted) == expected

    graph = _build(extracted)

    _assert_one_node_and_one_declares_per_identity(graph, extracted)
    entities = [n.identifier for n in graph.nodes if n.kind is KnowledgeNodeKind.ENTITY]
    assert entities == [f"entity:{relative_path}"]
    warnings = [line for line in log_capture.lines() if line[0] == logging.WARNING]
    assert warnings == [(logging.WARNING, _warning_message(expected))]


def test_real_parser_accessor_pair_is_one_method_symbol_with_one_declares() -> None:
    """The Python property getter/setter pair is a single `kind=method` node."""
    graph = _build(_extract_sources({"accessors.py": _ACCESSORS_PY}))
    node = graph.get_node("symbol:accessors.py::A.x")
    assert node.attributes == ("kind=method",)
    declares = [r for r in graph.relations if r.target == "symbol:accessors.py::A.x"]
    assert [r.kind for r in declares] == [KnowledgeRelationKind.DECLARES]


def test_real_parser_overloads_keep_one_capability_despite_differing_docstrings() -> None:
    """Python overloads (docstring only on the implementation) are one capability node."""
    extracted = _extract_sources({"accessors.py": _ACCESSORS_PY})
    candidates = [
        c for result in extracted.foundation_results for c in result.candidates if c.name == "f"
    ]
    assert [c.has_docstring for c in candidates] == [False, False, True]
    graph = _build(extracted)
    assert graph.get_node("capability:accessors.py::f").attributes == ()


def test_all_languages_build_together_with_one_node_per_identity(log_capture: _Capture) -> None:
    """The five languages in one build: every duplicate coalesces and the WARNING totals them."""
    extracted = _extract_sources(_COALESCING_FILES)
    expected = {i: n for group in _EXPECTED_BY_FILE.values() for i, n in group.items()}
    assert _multi_record_identities(extracted) == expected

    graph = _build(extracted)

    _assert_one_node_and_one_declares_per_identity(graph, extracted)
    warnings = [line for line in log_capture.lines() if line[0] == logging.WARNING]
    assert warnings == [(logging.WARNING, _warning_message(expected))]
    assert "Coalesced 13 colliding node group(s) covering 30 declaration(s)" in warnings[0][1]
    debug_messages = [m for level, m in log_capture.lines() if level == logging.DEBUG]
    assert [m.split(" ")[1] for m in debug_messages] == sorted(expected)


def test_repeated_builds_over_real_results_are_deterministic(log_capture: _Capture) -> None:
    """Rebuilding, and rebuilding from freshly extracted input, never changes the graph or logs."""
    first_extracted = _extract_sources(_COALESCING_FILES)
    reference = _build(first_extracted)
    reference_lines = log_capture.lines()
    for _ in range(3):
        log_capture.records.clear()
        assert _build(first_extracted).to_mapping() == reference.to_mapping()
        assert log_capture.lines() == reference_lines
    log_capture.records.clear()
    assert _build(_extract_sources(_COALESCING_FILES)).to_mapping() == reference.to_mapping()
    assert log_capture.lines() == reference_lines


# -- Parser level: non-equivalent conflicts --------------------------------------------------------


@pytest.mark.parametrize(
    ("sources", "expected"),
    [
        pytest.param(
            {"m.py": _CONFLICT_FILES["m.py"]},
            {k: v for k, v in _EXPECTED_CONFLICTS.items() if ":m.py::" in k},
            id="python-class-versus-function",
        ),
        pytest.param(
            {"c.ts": _CONFLICT_FILES["c.ts"]},
            {k: v for k, v in _EXPECTED_CONFLICTS.items() if ":c.ts::" in k},
            id="typescript-class-versus-const",
        ),
        pytest.param(
            {"abstract.py": _CONFLICT_FILES["abstract.py"]},
            {k: v for k, v in _EXPECTED_CONFLICTS.items() if ":abstract.py::" in k},
            id="python-redefined-abc-is-an-interface-collision",
        ),
    ],
)
def test_real_parser_conflicts_are_rejected(
    sources: dict[str, str],
    expected: dict[str, tuple[str, str, list[str]]],
    log_capture: _Capture,
) -> None:
    """Non-equivalent real declarations, and any INTERFACE collision, reject the whole build."""
    extracted = _extract_sources(sources)
    with pytest.raises(ValidationError) as excinfo:
        _build(extracted)
    error = excinfo.value
    assert str(error).startswith(f"{_DUPLICATE_PREFIX}; {len(expected)} colliding identifier(s)")
    collisions: list[dict[str, Any]] = error.details["collisions"]
    assert [c["identifier"] for c in collisions] == sorted(expected)
    for collision in collisions:
        node_kind, reason, differing = expected[collision["identifier"]]
        assert (collision["node_kind"], collision["reason"]) == (node_kind, reason)
        assert collision["differing_fields"] == differing
        assert len(collision["records"]) == 2
    assert log_capture.records == []

    # The same input rejects identically every time.
    with pytest.raises(ValidationError) as again:
        _build(_extract_sources(sources))
    assert str(again.value) == str(error)
    assert again.value.details == error.details


# -- Pipeline level: real repository analysis ------------------------------------------------------


def _config(raw: dict[str, object]) -> AppConfig:
    """Build an `AppConfig` directly from a raw mapping, bypassing `load_config`/YAML/env."""
    return AppConfig(raw=raw)


def _run_git(*args: str, cwd: Path) -> None:
    """Run a `git` subcommand in `cwd`, raising if it fails."""
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _skip_without_git() -> None:
    """Skip the calling test if the real `git` executable is unavailable."""
    if shutil.which("git") is None:
        pytest.skip("git executable not found on PATH")


def _make_source_repository(tmp_path: Path, name: str, files: dict[str, str]) -> Path:
    """Create a local Git repository under `tmp_path` holding `files`, with one commit."""
    source_repo = tmp_path / name
    source_repo.mkdir()
    _run_git("init", cwd=source_repo)
    _run_git("config", "user.email", "test@example.com", cwd=source_repo)
    _run_git("config", "user.name", "Test", cwd=source_repo)
    _run_git("checkout", "-b", "main", cwd=source_repo)
    for relative_path, content in files.items():
        (source_repo / relative_path).write_text(content, encoding="utf-8")
    _run_git("add", "-A", cwd=source_repo)
    _run_git("commit", "-m", "fixture repository", cwd=source_repo)
    return source_repo


async def _analyze(source_repo: Path, tmp_path: Path, tag: str) -> _Extracted:
    """Run the real composition over `source_repo` and collect the results the builder consumes.

    Each `tag` gets its own storage and workspace roots, so repeated runs are fully independent.
    """
    config = _config(
        {
            "collectors": {"backend": "filesystem", "source": str(source_repo)},
            "storage": {
                "backend": "filesystem",
                "filesystem": {"root": str(tmp_path / f"storage-{tag}")},
            },
            "repository": {"workspace_root": str(tmp_path / f"workspaces-{tag}")},
        }
    )
    result = await bootstrap(config, extra_steps=build_analysis_steps(config))
    return _Extracted(
        symbol_results=tuple(result.context.require("symbol_results")),
        interface_results=tuple(result.context.require("interface_results")),
        foundation_results=tuple(result.context.require("foundation_results")),
    )


@pytest.mark.asyncio
async def test_real_analysis_of_an_accepted_repository_coalesces_every_duplicate(
    tmp_path: Path, log_capture: _Capture
) -> None:
    """The real composition's duplicates (all five languages) build into one node per identity."""
    _skip_without_git()
    repo = _make_source_repository(tmp_path, "accepted_repo", _COALESCING_FILES)
    extracted = await _analyze(repo, tmp_path, "a")
    expected = {i: n for group in _EXPECTED_BY_FILE.values() for i, n in group.items()}
    assert _multi_record_identities(extracted) == expected

    graph = _build(extracted)

    _assert_one_node_and_one_declares_per_identity(graph, extracted)
    entities = {n.identifier for n in graph.nodes if n.kind is KnowledgeNodeKind.ENTITY}
    assert entities == {f"entity:{path}" for path in _COALESCING_FILES}
    warnings = [line for line in log_capture.lines() if line[0] == logging.WARNING]
    assert warnings == [(logging.WARNING, _warning_message(expected))]
    debug_messages = [m for level, m in log_capture.lines() if level == logging.DEBUG]
    assert [m.split(" ")[1] for m in debug_messages] == sorted(expected)


@pytest.mark.asyncio
async def test_real_analysis_results_build_deterministically_across_runs(
    tmp_path: Path, log_capture: _Capture
) -> None:
    """Repeated builds and two independent analysis runs give identical graphs and log records."""
    _skip_without_git()
    repo = _make_source_repository(tmp_path, "accepted_repo", _COALESCING_FILES)
    first = await _analyze(repo, tmp_path, "a")
    second = await _analyze(repo, tmp_path, "b")

    reference = _build(first)
    reference_lines = log_capture.lines()
    assert reference_lines

    for extracted in (first, first, second):
        log_capture.records.clear()
        graph = _build(extracted)
        assert graph == reference
        assert graph.to_mapping() == reference.to_mapping()
        assert log_capture.lines() == reference_lines


@pytest.mark.asyncio
async def test_real_analysis_of_a_conflicting_repository_is_rejected_deterministically(
    tmp_path: Path, log_capture: _Capture
) -> None:
    """Class/function, class/`const`, and a redefined `ABC` reject; coalescible groups don't leak.

    `helpers.py` (a repeated function) and the redefined `ABC`'s own symbols and capabilities are
    equivalent and would coalesce, but a rejected build reports only its rejected groups and logs
    no coalescing records.
    """
    _skip_without_git()
    repo = _make_source_repository(tmp_path, "conflict_repo", _CONFLICT_FILES)
    first = await _analyze(repo, tmp_path, "a")
    second = await _analyze(repo, tmp_path, "b")

    with pytest.raises(ValidationError) as excinfo:
        _build(first)
    error = excinfo.value
    assert str(error) == (
        f"{_DUPLICATE_PREFIX}; 4 colliding identifier(s) rejected: "
        "'capability:m.py::Foo', 'interface:abstract.py::Shape', "
        "'symbol:c.ts::Foo', 'symbol:m.py::Foo'"
    )
    assert error.details["collision_count"] == 4
    collisions: list[dict[str, Any]] = error.details["collisions"]
    assert [c["identifier"] for c in collisions] == sorted(_EXPECTED_CONFLICTS)
    for collision in collisions:
        node_kind, reason, differing = _EXPECTED_CONFLICTS[collision["identifier"]]
        assert (collision["node_kind"], collision["reason"]) == (node_kind, reason)
        assert collision["differing_fields"] == differing
        assert len(collision["records"]) == 2
    assert log_capture.records == []

    for extracted in (first, second):
        with pytest.raises(ValidationError) as again:
            _build(extracted)
        assert str(again.value) == str(error)
        assert again.value.details == error.details
