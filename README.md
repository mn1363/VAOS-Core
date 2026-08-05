# VAOS -- Phase 1 Core Skeleton

Architecture-only implementation skeleton for VAOS: interfaces, dataclasses,
and wiring, with no business, extraction, analysis, or scoring logic.

## Requirements

- Python 3.13
- Clean Architecture, SOLID, dependency injection, async-first, type hints everywhere

## Layout

See `docs/architecture.md` for the full folder tree, dependency graph, and
bootstrap order.

## Getting started

```bash
bash scripts/dev_setup.sh
bash scripts/run_api.sh             # start the API
bash scripts/run_cli.sh --version   # exercise the CLI
pytest                              # run the test suite
```
