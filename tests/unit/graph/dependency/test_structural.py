"""Unit tests for `src.graph.dependency.structural`.

Every test builds `ImportExtractionResult`s by hand -- the builder is pure string work and never
touches a filesystem, so none of the paths below need to exist.
"""

import ast
import itertools
from collections.abc import Sequence
from pathlib import Path

import pytest
import src.graph.dependency.structural as structural_module
from src.core.exceptions import ValidationError
from src.extractors.imports.base import DependencyEdge, ImportExtractionResult
from src.graph.dependency.base import (
    DependencyGraph,
    DependencyGraphBuilder,
    DependencyNode,
    DependencyNodeKind,
    DependencyRelationEdge,
)
from src.graph.dependency.structural import StructuralDependencyGraphBuilder

INTERNAL_FILE = DependencyNodeKind.INTERNAL_FILE
EXTERNAL_MODULE = DependencyNodeKind.EXTERNAL_MODULE
UNRESOLVED_INTERNAL = DependencyNodeKind.UNRESOLVED_INTERNAL


def _edge(
    source: str,
    target: str,
    *,
    internal: bool = False,
    names: tuple[str, ...] = (),
    alias: str | None = None,
    line: int = 1,
) -> DependencyEdge:
    """Build one upstream `DependencyEdge`."""
    return DependencyEdge(
        source_path=source,
        target_module=target,
        imported_names=names,
        alias=alias,
        is_internal=internal,
        line_number=line,
    )


def _result(path: str, *edges: DependencyEdge) -> ImportExtractionResult:
    """Build a successful `ImportExtractionResult` for `path`."""
    return ImportExtractionResult.ok(relative_path=path, edges=edges)


def _build(*results: ImportExtractionResult) -> DependencyGraph:
    """Build a graph from `results` with a fresh builder."""
    return StructuralDependencyGraphBuilder().build(results)


def _resolve(
    source: str,
    target: str,
    *,
    internal: bool,
    files: Sequence[str] = (),
    names: tuple[str, ...] = (),
) -> tuple[DependencyNodeKind, str, bool]:
    """Resolve a single edge `source -> target` with `files` also present in the input.

    Returns:
        The target node's kind and identifier, and the output edge's `is_internal`.
    """
    results = [_result(source, _edge(source, target, internal=internal, names=names))]
    results.extend(_result(path) for path in files if path != source)
    graph = _build(*results)
    assert graph.edge_count == 1
    only_edge = graph.edges[0]
    assert only_edge.source == source
    return graph.get_node(only_edge.target).kind, only_edge.target, only_edge.is_internal


# --------------------------------------------------------------------------- construction/Port


def test_builder_is_zero_argument_and_stateless() -> None:
    """Construction takes no arguments and the instance holds no state."""
    builder = StructuralDependencyGraphBuilder()
    assert not vars(builder)


def test_builder_conforms_to_the_port() -> None:
    """The concrete builder is a `DependencyGraphBuilder` and returns a `DependencyGraph`."""
    builder = StructuralDependencyGraphBuilder()
    assert isinstance(builder, DependencyGraphBuilder)
    assert isinstance(builder.build(()), DependencyGraph)


def test_one_instance_is_reusable_across_builds() -> None:
    """A single instance gives independent, correct results across calls."""
    builder = StructuralDependencyGraphBuilder()
    first = builder.build((_result("a.py", _edge("a.py", "os")),))
    second = builder.build((_result("b.py"),))
    assert [node.identifier for node in first.nodes] == ["a.py", "external:os"]
    assert [node.identifier for node in second.nodes] == ["b.py"]


# ------------------------------------------------------------------------------ empty / zero


def test_empty_input_returns_an_empty_graph() -> None:
    """`build(())` returns `DependencyGraph()` for any empty sequence."""
    assert StructuralDependencyGraphBuilder().build(()) == DependencyGraph()
    assert StructuralDependencyGraphBuilder().build([]) == DependencyGraph()


def test_zero_import_file_is_still_an_internal_file_node() -> None:
    """A successful extraction with no edges contributes a node and no edge."""
    graph = _build(_result("empty.py"))
    assert graph.nodes == (DependencyNode(identifier="empty.py", kind=INTERNAL_FILE),)
    assert graph.edges == ()


def test_every_input_file_is_a_node_even_if_never_imported() -> None:
    """Files that import nothing and are imported by nothing are all present."""
    graph = _build(_result("a.py"), _result("b.py"), _result("c.go"))
    assert [(n.identifier, n.kind) for n in graph.nodes] == [
        ("a.py", INTERNAL_FILE),
        ("b.py", INTERNAL_FILE),
        ("c.go", INTERNAL_FILE),
    ]


# ------------------------------------------------------------------------- multiple / ordering


