# Concrete Graph Builder Summary: `StructuralArchitectureGraphBuilder`

Milestone: **Concrete Architecture Graph Builder.** Not a numbered phase. An additive concrete
implementation of the already-frozen Phase 8 `ArchitectureGraphBuilder` Port
(`src/graph/architecture/base.py`), approved and scoped by the Architecture Graph Builder
Contract Discovery report this implements (first concrete graph builder).

## Responsibility

`StructuralArchitectureGraphBuilder` (`src/graph/architecture/structural.py`) assembles many
files' already-extracted `PackageUnit`s into one repository-wide `ArchitectureGraph`: a connected
containment tree of `PackageNode`s linked by `PackageContainmentEdge`s. It uses only each unit's
own `package_path`, `relative_path`, and `is_package_root`. It resolves no modules, infers no
dependencies, interprets no `declared_modules`, normalizes no paths, judges no structure, and
scores or ranks nothing.

## Contract

- Zero-argument, stateless: no `__init__` override, exactly like the existing concrete
  extractors (`StructuralImportExtractor`, `StructuralAstExtractor`, `StructuralSymbolExtractor`,
  `StructuralArchitectureExtractor`, and the others).
- `build(self, extraction_results: Sequence[ArchitectureExtractionResult]) -> ArchitectureGraph`
  — identical signature to the abstract method it implements.
- **Input:** every entry must be a successful `ArchitectureExtractionResult`, as produced by
  `StructuralArchitectureExtractor` (the `architecture_results` context key of the real
  repository analysis composition).
- First action: `require_successful_extractions(extraction_results)`, the already-existing,
  already-tested helper from `graph/architecture/base.py`.

## Algorithm

1. Call `require_successful_extractions`.
2. If `extraction_results` is empty, return `ArchitectureGraph()`.
3. Group each unit by `unit.package_path`: accumulate `unit.relative_path` into a per-package
   `set`, and record every package containing at least one unit with `is_package_root=True`.
4. The node set is every observed `package_path` plus every path returned by
   `ancestor_package_paths(package_path)` for each of them. No other package path is
   synthesized.
5. Build one `PackageNode` per node path, in ascending `package_path` tuple order:
   `file_paths = tuple(sorted(files))` (empty for a path no unit belongs to) and
   `has_package_root_file` = whether that package was recorded in step 3.
6. Build one `PackageContainmentEdge(parent_path=p[:-1], child_path=p)` per non-root node path
   `p`, sorted by `(parent_path, child_path)`.
7. Return `ArchitectureGraph(nodes=..., edges=...)`.

The builder does not re-implement any of `ArchitectureGraph`'s own validation (node and edge
ordering, duplicate nodes, `file_paths` ordering, immediate-child edges, edge references, single
parentage): those `__post_init__` checks already run on every graph it returns.

## Behavior

### Empty input

`build(())` (or any empty sequence) returns `ArchitectureGraph()`: no nodes, no edges. No root
node is synthesized, because nothing was observed and nothing is implied.

### Package grouping

Nodes are packages (directories), not files. Every unit sharing a `package_path` contributes to
the same single `PackageNode`; files appear only inside `PackageNode.file_paths`.

### Ancestor synthesis

Exactly `ancestor_package_paths`: every proper prefix of each observed `package_path`, from the
repository root `()` inward. An ancestor no unit belongs to directly is an ordinary `PackageNode`
with `file_paths=()` and `has_package_root_file=False`. The existing helper is sufficient on its
own; the builder adds no ancestor rule.

### Root behavior

The repository-root node `package_path == ()` is present in every non-empty graph, either because
a unit sits at the root or because it is an ancestor of every non-root package. Root-level files
belong to that node. The root has no parent, so it is never the `child_path` of an edge.

### File membership

A unit contributes `unit.relative_path` — never `ArchitectureExtractionResult.relative_path` —
to the node at `unit.package_path`. Membership is deduplicated (`set`) and sorted
lexicographically, so identical results collapse and input order is irrelevant. Package-root
marker files (`__init__.py`, `mod.rs`, ...) are ordinary members of their directory's node.

### Package-root propagation

