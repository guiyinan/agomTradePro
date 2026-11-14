"""Repository transaction gates for immutable plan event review and insertion."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timedelta

import pytest

from apps.portfolio.application.transition_plan_lifecycle import (
    TransitionPlanEventReviewRequired,
    TransitionPlanRevisionBlocked,
    derive_transition_plan_review_artifact_identity,
)
from apps.portfolio.domain.transition_plan_event_review import (
    TransitionPlanEventReviewAssessment,
    TransitionPlanEventReviewState,
)
from apps.portfolio.domain.transition_plan_revision import TransitionPlanRevision
from apps.portfolio.infrastructure import transition_plan_revision_repository as repository_module
from apps.portfolio.infrastructure.transition_plan_revision_repository import (
    DjangoTransitionPlanRevisionRepository,
)
from tests.unit.portfolio.test_transition_plan_revision_asset_identity import _NOW, _revision


class _EventReviewValidator:
    """Return one review-required result and retain every exact invocation."""

    def __init__(self) -> None:
        self.calls: list[tuple[TransitionPlanRevision, datetime]] = []

    def assess(
        self, revision: TransitionPlanRevision, *, as_of: datetime
    ) -> TransitionPlanEventReviewAssessment:
        """Return the current missing-pin status without writing plan state."""

        self.calls.append((revision, as_of))
        return TransitionPlanEventReviewAssessment(
            state=TransitionPlanEventReviewState.REVIEW_REQUIRED,
            reason_code="EVENT_COVERAGE_PIN_MISSING",
        )


class _PendingRow:
    """Model only the fields read by the repository's pending exact-retry branch."""

    def __init__(self, review_subject_id: str) -> None:
        self.status = "APPROVAL_PENDING"
        self.approval_request_id = review_subject_id
        self.expires_at = _NOW + timedelta(minutes=20)
        self.save_calls = 0

    def save(self, *, update_fields: list[str]) -> None:
        """Record an unexpected persistence attempt in this read-only retry test."""

        self.save_calls += 1


class _Manager:
    """Serve one synthetic locked row for the actual repository method path."""

    def __init__(self, row: _PendingRow, *, plan_id: str) -> None:
        self.row = row
        self.plan_id = plan_id

    def select_for_update(self) -> _Manager:
        """Keep the repository lock-chain API while avoiding a database connection."""

        return self

    def get(self, **kwargs: object) -> _PendingRow:
        """Return the exact test row selected by its pinned identity."""

        assert kwargs == {"plan_id": self.plan_id, "plan_version": 1}
        return self.row


def test_exact_pending_retry_revalidates_unbound_revision_before_early_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An approval-pending retry cannot bypass current event review for a legacy plan."""

    revision = _revision()
    subject_id = derive_transition_plan_review_artifact_identity(revision).subject_id
    row = _PendingRow(subject_id)
    manager = _Manager(row, plan_id=revision.identity.plan_id)
    validator = _EventReviewValidator()
    repository = DjangoTransitionPlanRevisionRepository(event_review_validator=validator)
    monkeypatch.setattr(repository_module.transaction, "atomic", lambda using: nullcontext())
    monkeypatch.setattr(repository, "_locked_account_revisions", lambda account_id: (revision,))
    monkeypatch.setattr(repository, "_manager", lambda: manager)
    monkeypatch.setattr(repository, "now", lambda: _NOW + timedelta(seconds=1))

    with pytest.raises(TransitionPlanEventReviewRequired):
        repository.submit_for_review(
            revision=revision,
            owner_user_id=revision.identity.owner_user_id,
            review_subject_id=subject_id,
            requested_at=_NOW,
        )

    assert len(validator.calls) == 1
    assert validator.calls[0] == (revision, _NOW + timedelta(seconds=1))
    assert row.save_calls == 0


def test_unbound_new_revision_insert_uses_current_event_review_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The actual pre-insert lease method checks plans that never stored event pins."""

    revision = _revision()
    validator = _EventReviewValidator()
    repository = DjangoTransitionPlanRevisionRepository(event_review_validator=validator)
    monkeypatch.setattr(repository, "now", lambda: _NOW + timedelta(seconds=1))

    with pytest.raises(TransitionPlanEventReviewRequired):
        repository._require_event_lease_before_insert(revision)

    assert validator.calls == [(revision, _NOW + timedelta(seconds=1))]


def test_unbound_new_revision_insert_blocks_when_validator_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repository construction without the current-policy reader is fail closed."""

    revision = _revision()
    repository = DjangoTransitionPlanRevisionRepository()
    monkeypatch.setattr(repository, "now", lambda: _NOW + timedelta(seconds=1))

    with pytest.raises(TransitionPlanRevisionBlocked) as error:
        repository._require_event_lease_before_insert(revision)

    assert error.value.code == "TRANSITION_PLAN_EVENT_REVIEW_UNAVAILABLE"
