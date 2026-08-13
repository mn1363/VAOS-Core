"""Graph layer: converts validated, already-produced analytical/extracted relationships into
graph representations.

`graph` answers "what does the *shape* of many files' already-extracted and already-analyzed
relationships look like, assembled into one connected structure a later phase can query
directly?" -- module/package containment trees, file-to-file dependency graphs, function/method
call graphs (where such relationships are available), and a semantic knowledge graph linking
repository entities to the capabilities, patterns, and other domain concepts recognized within
them. It does not parse source code, collect repositories, extract raw structures, analyze or
score a single file's own content, select foundations, implement storage, or perform vector
search -- those are `parsers`, `collectors`, `extractors`, `analyzers` (already built) or
`foundation`, `storage`, `vector` (later, not-yet-built phases') concerns.

Each of its four subpackages -- `architecture`, `callgraph`, `dependency`, `knowledge` -- defines
exactly one graph-construction contract in its own `base.py`: a frozen, slotted set of node and
edge DTOs describing that concern's representation, an abstract `...GraphBuilder` Port with a
single `build(...)` method, and (where the concern has one) a small helper validating that every
per-file result fed into a build is itself successful -- following the same `require_successful_
extraction`-per-item pattern every one of `extractors.*.base`'s and `analyzers.*.base`'s own
validators already established, applied here across a whole sequence at once rather than to a
single result.

Every graph DTO here is deterministic (nodes and edges are validated as sorted and free of
duplicates at construction time, exactly like `analyzers.dependency.base.DependencyProfile.
external_targets`) and serializable (each graph exposes its own `to_mapping()`, returning a plain,
JSON-safe nested structure). No graph here performs I/O, mutates its inputs, or re-derives
structure from raw source -- each `build` implementation is expected to operate on already-
produced, in-memory `...ExtractionResult` sequences from `src.extractors` (the same per-file DTOs
`src.analyzers` itself consumes), matching every upstream Port's own pure, synchronous shape.

Each module here is self-contained and imported directly by its full path (e.g. `from
src.graph.dependency.base import DependencyGraphBuilder`); this package intentionally does not
re-export a combined surface from `__init__.py`. Unlike `extractors` and `analyzers`, sibling
subpackages *may* import from one another here (`knowledge/base.py` imports `PackageNode` from
`architecture/base.py` to represent a file's package membership) -- a deliberate, narrow
loosening of the strict sibling-isolation every prior phase observed, since a semantic knowledge
graph naturally needs to reference the same package concept `architecture/base.py` already
defines rather than redefining it.
"""
