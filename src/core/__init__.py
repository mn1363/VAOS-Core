"""Core layer: configuration, logging, exceptions, protocols, and utilities.

`core` is the innermost layer of VAOS's Clean Architecture. It has no
dependency on any other VAOS package, and every other layer may depend on
it. Each module here is self-contained and imported directly by its full
path (e.g. `from src.core.config import load_config`); this package
intentionally does not re-export a combined surface from `__init__.py`.
"""
