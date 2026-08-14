# VAOS Phase 9 — Foundation Layer Summary

**Scope:** `src/foundation/__init__.py`, plus one `base.py` per concern —
`comparer/`, `ranking/`, `selector/`, `merger/`, `exporter/` — exactly the
five-subpackage structure specified for this phase.
**`src/core`, `src/domain`, `src/repository`, `src/collectors`,
`src/parsers`, `src/extractors`, `src/analyzers`, and `src/graph` were
not modified.**
`pyproject.toml` was not modified — no new dependency was needed this
phase (the one new technique used, SHA-256 export checksums, is stdlib
`hashlib`/`json`, already available without any dependency change, and
already precedented by `parsers.base.compute_content_hash`).
**Generated:** 2026-08-14

## No contract gap; one contract-shaped design decision reported up front

Before writing any code, every frozen `extractors.*`/`analyzers.*`/
`graph.*` contract was inspected (in particular `extractors.foundation.
base`, `graph.knowledge.base`, and all eight `analyzers.*.base` modules)
and the whole `src/` tree was grepped for any existing "candidate
capabilities/components from analyzed repositories" concept this phase
could consume directly. `extractors.foundation.base.FoundationCandidate`
is exactly that concept, and its own docstring explicitly defers
"combining [its signals] into a score" and "selecting which candidates
actually become part of a foundation" to this phase, by name. No STOP
condition was reached — every capability this phase's own RESPONSIBILITY
section names (compare, rank, select, merge, export) is backed by real,
existing upstream data.

