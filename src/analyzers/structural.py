"""Deterministic structural implementations of the analyzer Ports.

These implementations use only facts already emitted by the extractors. They do not claim
control-flow complexity, vulnerability detection, or executed test coverage.
"""

from collections.abc import Callable
from typing import TypeVar

from src.analyzers.architecture.base import (
    ArchitectureAnalysisResult,
    ArchitectureAnalyzer,
    ArchitectureAssessment,
    ArchitectureMemoryCheck,
)
from src.analyzers.architecture.base import (
    require_successful_extraction as require_architecture,
)
from src.analyzers.complexity.base import (
    ComplexityAnalysisResult,
    ComplexityAnalyzer,
    ComplexityMetrics,
    safe_ratio,
)
from src.analyzers.complexity.base import (
    require_successful_extraction as require_complexity,
)
from src.analyzers.dependency.base import (
    DependencyAnalysisResult,
    DependencyAnalyzer,
    DependencyProfile,
    summarize_external_targets,
)
from src.analyzers.dependency.base import (
    require_successful_extraction as require_dependency,
)
from src.analyzers.documentation.base import (
    DocumentationAnalysisResult,
    DocumentationAnalyzer,
    DocumentationCoverage,
    coverage_ratio,
)
from src.analyzers.documentation.base import (
    require_successful_extraction as require_documentation,
)
from src.analyzers.metrics.base import (
    MetricsAnalysisResult,
    MetricsAnalyzer,
    NormalizedCodeMetrics,
    per_kloc,
)
from src.analyzers.metrics.base import (
    require_successful_extraction as require_metrics,
)
from src.analyzers.quality.base import (
    QualityAnalysisResult,
    QualityAnalyzer,
    QualityAssessment,
    QualityIndicator,
)
from src.analyzers.quality.base import (
    require_successful_extraction as require_quality,
)
from src.analyzers.security.base import (
    SecurityAnalysisResult,
    SecurityAnalyzer,
    SecurityAssessment,
    SecurityIndicator,
)
from src.analyzers.security.base import (
    require_successful_extraction as require_security,
)
from src.analyzers.tests.base import (
    TestEvidence,
    TestIndicator,
    TestsAnalysisResult,
    TestsAnalyzer,
    is_test_file,
    is_test_symbol_name,
)
from src.analyzers.tests.base import (
    require_successful_extraction as require_tests,
)
from src.core.exceptions import ValidationError
from src.domain.entities import FindingSeverity
from src.extractors.architecture.base import ArchitectureExtractionResult
from src.extractors.ast.base import AstExtractionResult
from src.extractors.foundation.base import FoundationExtractionResult
from src.extractors.imports.base import ImportExtractionResult
from src.extractors.symbols.base import ExtractedSymbolKind, SymbolExtractionResult
from src.memory.base import MemoryRecord
from src.memory.contracts import ArchitectureMemoryContent
from src.memory.policy import select_memory_for_analyzer

ExtractionT = TypeVar(
    "ExtractionT",
    ArchitectureExtractionResult,
    AstExtractionResult,
    FoundationExtractionResult,
    ImportExtractionResult,
    SymbolExtractionResult,
)
AnalysisT = TypeVar(
    "AnalysisT",
    ArchitectureAnalysisResult,
    ComplexityAnalysisResult,
    DependencyAnalysisResult,
    DocumentationAnalysisResult,
    MetricsAnalysisResult,
    QualityAnalysisResult,
    SecurityAnalysisResult,
    TestsAnalysisResult,
)


class StructuralArchitectureAnalyzer(ArchitectureAnalyzer):
    """Summarize package placement from architecture extraction."""

    def analyze(
        self, extraction_result: ArchitectureExtractionResult
    ) -> ArchitectureAnalysisResult:
        result = require_architecture(extraction_result)
        unit = result.unit
        assert unit is not None
        return ArchitectureAnalysisResult.ok(
            relative_path=result.relative_path,
            assessment=ArchitectureAssessment(
                relative_path=result.relative_path,
                package_path=unit.package_path,
                is_package_root=unit.is_package_root,
                declared_module_count=len(unit.declared_modules),
            ),
        )

    def analyze_with_memory(
        self,
        extraction_result: ArchitectureExtractionResult,
        memory_records: tuple[MemoryRecord, ...],
    ) -> ArchitectureAnalysisResult:
        """Compare observed placement with eligible memory; never create findings."""
        result = self.analyze(extraction_result)
        if not result.succeeded or result.assessment is None:
            return result
        eligible = select_memory_for_analyzer(memory_records, analyzer="architecture")
        checks: list[ArchitectureMemoryCheck] = []
        for record in eligible:
            content = ArchitectureMemoryContent.from_record(record)
            if content is None:
                continue
            checks.append(
                ArchitectureMemoryCheck(
                    memory_record_id=record.id,
                    expected_package_path=content.expected_package_path,
                    matches=result.assessment.package_path == content.expected_package_path,
                )
            )
        assessment = ArchitectureAssessment(
            relative_path=result.assessment.relative_path,
            package_path=result.assessment.package_path,
            is_package_root=result.assessment.is_package_root,
            declared_module_count=result.assessment.declared_module_count,
            memory_checks=tuple(checks),
        )
        return ArchitectureAnalysisResult.ok(relative_path=result.relative_path, assessment=assessment)


