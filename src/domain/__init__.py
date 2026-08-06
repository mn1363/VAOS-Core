"""Domain layer: entities, DTOs, and persistence Ports.

`domain` is the second-innermost layer of VAOS's Clean Architecture. It
may depend on `core` (for the shared exception hierarchy) but not on
`application`, `infrastructure`, or any other layer. Each module here is
self-contained and imported directly by its full path (e.g.
`from src.domain.entities import SourceRepository`); this package
intentionally does not re-export a combined surface from `__init__.py`.
"""