def test_multiple_input_files_produce_all_nodes_and_edges() -> None:
    """Several files with several imports produce the full node and edge sets."""
    graph = _build(
        _result("pkg/a.py", _edge("pkg/a.py", "pkg.b"), _edge("pkg/a.py", "os", line=2)),
        _result("pkg/b.py", _edge("pkg/b.py", ".a", internal=True)),
    )
    assert [(n.identifier, n.kind) for n in graph.nodes] == [
        ("external:os", EXTERNAL_MODULE),
        ("pkg/a.py", INTERNAL_FILE),
        ("pkg/b.py", INTERNAL_FILE),
    ]
    assert [(e.source, e.target, e.is_internal) for e in graph.edges] == [
        ("pkg/a.py", "external:os", False),
        ("pkg/a.py", "pkg/b.py", True),
        ("pkg/b.py", "pkg/a.py", True),
    ]


def test_nodes_are_sorted_by_identifier_regardless_of_input_order() -> None:
    """Node order is by identifier, not by input or discovery order."""
    graph = _build(
        _result("z.py", _edge("z.py", "zlib")),
        _result("a.py", _edge("a.py", "abc")),
        _result("m.py", _edge("m.py", "z", internal=True)),
    )
    identifiers = [node.identifier for node in graph.nodes]
    assert identifiers == sorted(identifiers)


def test_edges_are_sorted_by_source_target_and_line() -> None:
    """Edges sort by `(source, target, line_number)` first."""
    graph = _build(
        _result("b.py", _edge("b.py", "os", line=9)),
        _result(
            "a.py",
            _edge("a.py", "sys", line=5),
            _edge("a.py", "os", line=7),
            _edge("a.py", "os", line=3),
        ),
    )
    assert [(e.source, e.target, e.line_number) for e in graph.edges] == [
        ("a.py", "external:os", 3),
        ("a.py", "external:os", 7),
        ("a.py", "external:sys", 5),
        ("b.py", "external:os", 9),
    ]


def test_edge_ties_break_on_names_then_alias_presence_then_alias() -> None:
    """Edges equal on `(source, target, line_number)` order by the frozen tie-break tuple."""
    edges = (
        _edge("a.py", "os", names=("b",), line=4),
        _edge("a.py", "os", names=("a",), alias="z", line=4),
        _edge("a.py", "os", names=("a",), alias="y", line=4),
        _edge("a.py", "os", names=("a",), alias=None, line=4),
        _edge("a.py", "os", names=(), alias="q", line=4),
        _edge("a.py", "os", names=(), alias=None, line=4),
    )
    graph = _build(_result("a.py", *edges))
    assert [(e.imported_names, e.alias) for e in graph.edges] == [
        ((), None),
        ((), "q"),
        (("a",), None),
        (("a",), "y"),
        (("a",), "z"),
        (("b",), None),
    ]
    assert _build(_result("a.py", *reversed(edges))) == graph


# --------------------------------------------------------------------- failure / path validity


def test_failed_extraction_is_rejected() -> None:
    """A failed `ImportExtractionResult` raises `ValidationError`."""
    failed = ImportExtractionResult.failed(relative_path="a.py", error_message="bad")
    with pytest.raises(ValidationError):
        StructuralDependencyGraphBuilder().build((_result("b.py"), failed))


def test_failed_extraction_check_runs_before_any_path_validation() -> None:
    """The failed-extraction check is the first action, ahead of path validation."""
    failed = ImportExtractionResult.failed(relative_path="a.py", error_message="bad")
    with pytest.raises(ValidationError, match="failed ImportExtractionResult"):
        StructuralDependencyGraphBuilder().build((_result("external:x.py"), failed))


def test_duplicate_relative_path_is_rejected() -> None:
    """Two results with the same `relative_path` raise `ValidationError`."""
    with pytest.raises(ValidationError):
        _build(_result("a.py"), _result("a.py"))


@pytest.mark.parametrize(
    "other",
    ["a\\b.py", "a//b.py", "./a/b.py", "a/./b.py", "a/b.py/", "x/../a/b.py", "a\\.\\b.py"],
)
def test_normalization_equivalent_duplicate_relative_paths_are_rejected(other: str) -> None:
    """Paths equal after normalization are duplicates, e.g. `a\\b.py` and `a/b.py`."""
    with pytest.raises(ValidationError):
        _build(_result("a/b.py"), _result(other))
    with pytest.raises(ValidationError):
        _build(_result(other), _result("a/b.py"))


def test_paths_differing_only_by_case_are_not_duplicates() -> None:
    """Matching is case-sensitive, so case-differing paths are distinct files."""
    graph = _build(_result("A.py"), _result("a.py"))
    assert [node.identifier for node in graph.nodes] == ["A.py", "a.py"]


@pytest.mark.parametrize(
    "path", ["external:a.py", "unresolved:a.py", "external:", "unresolved:x/y.py"]
)
def test_reserved_prefix_input_paths_are_rejected(path: str) -> None:
    """An input path beginning with `external:` or `unresolved:` raises `ValidationError`."""
    with pytest.raises(ValidationError):
        _build(_result(path))


@pytest.mark.parametrize(
    "path",
    [
        "",
        "   ",
        "/abs/a.py",
        "\\abs\\a.py",
        "C:\\x\\a.py",
        "c:/x/a.py",
        "../a.py",
        "a/../../b.py",
        ".",
    ],
)
def test_invalid_source_paths_are_rejected(path: str) -> None:
    """Blank, absolute, drive-prefixed, root-escaping, or root-naming source paths are invalid."""
    with pytest.raises(ValidationError):
        _build(_result(path))


