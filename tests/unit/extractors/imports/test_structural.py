"""Unit tests for `src.extractors.imports.structural`.

Each of the five language-specific cases below parses a small, real source snippet with one of
the five existing concrete `Parser` implementations, then runs the resulting real `ParseResult`
through a single, shared `StructuralImportExtractor` instance -- proving one implementation
handles every language, not five per-language variants.
"""

import pytest
from src.core.exceptions import ValidationError
from src.domain.entities import SourceLanguage
from src.extractors.imports.base import ImportExtractor
from src.extractors.imports.structural import StructuralImportExtractor
from src.parsers.base import ParseResult
from src.parsers.cpp.parser import CppParser
from src.parsers.go.parser import GoParser
from src.parsers.python.parser import PythonParser
from src.parsers.rust.parser import RustParser
from src.parsers.typescript.parser import TypeScriptParser


def _failed_parse_result(relative_path: str = "a.py") -> ParseResult:
    """Build a minimal, failed `ParseResult` for use in extraction tests."""
    return ParseResult.failed(
        relative_path=relative_path, language=SourceLanguage.PYTHON, error_message="bad syntax"
    )


# --- one implementation, five languages, all real parser output --------------------------


def test_python_import_produces_expected_edge() -> None:
    """A real `import ... as ...` statement, parsed by the real `PythonParser`, maps exactly."""
    parse_result = PythonParser().parse(relative_path="a.py", content="import numpy as np\n")
    result = StructuralImportExtractor().extract(parse_result)

    assert result.succeeded is True
    assert len(result.edges) == 1
    edge = result.edges[0]
    assert edge.source_path == "a.py"
    assert edge.target_module == "numpy"
    assert edge.imported_names == ()
    assert edge.alias == "np"
    assert edge.is_internal is False
    assert edge.line_number == 1


def test_rust_import_produces_expected_edge() -> None:
    """A real external `use` statement, parsed by the real `RustParser`, maps exactly."""
    parse_result = RustParser().parse(relative_path="a.rs", content="use serde::Serialize;\n")
    result = StructuralImportExtractor().extract(parse_result)

    assert result.succeeded is True
    assert len(result.edges) == 1
    edge = result.edges[0]
    assert edge.source_path == "a.rs"
    assert edge.target_module == "serde"
    assert edge.imported_names == ("Serialize",)
    assert edge.is_internal is False
    assert edge.line_number == 1


def test_go_import_produces_expected_edge() -> None:
    """A real single-line `import` statement, parsed by the real `GoParser`, maps exactly."""
    parse_result = GoParser().parse(
        relative_path="a.go", content='package main\n\nimport "fmt"\n'
    )
    result = StructuralImportExtractor().extract(parse_result)

    assert result.succeeded is True
    assert len(result.edges) == 1
    edge = result.edges[0]
    assert edge.source_path == "a.go"
    assert edge.target_module == "fmt"
    assert edge.alias is None
    assert edge.is_internal is False
    assert edge.line_number == 3


def test_typescript_import_produces_expected_edge() -> None:
    """A real named-import statement, parsed by the real `TypeScriptParser`, maps exactly."""
    parse_result = TypeScriptParser().parse(
        relative_path="a.ts", content="import { useState } from 'react';\n"
    )
    result = StructuralImportExtractor().extract(parse_result)

    assert result.succeeded is True
    assert len(result.edges) == 1
    edge = result.edges[0]
    assert edge.source_path == "a.ts"
    assert edge.target_module == "react"
    assert edge.imported_names == ("useState",)
    assert edge.is_internal is False
    assert edge.line_number == 1


def test_cpp_import_produces_expected_edge() -> None:
    """A real angle-bracket `#include`, parsed by the real `CppParser`, maps exactly."""
    parse_result = CppParser().parse(relative_path="a.cpp", content="#include <vector>\n")
    result = StructuralImportExtractor().extract(parse_result)

    assert result.succeeded is True
    assert len(result.edges) == 1
    edge = result.edges[0]
    assert edge.source_path == "a.cpp"
    assert edge.target_module == "vector"
    assert edge.is_internal is False
    assert edge.line_number == 1


