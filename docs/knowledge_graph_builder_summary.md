# Knowledge Graph Builder — Summary

`StructuralKnowledgeGraphBuilder` (`src/graph/knowledge/structural.py`) is the first concrete
`KnowledgeGraphBuilder`. It assembles already-extracted symbols, patterns, interfaces, and
foundation candidates — plus, optionally, an already-built `ArchitectureGraph` — into one
deterministic `KnowledgeGraph`.

**Status: not wired into production analysis.** No pipeline step, bootstrap composition, CLI
command, or other module calls it. `src/bootstrap/analysis_steps.py` is unchanged, so the real
composition still has exactly its 16 steps and produces no knowledge graph. The builder is
exercised only by its own unit tests and by integration tests that invoke it directly on real
extraction results: `tests/integration/test_knowledge_graph.py` (the real composition) and
`tests/integration/test_knowledge_graph_coalescing.py` (the duplicate identity policy).

## Contract implemented

- `StructuralKnowledgeGraphBuilder(KnowledgeGraphBuilder)`: zero-argument constructible,
  stateless, no `__init__` override. One instance may be reused for any number of builds.
- `build` has the Port's exact keyword-only signature: `symbol_results`, `pattern_results`,
  `interface_results`, `foundation_results` (all `Sequence[...] = ()`), and
  `architecture_graph: ArchitectureGraph | None = None`.
- `src/graph/knowledge/base.py` — its DTOs, enums, node-ID helpers, validators, and signatures — is
  unchanged. The builder imports it and builds only valid `KnowledgeNode`, `KnowledgeRelation`,
  and `KnowledgeGraph` values.

## Input and output semantics

**Validation first.** All four result sequences are validated with the existing
`require_successful_*_extractions` helpers (symbol, pattern, interface, foundation, in that
order) before anything is assembled. A failed extraction anywhere raises the existing
`ValidationError`; nothing is partially built. Only then are concept collision groups evaluated
(see *Duplicate identity policy*), still before any node or relation is assembled.

**Empty input.** Empty successful input (no arguments, or four empty sequences) returns an empty
`KnowledgeGraph()`.

**Purity.** Input records and the architecture graph are only read, never mutated. Output does
not depend on the order of the input sequences.

## Node mapping

Identifiers always come from the frozen helpers in `base.py`. Because the identifier scheme
namespaces every node by kind, the same name may exist as a symbol, an interface, and a capability
in one file without colliding.

**One node per distinct accepted identity.** A concept node stands for one *distinct accepted
identity*, not for one input record: records that share a node identifier are grouped and then
either coalesced into one node or rejected (see *Duplicate identity policy*). The frozen
`KnowledgeGraphBuilder` docstring in `base.py` says the nodes “cover every recognized concept”;
under this policy that means every distinct accepted identity is represented exactly once, so the
node count can be smaller than the number of input records. `base.py` is frozen and is
deliberately not edited to say so; this document is where that semantics is recorded.

| Kind | Identifier | Label | `relative_path` | Attributes |
|---|---|---|---|---|
| `ENTITY` | `entity_node_id(relative_path=path)` | the path | the path | `()` |
| `SYMBOL` | `symbol:` + `ExtractedSymbol.qualified_name` | `symbol.name` | `symbol.relative_path` | `("kind=<kind>",)`, where `<kind>` is `class`, `function`, `method`, `constant`, or `property` |
| `PATTERN` | `pattern_node_id(relative_path, subject_name, name)` | `pattern.name` | `pattern.relative_path` | `("description=…", "evidence=…", …)` |
| `INTERFACE` | `interface_node_id(relative_path, name)` | `interface.name` | `interface.relative_path` | `("origin=<origin>", "method_signature=…", …)` |
| `CAPABILITY` | `capability_node_id(relative_path, name)` | `candidate.name` | `candidate.relative_path` | `candidate.signals`, verbatim |
| `PACKAGE` | `package_node_id(package_node)` | `PackageNode.node_id` | `None` | `("has_package_root_file=true\|false",)` |

**Symbols.** The identifier suffix is the DTO's own, already-qualified `qualified_name`, used
verbatim (via the base module's `_node_id` namespacing helper, because the public
`symbol_node_id` can only rebuild a qualified name from an owner and name — which would mean
reconstructing method ownership). A unit test checks that a method's identifier equals the frozen
`symbol_node_id(relative_path=…, name=…, owner=…)` result.

