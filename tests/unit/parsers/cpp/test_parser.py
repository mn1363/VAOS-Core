"""Unit tests for `src.parsers.cpp.parser`."""

import pytest
from src.core.exceptions import ValidationError
from src.domain.entities import SourceLanguage
from src.parsers.base import SymbolKind
from src.parsers.cpp.parser import CppParser


def test_language_is_cpp() -> None:
    """`CppParser.language` should report `SourceLanguage.CPP`."""
    assert CppParser().language is SourceLanguage.CPP


@pytest.mark.parametrize("path", ["main.cpp", "widget.hpp", "a.cc", "a.cxx", "a.hh", "a.h"])
def test_supports_accepts_cpp_extensions(path: str) -> None:
    """`supports` should accept common C++ source and header extensions."""
    assert CppParser().supports(path) is True


@pytest.mark.parametrize("path", ["main.py", "main.rs"])
def test_supports_rejects_non_cpp_extensions(path: str) -> None:
    """`supports` should reject files without a recognized C++ extension."""
    assert CppParser().supports(path) is False


def test_parse_rejects_a_blank_relative_path() -> None:
    """`parse` should raise `ValidationError` for a blank `relative_path`."""
    with pytest.raises(ValidationError):
        CppParser().parse(relative_path="", content="int main() { return 0; }")


def test_parse_succeeds_on_empty_content() -> None:
    """`parse` should succeed on an empty file."""
    result = CppParser().parse(relative_path="empty.cpp", content="")
    assert result.succeeded is True
    assert result.metadata is not None


def test_parse_extracts_angle_include_as_non_relative() -> None:
    """`parse` should extract `#include <header>` as a non-relative import."""
    result = CppParser().parse(relative_path="a.cpp", content="#include <vector>\n")

    imported = result.imports[0]
    assert imported.module == "vector"
    assert imported.is_relative is False


def test_parse_extracts_quoted_include_as_relative() -> None:
    """`parse` should extract `#include "header.h"` as a relative import."""
    result = CppParser().parse(relative_path="a.cpp", content='#include "myheader.h"\n')

    imported = result.imports[0]
    assert imported.module == "myheader.h"
    assert imported.is_relative is True


def test_parse_extracts_a_namespace_as_a_module() -> None:
    """`parse` should extract a `namespace name { ... }` block as a `ParsedModule`."""
    result = CppParser().parse(relative_path="a.cpp", content="namespace app {\n}\n")
    assert [module.name for module in result.modules] == ["app"]


def test_parse_extracts_a_class_with_base_list() -> None:
    """`parse` should extract a class's base classes, with access specifiers stripped."""
    content = "class Point : public Base, private Serializable {\n};\n"
    result = CppParser().parse(relative_path="a.cpp", content=content)

    assert result.classes[0].name == "Point"
    assert result.classes[0].base_classes == ("Base", "Serializable")


def test_parse_extracts_a_struct_as_a_class() -> None:
    """`parse` should extract a `struct` declaration as a `ParsedClass`."""
    result = CppParser().parse(
        relative_path="a.cpp", content="struct Vec3 {\n    double x, y, z;\n};\n"
    )
    assert [cls.name for cls in result.classes] == ["Vec3"]


def test_parse_extracts_in_class_methods() -> None:
    """`parse` should extract a method declared inside a class body."""
    content = "class Point {\npublic:\n    double distance(const Point& other) const {\n        return 0.0;\n    }\n};\n"
    result = CppParser().parse(relative_path="a.cpp", content=content)

    methods = result.classes[0].methods
    assert [m.name for m in methods] == ["distance"]
    assert methods[0].parameters == ("const Point& other",)
    assert methods[0].is_method is True


def test_parse_extracts_a_destructor() -> None:
    """`parse` should extract a destructor, keeping its leading `~`."""
    content = "class Widget {\npublic:\n    ~Widget() {\n        cleanup();\n    }\n};\n"
    result = CppParser().parse(relative_path="a.cpp", content=content)

    assert [m.name for m in result.classes[0].methods] == ["~Widget"]


def test_parse_does_not_mistake_a_nested_call_for_a_sibling_method() -> None:
    """`parse` should not treat a call statement inside a method's body as its own method."""
    content = "class Foo {\npublic:\n    void bar() {\n        doSomething(a, b);\n    }\n};\n"
    result = CppParser().parse(relative_path="a.cpp", content=content)

    assert [m.name for m in result.classes[0].methods] == ["bar"]


