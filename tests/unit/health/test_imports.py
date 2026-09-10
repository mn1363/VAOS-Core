"""Import verification for `src.health`.

Every `health` module must import cleanly on its own -- this is checked separately from
`test_dependency_boundaries.py`'s static analysis, which inspects import *statements* without
executing them.
"""

import importlib

import pytest


@pytest.mark.parametrize(
    "module_name",
    [
        "src.health",
        "src.health.health",
    ],
)
def test_health_module_imports_successfully(module_name: str) -> None:
    """Every `health` module should import without raising."""
    importlib.import_module(module_name)