**Interface properties.** A TypeScript interface property reaches the graph through the existing
symbol flow, with no change to the builder, the identity helpers, or the node and relation kinds.
The symbol extractor emits it as an `ExtractedSymbol` of kind `ExtractedSymbolKind.PROPERTY` whose
`qualified_name` is qualified by its interface (`ports.ts::User.id`), and the builder maps it like
any other symbol:

- It becomes a `SYMBOL` node, identified by `symbol:` + the preserved qualified name
  (`symbol:ports.ts::User.id`), labeled with the property's own name (`id`), carrying the file's
  `relative_path`, with the single attribute `kind=property`.
- Its file's entity receives the normal `DECLARES` relation to it, exactly one per node.
- There is no property-specific node kind and no property-specific relation kind.
- Same-named properties of different interfaces (`Reader.id` and `Writer.id`) are different
  identities and therefore different nodes.
- Only the node projection above is carried. A property's type, `?` optionality, and `readonly`
  status are not fields of `ExtractedSymbol`, so they do not reach the graph; its line number is on
  the symbol but, as for every symbol, is not projected into the node.
- The duplicate identity policy applies unchanged. Equivalent property records (same qualified
  name, name, kind, and path) coalesce into one node; a property and a method with the same owner
  and name differ in declaration kind and are rejected as a conflict.

Only TypeScript produces interface properties, because only `TypeScriptParser` reports interface
properties; see `docs/extractor_symbols_summary.md`.

**Entities.** One per distinct file path, collected from: every result's `relative_path` in all
four sequences (including successful results with no concepts); every concept's own
`relative_path`; and, when an architecture graph is supplied, every path in every
`PackageNode.file_paths`. For results produced by the real extractors a concept's path always
equals its result's path; if constructed data ever disagrees, the concept's own path owns it
(see `DECLARES`) and both paths get an entity.

**Packages.** Emitted only when `architecture_graph` is supplied, one per `PackageNode`. The
repository-root package has `node_id == ""`, so its identifier is `package:` and its label is the
empty string. Package nodes are **not** deduplicated by the builder: two `PackageNode`s whose
`node_id` collide still fail the frozen `KnowledgeGraph` validator with its existing error and empty
`details`.

## Attribute encoding

`KnowledgeNode.attributes` is a tuple of strings. Where the builder adds an encoding it is
`"<key>=<value>"`, split on the first `"="`, in a fixed order:

- `SYMBOL`: exactly one entry, `kind=class`, `kind=function`, `kind=method`, `kind=constant`, or
  `kind=property` (the `ExtractedSymbolKind` value). `kind=property` is used for TypeScript
  interface properties.
- `PATTERN`: `description=<description>` first, then one `evidence=<item>` per evidence item, in
  the original order.
- `INTERFACE`: `origin=<InterfaceOrigin value>` (`language_interface`, `trait`, or
  `abstract_class`) first, then one `method_signature=<name>` per method signature, in the
  original order. Base interfaces are **not** encoded as attributes; they are `EXTENDS`
  relations.
- `CAPABILITY`: the candidate's `signals`, exactly and unprefixed. The builder never creates,
  infers, or invents a signal. A candidate with no signals (which is every candidate the current
  Foundation extractor produces) has empty attributes.
- `PACKAGE`: `has_package_root_file=true` or `has_package_root_file=false`.
- `ENTITY`: empty.

Details the contract does not ask to carry are not carried: line numbers, `FoundationCandidate`'s
`kind`/`is_public`/`has_docstring`, and `ExtractedInterface.line_number`. These are exactly the
fields whose per-declaration values coalescing cannot preserve (see below).

## Relations

- **`DECLARES`** — from the entity of a concept's `relative_path` to every symbol, pattern,
  interface, and capability node found in that file. Exactly one per concept node -- a coalesced
  node has one, however many declarations it stands for.
- **`BELONGS_TO_PACKAGE`** — for each path in a `PackageNode.file_paths`, from that file's entity
  to the package node. Omitted entirely without an architecture graph.
- **`EXTENDS`** — one per entry in each interface's `base_interfaces`; see below.

## Base-interface resolution (exact name only)

For each `base_interfaces` entry:

1. If **exactly one** extracted interface, across all of `interface_results` (any file), has a
   `name` exactly equal to the entry, the relation targets that interface's node.
