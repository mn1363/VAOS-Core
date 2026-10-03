"""Structural dependency graph builder: the first concrete `DependencyGraphBuilder`.

`StructuralDependencyGraphBuilder` assembles many files' already-extracted
`extractors.imports.base.ImportExtractionResult`s into one repository-wide `DependencyGraph`,
resolving each import's `target_module` against nothing but the `relative_path`s present in its own
input, following the frozen Dependency Graph Resolution Contract v1. It is pure string work: it
performs no I/O, reads no source file, parses nothing, inspects no AST, consults no `go.mod`,
`Cargo.toml`, `tsconfig.json`, or compilation database, and detects no cycles.

**Language inference.** `DependencyEdge` carries no language field, so the language of a source
file is inferred only from its `relative_path` suffix, using one fixed, closed, case-insensitive
table (`_LANGUAGE_BY_SUFFIX`) that mirrors the five existing parsers' extension tuples. This is
deterministic classification, not parser dispatch: no parser is called and nothing is registered.
A source whose suffix is in no row of the table has no language-specific rule; see
`_resolve_without_language`.

**Resolution outcomes** (the upstream `DependencyEdge.is_internal` flag is an *internal candidate*
signal, never copied blindly onto the output edge):

- Upstream `True` resolves to `INTERNAL_FILE` or `UNRESOLVED_INTERNAL`, and never to
  `EXTERNAL_MODULE`.
- Upstream `False` resolves to `EXTERNAL_MODULE`, except a Python absolute import whose module
  path matches an input file by the frozen candidate order, which resolves to `INTERNAL_FILE`.
- Every output edge's `is_internal` is `target.kind is not EXTERNAL_MODULE`, exactly as the
  `DependencyGraph` validator requires.

**Node identifiers.** `INTERNAL_FILE` is the verbatim input `relative_path`; `EXTERNAL_MODULE` is
`external:` + the raw `target_module`; `UNRESOLVED_INTERNAL` is `unresolved:` + a payload (see
`_unresolved_path` and `_unresolved_qualified`). Path normalization is used only to build match
keys and unresolved payloads; it never rewrites an `INTERNAL_FILE` identifier or raw external text.
"""

import re
from collections.abc import Sequence
from enum import StrEnum, auto

from src.core.exceptions import ValidationError
from src.extractors.imports.base import DependencyEdge, ImportExtractionResult
from src.graph.dependency.base import (
    DependencyGraph,
    DependencyGraphBuilder,
    DependencyNode,
    DependencyNodeKind,
    DependencyRelationEdge,
    require_successful_extractions,
)

_EXTERNAL_PREFIX = "external:"
_UNRESOLVED_PREFIX = "unresolved:"
_RESERVED_PREFIXES = (_EXTERNAL_PREFIX, _UNRESOLVED_PREFIX)
_DRIVE_PREFIX_PATTERN = re.compile(r"^[A-Za-z]:")


class _Language(StrEnum):
    """The five languages a source file's suffix may identify."""

    PYTHON = auto()
    TYPESCRIPT = auto()
    GO = auto()
    RUST = auto()
    CPP = auto()


_LANGUAGE_BY_SUFFIX: tuple[tuple[str, _Language], ...] = (
    (".py", _Language.PYTHON),
    (".pyi", _Language.PYTHON),
    (".ts", _Language.TYPESCRIPT),
    (".tsx", _Language.TYPESCRIPT),
    (".go", _Language.GO),
    (".rs", _Language.RUST),
    (".cpp", _Language.CPP),
    (".cc", _Language.CPP),
    (".cxx", _Language.CPP),
    (".hpp", _Language.CPP),
    (".hh", _Language.CPP),
    (".hxx", _Language.CPP),
    (".h", _Language.CPP),
)
"""The frozen, closed suffix-to-language table. No suffix here is a suffix of another."""

_PYTHON_MODULE_CANDIDATES = ("{p}/__init__.py", "{p}.py", "{p}/__init__.pyi", "{p}.pyi")
_PYTHON_PACKAGE_ROOT_CANDIDATES = ("{p}/__init__.py", "{p}/__init__.pyi")
_TYPESCRIPT_CANDIDATES = ("{p}", "{p}.ts", "{p}.tsx", "{p}/index.ts", "{p}/index.tsx")


