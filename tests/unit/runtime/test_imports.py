"""Import verification for `src.runtime`.

Every `runtime` module must import cleanly on its own -- this is checked separately from
`test_dependency_boundaries.py`'s static analysis, which inspects import *statements* without
executing them.
"""

import importlib

import pytest


@pytest.mark.parametrize(
    "module_name",
    [
        "src.runtime",
        "src.runtime.errors",
        "src.runtime.runtime",
    ],
)
def test_runtime_module_imports_successfully(module_name: str) -> None:
    """Every `runtime` module should import without raising."""
    importlib.import_module(module_name)
