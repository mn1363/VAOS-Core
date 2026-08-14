"""Foundation comparer Port: deterministic pairwise candidate comparison.

`FoundationComparer` compares two `FoundationSubject`s -- each an `extractors.foundation.base.
FoundationCandidate` identified within one specific repository -- and reports how they relate,
using only signals the candidate itself already carries (`name`, `kind`, `signals`): whether they
are interchangeable duplicates (`EQUIVALENT`), share a construct kind and at least one signal
without naming the same thing (`COMPATIBLE`), name the same construct but disagree on their
signals (`CONFLICTING`), or share nothing meaningful (`DISTINCT`). It does not decide which
candidates are worth keeping -- that is `foundation.ranking`'s and `foundation.selector`'s
concern -- and it does not itself extract, parse, or collect anything, all upstream concerns
already handled by `src.parsers`/`src.extractors`/`src.collectors`.

This module also defines `FoundationSubject` -- pairing a `FoundationCandidate` with the
identifier of the repository it was found in, since the candidate alone carries no repository
context and comparing "candidate capabilities/components from analyzed repositories" (plural)
requires one -- and `build_subjects`, assembling every subject in one repository from its files'
`FoundationExtractionResult`s. Every other `foundation` subpackage imports `FoundationSubject`
from here rather than redefining it.
"""

import itertools
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum, auto
from uuid import UUID

from src.core.exceptions import ValidationError
from src.core.logging import get_logger
from src.extractors.foundation.base import FoundationCandidate, FoundationExtractionResult
from src.extractors.symbols.base import build_qualified_name

_logger = get_logger("foundation.comparer")


@dataclass(frozen=True, slots=True)
class FoundationSubject:
    """A single `FoundationCandidate`, identified within one specific repository.

    Attributes:
        repository_id: Identifier of the `domain.entities.SourceRepository` the candidate was
            found in, matching `domain.entities.SourceFile.repository_id`'s own field name and
            type so this stays the same repository-identity scheme `domain` already establishes,
            without importing the entity itself.
        candidate: The raw, per-file reuse-candidacy signal set this subject wraps, exactly as
            produced by `extractors.foundation.base.FoundationExtractor.extract`.
    """

    repository_id: UUID
    candidate: FoundationCandidate

    @property
    def subject_id(self) -> str:
        """Globally-unique identifier for this subject, across every repository being compared.

        Returns:
            `repository_id` joined to the candidate's own qualified name, built with the same
            `extractors.symbols.base.build_qualified_name` scheme `graph.knowledge.base.
            capability_node_id` already uses for `FoundationCandidate`-derived identifiers,
            reused here rather than redefined.
        """
        qualified_name = build_qualified_name(
            relative_path=self.candidate.relative_path, name=self.candidate.name
        )
        return f"{self.repository_id}:{qualified_name}"


def require_successful_foundation_extractions(
    extraction_results: Sequence[FoundationExtractionResult],
) -> Sequence[FoundationExtractionResult]:
    """Validate that every entry in `extraction_results` represents a successful extraction.

    Every `build_subjects` call validates its input this way first, so a caller error (a
    `FoundationExtractionResult` with `succeeded=False` mixed into the sequence) is reported the
    same way -- as an immediate `ValidationError` -- matching every `require_successful_
    extraction(s)` helper already established across `src.extractors`/`src.analyzers`/`src.graph`.

    Args:
        extraction_results: The raw `extraction_results` argument passed to `build_subjects`.

    Returns:
        `extraction_results`, unchanged.

    Raises:
        ValidationError: If any entry's `succeeded` is False.
    """
    for extraction_result in extraction_results:
        if not extraction_result.succeeded:
            _logger.debug(
                "Rejected subject construction from an unsuccessful foundation extraction of "
                "'%s'",
                extraction_result.relative_path,
            )
            raise ValidationError(
                "cannot build FoundationSubjects from a failed FoundationExtractionResult",
                details={"relative_path": extraction_result.relative_path},
            )
    return extraction_results


def build_subjects(
    *, repository_id: UUID, extraction_results: Sequence[FoundationExtractionResult]
) -> tuple[FoundationSubject, ...]:
    """Build every `FoundationSubject` found in one repository's extraction results.

    Args:
        repository_id: Identifier of the repository `extraction_results` was extracted from.
        extraction_results: Outcomes of extracting foundation candidates for every file under
            consideration in that repository, as produced by `src.extractors.foundation`. Every
            entry must be successful -- see `require_successful_foundation_extractions`.

    Returns:
        One `FoundationSubject` per candidate across every entry in `extraction_results`, sorted
        by `subject_id` so the result is deterministic regardless of input order.

    Raises:
        ValidationError: If any entry in `extraction_results` is itself a failed extraction, or
            if two candidates resolve to the same `subject_id` (the same repository, file, and
            candidate name appearing more than once).
    """
    require_successful_foundation_extractions(extraction_results)
    subjects = [
        FoundationSubject(repository_id=repository_id, candidate=candidate)
        for extraction_result in extraction_results
        for candidate in extraction_result.candidates
    ]
    subjects.sort(key=lambda subject: subject.subject_id)

    subject_ids = [subject.subject_id for subject in subjects]
    if len(set(subject_ids)) != len(subject_ids):
        raise ValidationError(
            "build_subjects: extraction_results produced two candidates with the same "
            "subject_id",
            details={"repository_id": str(repository_id)},
        )
    return tuple(subjects)


