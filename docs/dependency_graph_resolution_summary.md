# Dependency Graph Resolution: `StructuralDependencyGraphBuilder`

Implements the frozen **Dependency Graph Resolution Contract v1** as the first concrete
`DependencyGraphBuilder` (`src/graph/dependency/structural.py`). It consumes
`ImportExtractionResult`s and returns one file-level `DependencyGraph`. It is zero-argument,
stateless, pure and deterministic. It performs no I/O, reads no source, parses nothing, inspects
no AST, detects no cycles, and is not wired into bootstrap or the CLI.

## Behavior

First action: `require_successful_extractions`. Then every input `relative_path` is validated and
indexed by a *normalized match key*.

**Language** is inferred only from the source suffix (case-insensitive, one closed table): Python
`.py .pyi`; TypeScript `.ts .tsx`; Go `.go`; Rust `.rs`; C++ `.cpp .cc .cxx .hpp .hh .hxx .h`.
This is classification, not parser dispatch.

**`is_internal`** (hybrid): upstream `True` is an *internal candidate* and resolves to
`INTERNAL_FILE` or `UNRESOLVED_INTERNAL`, never `EXTERNAL_MODULE`. Upstream `False` is
`EXTERNAL_MODULE`, except a Python absolute import that matches an input file. The output edge's
`is_internal` is `target.kind != EXTERNAL_MODULE`; the upstream flag is not copied.

**Identifiers:** `INTERNAL_FILE` = verbatim input path; `EXTERNAL_MODULE` = `external:` + raw
target; `UNRESOLVED_INTERNAL` = `unresolved:` + normalized would-be target, or (for `/x`)
`unresolved:/x`, or (Rust, root escape, non-path internal forms) `unresolved:` + normalized
source path + `#` + raw target.

### Per language

| Language | Rule |
|---|---|
| Python absolute | Dots become `/` from the repo root; candidates in order `P/__init__.py`, `P.py`, `P/__init__.pyi`, `P.pyi`; first input match wins, else `EXTERNAL_MODULE`. `from x import y` uses `x` only. |
| Python relative | `.x` resolves `dir/x`; N dots = N-1 parent hops; `from . import name` tries submodule candidates for `dir/name`, then the package root (`dir/__init__.py`, `dir/__init__.pyi`); no match is `UNRESOLVED_INTERNAL`; root escape is `UNRESOLVED_INTERNAL`. |
| TypeScript | Internal `./x`, `../x`: candidates exact, `.ts`, `.tsx`, `index.ts`, `index.tsx`; no match is unresolved. `/x` is always `unresolved:/x`. All upstream-`False` (aliases, bare packages) are external. |
| Go | Never `INTERNAL_FILE`. `./x`, `../x` are `unresolved:` + would-be directory; module paths are external. |
| Rust | Never `INTERNAL_FILE`. `crate`/`self`/`super` forms are source-qualified unresolved; bare paths are external. |
| C++ | Quoted include resolves relative to the includer's directory by exact match, else unresolved; angle includes and C++20 `import` are external. |

### Paths

Normalization (`\` to `/`, `.`/`..` lexical, duplicate and trailing separators collapsed,
case-sensitive) is used only for matching keys and unresolved payloads. `INTERNAL_FILE`
identifiers and raw external text are never rewritten, which keeps the existing platform-native
(Windows) `_enumerate_files` paths working unchanged.

### Inputs

Rejected with `ValidationError`: a failed extraction; a blank, absolute, drive-prefixed or
root-escaping input path; a path beginning `external:` or `unresolved:`; duplicate paths including
normalization-equivalent ones; a blank `target_module`. Edges are never deduplicated. Every
successful input file is a node, even with zero edges; `build(())` is `DependencyGraph()`.
Edges sort by `(source, target, line_number, imported_names, alias is not None, alias or "")`.

## Cases the frozen text did not spell out

These follow the nearest frozen rule and are listed for Project Manager visibility:

1. A source suffix outside the language table has no language rule: upstream `True` becomes
   source-qualified `UNRESOLVED_INTERNAL`, upstream `False` becomes external.
2. Edge `source` is the result's `relative_path`; `edge.source_path` is not cross-checked.
3. "Package-root candidates" for `from . import name` means `dir/__init__.py` then
   `dir/__init__.pyi` only. The unresolved payload is `dir/name` (single simple name) else `dir`.
4. TypeScript `.`/`..` are relative specifiers; other internal-flagged forms with no normalizable
   path (e.g. `.foo`), root-escaping Go/TS/C++ targets, and absolute quoted C++ includes use the
   source-qualified unresolved form.
5. A blank `target_module` is rejected explicitly, because the prefix means the DTO's blank
   identifier check could never fire.
6. A malformed dotted Python module (empty component) is treated as external.

## Port amendment

`src/graph/dependency/base.py`: docstrings only (edge `is_internal` is derived from the final
target kind; `INTERNAL_FILE` includes every successful input file; `external:`/`unresolved:`
identifier prefixes; `EXTERNAL_MODULE` no longer implies known third-party/stdlib). No field,
signature, validator, dataclass or enum changed.

## Tests

`tests/unit/graph/dependency/test_structural.py` covers every contract rule with hand-built
inputs, including backslash paths. `tests/integration/test_dependency_graph.py` runs the real
composition (real enumeration, five parsers, `StructuralImportExtractor`) over a small local git
repository and builds the graph from the real `import_results`; assertions are platform-aware.