def test_blank_target_module_is_rejected() -> None:
    """A blank `target_module` raises `ValidationError` instead of becoming a prefixed node."""
    with pytest.raises(ValidationError):
        _build(_result("a.py", _edge("a.py", "  ")))
    with pytest.raises(ValidationError):
        _build(_result("a.cpp", _edge("a.cpp", "", internal=True)))


# ------------------------------------------------------------------------------ Python


def test_python_absolute_import_resolves_to_a_module_file() -> None:
    """`import x.y` / `from x.y import z` (upstream False) resolves to `x/y.py`."""
    assert _resolve("main.py", "pkg.util", internal=False, files=["pkg/util.py"]) == (
        INTERNAL_FILE,
        "pkg/util.py",
        True,
    )


def test_python_absolute_from_import_ignores_the_imported_name() -> None:
    """`from pkg import sub` targets `pkg` itself, never `pkg/sub.py`."""
    kind, identifier, is_internal = _resolve(
        "main.py", "pkg", internal=False, names=("sub",), files=["pkg/__init__.py", "pkg/sub.py"]
    )
    assert (kind, identifier, is_internal) == (INTERNAL_FILE, "pkg/__init__.py", True)


def test_python_absolute_import_does_not_match_on_a_prefix_only() -> None:
    """`import pkg.util.deep` does not fall back to `pkg/util.py`."""
    assert _resolve("main.py", "pkg.util.deep", internal=False, files=["pkg/util.py"]) == (
        EXTERNAL_MODULE,
        "external:pkg.util.deep",
        False,
    )


def test_python_absolute_import_is_external_when_nothing_matches() -> None:
    """An upstream-False import matching no file stays `EXTERNAL_MODULE`."""
    assert _resolve("main.py", "numpy", internal=False, files=["pkg/util.py"]) == (
        EXTERNAL_MODULE,
        "external:numpy",
        False,
    )


@pytest.mark.parametrize(
    ("present", "expected"),
    [
        (["m/__init__.py", "m.py", "m/__init__.pyi", "m.pyi"], "m/__init__.py"),
        (["m.py", "m/__init__.pyi", "m.pyi"], "m.py"),
        (["m/__init__.pyi", "m.pyi"], "m/__init__.pyi"),
        (["m.pyi"], "m.pyi"),
        (["m/__init__.py", "m.py"], "m/__init__.py"),
    ],
)
def test_python_candidate_priority_is_package_then_module_then_stub(
    present: list[str], expected: str
) -> None:
    """Candidate order is exactly `P/__init__.py`, `P.py`, `P/__init__.pyi`, `P.pyi`."""
    kind, identifier, is_internal = _resolve("main.py", "m", internal=False, files=present)
    assert (kind, identifier, is_internal) == (INTERNAL_FILE, expected, True)


def test_python_relative_import_from_current_package() -> None:
    """`from .x import y` resolves `dir/x` relative to the source file's directory."""
    assert _resolve("pkg/a.py", ".b", internal=True, files=["pkg/b.py"]) == (
        INTERNAL_FILE,
        "pkg/b.py",
        True,
    )
    assert _resolve("pkg/a.py", ".sub.c", internal=True, files=["pkg/sub/c.py"]) == (
        INTERNAL_FILE,
        "pkg/sub/c.py",
        True,
    )


def test_python_relative_import_at_the_repository_root() -> None:
    """A root-level file's `.x` resolves to a root-level `x.py`."""
    assert _resolve("a.py", ".b", internal=True, files=["b.py"]) == (INTERNAL_FILE, "b.py", True)


def test_python_relative_import_unresolved_when_no_candidate_matches() -> None:
    """An internal-candidate relative import matching no file is `UNRESOLVED_INTERNAL`."""
    assert _resolve("pkg/a.py", ".missing", internal=True, files=["pkg/b.py"]) == (
        UNRESOLVED_INTERNAL,
        "unresolved:pkg/missing",
        True,
    )


@pytest.mark.parametrize(
    ("source", "target", "files", "expected"),
    [
        ("a/b/c.py", "..x", ["a/x.py"], "a/x.py"),
        ("a/b/c.py", "...x", ["x.py"], "x.py"),
        ("a/b/c.py", "..x.y", ["a/x/y.py"], "a/x/y.py"),
        ("a/b/c.py", "..x", ["a/x/__init__.py", "a/x.py"], "a/x/__init__.py"),
    ],
)
def test_python_multiple_leading_dots_hop_parent_directories(
    source: str, target: str, files: list[str], expected: str
) -> None:
    """N leading dots mean N-1 parent-directory hops from the source's directory."""
    assert _resolve(source, target, internal=True, files=files) == (INTERNAL_FILE, expected, True)


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("a.py", "..x"),
        ("a/b.py", "...x"),
        ("a/b/c.py", "....x"),
        ("a.py", ".."),
    ],
)
def test_python_root_escape_is_unresolved_and_non_fatal(source: str, target: str) -> None:
    """Escaping the repository root is `UNRESOLVED_INTERNAL`, source-qualified, no exception."""
    kind, identifier, is_internal = _resolve(source, target, internal=True, files=["x.py"])
    assert kind is UNRESOLVED_INTERNAL
    assert identifier == f"unresolved:{source}#{target}"
    assert is_internal is True


