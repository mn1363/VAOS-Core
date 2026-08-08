"""Unit tests for `src.parsers.base`."""

import pytest
from src.core.exceptions import ValidationError
from src.domain.entities import SourceLanguage
from src.parsers.base import (
    FileMetadata,
    ParsedClass,
    ParsedExport,
    ParsedFunction,
    ParsedImport,
    ParsedModule,
    ParsedSymbol,
    Parser,
    ParseResult,
    SymbolKind,
    build_file_metadata,
    compute_content_hash,
    find_matching_brace,
    find_matching_paren,
    has_extension,
    is_top_level_of_span,
    leading_comment_lines,
    line_number_at,
    require_relative_path,
    split_top_level,
    strip_c_style_comments,
)


def _metadata() -> FileMetadata:
    """Build a minimal, valid `FileMetadata` for use in result-construction tests."""
    return FileMetadata(
        relative_path="a.py",
        language=SourceLanguage.PYTHON,
        size_bytes=1,
        line_count=1,
        content_hash="deadbeef",
    )


def test_parser_cannot_be_instantiated_directly() -> None:
    """The abstract `Parser` Port must not be instantiable."""
    with pytest.raises(TypeError):
        Parser()  # type: ignore[abstract]


def test_parse_result_ok_builds_a_successful_result() -> None:
    """`ParseResult.ok` should set `succeeded=True` and carry the given constructs."""
    metadata = _metadata()
    function = ParsedFunction(name="foo")

    result = ParseResult.ok(
        relative_path="a.py",
        language=SourceLanguage.PYTHON,
        metadata=metadata,
        functions=[function],
    )

    assert result.succeeded is True
    assert result.relative_path == "a.py"
    assert result.metadata == metadata
    assert result.functions == (function,)
    assert result.error_message is None


def test_parse_result_ok_defaults_to_no_constructs() -> None:
    """`ParseResult.ok` should accept omitted construct sequences as empty."""
    result = ParseResult.ok(
        relative_path="a.py", language=SourceLanguage.PYTHON, metadata=_metadata()
    )

    assert result.modules == ()
    assert result.classes == ()
    assert result.functions == ()
    assert result.imports == ()
    assert result.exports == ()
    assert result.symbols == ()


def test_parse_result_failed_builds_a_failed_result() -> None:
    """`ParseResult.failed` should set `succeeded=False` and carry the error message."""
    result = ParseResult.failed(
        relative_path="a.py", language=SourceLanguage.PYTHON, error_message="bad syntax"
    )

    assert result.succeeded is False
    assert result.relative_path == "a.py"
    assert result.metadata is None
    assert result.error_message == "bad syntax"


def test_parse_result_rejects_error_message_on_success() -> None:
    """Constructing a successful result with an error message should raise."""
    with pytest.raises(ValidationError):
        ParseResult(
            relative_path="a.py", succeeded=True, metadata=_metadata(), error_message="unexpected"
        )


def test_parse_result_requires_metadata_on_success() -> None:
    """Constructing a successful result without metadata should raise."""
    with pytest.raises(ValidationError):
        ParseResult(relative_path="a.py", succeeded=True, metadata=None)


def test_parse_result_rejects_metadata_on_failure() -> None:
    """Constructing a failed result with metadata attached should raise."""
    with pytest.raises(ValidationError):
        ParseResult(
            relative_path="a.py",
            succeeded=False,
            metadata=_metadata(),
            error_message="went wrong",
        )


def test_parse_result_rejects_parsed_content_on_failure() -> None:
    """Constructing a failed result with parsed content attached should raise."""
    with pytest.raises(ValidationError):
        ParseResult(
            relative_path="a.py",
            succeeded=False,
            functions=(ParsedFunction(name="foo"),),
            error_message="went wrong",
        )


def test_parse_result_requires_error_message_on_failure() -> None:
    """Constructing a failed result without an error message should raise."""
    with pytest.raises(ValidationError):
        ParseResult(relative_path="a.py", succeeded=False)


def test_require_relative_path_returns_a_non_blank_value_unchanged() -> None:
    """`require_relative_path` should pass a non-blank string through unchanged."""
    assert require_relative_path("src/main.py") == "src/main.py"


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_require_relative_path_rejects_blank_values(blank: str) -> None:
    """`require_relative_path` should raise `ValidationError` for empty/whitespace-only input."""
    with pytest.raises(ValidationError):
        require_relative_path(blank)


def test_has_extension_matches_case_insensitively() -> None:
    """`has_extension` should match regardless of the extension's letter case."""
    assert has_extension("Main.PY", (".py",)) is True


def test_has_extension_rejects_a_non_matching_path() -> None:
    """`has_extension` should reject a path with none of the given extensions."""
    assert has_extension("main.txt", (".py", ".pyi")) is False


def test_compute_content_hash_is_deterministic() -> None:
    """`compute_content_hash` should return the same digest for the same content."""
    assert compute_content_hash("hello") == compute_content_hash("hello")


def test_compute_content_hash_differs_for_different_content() -> None:
    """`compute_content_hash` should return different digests for different content."""
    assert compute_content_hash("hello") != compute_content_hash("world")


def test_build_file_metadata_computes_size_lines_and_hash() -> None:
    """`build_file_metadata` should compute byte size, line count, and content hash."""
    metadata = build_file_metadata(
        relative_path="a.py", language=SourceLanguage.PYTHON, content="a\nb\n"
    )

    assert metadata.relative_path == "a.py"
    assert metadata.language is SourceLanguage.PYTHON
    assert metadata.size_bytes == 4
    assert metadata.line_count == 2
    assert metadata.content_hash == compute_content_hash("a\nb\n")


