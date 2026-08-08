"""Unit tests for `src.parsers.python.parser`."""

import pytest
from src.core.exceptions import ValidationError
from src.domain.entities import SourceLanguage
from src.parsers.base import SymbolKind
from src.parsers.python.parser import PythonParser


def test_language_is_python() -> None:
    """`PythonParser.language` should report `SourceLanguage.PYTHON`."""
    assert PythonParser().language is SourceLanguage.PYTHON


@pytest.mark.parametrize("path", ["main.py", "package/__init__.py", "stub.pyi", "Main.PY"])
def test_supports_accepts_python_extensions(path: str) -> None:
    """`supports` should accept `.py` and `.pyi` files, case-insensitively."""
    assert PythonParser().supports(path) is True


@pytest.mark.parametrize("path", ["main.txt", "main.js", "main"])
def test_supports_rejects_non_python_extensions(path: str) -> None:
    """`supports` should reject files without a Python extension."""
    assert PythonParser().supports(path) is False


def test_parse_rejects_a_blank_relative_path() -> None:
    """`parse` should raise `ValidationError` for a blank `relative_path`."""
    with pytest.raises(ValidationError):
        PythonParser().parse(relative_path="  ", content="x = 1")


def test_parse_reports_failure_for_a_syntax_error() -> None:
    """`parse` should return a failed result, not raise, for invalid Python syntax."""
    result = PythonParser().parse(relative_path="bad.py", content="def foo(:\n    pass")

    assert result.succeeded is False
    assert result.metadata is None
    assert result.error_message is not None


def test_parse_succeeds_on_empty_content() -> None:
    """`parse` should succeed on an empty file, with zero size and zero lines."""
    result = PythonParser().parse(relative_path="empty.py", content="")

    assert result.succeeded is True
    assert result.metadata is not None
    assert result.metadata.size_bytes == 0
    assert result.metadata.line_count == 0


def test_parse_never_produces_modules() -> None:
    """`parse` should always report an empty `modules` tuple; Python has no nested-module form."""
    result = PythonParser().parse(relative_path="a.py", content="import os\n")
    assert result.modules == ()


def test_parse_extracts_plain_imports_with_alias() -> None:
    """`parse` should extract `import x as y` with its alias."""
    result = PythonParser().parse(relative_path="a.py", content="import os.path as osp\n")

    assert len(result.imports) == 1
    imported = result.imports[0]
    assert imported.module == "os.path"
    assert imported.alias == "osp"
    assert imported.imported_names == ()
    assert imported.is_relative is False
    assert imported.line_number == 1


def test_parse_extracts_from_imports_with_multiple_names() -> None:
    """`parse` should extract one entry per name in a `from x import a, b` statement."""
    result = PythonParser().parse(
        relative_path="a.py", content="from typing import Any, Optional\n"
    )

    assert [imported.imported_names for imported in result.imports] == [("Any",), ("Optional",)]
    assert all(imported.module == "typing" for imported in result.imports)


def test_parse_marks_relative_imports() -> None:
    """`parse` should mark a `from . import x` statement as relative, with dots preserved."""
    result = PythonParser().parse(relative_path="a.py", content="from ..pkg import thing\n")

    imported = result.imports[0]
    assert imported.module == "..pkg"
    assert imported.is_relative is True


def test_parse_finds_imports_nested_inside_a_function() -> None:
    """`parse` should find an import statement regardless of its nesting depth."""
    content = "def foo():\n    import json\n    return json\n"
    result = PythonParser().parse(relative_path="a.py", content=content)

    assert len(result.imports) == 1
    assert result.imports[0].module == "json"


def test_parse_extracts_all_as_exports() -> None:
    """`parse` should extract each string literal in a module-level `__all__` list."""
    result = PythonParser().parse(relative_path="a.py", content='__all__ = ["foo", "bar"]\n')

    assert [export.name for export in result.exports] == ["foo", "bar"]


def test_parse_reports_no_exports_without_all() -> None:
    """`parse` should report no exports when the module defines no `__all__`."""
    result = PythonParser().parse(relative_path="a.py", content="def foo():\n    pass\n")
    assert result.exports == ()


def test_parse_extracts_a_class_with_bases_and_docstring() -> None:
    """`parse` should extract a class's name, base classes, decorators, and docstring."""
    content = '''
class Base:
    pass


@final
class Foo(Base, metaclass=type):
    """A class."""

    def method(self) -> None:
        pass
'''
    result = PythonParser().parse(relative_path="a.py", content=content)

    assert [cls.name for cls in result.classes] == ["Base", "Foo"]
    foo = result.classes[1]
    assert foo.base_classes == ("Base",)
    assert foo.decorators == ("final",)
    assert foo.docstring == "A class."
    assert [method.name for method in foo.methods] == ["method"]
    assert foo.methods[0].is_method is True


def test_parse_extracts_module_level_functions_only() -> None:
    """`parse` should report class methods separately from module-level `functions`."""
    content = "class Foo:\n    def method(self):\n        pass\n\n\ndef free():\n    pass\n"
    result = PythonParser().parse(relative_path="a.py", content=content)

    assert [function.name for function in result.functions] == ["free"]
    assert result.functions[0].is_method is False


def test_parse_extracts_function_parameters_with_types_and_defaults() -> None:
    """`parse` should render each parameter, including annotations, defaults, and `*`/`**`."""
    content = 'def foo(a, b: int, c=1, *args, d, e: str = "x", **kwargs) -> bool:\n    pass\n'
    result = PythonParser().parse(relative_path="a.py", content=content)

    function = result.functions[0]
    assert function.parameters == (
        "a",
        "b: int",
        "c = 1",
        "*args",
        "d",
        "e: str = 'x'",
        "**kwargs",
    )
    assert function.return_type == "bool"


def test_parse_marks_async_functions() -> None:
    """`parse` should set `is_async=True` for an `async def` function."""
    result = PythonParser().parse(relative_path="a.py", content="async def foo():\n    pass\n")
    assert result.functions[0].is_async is True


def test_parse_captures_function_docstring_and_decorators() -> None:
    """`parse` should capture a function's docstring and decorator list."""
    content = '@staticmethod\ndef foo():\n    """Doc."""\n    pass\n'
    result = PythonParser().parse(relative_path="a.py", content=content)

    function = result.functions[0]
    assert function.docstring == "Doc."
    assert function.decorators == ("staticmethod",)


def test_parse_builds_symbols_from_classes_methods_and_functions() -> None:
    """`parse` should list classes, their methods, and free functions in the symbol table."""
    content = "class Foo:\n    def method(self):\n        pass\n\n\ndef free():\n    pass\n"
    result = PythonParser().parse(relative_path="a.py", content=content)

    kinds = {(symbol.name, symbol.kind) for symbol in result.symbols}
    assert (("Foo", SymbolKind.CLASS)) in kinds
    assert (("method", SymbolKind.METHOD)) in kinds
    assert (("free", SymbolKind.FUNCTION)) in kinds


def test_parse_reports_file_metadata() -> None:
    """`parse` should report line count, byte size, and a content hash for valid content."""
    content = "x = 1\ny = 2\n"
    result = PythonParser().parse(relative_path="a.py", content=content)

    assert result.metadata is not None
    assert result.metadata.language is SourceLanguage.PYTHON
    assert result.metadata.line_count == 2
    assert result.metadata.size_bytes == len(content.encode("utf-8"))
    assert len(result.metadata.content_hash) == 64