2. Otherwise — no match, or more than one match — it targets
   `interface:external::<base-name>`.

Matching is case-sensitive, whitespace-sensitive, and unqualified: `"base"`, `"pkg.Base"`, and
`" Base"` never match an interface named `Base`. There is no import resolution, module-path
inference, ranking, or tie-breaking; an ambiguous name is never resolved to any candidate (both
candidate nodes still exist). Targets of the `interface:external::…` form are not nodes; the frozen
`KnowledgeGraph` validator permits an `EXTENDS` target to be absent. Consequences worth knowing:

- A base name repeated within one interface produces a repeated relation. Nothing is
  deduplicated.
- An interface whose own name is the only match for one of its bases resolves to itself; there is
  no self-exclusion.
- A real file whose path is literally `external` and that declares an interface `X` would produce
  the same identifier as the external reference for a base named `X`. This follows from the frozen
  identifier scheme and is not special-cased.

## Duplicate identity policy

Concept records are grouped by `(node kind, node identifier)` across **every** entry of every
successful input sequence, using the frozen identifier helpers; a group is exactly the set of
records that would otherwise produce the same node. A group of one record is emitted unchanged. A
multi-record group is resolved **as a whole** -- coalesced or rejected -- with no partial
coalescing, representative selection, majority rule, or precedence: a group `{A, A, B}` is rejected
entirely.

### Equivalence keys and projections

| Kind | Identity (unchanged) | Complete equivalence key | Ignored | Multi-record group |
|---|---|---|---|---|
| `SYMBOL` | `symbol:` + `qualified_name` | `(qualified_name, name, kind, relative_path)`; `kind` compared as the `ExtractedSymbolKind` member | `line_number` | coalesced only if every member has the same key |
| `CAPABILITY` | `capability_node_id(relative_path, name)` | `(relative_path, name, kind, signals)`; `kind` compared as the `FoundationCandidateKind` member, `signals` as an ordered tuple | `is_public`, `has_docstring`, `line_number` | coalesced only if every member has the same key |
| `INTERFACE` | `interface_node_id(relative_path, name)` | none | — | always rejected, identical records included |
| `PATTERN` | `pattern_node_id(relative_path, subject_name, name)` | none | — | always rejected, identical records included |

The node projections are unchanged: a `SYMBOL` node is identified by `qualified_name`, labeled with
`name`, carries `relative_path`, and has the single attribute `kind=<value>`; a `CAPABILITY` node is
identified by `capability_node_id(relative_path, name)`, labeled with `name`, carries
`relative_path`, and has `signals` as its attributes. A coalesced group yields **one** node built
from its equivalence key through that same projection, so it is identical to the node a singleton
record with that key would produce -- no source record is chosen or copied -- plus **exactly one**
`DECLARES` relation from the file's entity.

- **The candidate `kind` is an explicit guard.** It is not part of the `CAPABILITY` node
  projection, yet a class and a function that share an identifier are conflicting records, not
  equivalent ones. (A class and a constant sharing a symbol identifier likewise differ in `kind`.)
- **Identifier equality is necessary but not sufficient.** Identifiers join path and name with a
  delimiter, so different `(relative_path, name)` pairs can produce one identifier:
  `("a::b", "c")` and `("a", "b::c")` both give `capability:a::b::c`. Because the *complete* key is
  compared, such a pair is a conflict (differing in `name` and `relative_path`), never a coalesced
  node.
- **`signals` order matters.** `("a", "b")` and `("b", "a")` are different keys.

### Rejection and diagnostics

Collision groups are evaluated across all four concept families before anything is assembled; every
rejected group is collected and **one** `ValidationError` is raised, so no partial graph is ever
returned. The message is

```
KnowledgeGraph: nodes must not contain duplicate identifiers; {count} colliding identifier(s) rejected: {listed}
```

where `count` is the number of rejected groups and `listed` is the first five rejected identifiers
in ascending order, each in single quotes and joined by `", "`, followed by ` (and {count-5} more)`
when there are more than five. The prefix is byte-identical to the frozen `KnowledgeGraph`
duplicate-identifier message. `details` is JSON-safe (strings, integers, booleans, lists):

```
{"collision_count": <int>,
 "collisions": [  # ordered by identifier
   {"identifier": ..., "node_kind": "symbol"|"capability"|"interface"|"pattern",
    "reason": "conflicting_records"|"coalescing_not_permitted",
    "differing_fields": [...], "records": [...]}]}
```

