# ADR-0001: Knowledge Graph declaration identity

- Status: Accepted for the current structural graph; revisit when a consumer requires declaration-level queries.
- Date: 2026-10-27

## Context

The structural Knowledge Graph currently uses stable, path-qualified identities. Multiple source declarations can therefore map to one symbol or capability node. This occurs for language constructs such as overloads, property accessor pairs, repeated declarations, and repeated extractor records.

The builder coalesces symbol records only when their complete identity keys match. It coalesces capability records only when their path, name, declaration kind, and ordered signals match. Conflicting groups are rejected. Interface and pattern collisions are rejected rather than coalesced. The extractor results remain the source of declaration-level details.

This policy means the graph is a structural view of distinct accepted identities, not a complete inventory of source declarations. Coalescing does not preserve declaration count or each declaration's line number; capability-node projection also omits per-declaration visibility and docstring flags.

## Decision

Keep the current one-node-per-distinct-accepted-identity policy for the structural Knowledge Graph.

Do not change frozen node-ID helpers or the graph DTO contract as part of this decision. Keep the Knowledge Graph opt-in and do not wire it into the default analysis pipeline until its consumers and declaration-level requirements are defined.

Consumers that need exact declaration counts, source locations, overload signatures, or per-declaration metadata must use the extraction results. They must not interpret one graph node as one source declaration.

## Alternatives considered

1. **One node per distinct accepted identity (chosen).** Preserves current identifiers and graph contract, supports deterministic aggregation, and keeps the graph compact. The trade-off is loss of declaration multiplicity and metadata not projected onto nodes.
2. **One node per source declaration.** Preserves declaration-level identity but requires a new identity scheme, DTO/relationship review, migration of graph consumers, and explicit rules for overloads and declarations that share a qualified name.
3. **Keep aggregated nodes and attach declaration records.** Could retain compact topology while preserving source locations and signatures, but requires a versioned declaration model and serialization/API decisions.

## Consequences

- Current node identifiers and coalescing behavior remain unchanged.
- Extractor outputs, not the graph, are authoritative for declaration multiplicity and per-declaration metadata.
- The graph remains opt-in. High coalescing counts in real repositories are a signal to review consumer needs, not by themselves proof of incorrect parser output.
- Before enabling the graph by default, add consumer-driven requirements and tests for declaration counts, source locations, overload signatures, and graph/extractor consistency.
- If declaration-level queries become a requirement, revisit this ADR and compare per-declaration nodes against attached declaration records before changing identifiers.

## Validation

The structural graph unit tests and real-parser coalescing integration tests pass. They cover equivalent and conflicting identities, deterministic diagnostics, node/relation behavior, and logging. These tests validate the chosen aggregation contract; they do not establish that aggregation is suitable for every future consumer.
