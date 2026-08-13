# VAOS Phase 8 — Graph Layer Summary

**Scope:** `src/graph/__init__.py`, plus one `base.py` per concern —
`architecture/`, `callgraph/`, `dependency/`, `knowledge/` — exactly the
four-subpackage structure specified for this phase.
**`src/core`, `src/domain`, `src/repository`, `src/collectors`,
`src/parsers`, `src/extractors`, and `src/analyzers` were not modified.**
`pyproject.toml` was not modified — no new dependency was needed this
phase.
**Generated:** 2026-08-11

## A genuine contract gap, reported per this phase's own STOP condition

Before writing any code, every frozen `extractors.*`/`analyzers.*`
contract was inspected and the whole `src/` tree was grepped for any
existing caller/callee, call-site, or "invokes" relationship. **None
exists.** `extractors.symbols` records that a function or method *is
declared* (`ExtractedSymbol`); nothing upstream — not `extractors.ast`,
not any analyzer — records what it *calls*.

This is exactly the situation this phase's own instructions anticipate
with "Represent function/method call relationships **when available**"
(the only one of the four graphs qualified that way). Rather than
guessing a resolution algorithm or silently shipping an always-empty
contract, `callgraph/base.py`:

- builds `CallableNode`s from genuinely available `SymbolExtractionResult`
  data (`FUNCTION`/`METHOD` symbols only — see `is_callable_symbol_kind`);
- accepts call relationships only via an explicit, externally-supplied
  `call_edges: Sequence[CallEdge] = ()` parameter on
  `CallGraphBuilder.build`, since there is currently nothing upstream a
  concrete implementation could derive them from;
- documents this gap prominently in the module's own docstring, so a
  future phase supplying resolved call sites (a corrected/extended
  `extractors.symbols`, or a new concern entirely) plugs directly into
  the existing parameter without any change to this contract.

No other contract gap was found. `architecture/base.py` and
`dependency/base.py` are both backed by real, complete upstream data
(`PackageUnit`, `DependencyEdge`) — see "What this layer does" below.

## What this layer does

`graph` answers one question: *what does the shape of many files'
already-extracted and already-analyzed relationships look like,
assembled into one connected structure a later phase can query
directly?* Each of the four `base.py` modules is fully self-contained
and defines: a small set of frozen, slotted node/edge DTOs; a top-level
`...Graph` DTO validated in `__post_init__` for determinism (nodes and
edges sorted, free of duplicates) and internal referential consistency;
`get_node`/lookup helpers built on `core.exceptions.NotFoundError`; a
`to_mapping()` method rendering the graph as a plain, JSON-safe nested
structure; an abstract `...GraphBuilder` Port with one `build(...)`
method; and a `require_successful_extractions`-shaped validator.

- **`architecture/base.py`** — `ArchitectureGraphBuilder`
  (`build(extraction_results: Sequence[ArchitectureExtractionResult]) ->
  ArchitectureGraph`), assembling many files' `PackageUnit`s into a
  connected `PackageNode`/`PackageContainmentEdge` containment tree —
  exactly the cross-file assembly step both `extractors.architecture.
  base` and `analyzers.architecture.base` explicitly name as "a `graph`
  concern" in their own docstrings. Built from the extractor-level DTO,
  not `analyzers.architecture.base.ArchitectureAssessment`, because the
  assessment already reduces `declared_modules` to a bare count and adds
  no structural detail a tree needs beyond what `PackageUnit` already
  has. Ancestor packages are synthesized for every prefix of every
  observed `package_path` (`ancestor_package_paths`), so the tree is
  always connected back to the repository root even when no file
  belongs to some intermediate package directly.
- **`dependency/base.py`** — `DependencyGraphBuilder`
  (`build(extraction_results: Sequence[ImportExtractionResult]) ->
  DependencyGraph`), assembling many files' `DependencyEdge`s into a
  `DependencyNode`/`DependencyRelationEdge` graph. Built from the
  extractor-level DTO, not `analyzers.dependency.base.DependencyProfile`,
  because a profile already collapses every edge to aggregate counts and
  drops internal edges entirely. Resolving an internal edge's
  `target_module` against the other files in the same build call is this
  Port's own job — `analyzers.dependency.base`'s docstring names
  "resolving imports to actual files" as explicitly a graph concern —
  and the three-way `DependencyNodeKind` (`INTERNAL_FILE`,
  `EXTERNAL_MODULE`, `UNRESOLVED_INTERNAL`) represents the outcome
  honestly rather than guessing a language-specific resolution heuristic
  no frozen contract specifies.