class StructuralComplexityAnalyzer(ComplexityAnalyzer):
    """Compute documented structural proxies, not cyclomatic complexity."""

    def analyze(self, extraction_result: AstExtractionResult) -> ComplexityAnalysisResult:
        result = require_complexity(extraction_result)
        metadata = result.metadata
        assert metadata is not None
        callable_count = metadata.function_count + metadata.method_count
        return ComplexityAnalysisResult.ok(
            relative_path=result.relative_path,
            metrics=ComplexityMetrics(
                relative_path=result.relative_path,
                methods_per_class=safe_ratio(metadata.method_count, metadata.class_count),
                lines_per_function=safe_ratio(metadata.line_count, metadata.function_count),
                async_function_ratio=safe_ratio(metadata.async_function_count, callable_count),
                class_count=metadata.class_count,
                function_count=metadata.function_count,
                method_count=metadata.method_count,
            ),
        )


class StructuralDependencyAnalyzer(DependencyAnalyzer):
    """Summarize internal and external import edges for one file."""

    def analyze(self, extraction_result: ImportExtractionResult) -> DependencyAnalysisResult:
        result = require_dependency(extraction_result)
        internal_count = sum(edge.is_internal for edge in result.edges)
        external_count = len(result.edges) - internal_count
        return DependencyAnalysisResult.ok(
            relative_path=result.relative_path,
            profile=DependencyProfile(
                relative_path=result.relative_path,
                total_dependency_count=len(result.edges),
                internal_dependency_count=internal_count,
                external_dependency_count=external_count,
                external_targets=summarize_external_targets(result.edges),
            ),
        )


class StructuralDocumentationAnalyzer(DocumentationAnalyzer):
    """Compute documentation coverage from AST docstring counts."""

    def analyze(self, extraction_result: AstExtractionResult) -> DocumentationAnalysisResult:
        result = require_documentation(extraction_result)
        metadata = result.metadata
        assert metadata is not None
        callable_count = metadata.function_count + metadata.method_count
        documented_callable_count = metadata.documented_function_count
        return DocumentationAnalysisResult.ok(
            relative_path=result.relative_path,
            coverage=DocumentationCoverage(
                relative_path=result.relative_path,
                class_count=metadata.class_count,
                documented_class_count=metadata.documented_class_count,
                class_documentation_ratio=coverage_ratio(
                    metadata.documented_class_count, metadata.class_count
                ),
                function_count=callable_count,
                documented_function_count=documented_callable_count,
                function_documentation_ratio=coverage_ratio(
                    documented_callable_count, callable_count
                ),
                overall_documentation_ratio=coverage_ratio(
                    metadata.documented_class_count + documented_callable_count,
                    metadata.class_count + callable_count,
                ),
            ),
        )


class StructuralMetricsAnalyzer(MetricsAnalyzer):
    """Normalize AST construct counts per thousand lines."""

    def analyze(self, extraction_result: AstExtractionResult) -> MetricsAnalysisResult:
        result = require_metrics(extraction_result)
        metadata = result.metadata
        assert metadata is not None
        return MetricsAnalysisResult.ok(
            relative_path=result.relative_path,
            metrics=NormalizedCodeMetrics(
                relative_path=result.relative_path,
                line_count=metadata.line_count,
                classes_per_kloc=per_kloc(metadata.class_count, metadata.line_count),
                functions_per_kloc=per_kloc(metadata.function_count, metadata.line_count),
                methods_per_kloc=per_kloc(metadata.method_count, metadata.line_count),
                symbols_per_kloc=per_kloc(metadata.symbol_count, metadata.line_count),
            ),
        )


