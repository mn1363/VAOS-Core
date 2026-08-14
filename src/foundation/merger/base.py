"""Foundation merger Port: coordinated merging of selected candidates into a Foundation result.

`FoundationMerger` turns a `foundation.selector.base.FoundationSelectionResult` into a
`FoundationResult` -- the flat, self-contained set of `FoundationMember`s that make up this
Foundation decision. It re-validates, rather than blindly trusts, that the selection it is given
is actually mergeable: every selected `subject_id` must be known to both `subjects` and `ranking`
(see `require_mergeable_selection`), and -- when `comparisons` is given -- no two selected
subjects may have been compared as `CONFLICTING` (see `require_no_conflicting_selection`), the
same defense-in-depth a selector's own compatibility check already applies, checked again here
since a `FoundationResult` is this layer's authoritative, external-facing outcome. It does not
itself decide which subjects are selected (that is `foundation.selector`'s concern) and does not
export the result -- that is `foundation.exporter`'s concern, which consumes the `FoundationResult`
this produces.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from src.core.exceptions import NotFoundError, ValidationError
from src.core.logging import get_logger
from src.extractors.foundation.base import FoundationCandidateKind
from src.foundation.comparer.base import (
    FoundationComparisonOutcome,
    FoundationComparisonVerdict,
    FoundationSubject,
)
from src.foundation.ranking.base import FoundationRanking
from src.foundation.selector.base import FoundationSelectionResult

_logger = get_logger("foundation.merger")


@dataclass(frozen=True, slots=True)
class FoundationMember:
    """A single selected subject's record within a `FoundationResult`.

    Flat and self-contained -- every field a consumer needs is carried through from the
    originating `FoundationSubject` and its `FoundationScore` directly, rather than requiring a
    downstream reader to re-join against `subjects`/`ranking`, matching the "carried through from
    the originating X unchanged" convention `analyzers.architecture.base.ArchitectureAssessment`
    already established.

    Attributes:
        subject_id: `FoundationSubject.subject_id` this member was built from.
        repository_id: The originating subject's `FoundationSubject.repository_id`.
        name: The originating candidate's `FoundationCandidate.name`.
        kind: The originating candidate's `FoundationCandidate.kind`.
        relative_path: The originating candidate's `FoundationCandidate.relative_path`.
        score: The originating subject's `FoundationScore.value`.
    """

    subject_id: str
    repository_id: UUID
    name: str
    kind: FoundationCandidateKind
    relative_path: str
    score: float

    def __post_init__(self) -> None:
        """Validate that identifying fields are non-blank and `score` is within range.

        Raises:
            ValidationError: If `subject_id`, `name`, or `relative_path` is blank, or `score`
                falls outside `[0.0, 1.0]`.
        """
        if not self.subject_id.strip():
            raise ValidationError("FoundationMember: subject_id must not be empty")
        if not self.name.strip():
            raise ValidationError("FoundationMember: name must not be empty")
        if not self.relative_path.strip():
            raise ValidationError("FoundationMember: relative_path must not be empty")
        if not 0.0 <= self.score <= 1.0:
            raise ValidationError("FoundationMember: score must be between 0.0 and 1.0")


@dataclass(frozen=True, slots=True)
class FoundationResult:
    """The merged outcome of one Foundation decision: every selected, compatible member.

    Attributes:
        members: Every merged member, sorted by `(-score, subject_id)` -- highest score first,
            matching `FoundationRanking.scores`' own order -- and free of duplicate `subject_id`s.
    """

    members: tuple[FoundationMember, ...] = ()

    def __post_init__(self) -> None:
        """Validate that `members` is sorted by `(-score, subject_id)` and free of duplicates.

        Raises:
            ValidationError: If `members` is not in `(-score, subject_id)` order, or contains two
                entries with the same `subject_id`.
        """
        sort_keys = [(-member.score, member.subject_id) for member in self.members]
        if sort_keys != sorted(sort_keys):
            raise ValidationError(
                "FoundationResult: members must be sorted by (-score, subject_id)"
            )
        subject_ids = [member.subject_id for member in self.members]
        if len(set(subject_ids)) != len(subject_ids):
            raise ValidationError("FoundationResult: members must not contain duplicate subjects")

    @property
    def member_count(self) -> int:
        """Total number of merged members."""
        return len(self.members)

    def get_member(self, subject_id: str) -> FoundationMember:
        """Retrieve a single member by its `subject_id`.

        Args:
            subject_id: The `FoundationSubject.subject_id` to look up.

        Returns:
            The matching `FoundationMember`.

        Raises:
            NotFoundError: If no entry in `members` has that `subject_id`.
        """
        for member in self.members:
            if member.subject_id == subject_id:
                return member
        raise NotFoundError(f"no FoundationMember for subject_id '{subject_id}' in this result")

    def to_mapping(self) -> dict[str, Any]:
        """Render this result as a plain, JSON-safe nested structure.

        Returns:
            A dict with one key, `"members"`, a list of dicts in `members`' existing order, each
            with `subject_id`, `repository_id` (rendered as its string form), `name`, `kind`
            (rendered as its string form), `relative_path`, and `score`.
        """
        return {
            "members": [
                {
                    "subject_id": member.subject_id,
                    "repository_id": str(member.repository_id),
                    "name": member.name,
                    "kind": str(member.kind),
                    "relative_path": member.relative_path,
                    "score": member.score,
                }
                for member in self.members
            ],
        }


class FoundationMerger(ABC):
    """Merges a selector's chosen, mutually-compatible subjects into a `FoundationResult`.

    A concrete implementation decides how to assemble `FoundationMember`s from `subjects` and
    `ranking`; it does not decide which subjects are selected (that is `foundation.selector`'s
    concern) or export the result -- that is `foundation.exporter`'s concern.
    """

    @abstractmethod
    def merge(
        self,
        subjects: Sequence[FoundationSubject],
        ranking: FoundationRanking,
        selection: FoundationSelectionResult,
        comparisons: Sequence[FoundationComparisonOutcome] = (),
    ) -> FoundationResult:
        """Merge every subject `selection` selected into a single `FoundationResult`.

        Args:
            subjects: Every candidate under consideration -- must include every subject
                `selection.selected_subject_ids` names.
            ranking: `subjects`' scores -- must include a score for every subject
                `selection.selected_subject_ids` names.
            selection: The selection to merge. Only `selection.selected_subject_ids` are
                included in the result; `selection.rejections` is not consulted.
            comparisons: Pairwise comparisons among `subjects`, re-checked so that no two members
                being merged were compared as `CONFLICTING`. Defaults to `()` (no re-check
                performed) when the caller has already guaranteed compatibility upstream.

        Returns:
            A `FoundationResult` with exactly one `FoundationMember` per entry in
            `selection.selected_subject_ids`.

        Raises:
            ValidationError: If `selection` selects a `subject_id` absent from `subjects` or
                `ranking` -- see `require_mergeable_selection` -- or if `comparisons` records two
                selected subjects as `CONFLICTING` -- see `require_no_conflicting_selection`.
        """
        ...


def require_mergeable_selection(
    subjects: Sequence[FoundationSubject],
    ranking: FoundationRanking,
    selection: FoundationSelectionResult,
) -> None:
    """Validate that every subject `selection` selected is known to both `subjects` and
    `ranking`.

    Every `FoundationMerger.merge` implementation calls this first, so a caller error (a
    selection built from a different subject set, or a ranking missing a selected subject's
    score) is reported the same way -- as an immediate `ValidationError` -- across every
    implementation.

    Args:
        subjects: The raw `subjects` argument passed to `merge`.
        ranking: The raw `ranking` argument passed to `merge`.
        selection: The raw `selection` argument passed to `merge`.

    Raises:
        ValidationError: If a `subject_id` in `selection.selected_subject_ids` is absent from
            `subjects`, or has no matching entry in `ranking.scores`.
    """
    known_subjects = {subject.subject_id for subject in subjects}
    known_scores = {score.subject_id for score in ranking.scores}
    for subject_id in selection.selected_subject_ids:
        if subject_id not in known_subjects:
            _logger.debug("Rejected merge: selected subject '%s' is unknown", subject_id)
            raise ValidationError(
                "cannot merge a selected subject absent from subjects",
                details={"subject_id": subject_id},
            )
        if subject_id not in known_scores:
            _logger.debug("Rejected merge: selected subject '%s' has no score", subject_id)
            raise ValidationError(
                "cannot merge a selected subject with no ranking score",
                details={"subject_id": subject_id},
            )


def require_no_conflicting_selection(
    selected_subject_ids: Sequence[str],
    comparisons: Sequence[FoundationComparisonOutcome],
) -> None:
    """Validate that no two `selected_subject_ids` were compared as `CONFLICTING`.

    Every `FoundationMerger.merge` implementation calls this when `comparisons` is non-empty, so
    a caller error (a selection that let two conflicting subjects through) is reported the same
    way -- as an immediate `ValidationError` -- across every implementation.

    Args:
        selected_subject_ids: `subject_id`s being merged together.
        comparisons: Pairwise comparisons to check `selected_subject_ids` against.

    Raises:
        ValidationError: If any entry in `comparisons` has `verdict == CONFLICTING` and both
            `left_subject_id` and `right_subject_id` are in `selected_subject_ids`.
    """
    selected = set(selected_subject_ids)
    for outcome in comparisons:
        if (
            outcome.verdict is FoundationComparisonVerdict.CONFLICTING
            and outcome.left_subject_id in selected
            and outcome.right_subject_id in selected
        ):
            _logger.debug(
                "Rejected merge: subjects '%s' and '%s' were compared as CONFLICTING",
                outcome.left_subject_id,
                outcome.right_subject_id,
            )
            raise ValidationError(
                "cannot merge two subjects compared as CONFLICTING",
                details={
                    "left_subject_id": outcome.left_subject_id,
                    "right_subject_id": outcome.right_subject_id,
                },
            )