def test_python_from_dot_import_name_prefers_the_submodule() -> None:
    """`from . import name` tries `dir/name` first, even if the package `__init__` exists."""
    files = ["pkg/__init__.py", "pkg/name.py"]
    assert _resolve("pkg/a.py", ".", internal=True, names=("name",), files=files) == (
        INTERNAL_FILE,
        "pkg/name.py",
        True,
    )


def test_python_from_dot_import_name_falls_back_to_the_package_root() -> None:
    """With no `dir/name` submodule, `from . import name` resolves to the package `__init__`."""
    assert _resolve("pkg/a.py", ".", internal=True, names=("name",), files=["pkg/__init__.py"]) == (
        INTERNAL_FILE,
        "pkg/__init__.py",
        True,
    )
    assert _resolve(
        "pkg/a.py", ".", internal=True, names=("name",), files=["pkg/__init__.pyi"]
    ) == (INTERNAL_FILE, "pkg/__init__.pyi", True)


def test_python_from_dot_import_name_unresolved_without_submodule_or_package_root() -> None:
    """`from . import name` with neither candidate is `UNRESOLVED_INTERNAL`."""
    assert _resolve("pkg/a.py", ".", internal=True, names=("name",), files=["pkg/other.py"]) == (
        UNRESOLVED_INTERNAL,
        "unresolved:pkg/name",
        True,
    )


def test_python_from_dot_import_at_the_root_uses_the_root_package_init() -> None:
    """At the repository root, the package-root candidate is the root `__init__.py`."""
    assert _resolve("a.py", ".", internal=True, names=("zzz",), files=["__init__.py"]) == (
        INTERNAL_FILE,
        "__init__.py",
        True,
    )


def test_python_from_double_dot_import_name_resolves_in_the_parent() -> None:
    """`from .. import name` looks in the parent directory."""
    assert _resolve("a/b/c.py", "..", internal=True, names=("n",), files=["a/n.py"]) == (
        INTERNAL_FILE,
        "a/n.py",
        True,
    )


def test_python_stub_files_are_python_sources() -> None:
    """A `.pyi` source resolves like a `.py` source."""
    assert _resolve("pkg/a.pyi", ".b", internal=True, files=["pkg/b.pyi"]) == (
        INTERNAL_FILE,
        "pkg/b.pyi",
        True,
    )


def test_python_matching_is_case_sensitive() -> None:
    """`pkg.util` does not match `Pkg/Util.py`."""
    assert _resolve("main.py", "pkg.util", internal=False, files=["Pkg/Util.py"]) == (
        EXTERNAL_MODULE,
        "external:pkg.util",
        False,
    )


# ------------------------------------------------------------------------------ TypeScript


def test_typescript_relative_specifiers_resolve_to_files() -> None:
    """`./x` and `../x` resolve relative to the source's directory."""
    assert _resolve("web/app/main.ts", "./util", internal=True, files=["web/app/util.ts"]) == (
        INTERNAL_FILE,
        "web/app/util.ts",
        True,
    )
    assert _resolve("web/app/main.ts", "../lib/api", internal=True, files=["web/lib/api.tsx"]) == (
        INTERNAL_FILE,
        "web/lib/api.tsx",
        True,
    )


@pytest.mark.parametrize(
    ("present", "expected"),
    [
        (["w/x", "w/x.ts", "w/x.tsx", "w/x/index.ts", "w/x/index.tsx"], "w/x"),
        (["w/x.ts", "w/x.tsx", "w/x/index.ts", "w/x/index.tsx"], "w/x.ts"),
        (["w/x.tsx", "w/x/index.ts", "w/x/index.tsx"], "w/x.tsx"),
        (["w/x/index.ts", "w/x/index.tsx"], "w/x/index.ts"),
        (["w/x/index.tsx"], "w/x/index.tsx"),
    ],
)
def test_typescript_extension_priority(present: list[str], expected: str) -> None:
    """Candidates are exact path, `.ts`, `.tsx`, `index.ts`, `index.tsx`, in that order."""
    kind, identifier, is_internal = _resolve(
        "w/main.ts", "./x", internal=True, files=[*present, "w/main.ts"]
    )
    assert (kind, identifier, is_internal) == (INTERNAL_FILE, expected, True)


def test_typescript_explicit_extension_matches_the_exact_path() -> None:
    """`./util.ts` matches the exact file."""
    assert _resolve("w/main.tsx", "./util.ts", internal=True, files=["w/util.ts"]) == (
        INTERNAL_FILE,
        "w/util.ts",
        True,
    )


def test_typescript_dot_and_dotdot_resolve_to_directory_index() -> None:
    """`.` and `..` resolve to the directory's `index.ts`/`index.tsx`."""
    assert _resolve("w/main.ts", ".", internal=True, files=["w/index.ts"]) == (
        INTERNAL_FILE,
        "w/index.ts",
        True,
    )
    assert _resolve("w/sub/main.ts", "..", internal=True, files=["w/index.tsx"]) == (
        INTERNAL_FILE,
        "w/index.tsx",
        True,
    )