def test_parse_extracts_a_free_function() -> None:
    """`parse` should extract a namespace/global-scope function declaration."""
    content = "int add(int a, int b) {\n    return a + b;\n}\n"
    result = CppParser().parse(relative_path="a.cpp", content=content)

    assert len(result.functions) == 1
    function = result.functions[0]
    assert function.name == "add"
    assert function.parameters == ("int a", "int b")
    assert function.return_type == "int"
    assert function.is_method is False


def test_parse_does_not_mistake_a_constructor_call_statement_for_a_free_function() -> None:
    """`parse` should not treat a constructor-call statement inside main() as a function."""
    content = "int main() {\n    Point p(1.0, 2.0);\n    return 0;\n}\n"
    result = CppParser().parse(relative_path="a.cpp", content=content)

    assert [function.name for function in result.functions] == ["main"]


def test_parse_does_not_emit_parameter_type_fragments_as_free_functions() -> None:
    """Function-like text inside nested parameter types is not a declaration."""
    content = "void wrapper(std::function<void(void)> callback) { }\n"
    result = CppParser().parse(relative_path="a.cpp", content=content)

    assert [function.name for function in result.functions] == ["wrapper"]


def test_parse_does_not_mistake_a_return_call_statement_for_a_free_function() -> None:
    """`parse` should not treat `return computeTotal(a, b);` as a new function declaration."""
    content = "int wrapper() {\n    return computeTotal(1, 2);\n}\n"
    result = CppParser().parse(relative_path="a.cpp", content=content)

    assert [function.name for function in result.functions] == ["wrapper"]


def test_parse_extracts_enum_and_using_alias_as_symbols() -> None:
    """`parse` should extract `enum class` and `using` alias declarations as symbols."""
    content = "enum class Color { Red, Green, Blue };\n\nusing Meters = double;\n"
    result = CppParser().parse(relative_path="a.cpp", content=content)

    kinds = {symbol.name: symbol.kind for symbol in result.symbols}
    assert kinds["Color"] is SymbolKind.ENUM
    assert kinds["Meters"] is SymbolKind.TYPE_ALIAS


def test_parse_extracts_typedef_as_a_type_alias() -> None:
    """`parse` should extract a `typedef Type Name;` declaration as a type alias symbol."""
    result = CppParser().parse(relative_path="a.cpp", content="typedef int MyInt;\n")

    kinds = {symbol.name: symbol.kind for symbol in result.symbols}
    assert kinds["MyInt"] is SymbolKind.TYPE_ALIAS


def test_parse_exports_only_export_keyword_declarations() -> None:
    """`parse` should export only declarations whose line starts with the `export` keyword."""
    content = "export int visible() { return 0; }\n\nint hidden() { return 0; }\n"
    result = CppParser().parse(relative_path="a.cpp", content=content)

    assert [export.name for export in result.exports] == ["visible"]


def test_parse_reports_no_exports_for_ordinary_cpp() -> None:
    """`parse` should report no exports for code with no C++20 `export` keyword."""
    result = CppParser().parse(relative_path="a.cpp", content="int main() { return 0; }\n")
    assert result.exports == ()


def test_parse_reports_file_metadata() -> None:
    """`parse` should report line count, byte size, and a content hash."""
    content = "int main() { return 0; }\n"
    result = CppParser().parse(relative_path="a.cpp", content=content)

    assert result.metadata is not None
    assert result.metadata.language is SourceLanguage.CPP
    assert result.metadata.line_count == 1
    assert len(result.metadata.content_hash) == 64


def test_parse_does_not_emit_out_of_class_member_definitions() -> None:
    """Out-of-class member definitions must not become free functions."""
    content = """\
namespace app {}
class Widget {
public:
    Widget(int value);
    int get() const;
};
Widget::Widget(int value) {}
int Widget::get() const { return 0; }
int app::helper() { return 1; }
"""
    result = CppParser().parse(relative_path="a.cpp", content=content)

    assert [function.name for function in result.functions] == ["helper"]