class StructuralDependencyGraphBuilder(DependencyGraphBuilder):
    """Assembles many files' import edges into one file-level `DependencyGraph`.

    Stateless and dependency-free: no `__init__` override, and a single instance may be reused
    across any number of `build` calls. Deterministic: the result does not depend on the order of
    `extraction_results`.
    """

    def build(self, extraction_results: Sequence[ImportExtractionResult]) -> DependencyGraph:
        """Assemble a `DependencyGraph` from many files' import statements.

        Args:
            extraction_results: The outcomes of extracting import statements for every file
                under consideration, as produced by `src.extractors.imports`. Every entry must
                be successful.

        Returns:
            An empty `DependencyGraph` for empty input. Otherwise a graph with one
            `INTERNAL_FILE` node per input file (even one with zero edges), identified by its
            verbatim `relative_path`, plus one shared `EXTERNAL_MODULE`/`UNRESOLVED_INTERNAL`
            node per distinct target identifier, sorted by `identifier`. `edges` holds exactly
            one `DependencyRelationEdge` per input `DependencyEdge` -- nothing is deduplicated --
            sorted by `(source, target, line_number, imported_names, alias is not None,
            alias or "")`.

        Raises:
            ValidationError: If any entry is itself a failed extraction; if any entry's
                `relative_path` is blank, absolute or drive-prefixed, escapes the repository root,
                or begins with the reserved `external:`/`unresolved:` prefix; if two entries'
                `relative_path`s are equal after normalization; or if any edge's `target_module`
                is blank.
        """
        require_successful_extractions(extraction_results)

        files_by_key, source_keys = _index_input_files(extraction_results)
        nodes: dict[str, DependencyNode] = {
            path: DependencyNode(identifier=path, kind=DependencyNodeKind.INTERNAL_FILE)
            for path in files_by_key.values()
        }
        edges: list[DependencyRelationEdge] = []
        file_keys = frozenset(files_by_key)

        for extraction_result, source_key in zip(extraction_results, source_keys, strict=True):
            language = _language_of(extraction_result.relative_path)
            for edge in extraction_result.edges:
                kind, identifier = _resolve(edge, source_key, language, file_keys)
                if kind is DependencyNodeKind.INTERNAL_FILE:
                    identifier = files_by_key[identifier]
                elif identifier not in nodes:
                    nodes[identifier] = DependencyNode(identifier=identifier, kind=kind)
                edges.append(
                    DependencyRelationEdge(
                        source=extraction_result.relative_path,
                        target=identifier,
                        is_internal=kind is not DependencyNodeKind.EXTERNAL_MODULE,
                        imported_names=edge.imported_names,
                        alias=edge.alias,
                        line_number=edge.line_number,
                    )
                )

        return DependencyGraph(
            nodes=tuple(sorted(nodes.values(), key=lambda node: node.identifier)),
            edges=tuple(sorted(edges, key=_edge_sort_key)),
        )


_EdgeSortKey = tuple[str, str, int, tuple[str, ...], bool, str]


def _edge_sort_key(edge: DependencyRelationEdge) -> _EdgeSortKey:
    """Return the frozen total-order key for an output edge."""
    return (
        edge.source,
        edge.target,
        edge.line_number,
        edge.imported_names,
        edge.alias is not None,
        edge.alias or "",
    )


def _index_input_files(
    extraction_results: Sequence[ImportExtractionResult],
) -> tuple[dict[str, str], list[str]]:
    """Validate every input `relative_path` and map its normalized match key to the verbatim path.

    Args:
        extraction_results: Every (already successful) input result.

    Returns:
        A mapping from each input file's normalized match key to its verbatim `relative_path`,
        and each input file's key in input order.

    Raises:
        ValidationError: If a path is blank, absolute, drive-prefixed, root-escaping, or uses a
            reserved prefix, or if two paths normalize to the same key.
    """
    files_by_key: dict[str, str] = {}
    keys: list[str] = []
    for extraction_result in extraction_results:
        path = extraction_result.relative_path
        if not path.strip():
            raise ValidationError("DependencyGraphBuilder: relative_path must not be blank")
        if path.startswith(_RESERVED_PREFIXES):
            raise ValidationError(
                "DependencyGraphBuilder: relative_path must not begin with a reserved prefix",
                details={"relative_path": path},
            )
        slashed = path.replace("\\", "/")
        if slashed.startswith("/") or _DRIVE_PREFIX_PATTERN.match(slashed):
            raise ValidationError(
                "DependencyGraphBuilder: relative_path must not be absolute or drive-prefixed",
                details={"relative_path": path},
            )
        key = _normalize(path)
        if not key:
            raise ValidationError(
                "DependencyGraphBuilder: relative_path must name a file inside the repository",
                details={"relative_path": path},
            )
        if key in files_by_key:
            raise ValidationError(
                "DependencyGraphBuilder: duplicate relative_path after normalization",
                details={"relative_path": path, "other_relative_path": files_by_key[key]},
            )
        files_by_key[key] = path
        keys.append(key)
    return files_by_key, keys