class StructuralQualityAnalyzer(QualityAnalyzer):
    """Flag public foundation candidates without extracted docstrings."""

    def analyze(self, extraction_result: FoundationExtractionResult) -> QualityAnalysisResult:
        result = require_quality(extraction_result)
        public_candidates = tuple(
            candidate for candidate in result.candidates if candidate.is_public
        )
        indicators = tuple(
            QualityIndicator(
                subject_name=candidate.name,
                relative_path=result.relative_path,
                severity=FindingSeverity.LOW,
                message="Public candidate has no extracted docstring",
                line_number=candidate.line_number,
            )
            for candidate in public_candidates
            if not candidate.has_docstring
        )
        return QualityAnalysisResult.ok(
            relative_path=result.relative_path,
            assessment=QualityAssessment(
                relative_path=result.relative_path,
                candidate_count=len(result.candidates),
                public_candidate_count=len(public_candidates),
                documented_public_ratio=coverage_ratio(
                    sum(candidate.has_docstring for candidate in public_candidates),
                    len(public_candidates),
                ),
                indicators=indicators,
            ),
        )


class StructuralSecurityAnalyzer(SecurityAnalyzer):
    """Report external dependency boundaries, not software vulnerabilities."""

    def analyze(self, extraction_result: ImportExtractionResult) -> SecurityAnalysisResult:
        result = require_security(extraction_result)
        external_edges = tuple(edge for edge in result.edges if not edge.is_internal)
        external_targets = summarize_external_targets(result.edges)
        indicators = tuple(
            SecurityIndicator(
                subject=target,
                relative_path=result.relative_path,
                severity=FindingSeverity.INFO,
                message=(
                    "External dependency is a trust boundary; "
                    "no vulnerability assessment was performed"
                ),
                line_number=min(
                    (edge.line_number for edge in external_edges if edge.target_module == target),
                    default=0,
                ),
            )
            for target in external_targets
        )
        return SecurityAnalysisResult.ok(
            relative_path=result.relative_path,
            assessment=SecurityAssessment(
                relative_path=result.relative_path,
                external_dependency_count=len(external_edges),
                external_targets=external_targets,
                indicators=indicators,
            ),
        )


class StructuralTestsAnalyzer(TestsAnalyzer):
    """Detect test naming conventions, not executed tests or runtime coverage."""

    def analyze(self, extraction_result: SymbolExtractionResult) -> TestsAnalysisResult:
        result = require_tests(extraction_result)
        test_file = is_test_file(result.relative_path.replace("\\", "/"))
        test_symbols = tuple(
            symbol for symbol in result.symbols if is_test_symbol_name(symbol.name, symbol.kind)
        )
        test_function_count = sum(
            symbol.kind in (ExtractedSymbolKind.FUNCTION, ExtractedSymbolKind.METHOD)
            for symbol in test_symbols
        )
        test_class_count = sum(symbol.kind is ExtractedSymbolKind.CLASS for symbol in test_symbols)
        indicators: tuple[TestIndicator, ...] = ()
        if test_file and not test_symbols:
            indicators = (
                TestIndicator(
                    subject_name=result.relative_path,
                    relative_path=result.relative_path,
                    severity=FindingSeverity.LOW,
                    message=(
                        "File follows a test path or filename convention but has no "
                        "test-shaped extracted symbols"
                    ),
                ),
            )
        return TestsAnalysisResult.ok(
            relative_path=result.relative_path,
            evidence=TestEvidence(
                relative_path=result.relative_path,
                is_test_file=test_file,
                test_function_count=test_function_count,
                test_class_count=test_class_count,
                indicators=indicators,
            ),
        )


def analyze_repository_result[ExtractionT, AnalysisT](
    extraction_result: ExtractionT,
    relative_path: str,
    analyzer: Callable[[ExtractionT], AnalysisT],
    failed: Callable[..., AnalysisT],
) -> AnalysisT:
    """Run an analyzer and preserve extraction failures as per-file analysis outcomes.

    The analyzer Ports reject failed extraction records by raising ValidationError. The pipeline
    converts that expected per-file condition into the matching failed analysis result, so one
    unsupported extraction does not abort analysis of other repository files.
    """
    try:
        return analyzer(extraction_result)
    except ValidationError as error:
        return failed(
            relative_path=relative_path,
            error_message=str(error),
        )