- `reason` is `conflicting_records` for a non-equivalent `SYMBOL`/`CAPABILITY` group and
  `coalescing_not_permitted` for any `INTERFACE`/`PATTERN` collision.
- `differing_fields` names, in ascending order, the key fields with more than one distinct value in
  the group; the DTO field `kind` is reported as `declaration_kind` (compared as the enum member,
  serialized as `.value`). It is never empty for a `SYMBOL`/`CAPABILITY` conflict, never contains
  `qualified_name` for a `SYMBOL` group (it determines the identifier), and is `[]` for
  `INTERFACE`/`PATTERN`.
- `records` lists **every** member, in canonical order (ascending by line number first, then the
  remaining fields), so the diagnostic does not depend on input order. Record fields, in order:
  `SYMBOL` — `qualified_name`, `name`, `declaration_kind`, `relative_path`, `line_number`;
  `CAPABILITY` — `name`, `declaration_kind`, `relative_path`, `signals`, `is_public`,
  `has_docstring`, `line_number`; `INTERFACE` — `name`, `origin`, `relative_path`,
  `method_signatures`, `base_interfaces`, `line_number`; `PATTERN` — `name`, `subject_name`,
  `relative_path`, `description`, `evidence`, `line_number`. Enums are serialized as `.value`,
  tuples as lists.

Example: a Python class `Foo` (line 1) and a function `Foo` (line 4) in `m.py`, each appearing in
both the symbol and foundation results, give the message `... 2 colliding identifier(s) rejected:
'capability:m.py::Foo', 'symbol:m.py::Foo'`, both with `conflicting_records` and
`differing_fields == ["declaration_kind"]`, the class listed before the function.

A package identifier collision is not a concept collision: it keeps the existing `KnowledgeGraph`
error and empty `details`. Because concept collisions are evaluated before assembly, a build with
both reports the concept collision.

### Coalescing and what it loses

Coalescing discards what the node does not carry: **how many source declarations there were**, and
each declaration's line number, `is_public`, and `has_docstring`. One node must therefore never be
read as one source declaration -- an overloaded function, a property getter/setter pair, a repeated
Go `init`, and a function declared once are all one node. The extractors' own output remains the
record of source declarations.

Supplying the same successful result twice therefore produces the same graph as supplying it once
for equivalent `SYMBOL`/`CAPABILITY` records, but a WARNING that counts all supplied declarations
(see below). If the doubled result contains an `INTERFACE` or `PATTERN`, its collision still
rejects the whole build. This asymmetry is deliberate and follows from the policy: only `SYMBOL`
and `CAPABILITY` groups may be coalesced, while `INTERFACE` and `PATTERN` collisions are never
coalesced, identical records included.

### Logging (best-effort)

Coalescing is logged per AM-8, best-effort: ordinary exceptions raised by logging do not change the
graph or whether it is returned (AM-8.1).

Logging uses the existing `get_logger("graph.knowledge.structural")` (logger
`vaos.graph.knowledge.structural`) and happens only after the graph is fully assembled and
validated, immediately before it is returned, and only if at least one `SYMBOL`/`CAPABILITY` group
was coalesced. A rejected or failed build logs nothing. It emits one aggregate WARNING:

```
Coalesced %d colliding node group(s) covering %d declaration(s): symbol=%d group(s)/%d declaration(s), capability=%d group(s)/%d declaration(s); declaration multiplicity and metadata outside the node projection are not preserved
```

The declaration total is the **sum of the coalesced groups' sizes** (a group of three contributes
three), not the number of records removed; zero counts are shown. When DEBUG is enabled it then
emits one DEBUG record per coalesced group in ascending identifier order, with members in canonical
order, e.g. `Coalesced symbol:m.py::A.x (symbol): 2 declaration(s); line_numbers=[3, 7]` and
`Coalesced capability:m.py::f (capability): 3 declaration(s); line_numbers=[4, 6, 8];
is_public=[False, False, False]; has_docstring=[False, False, True]`.