def _normalize(path: str) -> str | None:
    """Lexically normalize `path` into a `/`-separated match key.

    Converts `\\` to `/`, collapses duplicate separators, strips trailing separators, drops `.`
    segments, and resolves `..` segments. Case is preserved. No filesystem is consulted.

    Args:
        path: The raw path or path-like text to normalize.

    Returns:
        The normalized key (the empty string denotes the repository root), or None if a `..`
        segment would climb above the repository root.
    """
    segments: list[str] = []
    for segment in path.replace("\\", "/").split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if not segments:
                return None
            segments.pop()
        else:
            segments.append(segment)
    return "/".join(segments)


def _directory_of(source_key: str) -> str:
    """Return the directory part of a normalized source key (`""` for a root-level file)."""
    return source_key.rpartition("/")[0]


def _join(base: str, relative: str) -> str | None:
    """Normalize `relative` interpreted from the normalized directory `base`.

    Returns:
        The normalized key, or None if the result would climb above the repository root.
    """
    return _normalize(f"{base}/{relative}" if base else relative)


def _language_of(relative_path: str) -> _Language | None:
    """Infer a source file's language from its suffix alone, case-insensitively."""
    lowered = relative_path.lower()
    for suffix, language in _LANGUAGE_BY_SUFFIX:
        if lowered.endswith(suffix):
            return language
    return None


def _external(edge: DependencyEdge) -> tuple[DependencyNodeKind, str]:
    """Return the `EXTERNAL_MODULE` outcome for `edge`: `external:` + the raw target."""
    return DependencyNodeKind.EXTERNAL_MODULE, _EXTERNAL_PREFIX + edge.target_module


def _unresolved_path(would_be_target: str) -> tuple[DependencyNodeKind, str]:
    """Return the `UNRESOLVED_INTERNAL` outcome for a normalized path-like target."""
    return DependencyNodeKind.UNRESOLVED_INTERNAL, _UNRESOLVED_PREFIX + would_be_target


def _unresolved_qualified(source_key: str, edge: DependencyEdge) -> tuple[DependencyNodeKind, str]:
    """Return the source-qualified `UNRESOLVED_INTERNAL` outcome for `edge`.

    Used for Rust internal forms, root-escaping targets, and any other internal form with no
    normalizable would-be path: `unresolved:` + normalized source path + `#` + raw target.
    """
    return (
        DependencyNodeKind.UNRESOLVED_INTERNAL,
        f"{_UNRESOLVED_PREFIX}{source_key}#{edge.target_module}",
    )


def _resolve(
    edge: DependencyEdge,
    source_key: str,
    language: _Language | None,
    file_keys: frozenset[str],
) -> tuple[DependencyNodeKind, str]:
    """Resolve one edge to a `(kind, identifier)` pair.

    For `INTERNAL_FILE` the returned identifier is the matched file's *normalized key*; the
    caller maps it back to the verbatim input path.

    Raises:
        ValidationError: If `edge.target_module` is blank. The `DependencyNode` blank-identifier
            check cannot catch this itself, because every non-file identifier carries a prefix.
    """
    if not edge.target_module.strip():
        raise ValidationError(
            "DependencyGraphBuilder: target_module must not be empty",
            details={"source": source_key},
        )
    match language:
        case _Language.PYTHON:
            return _resolve_python(edge, source_key, file_keys)
        case _Language.TYPESCRIPT:
            return _resolve_typescript(edge, source_key, file_keys)
        case _Language.GO:
            return _resolve_go(edge, source_key)
        case _Language.RUST:
            return _resolve_rust(edge, source_key)
        case _Language.CPP:
            return _resolve_cpp(edge, source_key, file_keys)
        case None:
            return _resolve_without_language(edge, source_key)


def _resolve_without_language(
    edge: DependencyEdge, source_key: str
) -> tuple[DependencyNodeKind, str]:
    """Resolve an edge from a source whose suffix is in no row of the language table.

    The frozen contract defines no language rule here, so only the frozen `is_internal` rule
    applies: an upstream-internal edge can never become external, and an upstream-external edge
    stays external.
    """
    if edge.is_internal:
        return _unresolved_qualified(source_key, edge)
    return _external(edge)


def _first_match(templates: Sequence[str], path: str, file_keys: frozenset[str]) -> str | None:
    """Return the first candidate key, in `templates` order, present in `file_keys`, if any.

    Each template's `{p}` is replaced by `path`; a candidate that would start with `/` because
    `path` is the repository root (`""`) has that leading `/` removed.
    """
    for template in templates:
        candidate = template.format(p=path).lstrip("/")
        if candidate in file_keys:
            return candidate
    return None


def _is_path_component(name: str) -> bool:
    """Report whether `name` is usable as a single path component (non-empty, no separators)."""
    return bool(name) and not any(char in name for char in "/\\.")


def _python_module_path(dotted: str) -> str | None:
    """Map a dotted module name to its `/`-separated path, or None if it is not well-formed."""
    parts = dotted.split(".")
    if not all(_is_path_component(part) for part in parts):
        return None
    return "/".join(parts)


