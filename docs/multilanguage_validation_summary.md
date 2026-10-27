# Parser and Knowledge Graph Validation Summary

Date: 2026-10-27

## Scope

This validation follows commit `4861b1a` (`Improve parser coverage and cross-platform handling`).
It combines an analysis run against the checked-out VAOS repository with representative parser smoke
fixtures for all five supported languages. The fixtures are synthetic examples, not independent
third-party repositories; multi-repository validation remains open.

## Checked-out repository

The full analysis composition completed successfully:

- 350 files were enumerated.
- 305 files parsed successfully; all 305 were Python files.
- 45 files were retained as unsupported parse results: 37 Markdown, 3 text, 2 YAML, 1 TOML,
  1 `.example`, and 1 extensionless file. These are unsupported file types, not failed Python parses.
- With the opt-in Knowledge Graph step, the 17-step pipeline completed successfully.
- The Knowledge Graph contained 5,575 nodes and 5,623 relations.
- No identity-collision failure occurred in this run.

This is evidence for the current Python-heavy VAOS repository only. It does not establish parser
accuracy on large or idiomatic third-party repositories in TypeScript, Go, Rust, or C++.

## Cross-language smoke coverage

Added `tests/integration/test_multilanguage_parser_smoke.py`. It checks that each of the five
parsers can recognize a representative class-like declaration, function, and import from a small
source example:

- Python
- TypeScript
- Go
- Rust
- C++

Initial smoke run: 5/5 passed.
Parser unit suite: 178 passed.
Combined focused run (smoke plus parser unit tests): 183 passed.

The language parsers other than Python use lightweight structural scanning rather than full compiler
grammars. The smoke tests establish baseline dispatch and extraction only; they do not prove complete
language conformance.

## Verification

- Full suite after the filesystem branch fix: `1963 passed, 1 skipped, 1 warning` in 70.16 seconds.
- Ruff over `src/` and `tests/`: passed.
- MyPy strict over `src/parsers`, `src/repository`, and `src/collectors`: passed (22 source files).
- `git diff --check`: passed.
- The warning is the existing Starlette/httpx TestClient deprecation notice; it did not fail tests.

## Independent repository validation

Shallow clones of five public repositories plus VAOS itself were analyzed through the 17-step
composition with the opt-in Knowledge Graph step. The initial run exposed a branch assumption in
`FilesystemCollector`; the collector has since been updated to use the checked-out branch for a
Git-managed local repository. The Go and Rust pipelines were rerun successfully with their original
`master` branch names. Earlier measurements used temporary local branch renames only; source files
were not changed.

| Repository | Language | Enumerated files | Parsed successfully | Unsupported/failed results | Knowledge Graph nodes | Relations | Coalesced collision groups |
|---|---|---:|---:|---:|---:|---:|---:|
| VAOS checkout | Python | 350 | 305 | 45 | 5,575 | 5,623 | 0 warnings |
| `pallets/click` | Python | 164 | 91 | 73 | 2,414 | 2,416 | 26 groups / 92 declarations |
| `sindresorhus/is` | TypeScript | 16 | 5 | 11 | 175 | 174 | 4 groups / 36 declarations |
| `go-chi/chi` | Go | 108 | 89 | 19 | 761 | 760 | 0 warnings |
| `rust-lang/regex` | Rust | 409 | 228 | 181 | 6,926 | 6,925 | 239 groups / 679 declarations |
| `CLIUtils/CLI11` | C++ | 244 | 114 | 130 | 1,336 | 1,335 | 191 groups / 593 declarations |

All five external/local analysis pipelines completed, and all five language smoke fixtures passed.
The unsupported/failed column counts all unsuccessful `ParseResult` entries, including files that
the fixed five-parser dispatcher does not claim (for example, Markdown and configuration files).
It is not a source-language parser failure rate.

### Findings

- **Knowledge Graph remains opt-in.** Rust and C++ each emitted hundreds of coalesced collision
  groups. Python Click and the TypeScript repository also emitted warnings. A duplicate-symbol
  spot-check found same-qualified-name declarations at different source lines, including C++
  overloads and Rust methods in separate implementation blocks. This matches the builder's
  documented coalescing policy; it is not evidence of cross-file identifier collisions. However,
  the graph intentionally loses declaration multiplicity and per-declaration line metadata. Decide
  whether graph consumers need per-declaration identity before enabling this step by default.
- **Local-repository branch assumption — fixed.** `FilesystemCollector` now records the checked-out
  branch for a Git-managed directory and falls back to `main` for a plain folder. A regression test
  covers a repository whose branch is `develop`; the Go and Rust analysis pipelines also passed with
  their `master` branches.
- **Coverage is not yet accuracy.** These runs count parsed results and graph outputs; they do not
  establish recall/precision against an independently labeled inventory of declarations/imports.

## Remaining risks and next gate

1. Decide whether the Knowledge Graph should represent one node per qualified name or preserve
   per-declaration identity for overloads and repeated implementations.
2. Define and test acceptance thresholds for coalescing and declaration/line metadata loss.
3. Measure parser declaration/import accuracy against a labeled inventory, not only pipeline success.
4. Keep Knowledge Graph opt-in until those questions are resolved.