def test_single_extractor_instance_handles_all_five_languages() -> None:
    """One `StructuralImportExtractor` instance, reused, succeeds against all five parsers."""
    extractor = StructuralImportExtractor()
    cases: tuple[tuple[ParseResult, str], ...] = (
        (PythonParser().parse(relative_path="a.py", content="import os\n"), "os"),
        (RustParser().parse(relative_path="a.rs", content="use std::fmt;\n"), "std"),
        (GoParser().parse(relative_path="a.go", content='import "fmt"\n'), "fmt"),
        (
            TypeScriptParser().parse(
                relative_path="a.ts", content="import { z } from 'zod';\n"
            ),
            "zod",
        ),
        (CppParser().parse(relative_path="a.cpp", content="#include <string>\n"), "string"),
    )
    for parse_result, expected_module in cases:
        result = extractor.extract(parse_result)
        assert result.succeeded is True
        assert result.edges[0].target_module == expected_module


# --- internal vs. external -----------------------------------------------------------------


def test_relative_import_is_marked_internal() -> None:
    """A real relative Python import maps to `is_internal=True`."""
    parse_result = PythonParser().parse(
        relative_path="pkg/mod.py", content="from .sibling import widget\n"
    )
    result = StructuralImportExtractor().extract(parse_result)

    assert result.edges[0].is_internal is True
    assert result.edges[0].target_module == ".sibling"
    assert result.edges[0].imported_names == ("widget",)


def test_external_import_is_marked_external() -> None:
    """A real absolute Python import maps to `is_internal=False`."""
    parse_result = PythonParser().parse(relative_path="mod.py", content="import requests\n")
    result = StructuralImportExtractor().extract(parse_result)

    assert result.edges[0].is_internal is False


def test_cpp_quoted_include_is_marked_internal() -> None:
    """A real quoted `#include`, parsed by the real `CppParser`, maps to `is_internal=True`."""
    parse_result = CppParser().parse(relative_path="a.cpp", content='#include "myheader.h"\n')
    result = StructuralImportExtractor().extract(parse_result)

    assert result.edges[0].is_internal is True
    assert result.edges[0].target_module == "myheader.h"


# --- empty, duplicates, ordering -----------------------------------------------------------


def test_empty_imports_produces_empty_edges() -> None:
    """A file with no import statements produces a successful, empty result."""
    parse_result = PythonParser().parse(relative_path="a.py", content="x = 1\n")
    result = StructuralImportExtractor().extract(parse_result)

    assert result.succeeded is True
    assert result.edges == ()


def test_duplicate_imports_are_preserved() -> None:
    """The same module, imported twice, produces two edges -- not merged into one.

    Each occurrence is a genuinely distinct statement at its own source line, so the two edges
    correctly differ in `line_number`; what this proves is that neither edge is dropped as a
    "duplicate" of the other.
    """
    parse_result = PythonParser().parse(
        relative_path="a.py", content="import os\nimport os\n"
    )
    result = StructuralImportExtractor().extract(parse_result)

    assert len(result.edges) == 2
    assert [edge.target_module for edge in result.edges] == ["os", "os"]
    assert [edge.line_number for edge in result.edges] == [1, 2]


def test_edge_order_matches_input_order() -> None:
    """Edges are produced in the file's own import order, not re-sorted."""
    parse_result = PythonParser().parse(
        relative_path="a.py", content="import zeta\nimport alpha\nimport middle\n"
    )
    result = StructuralImportExtractor().extract(parse_result)

    assert [edge.target_module for edge in result.edges] == ["zeta", "alpha", "middle"]


# --- failure behavior ------------------------------------------------------------------------


def test_failed_parse_result_raises_validation_error() -> None:
    """A failed `ParseResult` raises `ValidationError` via `require_successful_parse`, unchanged."""
    with pytest.raises(ValidationError):
        StructuralImportExtractor().extract(_failed_parse_result())


def test_structural_import_extractor_is_an_import_extractor() -> None:
    """`StructuralImportExtractor` is a genuine `ImportExtractor`, not just structurally similar."""
    assert isinstance(StructuralImportExtractor(), ImportExtractor)
