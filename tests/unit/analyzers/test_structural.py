"""Tests for concrete structural analyzer implementations."""

from uuid import uuid4

import pytest
from src.analyzers.structural import (
    StructuralArchitectureAnalyzer,
    StructuralComplexityAnalyzer,
    StructuralDependencyAnalyzer,
    StructuralDocumentationAnalyzer,
    StructuralMetricsAnalyzer,
    StructuralQualityAnalyzer,
    StructuralSecurityAnalyzer,
    StructuralTestsAnalyzer,
)
from src.core.exceptions import ValidationError
from src.extractors.architecture.structural import StructuralArchitectureExtractor
from src.extractors.ast.structural import StructuralAstExtractor
from src.extractors.foundation.structural import StructuralFoundationExtractor
from src.extractors.imports.structural import StructuralImportExtractor
from src.extractors.symbols.structural import StructuralSymbolExtractor
from src.memory.contracts import create_architecture_memory_record
from src.parsers.python.parser import PythonParser

_SOURCE = '''"""Module documentation."""

__all__ = ["PublicThing", "public_function"]

import os

class PublicThing:
    """Class documentation."""

    def documented(self):
        """Method documentation."""
        return os.name

    def test_example(self):
        return True


def public_function():
    """Function documentation."""
    return 1
'''


def _parse():
    result = PythonParser().parse(
        relative_path="tests/test_sample.py",
        content=_SOURCE,
    )
    assert result.succeeded
    return result


def test_structural_architecture_analyzer_uses_extracted_package_facts() -> None:
    extraction = StructuralArchitectureExtractor().extract(_parse())

    result = StructuralArchitectureAnalyzer().analyze(extraction)

    assert result.succeeded
    assert result.assessment is not None
    assert result.assessment.relative_path == "tests/test_sample.py"
    assert result.assessment.package_path == ("tests",)
    assert result.assessment.is_package_root is False


def test_structural_architecture_analyzer_checks_explicit_memory_without_changing_source_facts() -> None:
    extraction = StructuralArchitectureExtractor().extract(_parse())
    matching = create_architecture_memory_record(
        record_id=uuid4(), memory_type="architecture_constraint", expected_package_path=("tests",),
        approved_by="project_owner",
        approval_source="user_instruction",
        approval_reference="test-fixture",
    )
    mismatch = create_architecture_memory_record(
        record_id=uuid4(), memory_type="architecture_decision", expected_package_path=("src", "application"),
        approved_by="project_owner",
        approval_source="user_instruction",
        approval_reference="test-fixture",
    )

    result = StructuralArchitectureAnalyzer().analyze_with_memory(extraction, (mismatch, matching))

    assert result.succeeded
    assert result.assessment is not None
    assert result.assessment.package_path == ("tests",)
    checks = {check.memory_record_id: check.matches for check in result.assessment.memory_checks}
    assert checks == {matching.id: True, mismatch.id: False}


def test_structural_architecture_analyzer_ignores_inactive_or_malformed_memory() -> None:
    extraction = StructuralArchitectureExtractor().extract(_parse())
    active = create_architecture_memory_record(
        record_id=uuid4(), memory_type="architecture_constraint", expected_package_path=("tests",),
        approved_by="project_owner",
        approval_source="user_instruction",
        approval_reference="test-fixture",
    )
    inactive = type(active)(
        id=active.id, memory_type=active.memory_type, content=active.content,
        metadata={**active.metadata, "status": "inactive"},
    )
    malformed = type(active)(
        id=uuid4(), memory_type="architecture_constraint",
        content={"expected_package_path": ["tests", "", 3]},
        metadata={"status": "active", "confidence": 0.99, "analysis_scopes": ["architecture"]},
    )

    result = StructuralArchitectureAnalyzer().analyze_with_memory(extraction, (inactive, malformed))

    assert result.succeeded
    assert result.assessment is not None
    assert result.assessment.memory_checks == ()


