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

- Full suite: `1962 passed, 1 skipped, 1 warning` in 70.13 seconds.
- Ruff over `src/` and `tests/`: passed.
- MyPy strict over `src/parsers` and `src/repository`: passed.
- `git diff --check`: passed.
- The warning is the existing Starlette/httpx TestClient deprecation notice; it did not fail tests.

## Remaining risks and next gate

1. Validate against independent, representative repositories for each supported language.
2. Measure declaration/import recall and unsupported-file rates on those repositories.
3. Re-run Knowledge Graph construction and check collision/error frequency across those inputs.
4. Keep the Knowledge Graph step opt-in until that evidence is available.

The current VAOS run had no Knowledge Graph collision. One successful run is not sufficient evidence
to enable the step by default.