def _resolve_python(
    edge: DependencyEdge, source_key: str, file_keys: frozenset[str]
) -> tuple[DependencyNodeKind, str]:
    """Resolve a Python edge: absolute (repository root) or relative (leading dots)."""
    module = edge.target_module
    if not edge.is_internal:
        module_path = _python_module_path(module)
        if module_path is not None:
            matched = _first_match(_PYTHON_MODULE_CANDIDATES, module_path, file_keys)
            if matched is not None:
                return DependencyNodeKind.INTERNAL_FILE, matched
        return _external(edge)

    dots = len(module) - len(module.lstrip("."))
    if dots == 0:
        return _unresolved_qualified(source_key, edge)
    base = _directory_of(source_key)
    for _ in range(dots - 1):
        if not base:
            return _unresolved_qualified(source_key, edge)
        base = _directory_of(base)
    remainder = module[dots:]

    if remainder:
        module_path = _python_module_path(remainder)
        if module_path is None:
            return _unresolved_qualified(source_key, edge)
        target = _join(base, module_path)
        if target is None:
            return _unresolved_qualified(source_key, edge)
        matched = _first_match(_PYTHON_MODULE_CANDIDATES, target, file_keys)
        if matched is not None:
            return DependencyNodeKind.INTERNAL_FILE, matched
        return _unresolved_path(target)

    # `from . import name` (and deeper): submodule `base/name` first, then `base` as a package.
    would_be = base
    if len(edge.imported_names) == 1 and _is_path_component(edge.imported_names[0]):
        submodule = _join(base, edge.imported_names[0])
        if submodule is not None:
            would_be = submodule
            matched = _first_match(_PYTHON_MODULE_CANDIDATES, submodule, file_keys)
            if matched is not None:
                return DependencyNodeKind.INTERNAL_FILE, matched
    matched = _first_match(_PYTHON_PACKAGE_ROOT_CANDIDATES, base, file_keys)
    if matched is not None:
        return DependencyNodeKind.INTERNAL_FILE, matched
    return _unresolved_path(would_be)


def _is_relative_path_specifier(specifier: str) -> bool:
    """Report whether `specifier` is a `.`/`..`-rooted relative path (`.`, `..`, `./x`, `../x`)."""
    return specifier in (".", "..") or specifier.startswith(("./", "../"))


def _resolve_typescript(
    edge: DependencyEdge, source_key: str, file_keys: frozenset[str]
) -> tuple[DependencyNodeKind, str]:
    """Resolve a TypeScript edge: `./x`/`../x` to a file, `/x` always unresolved."""
    if not edge.is_internal:
        return _external(edge)
    specifier = edge.target_module
    if specifier.startswith("/"):
        return _unresolved_path(specifier)
    if not _is_relative_path_specifier(specifier):
        return _unresolved_qualified(source_key, edge)
    target = _join(_directory_of(source_key), specifier)
    if target is None:
        return _unresolved_qualified(source_key, edge)
    matched = _first_match(_TYPESCRIPT_CANDIDATES, target, file_keys)
    if matched is not None:
        return DependencyNodeKind.INTERNAL_FILE, matched
    return _unresolved_path(target)


def _resolve_go(edge: DependencyEdge, source_key: str) -> tuple[DependencyNodeKind, str]:
    """Resolve a Go edge: never to a file. Relative paths are unresolved, module paths external."""
    if not edge.is_internal:
        return _external(edge)
    specifier = edge.target_module
    if not _is_relative_path_specifier(specifier):
        return _unresolved_qualified(source_key, edge)
    would_be_directory = _join(_directory_of(source_key), specifier)
    if would_be_directory is None:
        return _unresolved_qualified(source_key, edge)
    return _unresolved_path(would_be_directory)


def _resolve_rust(edge: DependencyEdge, source_key: str) -> tuple[DependencyNodeKind, str]:
    """Resolve a Rust edge: never to a file. `crate`/`self`/`super` forms are unresolved."""
    if edge.is_internal:
        return _unresolved_qualified(source_key, edge)
    return _external(edge)


def _resolve_cpp(
    edge: DependencyEdge, source_key: str, file_keys: frozenset[str]
) -> tuple[DependencyNodeKind, str]:
    """Resolve a C++ edge: a quoted include relative to the includer; angle/`import` external."""
    if not edge.is_internal:
        return _external(edge)
    include = edge.target_module
    slashed = include.replace("\\", "/")
    if slashed.startswith("/") or _DRIVE_PREFIX_PATTERN.match(slashed):
        return _unresolved_qualified(source_key, edge)
    target = _join(_directory_of(source_key), include)
    if target is None:
        return _unresolved_qualified(source_key, edge)
    if target in file_keys:
        return DependencyNodeKind.INTERNAL_FILE, target
    return _unresolved_path(target)