One design decision was, however, required rather than found ready-made:
`FoundationCandidate` alone carries no repository context (only
`relative_path`, unique within one repository, not across the several
this phase's own comparer must compare candidates *from*). `comparer/
base.py` therefore defines `FoundationSubject`, pairing a
`FoundationCandidate` with a `repository_id: UUID` — deliberately reusing
`domain.entities.SourceFile.repository_id`'s own field name and type
rather than inventing a second repository-identity scheme, without
importing `domain.entities` itself (see design decision 2). Every other
subpackage imports `FoundationSubject` from `comparer.base` rather than
redefining it.

## What this layer does

`foundation` answers one question: *of everything already extracted as a
candidate for reuse, across one or more analyzed repositories, what is
actually worth keeping, and what does the reusable set built from it look
like?* Each of the five `base.py` modules is fully self-contained and
defines: one or more frozen, slotted DTOs validated in `__post_init__`
for determinism (sorted, duplicate-free where a collection is involved)
and internal consistency; an abstract `Foundation...` Port with one
method; and one or more `require_...` helpers every concrete
implementation of that Port is documented to call first, so a caller
error is reported the same way — an immediate `ValidationError` — no
matter which concrete implementation eventually catches it.

- **`comparer/base.py`** — `FoundationComparer`
  (`compare(left: FoundationSubject, right: FoundationSubject) ->
  FoundationComparisonOutcome`), plus `FoundationSubject` and
  `build_subjects(*, repository_id, extraction_results) ->
  tuple[FoundationSubject, ...]`, assembling every subject in one
  repository from its files' `FoundationExtractionResult`s
  (`require_successful_foundation_extractions` first). Comparison is
  deterministic and signal-based only (`name`, `kind`, `signals` — no
  fuzzy matching): same kind and name with identical signals is
  `EQUIVALENT`; same kind and name with differing signals is
  `CONFLICTING`; different name but shared kind and at least one signal
  is `COMPATIBLE`; anything else is `DISTINCT`. `compare_all(comparer,
  subjects)` fans a `FoundationComparer` out across every distinct pair,
  first sorting `subjects` by `subject_id` so the result is deterministic
  regardless of input order.
- **`ranking/base.py`** — `FoundationRanker` (`rank(subjects:
  Sequence[FoundationSubject]) -> FoundationRanking`,
  `require_unique_subjects` first), producing one `FoundationScore`
  (`value` normalized to `[0.0, 1.0]`, freeform `rationale`) per subject,
  collected into a `FoundationRanking` whose `__post_init__` enforces
  `(-value, subject_id)` order — the exact deterministic scoring formula
  is a concrete implementation's own decision, matching this codebase's
  established Port-only, no-business-logic-in-`base.py` convention (see
  "A note on what 'Port-defining' means," below).
- **`selector/base.py`** — `FoundationSelector` (`select(subjects,
  ranking, comparisons, policy: FoundationSelectionPolicy) ->
  FoundationSelectionResult`, `require_consistent_inputs` first), the one
  subpackage whose Port takes both a `FoundationRanking` (from `ranking`)
  and `Sequence[FoundationComparisonOutcome]` (from `comparer`) as input,
  honoring an explicit, serializable `FoundationSelectionPolicy`
  (`minimum_score`, `maximum_selected`, `required_kind`) and rejecting
  any subject whose only disqualification is having been compared as
  `CONFLICTING` against an already-selected subject
  (`FoundationRejectionReason.CONFLICTING_WITH_SELECTED`) — "compatibility"
  is not a separate ad hoc check invented here, it is `comparer`'s own
  verdict, consumed.
- **`merger/base.py`** — `FoundationMerger` (`merge(subjects, ranking,
  selection, comparisons=()) -> FoundationResult`,
  `require_mergeable_selection` and, when `comparisons` is given,
  `require_no_conflicting_selection` first — defense-in-depth re-checking
  the same compatibility constraint `selector` already enforced, since a
  `FoundationResult` is this layer's authoritative, external-facing
  outcome), producing a `FoundationResult` of flat, self-contained
  `FoundationMember`s (`subject_id`, `repository_id`, `name`, `kind`,
  `relative_path`, `score` all carried through, so a downstream reader
  never re-joins against `subjects`/`ranking`) and its own
  `to_mapping()`, matching every prior phase's `...Graph.to_mapping()`
  convention.
- **`exporter/base.py`** — `FoundationExporter` (`export(result:
  FoundationResult) -> FoundationExport`), wrapping
  `result.to_mapping()` with a `format_version` tag and a
  `compute_export_checksum` SHA-256 digest over the payload's canonical
  (sorted-key, whitespace-free) JSON form — mirroring `parsers.base.
  compute_content_hash`'s own SHA-256-over-canonical-text approach — so a
  consumer can verify two exports represent the same result without
  comparing nested structures directly.

## Design decisions made within scope

1. **`FoundationSubject` defined once, in `comparer/base.py`, reused
   everywhere else.** `ranking`, `selector`, and `merger` all import it
   from there rather than redefining it — the intra-`foundation` sibling
   import this phase's own dependency rules newly permit ("Intra-package
   imports inside `src.foundation` are allowed"), used deliberately at
   exactly this one point of origin, mirroring `graph.knowledge`
   importing `PackageNode` from `graph.architecture` in Phase 8.
   `exporter` imports only `FoundationResult` from `merger`; it has no
   need for `FoundationSubject` itself.
2. **`src.domain`, `src.analyzers`, and `src.graph` are each allowed for
   this whole package and are deliberately unused throughout.**
   `FoundationSubject.repository_id: UUID` reuses `domain.entities.
   SourceFile.repository_id`'s own field name and type without importing
   the entity itself — the same allowed-but-unused pattern Phase 6 and
   Phase 8 both already established for `src.domain`. More significantly:
   `graph.knowledge.base.KnowledgeGraph`'s own `CAPABILITY` nodes are
   already built *from* `FoundationCandidate`, but `KnowledgeNode`'s
   fixed shape (`identifier`, `kind`, `label`, `relative_path`,
   `attributes`) does not retain `is_public`, `has_docstring`, or
   `FoundationCandidateKind` — exactly the fields `ranking` and `selector`
   need. Every `analyzers.*.base` assessment/profile DTO is, similarly,
   already a per-file aggregated judgment, not additional per-candidate
   detail. This is the same "already a reduction, not additional detail"
   reasoning `graph.architecture`/`graph.dependency` used in Phase 8 to
   prefer extractor-level DTOs over analyzer-level ones — applied here
   one layer further up the stack, preferring the extractor-level
   `FoundationCandidate` over the graph-level `KnowledgeNode` for the
   same reason.
3. **A validator with the same name already exists one layer away
   (`graph.knowledge.base.require_successful_foundation_extractions`) —
   deliberately not reused, for the same reason Phase 8 gave for not
   reusing `analyzers.tests.base`'s coincidentally-matching validator.**
   A `foundation.comparer -> graph.knowledge` dependency, for one
   validator function, when nothing else in this phase touches
   `graph.knowledge` at all, would be exactly the kind of surprising,
   narrow dependency Phase 8 avoided creating for `graph.callgraph`. A
   local, four-line validator was written instead, at
   `comparer.base.require_successful_foundation_extractions`, over the
   exact same `Sequence[FoundationExtractionResult]` type.
4. **Compatibility, throughout, is `comparer`'s verdict, never
   re-derived.** `selector.FoundationRejectionReason.
   CONFLICTING_WITH_SELECTED` and `merger.require_no_conflicting_
   selection` both key off `FoundationComparisonVerdict.CONFLICTING`
   from `comparisons`, an input both Ports accept — no subpackage
   invents its own second notion of what "compatible" means.
5. **Foundation DTOs validate determinism structurally, matching every
   prior phase's own choice for its own aggregate DTOs.**
   `FoundationComparisonOutcome.shared_signals`, `FoundationRanking.
   scores`, `FoundationSelectionResult.selected_subject_ids`/
   `rejections`, and `FoundationResult.members` each reject
   out-of-order or duplicate content in `__post_init__`
   (`ValidationError`) rather than merely documenting an expectation —
   the same choice `graph`'s node/edge collections and `analyzers.
   dependency.base.DependencyProfile.external_targets` already made.
   `FoundationSelectionResult` additionally enforces that no
   `subject_id` appears in both `selected_subject_ids` and `rejections`.
6. **A checksum was added to `exporter`, beyond a bare `to_mapping()`
   wrapper, because "stable, deterministic representations" (this
   phase's own wording) implies a way to *verify* stability, not just
   assert it.** `compute_export_checksum` is a thin, five-line function
   over stdlib `json`/`hashlib` — no new dependency, no speculative
   format beyond what `FoundationResult.to_mapping()` already produces —
   and raises `ValidationError` (not a bare `TypeError`) if ever handed a
   non-JSON-safe payload, matching this phase's own "explicit about
   errors" requirement.
7. **No scoring formula, no selection algorithm, no merge-assembly logic
   was implemented in `base.py`, anywhere in this phase.** Every
   `Foundation...` Port's single method is abstract; only its
   validation helpers and DTOs are concrete — see "A note on what
   'Port-defining' means," below, for why this matches every prior
   `extractors`/`analyzers`/`graph` phase's own scope rather than
   narrowing it further or expanding beyond it.

## Counts

| Metric | Count |
|---|---|
| Foundation source files (`src/foundation/**/*.py`) | 11 |
| Foundation test files (`test_*.py`) | 7 (5 per-subpackage + `test_imports.py` + `test_dependency_boundaries.py`) |
| Foundation test functions (test cases after parametrization) | 129 |
| — by file: `comparer` | 23 |
| — by file: `ranking` | 19 |
| — by file: `selector` | 19 |
| — by file: `merger` | 19 |
| — by file: `exporter` | 15 |
| — by file: `test_imports.py` | 11 |
| — by file: `test_dependency_boundaries.py` | 23 |
| **Total project test count (Core + Domain + Repository + Collectors + Parsers + Extractors + Analyzers + Graph + Foundation)** | **825** |
| Total source files (`src/**/*.py`) | 86 |
| Total test files (`tests/**/*.py`) | 90 |
| `Foundation...` Ports defined this phase | 5 (`FoundationComparer`, `FoundationRanker`, `FoundationSelector`, `FoundationMerger`, `FoundationExporter`) |
| Public module-level symbols across `src/foundation/*/base.py` | 27 (5 Ports, 10 DTOs, 2 `StrEnum` kinds, 9 helper functions, 1 constant) |

## Verification (all steps)

1. **Import validation** — every file in `src/foundation/` and its five
   subpackages imports successfully, verified two ways: directly in a
   Python interpreter for all 11 modules (including the package and
   subpackage `__init__.py` files), and via a dedicated, automated
   `tests/unit/foundation/test_imports.py` (11 parametrized cases) that
   is part of the committed suite, not just a one-off manual check.
2. **Dependency-boundary validation (foundation imports)** — every
   `import`/`from` statement in `src/foundation/**/*.py` was enumerated:
   `core.exceptions`, `core.logging`, `extractors.foundation.base`, and
   `extractors.symbols.base` (for `build_qualified_name`, reused rather
   than reimplemented — see "What this layer does," `comparer/base.py`)
   from outside the package, plus the one intra-package edge from design
   decision 1 — nothing else, and no file imports any of the forbidden
   packages (`collectors`, `parsers`, `repository`, `storage`, `memory`,
   `vector`, `pipeline`, `plugins`, `api`, `cli`, `application`,
   `bootstrap`), confirmed by an explicit negative grep across all of
   them that found zero matches, and re-confirmed by an automated,
   AST-based `tests/unit/foundation/test_dependency_boundaries.py` (23
   parametrized cases, two per source file plus one whole-package check)
   that is itself part of the committed suite.
3. **Sibling-import / architecture-boundary validation** — confirmed
   `comparer` imports no sibling subpackage; `ranking` imports exactly
   one (`comparer.base`, for `FoundationSubject`); `selector` imports two
   (`comparer.base`, `ranking.base`); `merger` imports three
   (`comparer.base`, `ranking.base`, `selector.base`); `exporter` imports
   one (`merger.base`) — every edge traceable directly to a DTO that
   subpackage's own Port signature requires, none redefined. See design
   decision 1.
4. **Circular dependency check** — the intra-`foundation` import graph
   (`comparer <- ranking <- selector <- merger <- exporter`, using each
   subpackage's own `base.py` imports of its siblings) is a strict linear
   DAG with no back-edges, confirmed both by inspection and by an
   automated depth-first-search test
   (`test_foundation_subpackages_have_no_import_cycle`). Reverse-direction
   check confirmed no file under `src/core`, `src/domain`, `src/
   repository`, `src/collectors`, `src/parsers`, `src/extractors`,
   `src/analyzers`, or `src/graph` imports `src.foundation` anywhere
   (AST-level grep, zero hits).
5. **Deterministic-output verification** — covered at three levels: (a)
   every Foundation DTO's `__post_init__` rejects out-of-order or
   duplicate content by construction (design decision 5), exercised by a
   dedicated "rejects unsorted ..." / "rejects duplicate ..." test per
   DTO; (b) `compare_all` is exercised directly for order-independence
   (`test_compare_all_is_deterministic_regardless_of_input_order`,
   asserting the same pair order results from both a subject list and
   its reverse); (c) an end-to-end pipeline check — trivial, throwaway
   concrete implementations of all five Ports (not part of the shipped
   contracts; this phase ships Ports only, see "A note on what
   'Port-defining' means," below) wired together and run twice over the
   same two-repository input — confirmed the full comparer → ranking →
   selector → merger → exporter pipeline produces a byte-identical
   `FoundationExport`, including its SHA-256 `checksum`, across both
   runs.
6. **Serialization** — `FoundationResult.to_mapping()` is exercised by a
   dedicated `test_foundation_result_to_mapping_is_json_safe` test
   asserting the exact plain-dict/list shape returned (`UUID` and
   `StrEnum` values rendered as their `str()` form), matching every
   prior phase's `...Graph.to_mapping()` convention; `exporter`'s
   `compute_export_checksum` is separately exercised for determinism,
   key-order independence, differing-payload discrimination, digest
   shape (64 lowercase hex characters), and rejection of a non-JSON-safe
   payload.
7. **Frozen-phase integrity** — `git status --short` shows only new,
   untracked paths (`src/foundation/`, `tests/unit/foundation/`, `docs/
   phase9_summary.md`) plus the three per-phase report files every prior
   phase already overwrites in place (`docs/{pytest,mypy,ruff}_report.
   txt`); `git diff --stat` against every previously-tracked file under
   `src/core`, `src/domain`, `src/repository`, `src/collectors`,
   `src/parsers`, `src/extractors`, `src/analyzers`, `src/graph`,
   `pyproject.toml`, and their matching `tests/unit/` trees is empty. No
   Phase 1–8 file was modified, confirmed by git itself rather than by
   inspection alone.
8. **Unit tests** — 129/129 pass for this layer (825/825 for the whole
   project). Every contract's `test_base.py` covers: the Port cannot be
   instantiated directly (`TypeError` on the bare ABC); every
   `__post_init__` invariant on every DTO, exercised in both the
   accepting and rejecting direction; lookup helpers
   (`FoundationRanking.score_for`, `FoundationResult.get_member`), both
   found and `NotFoundError`-raising; every `require_...` validator
   passing consistent input through unchanged and raising
   `ValidationError` on each documented failure mode; and each
   contract's own extra helper directly (`build_subjects`, `compare_all`,
   `compute_export_checksum`).
9. **mypy --strict** — clean on the full `src` tree (86 files, including
   `src/foundation`) and on the full `tests` tree (90 files,
   informational), targeting `--python-version 3.13` per `pyproject.
   toml`'s `[tool.mypy]` configuration. See `mypy_report.txt` for the
   full output, scoped (`src/foundation`, `tests/unit/foundation`: 24
   files) and unscoped (176 files).
10. **ruff** — clean across `src/foundation` and `tests/unit/foundation`
    (this phase's own scope) in full; one pre-existing, already-documented
    finding remains project-wide (`UP046` on `Repository`'s
    `Generic[EntityT]` base in `src/domain/interfaces.py`, a frozen
    Phase 2 file, first reported in Phase 6's, Phase 7's, and Phase 8's
    own `ruff_report.txt`, confirmed present in this phase's own clean
    Phase-8 baseline *before* any Phase 9 file was written) and was left
    untouched per this phase's own "do not modify Phase 1–8
    implementation" instruction. See `ruff_report.txt` for both the full
    and scoped runs.

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
implementations; `src/extractors`, `src/analyzers`, and `src/graph`, by
contrast, are contracts-only: one `base.py` Port per concern, no concrete
implementation anywhere yet — verified directly via the repository's own
file tree before writing anything this phase. This phase continues that
same contracts-only scope for `src/foundation` — matching the five-file
target tree this phase's own instructions asked for (one `base.py` per
subpackage, nothing more) — rather than introducing the first concrete
implementation in the project. No concrete `Foundation...` implementation
was written into `src/foundation` this phase, by design; the trivial
stub implementations used for the end-to-end determinism check (item 5
above) live outside the package entirely and are not part of this
phase's deliverable.

## Package contents added this phase

```
src/foundation/
├── __init__.py                        (package docstring only, no re-exports)
├── comparer/
│   ├── __init__.py
│   └── base.py    (FoundationComparer, FoundationSubject, FoundationComparisonOutcome, FoundationComparisonVerdict)
├── ranking/
│   ├── __init__.py
│   └── base.py    (FoundationRanker, FoundationRanking, FoundationScore)
├── selector/
│   ├── __init__.py
│   └── base.py    (FoundationSelector, FoundationSelectionPolicy, FoundationSelectionResult, FoundationRejection, FoundationRejectionReason)
├── merger/
│   ├── __init__.py
│   └── base.py    (FoundationMerger, FoundationResult, FoundationMember)
└── exporter/
    ├── __init__.py
    └── base.py    (FoundationExporter, FoundationExport, compute_export_checksum)

tests/unit/foundation/
├── __init__.py
├── comparer/test_base.py               (23 tests)
├── ranking/test_base.py                (19 tests)
├── selector/test_base.py               (19 tests)
├── merger/test_base.py                 (19 tests)
├── exporter/test_base.py               (15 tests)
├── test_imports.py                     (11 tests)
└── test_dependency_boundaries.py       (23 tests)
```

Every other not-yet-built package (`storage`, `memory`, `vector`,
`pipeline`, `api`, `cli`, `plugins`, `application`, `bootstrap`) — none
were touched. No file parses source, collects repositories, extracts raw
structures, analyzes a single file's own content, creates graphs,
implements storage, implements vector search, implements a memory
system, or executes a pipeline anywhere in this layer — see "What this
layer does," above.

---

**Phase 9 complete. `src/core`, `src/domain`, `src/repository`,
`src/collectors`, `src/parsers`, `src/extractors`, `src/analyzers`, and
`src/graph` unmodified. No genuine contract gap encountered; one
contract-shaped design decision (`FoundationSubject`'s repository
pairing) reported above rather than left implicit. Next phase not
started — awaiting your instruction.**

**PHASE 9 READY FOR FREEZE**