**Exception boundary.** Every count and payload is computed before the guarded region; the guarded
region contains only the DEBUG enablement check and the logging calls, and catches `Exception`
only. An ordinary exception raised by logging (a handler's `emit`, a handler or logger filter, ...)
is suppressed without re-raising, re-logging, or any alternative reporting, and the remaining log
calls for that build are skipped. Exceptions that derive from `BaseException` but not from
`Exception` (`KeyboardInterrupt`, `SystemExit`, ...) are **not** suppressed and may prevent the
graph from being returned. Extraction checks, collision evaluation, diagnostics, assembly, and
`KnowledgeGraph` validation are never inside the guarded region. For identical successful input the
returned graph and its `to_mapping()` are identical regardless of log level, DEBUG enablement, or
ordinary `Exception` failures from logging (AM-8.9). Logging is best-effort: WARNING/DEBUG records
may be missing or incomplete if the logging subsystem itself fails. `src/core/logging.py` is
unchanged and no logging infrastructure was added.

### Entities, packages, and relations

- **Entities** are deduplicated by path, including paths contributed by coalesced records: one
  entity per distinct path.
- **Packages** are not deduplicated by the builder; one node per `PackageNode`, and a colliding
  package identifier still fails the frozen validator.
- **Identity helpers and relation semantics are unchanged.** All identifiers still come from the
  frozen helpers in `base.py`. No general relation deduplication was introduced: `EXTENDS` still
  yields one relation per `base_interfaces` entry (a repeated base name gives a repeated relation),
  `BELONGS_TO_PACKAGE` is unchanged, and sorting and uniqueness validation are the frozen
  `KnowledgeGraph`'s.
- `KnowledgeGraph(nodes=(n, n))` constructed directly still rejects the duplicate; only this
  builder resolves identity groups before constructing the graph.

### Deliberate mismatch with `foundation.comparer.build_subjects`

`foundation.comparer.build_subjects` is unchanged and still **rejects** two candidates that share a
`(relative_path, name)` subject identity. The Knowledge Graph builder instead **coalesces**
equivalent candidates and rejects only conflicting ones. The two are separate aggregation layers
with separate contracts: a candidate set the Knowledge Graph accepts (for example, overloads) can
still be refused by `build_subjects`. See `docs/extractor_foundation_summary.md`.

## Determinism and sorting

`nodes` are sorted by `identifier`; `relations` are sorted by `(source, target, kind.value)` —
exactly the orderings the frozen `KnowledgeGraph` validator requires. Output is identical across
repeated builds, across independent analysis runs, and for any permutation of the input
sequences, of the result entries within them, and of the records within each result. Collision
diagnostics and log records are ordered the same way, so a rejected input produces identical
message text and `details` however it is arranged.

## Optional architecture graph

`architecture_graph=None` (the default) yields no `PACKAGE` nodes and no `BELONGS_TO_PACKAGE`
relations. When supplied, every package becomes a node (including ancestor-only packages with no
files), and every file it lists becomes an entity even if no extraction result represents it. An
empty `ArchitectureGraph()` contributes nothing.

## Explicitly excluded

Not implemented, by design: wiring into `analysis_steps.py`, the pipeline, bootstrap, or the CLI;
cycle detection; scoring, ranking, or selection; any analysis or inference; persistence;
serialization formats beyond the existing `KnowledgeGraph.to_mapping`; API surfaces; CLI output;
import or module resolution; path normalization; relation deduplication; any merging of concept records beyond the exact-key
coalescing described under *Duplicate identity policy* (no representative selection, majority rule,
or precedence); and a concrete Pattern Extractor (the integration test passes `pattern_results=()`, and non-empty
pattern mapping is tested at unit level with constructed `PatternExtractionResult` data).

## Files

- `src/graph/knowledge/structural.py` — the builder.
- `tests/unit/graph/knowledge/test_structural.py` — unit tests over constructed DTOs, including
  property symbols (`kind=property`, identity, `DECLARES`, same-named properties of different
  interfaces, and their place in the duplicate identity policy).
- `tests/integration/test_knowledge_graph.py` — real temporary Git repository, real parsers and
  extractors, builder invoked directly on the composition's results with its architecture graph;
  includes real TypeScript interface properties flowing into `SYMBOL` nodes.
- `tests/integration/test_knowledge_graph_coalescing.py` — the duplicate identity policy over real
  parsers (Python, Go, Rust, TypeScript, C++) and, with a real temporary Git repository, the real
  composition: one accepted fixture (every duplicate coalesces) and one non-equivalent conflict
  fixture (rejected deterministically).