- **`callgraph/base.py`** — `CallGraphBuilder`
  (`build(extraction_results: Sequence[SymbolExtractionResult],
  call_edges: Sequence[CallEdge] = ()) -> CallGraph`) — see the reported
  gap above.
- **`knowledge/base.py`** — `KnowledgeGraphBuilder`
  (`build(*, symbol_results=..., pattern_results=..., interface_results=...,
  foundation_results=..., architecture_graph: ArchitectureGraph | None =
  None) -> KnowledgeGraph`), the widest-scoped of the four: it draws on
  every extractor whose output names a reusable domain concept —
  `extractors.symbols` (`SYMBOL`), `extractors.patterns` (`PATTERN`),
  `extractors.interfaces` (`INTERFACE`), `extractors.foundation`
  (`CAPABILITY`) — plus, when given, an already-built `ArchitectureGraph`
  for `PACKAGE` nodes and `BELONGS_TO_PACKAGE` relations. Every node's
  `identifier` is namespaced by its own `KnowledgeNodeKind` (`_node_id`)
  so identity stays globally unique across all six kinds without relying
  on the underlying path/name strings happening never to collide.

## Design decisions made within scope

1. **A real bug caught and fixed by re-reading frozen source rather than
   trusting memory.** The first drafts of `architecture/base.py` and
   `dependency/base.py` imported a `require_successful_extraction`
   function from `extractors.architecture.base`/`extractors.imports.
   base` — which does not exist there. Extractors validate their own
   *input* (`ParseResult`, via `require_successful_parse`); the
   validator for an `...ExtractionResult`'s own `succeeded` flag lives
   one layer up, in `analyzers.architecture.base`/`analyzers.dependency.
   base`, because that is where the DTO is consumed as input needing
   validation. Both files were corrected to import and reuse the actual,
   existing validators from `src.analyzers` — this is also the only
   place this phase uses `src.analyzers` at all (see point 2).
2. **`src.analyzers` used only for two tiny, already-existing, exactly
   type-matched validators — not for any DTO or data modeling.** Every
   analyzer-level result DTO (`ArchitectureAssessment`,
   `DependencyProfile`, and the rest) is already an aggregated judgment
   about one file, not additional structural detail a graph needs — see
   each analyzer's own docstring for what it adds instead, and the
   "What this layer does" section above for the specific fields lost in
   each case. `graph.callgraph` deliberately does *not* reuse
   `analyzers.tests.base`'s same-shaped `SymbolExtractionResult`
   validator, despite the type matching exactly, because that
   coincidental match would create a `callgraph -> analyzers.tests`
   dependency a future reader would have no reason to expect; a four-line
   local validator was written instead. `src.domain` is allowed for this
   whole package and is unused throughout: every node here is keyed by
   the same path/qualified-name strings `src.extractors` already uses,
   not the domain layer's UUID-keyed entities, so every graph's
   identifier scheme stays internally consistent. This mirrors Phase 6's
   own finding that `src.domain` was allowed but unused there.
3. **Intra-`graph` sibling imports used exactly once, exactly where the
   task's own dependency rules newly permit it.** Every prior
   `extractors`/`analyzers` phase enforced strict sibling isolation
   (no subpackage imports another). This phase's instructions
   explicitly allow "intra-package imports inside `src.graph`," a
   deliberate loosening — used only in `knowledge/base.py`, which
   imports `PackageNode` from `architecture/base.py` rather than
   redefining a second notion of "package" for the same repository.
   `architecture`, `dependency`, and `callgraph` remain independently
   self-contained, importing no sibling.
