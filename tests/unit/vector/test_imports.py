"""Import verification for `src.vector`.

Every `vector` module must import cleanly on its own -- this is checked separately from
`test_dependency_boundaries.py`'s static analysis, which inspects import *statements* without
executing them.
"""

import importlib

import pytest


@pytest.mark.parametrize(
    "module_name",
    [
        "src.vector",
        "src.vector.base",
    ],
)
def test_vector_module_imports_successfully(module_name: str) -> None:
    """Every `vector` module should import without raising."""
    importlib.import_module(module_name)