def test_build_file_metadata_handles_empty_content() -> None:
    """`build_file_metadata` should report zero size and zero lines for empty content."""
    metadata = build_file_metadata(relative_path="a.py", language=SourceLanguage.PYTHON, content="")

    assert metadata.size_bytes == 0
    assert metadata.line_count == 0


def test_line_number_at_returns_one_for_the_first_line() -> None:
    """`line_number_at` should return 1 for an offset on the first line."""
    assert line_number_at("abc\ndef", 1) == 1


def test_line_number_at_counts_preceding_newlines() -> None:
    """`line_number_at` should return the 1-indexed line containing the given offset."""
    content = "line one\nline two\nline three"
    assert line_number_at(content, content.index("two")) == 2


def test_find_matching_brace_finds_the_closing_brace() -> None:
    """`find_matching_brace` should find the `}` that closes the given `{`."""
    content = "fn foo() { bar(); }"
    open_index = content.index("{")

    assert find_matching_brace(content, open_index) == len(content) - 1


def test_find_matching_brace_handles_nesting() -> None:
    """`find_matching_brace` should skip over nested `{ }` pairs."""
    content = "{ { } }"
    assert find_matching_brace(content, 0) == 6


def test_find_matching_brace_returns_length_when_unclosed() -> None:
    """`find_matching_brace` should return `len(content)` for an unclosed brace."""
    content = "{ unclosed"
    assert find_matching_brace(content, 0) == len(content)


def test_find_matching_paren_finds_the_closing_paren() -> None:
    """`find_matching_paren` should find the `)` that closes the given `(`."""
    content = "foo(a, b)"
    assert find_matching_paren(content, 3) == 8


def test_find_matching_paren_handles_nested_parens() -> None:
    """`find_matching_paren` should skip over nested `( )` pairs, e.g. a function-typed param."""
    content = "foo(f(int) string)"
    assert find_matching_paren(content, 3) == len(content) - 1


def test_split_top_level_splits_on_plain_commas() -> None:
    """`split_top_level` should split simple comma-separated entries."""
    assert split_top_level("a, b, c") == ("a", "b", "c")


def test_split_top_level_ignores_commas_nested_in_brackets() -> None:
    """`split_top_level` should not split on a comma nested inside `()`, `[]`, or `{}`."""
    assert split_top_level("f func(int, string), x int") == ("f func(int, string)", "x int")


def test_split_top_level_drops_empty_segments() -> None:
    """`split_top_level` should drop empty/whitespace-only segments."""
    assert split_top_level("") == ()
    assert split_top_level("   ") == ()


def test_strip_c_style_comments_blanks_line_comments() -> None:
    """`strip_c_style_comments` should blank a `//` comment but keep the newline."""
    content = "int x; // comment\nint y;"
    stripped = strip_c_style_comments(content)

    assert "comment" not in stripped
    assert stripped.count("\n") == content.count("\n")
    assert len(stripped) == len(content)


def test_strip_c_style_comments_blanks_block_comments() -> None:
    """`strip_c_style_comments` should blank a `/* ... */` block, preserving line count."""
    content = "int x; /* a\nb */ int y;"
    stripped = strip_c_style_comments(content)

    assert "a" not in stripped
    assert "b" not in stripped
    assert stripped.count("\n") == content.count("\n")


def test_strip_c_style_comments_preserves_non_comment_code() -> None:
    """`strip_c_style_comments` should leave ordinary code untouched."""
    content = "int x = 1;"
    assert strip_c_style_comments(content) == content


def test_leading_comment_lines_collects_consecutive_prefixed_lines() -> None:
    """`leading_comment_lines` should collect and join consecutive `///` lines above a line."""
    lines = ["/// First line.", "/// Second line.", "fn foo() {}"]

    assert leading_comment_lines(lines, 3, prefix="///") == "First line.\nSecond line."


def test_leading_comment_lines_returns_none_when_no_comment_precedes() -> None:
    """`leading_comment_lines` should return None when the preceding line is not a comment."""
    lines = ["let x = 1;", "fn foo() {}"]
    assert leading_comment_lines(lines, 2, prefix="///") is None


def test_leading_comment_lines_stops_at_a_non_matching_line() -> None:
    """`leading_comment_lines` should stop collecting at the first non-matching line."""
    lines = ["let x = 1;", "/// Only this line.", "fn foo() {}"]

    assert leading_comment_lines(lines, 3, prefix="///") == "Only this line."


def test_is_top_level_of_span_true_at_zero_depth() -> None:
    """`is_top_level_of_span` should be True when brace counts balance out to zero."""
    scan = "member();"
    assert is_top_level_of_span(scan, 0, len(scan) - 1) is True


def test_is_top_level_of_span_false_when_nested() -> None:
    """`is_top_level_of_span` should be False for a position nested inside an open `{`."""
    scan = "method() { call();"
    call_index = scan.index("call")
    assert is_top_level_of_span(scan, 0, call_index) is False


@pytest.mark.parametrize(
    "dto",
    [
        ParsedImport(module="os"),
        ParsedExport(name="foo"),
        ParsedFunction(name="foo"),
        ParsedClass(name="Foo"),
        ParsedModule(name="mod"),
        ParsedSymbol(name="foo", kind=SymbolKind.FUNCTION),
    ],
)
def test_parsed_construct_dtos_are_frozen(dto: object) -> None:
    """Every parsed-construct DTO should be immutable once constructed."""
    with pytest.raises(AttributeError):
        dto.line_number = 99  # type: ignore[attr-defined]