`has_package_root_file` is `any(unit.is_package_root)` over the units placed directly in that
package. The builder holds no marker names and no language logic; `_PACKAGE_ROOT_MARKERS` (in
`extractors/architecture/base.py`) is untouched. The flag never propagates to ancestors,
descendants, or siblings.

### Node ordering

Ascending by the **`package_path` tuple**, never by the `node_id` string. The two disagree: the
tuples `("a", "b")` and `("a-b",)` sort in that order, while the ids `"a/b"` and `"a-b"` sort the
other way, and `ArchitectureGraph` validates the tuple order.

### Edge ordering

Ascending by `(parent_path, child_path)`. Edges from different parents therefore interleave by
parent first: all `() -> x` edges, then `("src",) -> ...`, and so on.

### Failure behavior

Exactly one error path: any failed `ArchitectureExtractionResult` anywhere in the input causes
`require_successful_extractions` to raise the existing `ValidationError` before any grouping
happens. No new exception type was introduced. Every other error the graph DTOs can raise is
unreachable by construction, because nodes, edges, and ancestors are all derived from the same
set of package paths.

### `declared_modules` are ignored

`PackageUnit.declared_modules` has no representation in `PackageNode` or `PackageContainmentEdge`.
It does not affect package identity, membership, or edges, and no node is created from it. No
field was added to any graph DTO.

### Path separators are not normalized

The builder is separator-agnostic. It never splits, joins, or rewrites `package_path` or
`relative_path`; it trusts each supplied `PackageUnit` exactly. Consequently a
backslash-separated `relative_path` (see below) is a single opaque string to this builder.

### Pure and stateless

No I/O, no logging, no mutation of its input, no instance state, and no dependency beyond the
existing graph and extractor contracts. A single instance can be reused across any number of
`build` calls, and equal input always produces an equal graph.

## Explicitly undefined Port-level cases (trusted verbatim)

The Port validates none of the following, and this implementation deliberately invents no
conflict handling for them. None is producible by `StructuralArchitectureExtractor`, which
derives `package_path` and `is_package_root` from `relative_path` alone:

- **The same `relative_path` under different `package_path`s.** Each unit is trusted; the file
  is listed under both nodes. Nothing is raised, reconciled, or normalized.
- **`ArchitectureExtractionResult.relative_path` differing from `unit.relative_path`.** Only
  `unit.relative_path` is used.
- **A `package_path` or `is_package_root` inconsistent with the unit's `relative_path`.** Trusted
  as given.

## Cross-platform note

`StructuralArchitectureExtractor` derives `package_path` by splitting `relative_path` on `/`, and
`_enumerate_files` produces `str(absolute.relative_to(workspace))`, which is backslash-separated
on Windows. On a Windows checkout the real extractor therefore places nested files in the root
package (`pkg\sub\util.py` gives `package_path == ()`), so the real graph there is a single root
node with no edges. That is pre-existing, frozen upstream behavior — the same class of issue
`docs/real_repository_analysis_verification_correction.md` records — and this milestone
deliberately does not change the extractor, the marker list, `_enumerate_files`, or add any
normalization to the builder.

The integration test accordingly asserts only values derived from the real
`unit.relative_path` / `unit.package_path` on every platform, and pins the exact nested graph
only when `os.sep == "/"`.

## Tests

`tests/unit/graph/architecture/test_base.py` — pre-existing, unchanged, still passing.

`tests/unit/graph/architecture/test_structural.py` — 34 new tests over real DTOs (no mocks):
instantiation and Port conformance; empty input; a root-level file; a root-level package-root
marker (no self-edge); one nested file; deep nesting with one edge per non-root package;
ancestor-only nodes (no files, no flag); a package with no direct file between populated
packages; no synthesis beyond observed packages and ancestors; grouping; file deduplication and
sorting; duplicate identical results collapsing; `has_package_root_file` true, false, and
non-leaking; membership from `unit.relative_path` rather than the result's; `declared_modules`
having no effect; node order by tuple rather than `node_id` (with a demonstrating case); edge
order by `(parent_path, child_path)`; a single incoming edge from the immediate parent for every
non-root node; reversed and exhaustive-permutation input orders giving equal graphs; repeated
builds; the exact mixed graph; a synthetic same-file/different-package input trusted verbatim; a
`package_path` disagreeing with `relative_path` trusted; backslash paths not normalized; and
failed-extraction rejection (mixed in, alone, and last in the sequence).