def test_typescript_unresolved_relative_specifier() -> None:
    """A relative specifier matching no file is `UNRESOLVED_INTERNAL` with the would-be path."""
    assert _resolve("web/app/main.ts", "./missing", internal=True, files=["web/app/other.ts"]) == (
        UNRESOLVED_INTERNAL,
        "unresolved:web/app/missing",
        True,
    )


def test_typescript_root_escape_is_unresolved_and_source_qualified() -> None:
    """A relative specifier climbing above the root is `UNRESOLVED_INTERNAL`, non-fatal."""
    assert _resolve("main.ts", "../x", internal=True) == (
        UNRESOLVED_INTERNAL,
        "unresolved:main.ts#../x",
        True,
    )


def test_typescript_slash_rooted_specifier_is_unresolved_with_the_raw_payload() -> None:
    """`/x` has undefined root semantics: `unresolved:` + the raw `/x`, even if `x.ts` exists."""
    assert _resolve("web/main.ts", "/x", internal=True, files=["x.ts", "web/x.ts"]) == (
        UNRESOLVED_INTERNAL,
        "unresolved:/x",
        True,
    )


@pytest.mark.parametrize("specifier", ["@/components/Button", "react", "@scope/pkg", "lib/x"])
def test_typescript_alias_and_bare_specifiers_are_external(specifier: str) -> None:
    """Upstream-False specifiers stay external, even if a matching repo file exists."""
    files = ["components/Button.ts", "web/lib/x.ts", "lib/x.ts", "react.ts"]
    assert _resolve("web/main.ts", specifier, internal=False, files=files) == (
        EXTERNAL_MODULE,
        f"external:{specifier}",
        False,
    )


def test_typescript_does_not_map_js_to_ts() -> None:
    """`./x.js` does not resolve to `x.ts`."""
    assert _resolve("w/main.ts", "./x.js", internal=True, files=["w/x.ts"]) == (
        UNRESOLVED_INTERNAL,
        "unresolved:w/x.js",
        True,
    )


# ------------------------------------------------------------------------------------ Go


def test_go_relative_import_is_unresolved_with_the_would_be_directory() -> None:
    """`./x` and `../x` are never files: `unresolved:` + the normalized would-be directory."""
    assert _resolve("cmd/app/main.go", "./util", internal=True, files=["cmd/app/util.go"]) == (
        UNRESOLVED_INTERNAL,
        "unresolved:cmd/app/util",
        True,
    )
    assert _resolve("cmd/app/main.go", "../util", internal=True, files=["cmd/util/u.go"]) == (
        UNRESOLVED_INTERNAL,
        "unresolved:cmd/util",
        True,
    )


def test_go_relative_import_escaping_the_root_is_source_qualified() -> None:
    """A Go relative path above the root is source-qualified, non-fatal."""
    assert _resolve("main.go", "../x", internal=True) == (
        UNRESOLVED_INTERNAL,
        "unresolved:main.go#../x",
        True,
    )


@pytest.mark.parametrize("module", ["fmt", "example.com/proj/internal/util", "github.com/a/b"])
def test_go_module_path_imports_are_external(module: str) -> None:
    """Module-path imports (upstream False) are external, including first-party-looking ones."""
    assert _resolve("cmd/main.go", module, internal=False, files=["internal/util/u.go"]) == (
        EXTERNAL_MODULE,
        f"external:{module}",
        False,
    )


# ---------------------------------------------------------------------------------- Rust


@pytest.mark.parametrize("module", ["crate", "crate::a::b", "self::x", "super", "super::super::y"])
def test_rust_crate_self_super_are_unresolved_and_source_qualified(module: str) -> None:
    """`crate`/`self`/`super` forms are never resolved to a file."""
    files = ["src/a.rs", "src/a/b.rs", "src/x.rs", "src/y.rs"]
    assert _resolve("src/m/n.rs", module, internal=True, files=files) == (
        UNRESOLVED_INTERNAL,
        f"unresolved:src/m/n.rs#{module}",
        True,
    )


def test_rust_identical_raw_strings_from_unrelated_files_do_not_collide() -> None:
    """The same raw `super::x` from two files yields two distinct unresolved nodes."""
    graph = _build(
        _result("a/one.rs", _edge("a/one.rs", "super::x", internal=True)),
        _result("b/two.rs", _edge("b/two.rs", "super::x", internal=True)),
    )
    unresolved = [n.identifier for n in graph.nodes if n.kind is UNRESOLVED_INTERNAL]
    assert unresolved == ["unresolved:a/one.rs#super::x", "unresolved:b/two.rs#super::x"]


@pytest.mark.parametrize("module", ["std::collections", "serde", "tokio::sync", "foo::bar"])
def test_rust_bare_paths_are_external(module: str) -> None:
    """Bare/non-relative crate and module paths are external."""
    assert _resolve("src/main.rs", module, internal=False, files=["src/foo.rs"]) == (
        EXTERNAL_MODULE,
        f"external:{module}",
        False,
    )


