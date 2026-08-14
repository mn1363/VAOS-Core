"""Import verification for `src.foundation`.

Every `foundation` module must import cleanly on its own -- this is checked separately from
`test_dependency_boundaries.py`'s static analysis, which inspects import *statements* without
executing them.
"""

import importlib

import pytest


@pytest.mark.parametrize(
    "module_name",
    [
        "src.foundation",
        "src.foundation.comparer",
        "src.foundation.comparer.base",
        "src.foundation.ranking",
        "src.foundation.ranking.base",
        "src.foundation.selector",
        "src.foundation.selector.base",
        "src.foundation.merger",
        "src.foundation.merger.base",
        "src.foundation.exporter",
        "src.foundation.exporter.base",
    ],
)
def test_foundation_module_imports_successfully(module_name: str) -> None:
    """Every `foundation` module should import without raising."""
    importlib.import_module(module_name)
