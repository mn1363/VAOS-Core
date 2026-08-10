"""Tests analyzer Port: test presence, structure, and quality-indicator analysis.

`TestsAnalyzer` turns a single file's `extractors.symbols.base.SymbolExtractionResult` into
`TestEvidence` -- whether the file is conventionally a test file (by path), how many test-shaped
functions and classes it declares (by name), and zero or more `TestIndicator` entries flagging
specific structural observations (e.g. a test file with no test-shaped symbols at all). `src.
extractors` exposes no test-execution results, so this Port evaluates *structural evidence* of
testing -- naming and path conventions -- not measured runtime coverage, which no upstream layer
provides and this Port does not invent.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from src.core.exceptions import ValidationError
from src.core.logging import get_logger
from src.domain.entities import FindingSeverity
from src.extractors.symbols.base import ExtractedSymbolKind, SymbolExtractionResult

_logger = get_logger("analyzers.tests")

#: Path segments that conventionally mark a file as belonging to a test suite, matched against
#: any `/`-separated segment of a `relative_path`.
_TEST_DIRECTORY_SEGMENTS = ("tests", "test")

#: Filename prefixes/suffixes that conventionally mark a file itself as a test file, matched
#: against the final `/`-separated segment of a `relative_path`, stem only (extension stripped).
_TEST_FILENAME_PREFIXES = ("test_",)
_TEST_FILENAME_SUFFIXES = ("_test",)


@dataclass(frozen=True, slots=True)
class TestIndicator:
    """A single test-structure observation about a file.

    Attributes:
        subject_name: Name of the symbol (or the file itself) this indicator is about.
        relative_path: Path of the file the subject was found in.
        severity: How significant this observation is.
        message: Human-readable explanation of the observation.
        line_number: 1-indexed line the subject is declared on. 0 if unknown or the indicator
            is about the file as a whole.
    """

    #: Tells pytest not to collect this class as a test case merely because its name starts
    #: with `Test`; it is a plain data class, not a test.
    __test__: ClassVar[bool] = False

    subject_name: str
    relative_path: str
    severity: FindingSeverity
    message: str
    line_number: int = 0

    def __post_init__(self) -> None:
        """Validate that `subject_name` and `message` are non-blank.

        Raises:
            ValidationError: If `subject_name` or `message` is blank.
        """
        if not self.subject_name.strip():
            raise ValidationError("TestIndicator: subject_name must not be empty")
        if not self.message.strip():
            raise ValidationError("TestIndicator: message must not be empty")


@dataclass(frozen=True, slots=True)
class TestEvidence:
    """A single file's test presence and structure, evaluated from its extracted symbols.

    Attributes:
        relative_path: Path of the source file this evidence was derived from.
        is_test_file: Whether `relative_path` itself conventionally marks the file as a test
            file (see `is_test_file`).
        test_function_count: Number of extracted functions/methods whose name conventionally
            marks them as a test (see `is_test_symbol_name`).
        test_class_count: Number of extracted classes whose name conventionally marks them as a
            test fixture/suite.
        indicators: Specific structural observations about the file's tests, possibly empty.
    """

    #: Tells pytest not to collect this class as a test case merely because its name starts
    #: with `Test`; it is a plain data class, not a test.
    __test__: ClassVar[bool] = False

    relative_path: str
    is_test_file: bool = False
    test_function_count: int = 0
    test_class_count: int = 0
    indicators: tuple[TestIndicator, ...] = ()

    def __post_init__(self) -> None:
        """Validate that the test counts are non-negative.

        Raises:
            ValidationError: If `test_function_count` or `test_class_count` is negative.
        """
        if self.test_function_count < 0 or self.test_class_count < 0:
            raise ValidationError("TestEvidence: test counts must not be negative")


@dataclass(frozen=True, slots=True)
class TestsAnalysisResult:
    """Outcome of a single `TestsAnalyzer.analyze` call.

    Attributes:
        relative_path: The file analysis was attempted against.
        succeeded: Whether analysis completed successfully.
        evidence: The resulting test evidence. Always present when `succeeded` is True, always
            None when `succeeded` is False.
        error_message: Explanation of the failure. Always None when `succeeded` is True, always
            set when `succeeded` is False.
    """

    #: Tells pytest not to collect this class as a test case merely because its name starts
    #: with `Test`; it is a plain data class, not a test.
    __test__: ClassVar[bool] = False

    relative_path: str
    succeeded: bool
    evidence: TestEvidence | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        """Validate that `succeeded`, `evidence`, and `error_message` are consistent.

        Raises:
            ValidationError: If a successful result is missing `evidence` or carries an error
                message, or a failed result carries `evidence` or no error message.
        """
        if self.succeeded:
            if self.error_message is not None:
                raise ValidationError(
                    "TestsAnalysisResult: error_message must be None when succeeded is True"
                )
            if self.evidence is None:
                raise ValidationError(
                    "TestsAnalysisResult: evidence is required when succeeded is True"
                )
        else:
            if self.evidence is not None:
                raise ValidationError(
                    "TestsAnalysisResult: evidence must be None when succeeded is False"
                )
            if self.error_message is None:
                raise ValidationError(
                    "TestsAnalysisResult: error_message is required when succeeded is False"
                )

    @classmethod
    def ok(cls, *, relative_path: str, evidence: TestEvidence) -> "TestsAnalysisResult":
        """Build a successful result.

        Args:
            relative_path: The file that was analyzed.
            evidence: The resulting test evidence.

        Returns:
            A `TestsAnalysisResult` with `succeeded=True`.
        """
        return cls(relative_path=relative_path, succeeded=True, evidence=evidence)

    @classmethod
    def failed(cls, *, relative_path: str, error_message: str) -> "TestsAnalysisResult":
        """Build a failed result.

        Args:
            relative_path: The file that analysis was attempted against.
            error_message: Human-readable explanation of the failure.

        Returns:
            A `TestsAnalysisResult` with `succeeded=False`.
        """
        _logger.debug("Tests analysis failed for '%s': %s", relative_path, error_message)
        return cls(relative_path=relative_path, succeeded=False, error_message=error_message)


class TestsAnalyzer(ABC):
    """Analyzes test presence, structure, and quality indicators from a file's already-extracted
    symbols.

    A concrete implementation decides which extracted symbols are test-shaped and which
    structural observations warrant a `TestIndicator`; it evaluates naming/path evidence only --
    `src.extractors` provides no test-execution or coverage-measurement data, so this Port does
    not report measured coverage, only structural evidence of testing.
    """

    @abstractmethod
    def analyze(self, extraction_result: SymbolExtractionResult) -> TestsAnalysisResult:
        """Analyze test presence and structure for the file described by `extraction_result`.

        Args:
            extraction_result: The outcome of extracting one file's classes, functions, and
                constants, as produced by `src.extractors.symbols`.

        Returns:
            A successful result carrying the file's `TestEvidence`, or a failed result carrying
            an explanation, if evidence cannot be derived from `extraction_result`.

        Raises:
            ValidationError: If `extraction_result.succeeded` is False -- analysis requires a
                successful extraction.
        """
        ...


def require_successful_extraction(
    extraction_result: SymbolExtractionResult,
) -> SymbolExtractionResult:
    """Validate that `extraction_result` represents a successful extraction.

    Every `TestsAnalyzer.analyze` implementation calls this first, so a caller error (a
    `SymbolExtractionResult` with `succeeded=False`) is reported the same way -- as an immediate
    `ValidationError` -- across every implementation.

    Args:
        extraction_result: The raw `extraction_result` argument passed to `analyze`.

    Returns:
        `extraction_result`, unchanged.

    Raises:
        ValidationError: If `extraction_result.succeeded` is False.
    """
    if not extraction_result.succeeded:
        _logger.debug(
            "Rejected analysis of an unsuccessful extraction of '%s'",
            extraction_result.relative_path,
        )
        raise ValidationError(
            "cannot analyze tests from a failed SymbolExtractionResult",
            details={"relative_path": extraction_result.relative_path},
        )
    return extraction_result


def is_test_file(relative_path: str) -> bool:
    """Report whether `relative_path` conventionally identifies a test file.

    Recognizes two independent conventions: the file living under a `tests`/`test` directory
    segment, or the file's own stem being prefixed/suffixed with `test`.

    Args:
        relative_path: Path of the candidate file, typically relative to a repository root.

    Returns:
        True if `relative_path` matches either convention.
    """
    segments = relative_path.split("/")
    if any(segment in _TEST_DIRECTORY_SEGMENTS for segment in segments[:-1]):
        return True
    filename = segments[-1]
    stem = filename.split(".", 1)[0]
    if stem.startswith(_TEST_FILENAME_PREFIXES):
        return True
    return stem.endswith(_TEST_FILENAME_SUFFIXES)


def is_test_symbol_name(name: str, kind: ExtractedSymbolKind) -> bool:
    """Report whether a symbol's own name conventionally marks it as test-shaped.

    A function or method is test-shaped when its name is prefixed with `test_` (the pytest/
    unittest convention). A class is test-shaped when its name is prefixed with `Test` (the
    unittest `TestCase` subclass convention). Constants are never test-shaped.

    Args:
        name: The symbol's own, unqualified name.
        kind: What kind of construct the symbol is.

    Returns:
        True if `name` matches the naming convention for `kind`.
    """
    if kind in (ExtractedSymbolKind.FUNCTION, ExtractedSymbolKind.METHOD):
        return name.startswith("test_")
    if kind is ExtractedSymbolKind.CLASS:
        return name.startswith("Test")
    return False