# ---------------------------------------------------------------------------------- C++


def test_cpp_quoted_include_resolves_relative_to_the_including_file() -> None:
    """`#include "x.h"` resolves against the including file's directory."""
    assert _resolve("src/net/conn.cpp", "conn.h", internal=True, files=["src/net/conn.h"]) == (
        INTERNAL_FILE,
        "src/net/conn.h",
        True,
    )
    assert _resolve(
        "src/net/conn.cpp", "../util/log.h", internal=True, files=["src/util/log.h"]
    ) == (INTERNAL_FILE, "src/util/log.h", True)
    assert _resolve("a.cc", "sub/b.hpp", internal=True, files=["sub/b.hpp"]) == (
        INTERNAL_FILE,
        "sub/b.hpp",
        True,
    )


def test_cpp_quoted_include_does_not_search_the_repository_root() -> None:
    """A quoted include missing next to the includer is unresolved even if it exists at the root."""
    assert _resolve("src/net/conn.cpp", "config.h", internal=True, files=["config.h"]) == (
        UNRESOLVED_INTERNAL,
        "unresolved:src/net/config.h",
        True,
    )


def test_cpp_quoted_include_unresolved_when_the_file_is_absent() -> None:
    """A quoted include matching no input file is `UNRESOLVED_INTERNAL`."""
    assert _resolve("src/a.cpp", "missing.h", internal=True) == (
        UNRESOLVED_INTERNAL,
        "unresolved:src/missing.h",
        True,
    )


def test_cpp_quoted_include_escaping_the_root_is_source_qualified() -> None:
    """A quoted include climbing above the root is unresolved, source-qualified."""
    assert _resolve("a.cpp", "../x.h", internal=True) == (
        UNRESOLVED_INTERNAL,
        "unresolved:a.cpp#../x.h",
        True,
    )


def test_cpp_absolute_quoted_include_is_unresolved_and_source_qualified() -> None:
    """An absolute quoted include has no includer-relative meaning, so it is never resolved."""
    assert _resolve("src/a.cpp", "/usr/x.h", internal=True, files=["src/usr/x.h", "usr/x.h"]) == (
        UNRESOLVED_INTERNAL,
        "unresolved:src/a.cpp#/usr/x.h",
        True,
    )


def test_cpp_matching_is_case_sensitive() -> None:
    """`"Conn.h"` does not match `conn.h`."""
    assert _resolve("a.cpp", "Conn.h", internal=True, files=["conn.h"]) == (
        UNRESOLVED_INTERNAL,
        "unresolved:Conn.h",
        True,
    )


def test_cpp_angle_include_is_always_external() -> None:
    """`#include <x.h>` is external even when a same-named repository header exists."""
    files = ["config.h", "src/config.h", "src/vector"]
    for target in ("vector", "config.h"):
        assert _resolve("src/a.cpp", target, internal=False, files=files) == (
            EXTERNAL_MODULE,
            f"external:{target}",
            False,
        )


def test_cpp20_import_is_external() -> None:
    """A C++20 `import std.core;` (upstream False) is external."""
    assert _resolve("a.cpp", "std.core", internal=False, files=["std/core.h"]) == (
        EXTERNAL_MODULE,
        "external:std.core",
        False,
    )