`tests/integration/test_architecture_graph.py` — 4 new tests, self-contained (its own local
`_config`, `_run_git`, fixture writer; imports nothing from another test module). Creates one
real local git repository with root files and a root-level package-root marker,
Python/TypeScript/Rust package-root markers, a three-deep package, a package with no direct
file, a directory holding only an unsupported file, and a dot-directory. Runs the existing
14-step composition through `bootstrap(config, extra_steps=build_analysis_steps(config))`
unmodified, then invokes the builder directly on the context's real `architecture_results` — no
step is added. Asserts: the graph is valid, non-empty, and tree-shaped; every real file sits
under the node for its `unit.package_path`; ancestor nodes exist for every real package path;
package-root flags match the real `is_package_root` values; repeated builds and two independent
analysis runs give equal graphs; and, on POSIX only, the exact nested graph. Requires the real
`git` executable; skipped, not failed, when unavailable.

## Exclusions

This milestone is builder-only. It does not:

- add a graph step to `src/bootstrap/analysis_steps.py`, change the 14-step analysis sequence,
  wire the builder into the CLI, print, persist, export, or serve the graph;
- implement `DependencyGraphBuilder` (blocked on a module-resolution contract that does not
  exist), `CallGraphBuilder` (no call-site producer upstream), or `KnowledgeGraphBuilder`;
- implement or wire `patterns`, run any analyzer, or make any foundation decision;
- normalize path separators, or modify any extractor, marker list, or enumeration;
- add DI, a container, a registry, a service locator, dynamic discovery, parser dispatch,
  scoring, ranking, or any new graph DTO.

A later composition milestone may decide how the builder is consumed.

## Verification results

Run against this checkout (`HEAD` = `ba5a7f7`), CPython 3.13.13 on Linux (the pinned
`requires-python = ">=3.13"` interpreter; not the Windows checkout, whose authoritative
verification remains a separate step):

- `pytest tests/unit/graph/architecture/test_structural.py` — **34 passed**.
- `pytest tests/integration/test_architecture_graph.py` — **4 passed** (including the POSIX-exact
  graph test).
- `pytest` (full suite) — **1519 passed**, 0 failed, 1 pre-existing, unrelated warning
  (`starlette`/`httpx`). 1481 (verified baseline before this implementation) + 34 + 4 = 1519.
  The two Windows-only baseline failures recorded in
  `docs/real_repository_analysis_verification_correction.md` do not occur on this platform.
- `mypy --strict src/` — Success: no issues found in **129** source files (128 before, +1 for
  `structural.py`).
- `ruff check src/ tests/` — exactly the one pre-existing, unrelated `UP046` finding in
  `src/domain/interfaces.py`; zero new findings.
- Windows-native path handling was additionally checked by running the real parsers and the real
  extractor over backslash-separated `relative_path`s and applying the integration test's
  platform-independent assertions to the result: they hold (single root node, no edges).

## Changed files

New files only:

```
src/graph/architecture/structural.py
tests/unit/graph/architecture/test_structural.py
tests/integration/test_architecture_graph.py
docs/graph_architecture_summary.md
```

## Confirmation that frozen files were untouched

`git diff --name-only` against `HEAD` (`ba5a7f7`) is empty for tracked files — the only changes
are the four new, untracked files above. Every `src/graph/*/base.py`, `src/extractors/**`,
`src/analyzers/**`, `src/bootstrap/**` (including `analysis_steps.py`), `src/cli/**`,
`src/domain/**`, `src/repository/**`, `src/collectors/**`, `src/pipeline/**`, the four
`tests/unit/graph/*/test_base.py` files, `tests/unit/bootstrap/test_analysis_steps.py`,
`tests/integration/test_real_repository_analysis.py`, `pyproject.toml`, and `configs/config.yaml`
are byte-for-byte unchanged. The 14-step composition is unchanged.
