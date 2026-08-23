"""Import verification for `src.memory`.

Every `memory` module must import cleanly on its own -- this is checked separately from
`test_dependency_boundaries.py`'s static analysis, which inspects import *statements* without
executing them. Mirrors `tests/unit/vector/test_imports.py`'s own structure exactly.
"""

import importlib

import pytest


@pytest.mark.parametrize(
    "module_name",
    [
        "src.memory",
        "src.memory.base",
    ],
)
def test_memory_module_imports_successfully(module_name: str) -> None:
    """Every `memory` module should import without raising."""
    importlib.import_module(module_name)
