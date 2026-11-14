"""Lifecycle enforcement for review of event-sensitive immutable plan revisions."""

from __future__ import annotations

from datetime import datetime

import pytest

from apps.portfolio.application.transition_plan_lifecycle import (
    RequestTransitionPlanRevisionReview,
    RequestTransitionPlanRevisionReviewUseCase,
    TransitionPlanEventReviewRequired,
    TransitionPlanRevisionBlocked,
)
from apps.portfolio.domain.transition_plan_event_review import (
    TransitionPlanEventReviewAssessment,
    TransitionPlanEventReviewState,
)
from apps.portfolio.domain.transition_plan_revision import TransitionPlanRevision
from tests.unit.portfolio.test_transition_plan_revision_asset_identity import (
    _NOW,
    _LifecycleAuthorizer,
    _LifecycleClock,
    _LifecycleRepository,
    _revision,
)


class _EventReviewValidator:
    """Return a fixed event status while recording lifecycle requests."""

    def __init__(self, state: TransitionPlanEventReviewState) -> None:
        self.state = state
        self.calls: list[tuple[TransitionPlanRevision, datetime]] = []

    def assess(
        self, revision: TransitionPlanRevision, *, as_of: datetime
    ) -> TransitionPlanEventReviewAssessment:
        """Return the test status for the exact revision and current cutoff."""

        self.calls.append((revision, as_of))
        return TransitionPlanEventReviewAssessment(
            state=self.state,
            reason_code=(
                "EVENT_COVERAGE_PIN_MISSING"
                if self.state is TransitionPlanEventReviewState.REVIEW_REQUIRED
                else "EVENTS_UNCHANGED"
            ),
        )


def _request(revision: TransitionPlanRevision) -> RequestTransitionPlanRevisionReview:
    """Build the exact owner review intent for one immutable plan revision."""

    return RequestTransitionPlanRevisionReview(
        actor_user_id=revision.identity.owner_user_id,
        account_id=revision.identity.account_id,
        plan_id=revision.identity.plan_id,
        version=revision.identity.version,
        expected_revision_hash=revision.identity.revision_hash,
    )


def test_unbound_affected_revision_is_stopped_before_repository_review() -> None:
    """A current policy result requiring pins prevents the legacy review transition."""

    revision = _revision()
    repository = _LifecycleRepository()
    repository._store(revision, revision.plan.idempotency_key)
    validator = _EventReviewValidator(TransitionPlanEventReviewState.REVIEW_REQUIRED)
    use_case = RequestTransitionPlanRevisionReviewUseCase(
        repository=repository,
        authorizer=_LifecycleAuthorizer(),
        clock=_LifecycleClock(_NOW),
        event_review_validator=validator,
    )

    with pytest.raises(TransitionPlanEventReviewRequired):
        use_case.execute(_request(revision))

    assert len(validator.calls) == 1
    assert repository.review_calls == 0


def test_missing_event_validator_fails_closed_for_unbound_revision() -> None:
    """A missing current-policy composition cannot silently treat no pins as unchanged."""

    revision = _revision()
    repository = _LifecycleRepository()
    repository._store(revision, revision.plan.idempotency_key)
    use_case = RequestTransitionPlanRevisionReviewUseCase(
        repository=repository,
        authorizer=_LifecycleAuthorizer(),
        clock=_LifecycleClock(_NOW),
    )

    with pytest.raises(TransitionPlanRevisionBlocked) as error:
        use_case.execute(_request(revision))

    assert error.value.code == "TRANSITION_PLAN_EVENT_REVIEW_UNAVAILABLE"
    assert repository.review_calls == 0