def test_structural_complexity_analyzer_computes_structural_ratios() -> None:
    extraction = StructuralAstExtractor().extract(_parse())

    result = StructuralComplexityAnalyzer().analyze(extraction)

    assert result.succeeded
    assert result.metrics is not None
    assert result.metrics.class_count == 1
    assert result.metrics.method_count == 2
    assert result.metrics.function_count == 1
    assert result.metrics.methods_per_class == 2.0


def test_structural_dependency_analyzer_counts_internal_and_external_edges() -> None:
    extraction = StructuralImportExtractor().extract(_parse())

    result = StructuralDependencyAnalyzer().analyze(extraction)

    assert result.succeeded
    assert result.profile is not None
    assert result.profile.total_dependency_count == 1
    assert result.profile.external_dependency_count == 1
    assert result.profile.external_targets == ("os",)


def test_structural_documentation_analyzer_reports_docstring_coverage() -> None:
    extraction = StructuralAstExtractor().extract(_parse())

    result = StructuralDocumentationAnalyzer().analyze(extraction)

    assert result.succeeded
    assert result.coverage is not None
    assert result.coverage.class_documentation_ratio == 1.0
    assert result.coverage.function_documentation_ratio == pytest.approx(2 / 3)
    assert result.coverage.overall_documentation_ratio == pytest.approx(3 / 4)


def test_structural_metrics_analyzer_normalizes_counts_per_kloc() -> None:
    extraction = StructuralAstExtractor().extract(_parse())

    result = StructuralMetricsAnalyzer().analyze(extraction)

    assert result.succeeded
    assert result.metrics is not None
    assert result.metrics.line_count > 0
    assert result.metrics.classes_per_kloc > 0
    assert result.metrics.functions_per_kloc > 0


def test_structural_quality_analyzer_checks_public_candidate_docstrings() -> None:
    extraction = StructuralFoundationExtractor().extract(_parse())

    result = StructuralQualityAnalyzer().analyze(extraction)

    assert result.succeeded
    assert result.assessment is not None
    assert result.assessment.candidate_count == 2
    assert result.assessment.public_candidate_count == 2
    assert result.assessment.documented_public_ratio == 1.0
    assert result.assessment.indicators == ()


def test_structural_security_analyzer_reports_external_boundaries_only() -> None:
    extraction = StructuralImportExtractor().extract(_parse())

    result = StructuralSecurityAnalyzer().analyze(extraction)

    assert result.succeeded
    assert result.assessment is not None
    assert result.assessment.external_dependency_count == 1
    assert result.assessment.external_targets == ("os",)
    assert result.assessment.indicators[0].severity.value == "info"
    assert "no vulnerability assessment" in result.assessment.indicators[0].message


def test_structural_tests_analyzer_detects_test_file_and_test_symbols() -> None:
    extraction = StructuralSymbolExtractor().extract(_parse())

    result = StructuralTestsAnalyzer().analyze(extraction)

    assert result.succeeded
    assert result.evidence is not None
    assert result.evidence.is_test_file is True
    assert result.evidence.test_function_count == 1


def test_structural_tests_analyzer_recognizes_windows_test_paths() -> None:
    extraction = StructuralSymbolExtractor().extract(_parse())
    extraction = type(extraction).ok(
        relative_path="tests\\unit\\test_sample.py",
        symbols=extraction.symbols,
    )

    result = StructuralTestsAnalyzer().analyze(extraction)

    assert result.succeeded
    assert result.evidence is not None
    assert result.evidence.is_test_file is True


def test_analyzers_reject_failed_extractions() -> None:
    failed_parse = PythonParser().parse(
        relative_path="broken.py",
        content="def broken(:",
    )
    assert failed_parse.succeeded is False

    with pytest.raises(ValidationError):
        StructuralArchitectureAnalyzer().analyze(
            StructuralArchitectureExtractor().extract(failed_parse)
        )