@pytest.mark.parametrize(
    "suffix", [".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".h", ".CPP", ".H"]
)
def test_every_cpp_suffix_is_inferred_as_cpp(suffix: str) -> None:
    """Every C++ suffix in the closed table (any case) gets the C++ quoted-include rule."""
    source = f"src/a{suffix}"
    assert _resolve(source, "b.h", internal=True, files=["src/b.h"]) == (
        INTERNAL_FILE,
        "src/b.h",
        True,
    )


# ------------------------------------------------------------------- language inference


def test_language_inference_is_case_insensitive() -> None:
    """An upper-case suffix selects the same language rule."""
    assert _resolve("pkg/A.PY", ".b", internal=True, files=["pkg/b.py"]) == (
        INTERNAL_FILE,
        "pkg/b.py",
        True,
    )
    assert _resolve("w/Main.TSX", "./x", internal=True, files=["w/x.ts"]) == (
        INTERNAL_FILE,
        "w/x.ts",
        True,
    )


def test_unknown_suffix_has_no_language_rule_but_obeys_the_is_internal_rule() -> None:
    """A suffix outside the closed table: upstream-True is never external; False stays external."""
    assert _resolve("notes.txt", "x", internal=False, files=["x.py"]) == (
        EXTERNAL_MODULE,
        "external:x",
        False,
    )
    assert _resolve("notes.txt", "./x", internal=True, files=["x.py"]) == (
        UNRESOLVED_INTERNAL,
        "unresolved:notes.txt#./x",
        True,
    )


def test_language_rules_do_not_leak_between_languages() -> None:
    """A Python-looking absolute import from a Go file stays external."""
    assert _resolve("main.go", "pkg.util", internal=False, files=["pkg/util.py"]) == (
        EXTERNAL_MODULE,
        "external:pkg.util",
        False,
    )


# --------------------------------------------------------------------- is_internal semantics


@pytest.mark.parametrize(
    "source",
    ["a.py", "a.pyi", "a.ts", "a.tsx", "a.go", "a.rs", "a.cpp", "a.h", "a.unknown"],
)
@pytest.mark.parametrize("target", ["./x", "../x", "/x", ".x", "..", "crate::x", "x", "<weird>"])
def test_upstream_internal_never_becomes_external(source: str, target: str) -> None:
    """Whatever the language or target text, upstream `True` never resolves to external."""
    kind, _, is_internal = _resolve(source, target, internal=True, files=["x.py", "x.ts", "x.h"])
    assert kind in (INTERNAL_FILE, UNRESOLVED_INTERNAL)
    assert is_internal is True


@pytest.mark.parametrize("source", ["a.ts", "a.go", "a.rs", "a.cpp", "a.unknown"])
def test_only_python_may_reclassify_an_upstream_false_import(source: str) -> None:
    """Upstream `False` outside Python is always external, even if a repository file matches."""
    kind, identifier, is_internal = _resolve(
        source, "pkg.util", internal=False, files=["pkg/util.py", "pkg/util.ts", "pkg/util.h"]
    )
    assert (kind, identifier, is_internal) == (EXTERNAL_MODULE, "external:pkg.util", False)


def test_output_edge_is_internal_matches_the_target_kind_for_every_edge() -> None:
    """The graph invariant `is_internal == (target.kind != EXTERNAL_MODULE)` holds throughout."""
    graph = _build(
        _result(
            "pkg/a.py",
            _edge("pkg/a.py", "pkg.b"),
            _edge("pkg/a.py", ".b", internal=True),
            _edge("pkg/a.py", ".gone", internal=True),
            _edge("pkg/a.py", "os"),
        ),
        _result("pkg/b.py"),
    )
    assert graph.edge_count == 4
    for edge in graph.edges:
        assert edge.is_internal is (graph.get_node(edge.target).kind is not EXTERNAL_MODULE)


# --------------------------------------------------------------- identifiers / verbatim paths


def test_internal_file_identifier_and_edge_source_are_verbatim_input_paths() -> None:
    """A backslash input path is never rewritten, yet is matched through its normalized key."""
    graph = _build(
        _result("pkg\\a.py", _edge("pkg\\a.py", ".b", internal=True)),
        _result("pkg\\b.py"),
        _result("main.py", _edge("main.py", "pkg.a")),
    )
    assert [n.identifier for n in graph.nodes] == ["main.py", "pkg\\a.py", "pkg\\b.py"]
    assert [(e.source, e.target) for e in graph.edges] == [
        ("main.py", "pkg\\a.py"),
        ("pkg\\a.py", "pkg\\b.py"),
    ]


def test_unresolved_payload_uses_the_normalized_forward_slash_path() -> None:
    """Unresolved payloads are built from normalized keys; source qualification likewise."""
    assert _resolve("web\\app\\main.ts", "./missing", internal=True) == (
        UNRESOLVED_INTERNAL,
        "unresolved:web/app/missing",
        True,
    )
    assert _resolve("web\\main.ts", "../../x", internal=True) == (
        UNRESOLVED_INTERNAL,
        "unresolved:web/main.ts#../../x",
        True,
    )


def test_external_identifier_keeps_the_raw_target_text() -> None:
    """Raw external module text is never normalized."""
    assert _resolve("a.ts", "..//weird\\Text", internal=False) == (
        EXTERNAL_MODULE,
        "external:..//weird\\Text",
        False,
    )


def test_input_paths_are_normalized_only_for_matching() -> None:
    """Duplicate separators, `.` segments and case in an input path survive in its identifier."""
    graph = _build(
        _result("./a//b.py", _edge("./a//b.py", "c")),
        _result("c.py"),
    )
    assert "./a//b.py" in {node.identifier for node in graph.nodes}
    assert [(e.source, e.target) for e in graph.edges] == [("./a//b.py", "c.py")]


# --------------------------------------------------------------- sharing / duplicate edges


def test_one_node_is_shared_by_many_edges() -> None:
    """Two files importing the same external module, and the same internal file, share nodes."""
    graph = _build(
        _result("a.py", _edge("a.py", "numpy"), _edge("a.py", "shared", line=2)),
        _result("b.py", _edge("b.py", "numpy"), _edge("b.py", "shared")),
        _result("shared.py"),
    )
    assert [n.identifier for n in graph.nodes].count("external:numpy") == 1
    assert [n.identifier for n in graph.nodes].count("shared.py") == 1
    assert sum(1 for e in graph.edges if e.target == "external:numpy") == 2
    assert sum(1 for e in graph.edges if e.target == "shared.py") == 2


def test_unresolved_target_nodes_are_shared_too() -> None:
    """The same unresolved would-be target from two files is one shared node."""
    graph = _build(
        _result("w/a.ts", _edge("w/a.ts", "./gone", internal=True)),
        _result("w/b.ts", _edge("w/b.ts", "./gone", internal=True)),
    )
    assert [n.identifier for n in graph.nodes if n.kind is UNRESOLVED_INTERNAL] == [
        "unresolved:w/gone"
    ]


def test_identical_duplicate_edges_are_all_preserved() -> None:
    """Three identical upstream edges give three identical output edges."""
    edge = _edge("a.py", "os", names=("path",), alias="p", line=3)
    graph = _build(_result("a.py", edge, edge, edge))
    assert graph.edge_count == 3
    assert len(set(graph.edges)) == 1


def test_duplicate_source_target_line_edges_are_preserved() -> None:
    """Edges sharing `(source, target, line_number)` are all kept."""
    graph = _build(
        _result("a.py", _edge("a.py", "os", line=2), _edge("a.py", "os", line=2, names=("x",)))
    )
    assert [(e.source, e.target, e.line_number) for e in graph.edges] == [
        ("a.py", "external:os", 2),
        ("a.py", "external:os", 2),
    ]


def test_same_line_different_imported_names_are_separate_edges() -> None:
    """`from x import a, b` on one line stays two edges, one per name."""
    graph = _build(
        _result(
            "a.py",
            _edge("a.py", "x", names=("b",), line=7),
            _edge("a.py", "x", names=("a",), line=7),
        )
    )
    assert [e.imported_names for e in graph.edges] == [("a",), ("b",)]


def test_same_line_different_aliases_are_separate_edges() -> None:
    """The same name imported under two aliases on one line stays two edges."""
    graph = _build(
        _result(
            "a.py",
            _edge("a.py", "x", names=("a",), alias="q", line=7),
            _edge("a.py", "x", names=("a",), alias=None, line=7),
            _edge("a.py", "x", names=("a",), alias="p", line=7),
        )
    )
    assert [e.alias for e in graph.edges] == [None, "p", "q"]


def test_edge_fields_are_carried_onto_the_output_edge() -> None:
    """Imported names, alias and line number pass through unchanged."""
    graph = _build(_result("a.py", _edge("a.py", "os", names=("path", "sep"), alias="o", line=12)))
    assert graph.edges == (
        DependencyRelationEdge(
            source="a.py",
            target="external:os",
            is_internal=False,
            imported_names=("path", "sep"),
            alias="o",
            line_number=12,
        ),
    )


# ------------------------------------------------------------------------- determinism


def _mixed_results() -> tuple[ImportExtractionResult, ...]:
    """A small multi-language input exercising every outcome kind."""
    return (
        _result(
            "pkg/a.py",
            _edge("pkg/a.py", "pkg.b", line=1),
            _edge("pkg/a.py", ".b", internal=True, line=2),
            _edge("pkg/a.py", ".", internal=True, names=("zed",), line=3),
            _edge("pkg/a.py", "os", line=4),
        ),
        _result("pkg/b.py"),
        _result("w/m.ts", _edge("w/m.ts", "./x", internal=True), _edge("w/m.ts", "react")),
        _result("w/x.tsx"),
        _result("c/n.cpp", _edge("c/n.cpp", "n.h", internal=True), _edge("c/n.cpp", "vector")),
        _result("c/n.h"),
    )


def test_repeat_builds_are_equal() -> None:
    """Building the same input twice gives equal graphs."""
    results = _mixed_results()
    builder = StructuralDependencyGraphBuilder()
    assert builder.build(results) == builder.build(results)


def test_input_permutations_give_the_same_graph() -> None:
    """Every ordering of the input results gives an identical graph."""
    results = _mixed_results()
    expected = StructuralDependencyGraphBuilder().build(results)
    for permutation in itertools.permutations(results[:4]):
        reordered = (*permutation, *results[4:])
        assert StructuralDependencyGraphBuilder().build(reordered) == expected
    assert StructuralDependencyGraphBuilder().build(tuple(reversed(results))) == expected


def test_edge_order_within_a_result_does_not_change_the_graph() -> None:
    """Reversing a file's own edge order gives the same graph."""
    edges = (
        _edge("a.py", "x", names=("b",), line=2),
        _edge("a.py", "x", names=("a",), line=2),
        _edge("a.py", "y", line=1),
    )
    assert _build(_result("a.py", *edges)) == _build(_result("a.py", *reversed(edges)))


def test_result_graph_is_valid_per_the_port_validator() -> None:
    """Rebuilding the graph from its own parts passes `DependencyGraph` validation."""
    graph = _build(*_mixed_results())
    assert DependencyGraph(nodes=graph.nodes, edges=graph.edges) == graph
    kinds = {node.kind for node in graph.nodes}
    assert kinds == {INTERNAL_FILE, EXTERNAL_MODULE, UNRESOLVED_INTERNAL}


# ------------------------------------------------------------------ no-source-parsing boundary


def test_builder_module_imports_nothing_that_could_read_or_parse_source() -> None:
    """The module imports no I/O, parsing, AST, parser, or dispatch machinery."""
    source = Path(structural_module.__file__).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
    forbidden = {"os", "io", "pathlib", "ast", "subprocess", "shutil", "tokenize", "importlib"}
    assert not imported & forbidden
    assert not any(
        name.startswith(("src.parsers", "src.bootstrap", "src.cli")) for name in imported
    )