4. **Graph DTOs validate determinism structurally, not just by
   convention.** Every `...Graph`'s `__post_init__` rejects unsorted or
   duplicate nodes/edges outright (`ValidationError`), the same choice
   `analyzers.dependency.base.DependencyProfile.external_targets` already
   made for its own sorted tuple — extended here to full node/edge
   collections with composite sort keys (e.g. `(source, target,
   line_number)` for `DependencyRelationEdge`, since two edges may
   legitimately share a `(source, target)` pair from two different import
   statements). `ArchitectureGraph` additionally enforces single-parent
   containment (no package has two parents); `DependencyGraph` enforces
   `is_internal` consistency against the target node's own `kind` in both
   directions; `CallGraph` requires every edge's `caller` to be a known
   node while deliberately *not* requiring `callee` to be (a call graph
   always knows who calls, not always what's being called); `KnowledgeGraph`
   applies the same asymmetry to `EXTENDS` relations only, since a base
   interface may be external to the given input.
5. **No graph algorithms were added.** The task names exactly two
   required graph properties — deterministic and serializable — not
   cycle detection, traversal, or topological sort. Each `...Graph`
   exposes only representation-level conveniences (`get_node`, one-hop
   neighbor lookups, `to_mapping`), deliberately stopping short of
   anything that would read as "analysis," which this phase's own scope
   excludes.

## Counts

| Metric | Count |
|---|---|
| Graph source files (`src/graph/**/*.py`) | 9 |
| Graph test files (`test_*.py`) | 4 |
| Graph test functions (test cases after parametrization) | 98 (100) |
| **Total project test count (Core + Domain + Repository + Collectors + Parsers + Extractors + Analyzers + Graph)** | **696** |
| Total source files (`src/**/*.py`) | 75 |
| Total test files (`tests/**/*.py`) | 77 |
| `...GraphBuilder` Ports defined this phase | 4 (`ArchitectureGraphBuilder`, `DependencyGraphBuilder`, `CallGraphBuilder`, `KnowledgeGraphBuilder`) |
| Public module-level symbols across `src/graph/*/base.py` | 34 (4 Ports, 12 node/edge DTOs, 4 `...Graph` DTOs, 3 `StrEnum` kinds, 4 primary `require_successful_extractions` validators + 3 extra knowledge-specific ones, 6 extra helpers — `ancestor_package_paths`, `is_callable_symbol_kind`, `symbol_node_id`, `pattern_node_id`, `interface_node_id`, `capability_node_id`, `entity_node_id`, `package_node_id`) |

## Verification (all steps)

1. **Import validation** — every file in `src/graph/` and its four
   subpackages imports successfully (verified directly in a Python
   interpreter for all 9 modules, including the package and subpackage
   `__init__.py` files), individually and alongside the full project.
2. **Dependency-boundary validation (graph imports)** — every `import`/
   `from` statement in `src/graph/**/*.py` was enumerated: `core.
   exceptions`, `core.logging`, one or more `extractors.*.base` modules,
   and, in exactly `architecture/base.py`/`dependency/base.py`, one
   `analyzers.*.base` validator import each (see design decision 1/2
   above) — nothing else, and no file imports any of the forbidden
   packages (`collectors`, `repository`, `parsers`, `foundation`,
   `storage`, `memory`, `vector`, `pipeline`, `plugins`, `api`, `cli`,
   `application`, `bootstrap`, plus `src.domain`, allowed but unused —
   see design decision 2), confirmed by an explicit negative grep across
   all of them that found zero matches.
3. **Sibling-import / architecture-boundary validation** — confirmed
   `architecture`, `dependency`, and `callgraph` import no sibling
   subpackage; `knowledge` imports exactly one (`graph.architecture.
   base`), the sole, deliberate use of this phase's newly-permitted
   intra-`graph` import allowance — see design decision 3.
4. **Circular dependency check** — package-level graph extends to
   `graph → {core, extractors, analyzers (partial), graph.architecture
   (from graph.knowledge only)}`. No cycles: `graph.architecture` does
   not import `graph.knowledge`, so the one intra-package edge is
   one-directional. Reverse-direction check confirmed no file under
   `src/core`, `src/domain`, `src/repository`, `src/collectors`,
   `src/parsers`, `src/extractors`, or `src/analyzers` imports `src.
   graph` anywhere (AST-level grep, zero hits).
5. **Deterministic graph behavior** — every `...Graph`'s `__post_init__`
   rejects out-of-order or duplicate nodes/edges by construction (see
   design decision 4); exercised directly in every `test_base.py` via a
   dedicated "rejects unsorted ..." / "rejects duplicate ..." test per
   DTO, so two `...Graph`s built from the same logical inputs in the
   same canonical order are always structurally equal, and any
   out-of-order construction fails loudly rather than silently
   producing a graph whose equality depends on construction order.
6. **Serialization** — every `...Graph.to_mapping()` is exercised by a
   dedicated `test_..._to_mapping_is_json_safe` test per subpackage,
   asserting the exact plain-dict/list shape returned (tuples rendered
   as lists, `StrEnum` values rendered as their `str()` form) rather
   than merely that the call succeeds.
7. **Frozen-phase integrity** — `git status --short` shows only new,
   untracked paths (`src/graph/`, `tests/unit/graph/`, `docs/
   phase8_summary.md`) plus the three per-phase report files every prior
   phase already overwrites in place (`docs/{pytest,mypy,ruff}_report.
   txt`); `git diff --stat` against every previously-tracked file under
   `src/core`, `src/domain`, `src/repository`, `src/collectors`,
   `src/parsers`, `src/extractors`, `src/analyzers`, and their matching
   `tests/unit/` trees is empty. No Phase 1–7 file was modified,
   confirmed by git itself rather than by inspection alone.
8. **Unit tests** — 100/100 pass for this layer (696/696 for the whole
   project). Every contract's `test_base.py` covers: the Port cannot be
   instantiated directly (`TypeError` on the bare ABC); every
   `__post_init__` invariant on every DTO, exercised in both the
   accepting and rejecting direction; `get_node`/lookup helpers, both
   found and `NotFoundError`-raising; `require_successful_extractions`
   passing all-successful input through unchanged and raising
   `ValidationError` on any failure; `to_mapping()`'s exact shape; and
   each contract's own extra helper(s) directly — `ancestor_package_
   paths`, `is_callable_symbol_kind`, and all six `knowledge` id-builder
   functions.
9. **mypy --strict** — clean on the full `src` tree (75 files, including
   `src/graph`) and on the full `tests` tree (77 files, informational),
   targeting `--python-version 3.13` per `pyproject.toml`'s `[tool.
   mypy]` configuration. See `mypy_report.txt` for the full output,
   scoped and unscoped.
10. **ruff** — clean across `src/graph` and `tests/unit/graph` (this
   phase's own scope) in full; one pre-existing, already-documented
   finding remains project-wide (`UP046` on `Repository`'s
   `Generic[EntityT]` base in `src/domain/interfaces.py`, a frozen
   Phase 2 file, first reported in Phase 6's and Phase 7's own
   `ruff_report.txt`) and was left untouched per this phase's own "do
   not modify Phase 1–7 implementation" instruction. See
   `ruff_report.txt` for both the full and scoped runs.

## A note on the Python version used to run verification

This sandboxed environment has Python 3.12.3 available (no 3.13
interpreter is installable here — the same substitution already present,
unremarked, in every prior phase's own `pytest_report.txt`, so it is not
a new deviation introduced here). `pytest_report.txt` and the
interpreter-dependent parts of `mypy_report.txt` reflect that. `mypy
--strict` was still run with `--python-version 3.13` (mypy's target
semantics are governed by this flag, independent of the interpreter
running mypy itself), matching `pyproject.toml`'s `[tool.mypy]
python_version = "3.13"`. No 3.13-exclusive syntax was used anywhere in
this phase's code.

## A note on what "Port-defining" means for this codebase so far

`src/collectors` and `src/parsers` each already have concrete
implementations (`filesystem`/`github`/`gitlab`/`local` collectors;
`cpp`/`go`/`python`/`rust`/`typescript` parsers) — verified directly via
the repository's own file tree before writing anything this phase.
`src/extractors` and `src/analyzers`, by contrast, are contracts-only:
one `base.py` Port per concern, no concrete implementation anywhere yet.
This phase continues that same contracts-only scope for `src/graph` —
matching the four-file target tree this phase's own instructions asked
for (one `base.py` per subpackage, nothing more) — rather than the
multi-file, concrete-implementation shape `collectors`/`parsers` phases
used. No concrete `...GraphBuilder` implementation was written this
phase, by design.

## Package contents added this phase

```
src/graph/
├── __init__.py                        (package docstring only, no re-exports)
├── architecture/
│   ├── __init__.py
│   └── base.py    (ArchitectureGraphBuilder, ArchitectureGraph, PackageNode, PackageContainmentEdge)
├── callgraph/
│   ├── __init__.py
│   └── base.py    (CallGraphBuilder, CallGraph, CallableNode, CallEdge)
├── dependency/
│   ├── __init__.py
│   └── base.py    (DependencyGraphBuilder, DependencyGraph, DependencyNode, DependencyRelationEdge)
└── knowledge/
    ├── __init__.py
    └── base.py    (KnowledgeGraphBuilder, KnowledgeGraph, KnowledgeNode, KnowledgeRelation)

tests/unit/graph/
├── __init__.py
├── architecture/test_base.py    (29 tests)
├── callgraph/test_base.py       (22 tests, 20 functions)
├── dependency/test_base.py      (21 tests)
└── knowledge/test_base.py       (28 tests)
```

Every other package (`foundation`, `storage`, `memory`, `vector`,
`pipeline`, `api`, `cli`, `plugins`, `application`, `bootstrap`) — none
were touched. No file parses source, collects repositories, extracts raw
structures, analyzes a single file's own content, scores, selects
foundations, implements storage, or performs vector search anywhere in
this layer — see "What this layer does," above.

---

**Phase 8 complete. `src/core`, `src/domain`, `src/repository`,
`src/collectors`, `src/parsers`, `src/extractors`, and `src/analyzers`
unmodified. One genuine contract gap reported (function/method call
relationships — see above), not guessed around. Next phase not started —
awaiting your instruction.**

**PHASE 8 READY FOR FREEZE**