class FoundationComparisonVerdict(StrEnum):
    """How two `FoundationSubject`s relate, per `FoundationComparer.compare`."""

    EQUIVALENT = auto()
    """Same construct kind, same name, and identical signals -- interchangeable duplicates."""

    COMPATIBLE = auto()
    """Same construct kind and at least one shared signal, but not naming the same construct --
    can coexist in the same Foundation result."""

    CONFLICTING = auto()
    """Same construct kind and same name, but signals disagree -- cannot be cleanly merged
    without reconciling which subject's signals are authoritative."""

    DISTINCT = auto()
    """Neither the same construct nor sharing any signal -- unrelated."""


@dataclass(frozen=True, slots=True)
class FoundationComparisonOutcome:
    """Outcome of a single `FoundationComparer.compare` call.

    Attributes:
        left_subject_id: `FoundationSubject.subject_id` of the first subject compared.
        right_subject_id: `FoundationSubject.subject_id` of the second subject compared. Always
            different from `left_subject_id` -- comparing a subject to itself is meaningless.
        verdict: How the two subjects relate.
        shared_signals: The subjects' common `FoundationCandidate.signals` entries, deduplicated
            and lexicographically sorted so the result is deterministic. Possibly empty, even for
            an `EQUIVALENT`/`CONFLICTING` verdict reached on `name`/`kind` alone.
    """

    left_subject_id: str
    right_subject_id: str
    verdict: FoundationComparisonVerdict
    shared_signals: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate that both subject ids are non-blank, distinct, and `shared_signals` is
        well-formed.

        Raises:
            ValidationError: If `left_subject_id` or `right_subject_id` is blank, if they are
                equal, or if `shared_signals` is not sorted and free of duplicates.
        """
        if not self.left_subject_id.strip():
            raise ValidationError("FoundationComparisonOutcome: left_subject_id must not be empty")
        if not self.right_subject_id.strip():
            raise ValidationError(
                "FoundationComparisonOutcome: right_subject_id must not be empty"
            )
        if self.left_subject_id == self.right_subject_id:
            raise ValidationError(
                "FoundationComparisonOutcome: left_subject_id and right_subject_id must differ",
                details={"subject_id": self.left_subject_id},
            )
        if list(self.shared_signals) != sorted(set(self.shared_signals)):
            raise ValidationError(
                "FoundationComparisonOutcome: shared_signals must be sorted and free of "
                "duplicates"
            )


class FoundationComparer(ABC):
    """Compares two `FoundationSubject`s using deterministic, signal-based comparison rules.

    A concrete implementation decides exactly how `name`/`kind`/`signals` combine into a
    `FoundationComparisonVerdict`; it does not score, select, or merge candidates -- those are
    `foundation.ranking`, `foundation.selector`, and `foundation.merger`'s concerns respectively.
    """

    @abstractmethod
    def compare(
        self, left: FoundationSubject, right: FoundationSubject
    ) -> FoundationComparisonOutcome:
        """Compare `left` and `right`, deterministically.

        Args:
            left: The first subject to compare.
            right: The second subject to compare. Must not be the same subject as `left` -- see
                `require_distinct_subjects`.

        Returns:
            A `FoundationComparisonOutcome` describing how `left` and `right` relate. Calling
            `compare(left, right)` and `compare(right, left)` must produce the same `verdict` and
            `shared_signals` (with `left_subject_id`/`right_subject_id` swapped accordingly) --
            comparison is symmetric.

        Raises:
            ValidationError: If `left` and `right` are the same subject (`subject_id` equal) --
                see `require_distinct_subjects`.
        """
        ...


def require_distinct_subjects(
    left: FoundationSubject, right: FoundationSubject
) -> tuple[FoundationSubject, FoundationSubject]:
    """Validate that `left` and `right` are not the same subject.

    Every `FoundationComparer.compare` implementation calls this first, so a caller error
    (comparing a subject to itself) is reported the same way -- as an immediate
    `ValidationError` -- across every implementation.

    Args:
        left: The raw `left` argument passed to `compare`.
        right: The raw `right` argument passed to `compare`.

    Returns:
        `(left, right)`, unchanged.

    Raises:
        ValidationError: If `left.subject_id == right.subject_id`.
    """
    if left.subject_id == right.subject_id:
        _logger.debug("Rejected comparison of subject '%s' to itself", left.subject_id)
        raise ValidationError(
            "cannot compare a FoundationSubject to itself",
            details={"subject_id": left.subject_id},
        )
    return left, right


def compare_all(
    comparer: FoundationComparer, subjects: Sequence[FoundationSubject]
) -> tuple[FoundationComparisonOutcome, ...]:
    """Compare every distinct pair of `subjects`, deterministically.

    Args:
        comparer: The `FoundationComparer` to compare each pair with.
        subjects: The subjects to compare, drawn from one or more repositories.

    Returns:
        One `FoundationComparisonOutcome` per unordered pair of `subjects`, in `(left_subject_id,
        right_subject_id)` order, over subjects first sorted by `subject_id` -- deterministic
        regardless of the order `subjects` was given in.
    """
    ordered = sorted(subjects, key=lambda subject: subject.subject_id)
    return tuple(
        comparer.compare(left, right) for left, right in itertools.combinations(ordered, 2)
    )