def test_parse_omits_unknown_qualified_definition_but_keeps_known_namespace_function() -> None:
    """A qualifier not proved to be a namespace must not be assumed to denote a free function."""
    content = """\\
namespace detail {}
int detail::helper() { return 0; }
int HeaderOnly::method() { return 1; }
"""
    result = CppParser().parse(relative_path="a.cpp", content=content)

    assert [function.name for function in result.functions] == ["helper"]


def test_parse_does_not_emit_out_of_class_template_constructor() -> None:
    """Template-qualified constructor definitions are not free functions."""
    content = """\
template <typename T>
class Matcher {
public:
    explicit Matcher(T value);
};
template <typename T>
Matcher<T>::Matcher(T value) {}
"""
    result = CppParser().parse(relative_path="a.cpp", content=content)

    assert result.functions == ()


def test_parse_does_not_emit_constructor_mem_initializer_fragments() -> None:
    """Mem-initializer entries are not standalone free functions."""
    content = """\
class Base {};
class Widget : public Base {
public:
    Widget(int value);
    int member;
};
Widget::Widget(int value)
    : Base(value),
      member(value) {}
"""
    result = CppParser().parse(relative_path="a.cpp", content=content)

    assert result.functions == ()


def test_parse_does_not_emit_macro_definition_fragments_as_functions() -> None:
    """Macro definitions and their continued lines are not free-function declarations."""
    content = """\
class CodeLocation {};
#define MAKE_LOC(file, line) \\
    ::testing::internal::CodeLocation(file, line)
"""
    result = CppParser().parse(relative_path="a.cpp", content=content)

    assert result.functions == ()


def test_parse_does_not_emit_call_initialized_variables_as_functions() -> None:
    """A variable initializer with a call expression is not a function definition."""
    content = """\
auto buffer_size = detail::buffer_size();
auto widget = makeWidget();
"""
    result = CppParser().parse(relative_path="a.cpp", content=content)

    assert result.functions == ()


def test_parse_keeps_same_name_top_level_class_and_function() -> None:
    """A valid class/function name conflict remains visible to the frozen graph policy."""
    result = CppParser().parse(
        relative_path="a.cpp", content="class Foo {};\nvoid Foo() {}\n"
    )

    assert [cls.name for cls in result.classes] == ["Foo"]
    assert [function.name for function in result.functions] == ["Foo"]


def test_parse_keeps_namespace_qualified_free_function_in_nested_namespace() -> None:
    """Known nested namespaces do not cause an unrelated free function to be filtered."""
    content = """\
namespace outer {
namespace inner {}
}
int outer::inner::helper() { return 0; }
"""
    result = CppParser().parse(relative_path="a.cpp", content=content)

    assert [function.name for function in result.functions] == ["helper"]


def test_parse_keeps_free_function_overloads() -> None:
    """Distinct free-function overloads remain in parser output for downstream coalescing."""
    content = """\
int add(int value) { return value; }
int add(double value) { return static_cast<int>(value); }
"""
    result = CppParser().parse(relative_path="a.cpp", content=content)

    assert [function.name for function in result.functions] == ["add", "add"]
    assert [function.parameters for function in result.functions] == [
        ("int value",),
        ("double value",),
    ]


@pytest.mark.parametrize(
    "prefix",
    [
        "constexpr int big = 1'000;",
        "#error don't build",
        "#define BROKEN(x (x)",
    ],
)
def test_parse_preprocessor_and_digit_separators_do_not_hide_later_functions(
    prefix: str,
) -> None:
    """Quotes and parentheses in non-code prefixes must not affect later declarations."""
    content = f"{prefix}\nint first() {{ return 1; }}\nint second() {{ return 2; }}\n"
    result = CppParser().parse(relative_path="a.cpp", content=content)
    assert [function.name for function in result.functions] == ["first", "second"]


def test_parse_keeps_function_with_default_template_argument() -> None:
    """An equals sign in a template parameter is not an expression initializer."""
    result = CppParser().parse(
        relative_path="a.cpp",
        content="template <typename T = int> void f(T value) {}\n",
    )
    assert [function.name for function in result.functions] == ["f"]


def test_parse_unterminated_character_literal_does_not_hide_later_functions() -> None:
    """An invalid character literal must not keep quote state across lines."""
    result = CppParser().parse(
        relative_path="a.cpp",
        content="char broken = '\nint visible() { return 1; }\n",
    )
    assert [function.name for function in result.functions] == ["visible"]
