"""Foundation layer: transforms the results of the previous analysis/graph stages into reusable
Foundation decisions.

`foundation` answers "which already-extracted candidate capabilities/components, across one or
more analyzed repositories, are actually worth reusing, and what does the reusable set built from
them look like?" -- deterministic pairwise comparison of candidates, deterministic scoring/
ranking, constraint- and compatibility-aware selection, coordinated merging of the selected,
mutually-compatible candidates into a single Foundation result, and export of that result into a
stable, deterministic external representation. It does not collect repositories, clone
repositories, parse source code, extract raw source information, perform low-level analysis,
create graphs, implement storage backends, implement vector databases, implement memory systems,
or execute pipelines -- those are `collectors`, `parsers`, `extractors`, `analyzers`, `graph`
(already built) or `storage`, `memory`, `vector`, `pipeline` (later, not-yet-built phases')
concerns.

Each of its five subpackages -- `comparer`, `ranking`, `selector`, `merger`, `exporter` --
defines exactly one Foundation contract in its own `base.py`: an abstract `Foundation...` Port
with a single method, the outcome/decision DTOs specific to that concern, and one or more small
`require_...` helpers validating that its own inputs are internally consistent before a concrete
implementation acts on them -- following the same defensive-validation idiom every
`extractors.*.base`/`analyzers.*.base`/`graph.*.base` module already established.

Every Foundation contract operates on `extractors.foundation.base.FoundationCandidate` -- the one
existing contract that already names "the raw, observable signals a later phase would want when
deciding what is worth reusing" and explicitly defers "combining them into a score" and
"selecting which candidates actually become part of a foundation" to this layer. `comparer/
base.py` defines `FoundationSubject`, pairing a `FoundationCandidate` with the identifier of the
repository it was found in (`repository_id: UUID`, matching `domain.entities.SourceFile.
repository_id`'s own field name and type rather than introducing a second repository-identity
scheme); every other subpackage imports `FoundationSubject` from there rather than redefining it,
the one deliberate intra-`foundation` sibling-import point this phase's own dependency rules
newly permit, mirroring `graph.knowledge` importing `PackageNode` from `graph.architecture` in
Phase 8.

`src.analyzers`, `src.graph`, and `src.domain` are each allowed dependencies for this whole
package but are deliberately unused throughout: every `analyzers.*.base` assessment/profile DTO
and `graph.knowledge.base.KnowledgeGraph`'s own `CAPABILITY` nodes already reduce a
`FoundationCandidate` to less detail than the candidate itself carries (dropping `is_public`,
`has_docstring`, and `FoundationCandidateKind`) -- exactly the same "already an aggregated
judgment, not additional detail" reasoning `graph.architecture`/`graph.dependency` used in Phase 8
to prefer extractor-level DTOs over analyzer-level ones. `src.domain` is likewise allowed but
unused: `FoundationSubject.repository_id` reuses `domain.entities.SourceFile`'s own field name and
`UUID` type without importing the entity itself, matching Phase 6's and Phase 8's own precedent
for this exact allowed-but-unused pattern.

Each module here is self-contained and imported directly by its full path (e.g. `from
src.foundation.selector.base import FoundationSelector`); this package intentionally does not
re-export a combined surface from `__init__.py`.
"""
