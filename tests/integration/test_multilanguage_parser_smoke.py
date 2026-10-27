"""Cross-language parser smoke tests for representative source files.

These tests complement parser-specific unit tests. They verify that each registered language
parser can recognize imports and named declarations from a compact, realistic source example.
They are smoke fixtures, not a substitute for validation against independent public repositories.
"""

import pytest

from src.parsers.base import Parser
from src.parsers.cpp.parser import CppParser
from src.parsers.go.parser import GoParser
from src.parsers.python.parser import PythonParser
from src.parsers.rust.parser import RustParser
from src.parsers.typescript.parser import TypeScriptParser


@pytest.mark.parametrize(
    ("parser", "relative_path", "content", "expected_class", "expected_function", "expected_import"),
    [
        (
            PythonParser(),
            "src/service.py",
            "from pathlib import Path\n\n"
            "class Project:\n"
            "    def load_config(self, path: Path) -> str:\n"
            "        return path.read_text()\n\n"
            "def normalize(value: str) -> str:\n"
            "    return value.strip()\n",
            "Project",
            "normalize",
            "pathlib",
        ),
        (
            TypeScriptParser(),
            "src/service.ts",
            'import { readFile } from "node:fs/promises";\n'
            "export class UserService {\n"
            "  async getUser(id: string): Promise<string> { return id; }\n"
            "}\n"
            "export function normalize(input: string): string { return input.trim(); }\n",
            "UserService",
            "normalize",
            "node:fs/promises",
        ),
        (
            GoParser(),
            "internal/point.go",
            'package geometry\nimport "fmt"\n'
            "type Point struct { X int; Y int }\n"
            "func (p *Point) Move(dx int) { p.X += dx }\n"
            "func Add(a int, b int) int { return a + b }\n",
            "Point",
            "Add",
            "fmt",
        ),
        (
            RustParser(),
            "src/point.rs",
            "use std::fmt;\n"
            "pub struct Point { x: f64, y: f64 }\n"
            "impl Point { pub fn new(x: f64, y: f64) -> Self { Self { x, y } } }\n"
            "pub fn add(a: i32, b: i32) -> i32 { a + b }\n",
            "Point",
            "add",
            "std",
        ),
        (
            CppParser(),
            "src/point.cpp",
            "#include <vector>\n"
            "namespace geometry {\n"
            "class Point { public: Point(double x, double y); };\n"
            "int add(int a, int b) { return a + b; }\n"
            "}\n",
            "Point",
            "add",
            "vector",
        ),
    ],
    ids=("python", "typescript", "go", "rust", "cpp"),
)
def test_parser_extracts_core_constructs_across_languages(
    parser: Parser,
    relative_path: str,
    content: str,
    expected_class: str,
    expected_function: str,
    expected_import: str,
) -> None:
    """Each language parser should recognize a class-like declaration, function, and import."""
    result = parser.parse(relative_path=relative_path, content=content)

    assert result.succeeded is True, result.error_message
    assert expected_class in {item.name for item in result.classes}
    assert expected_function in {item.name for item in result.functions}
    assert expected_import in {item.module for item in result.imports}
