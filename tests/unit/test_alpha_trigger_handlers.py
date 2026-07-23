"""Behavior contracts for Alpha Trigger event handlers."""

from datetime import UTC, datetime

from apps.alpha_trigger.application.handlers import (
    CandidatePromotionHandler,
    TriggerInvalidationHandler,
)
from apps.alpha_trigger.domain.entities import (
    AlphaCandidate,
    CandidateStatus,
    SignalStrength,
)
from apps.alpha_trigger.infrastructure.repositories import AlphaCandidateRepository
from apps.events.domain.entities import DomainEvent, EventType


class _CandidateRepository:
    def __init__(self, candidate: AlphaCandidate) -> None:
        self.candidate = candidate
        self.status_updates: list[CandidateStatus] = []

    def get_by_trigger_id(self, trigger_id: str) -> AlphaCandidate | None:
        assert trigger_id == self.candidate.trigger_id
        return self.candidate

    def update_status(
        self,
        candidate_id: str,
        status: CandidateStatus,
    ) -> AlphaCandidate:
        assert candidate_id == self.candidate.candidate_id
        self.status_updates.append(status)
        self.candidate.status = status
        return self.candidate


class _EventPublisher:
    def publish(self, event: DomainEvent) -> None:
        pass


def _event(event_type: EventType, **payload: object) -> DomainEvent:
    return DomainEvent(
        event_id="event-1",
        event_type=event_type,
        occurred_at=datetime.now(UTC),
        payload=payload,
    )


def _candidate() -> AlphaCandidate:
    return AlphaCandidate(
        candidate_id="candidate-1",
        trigger_id="trigger-1",
        asset_code="000001.SH",
        asset_class="a_share",
        direction="LONG",
        strength=SignalStrength.STRONG,
        confidence=0.8,
        thesis="typed promotion",
    )


def test_invalidation_handler_accepts_fired_event() -> None:
    """Use the event type that is actually published by Alpha Trigger."""

    handler = TriggerInvalidationHandler(object(), event_bus=_EventPublisher())

    assert handler.can_handle(EventType.ALPHA_TRIGGER_FIRED)


def test_candidate_promotion_passes_domain_status_to_repository() -> None:
    """Keep the promotion handler aligned with the repository enum contract."""

    repository = _CandidateRepository(_candidate())
    handler = CandidatePromotionHandler(repository, event_bus=None)

    handler.handle(
        _event(
            EventType.ALPHA_TRIGGER_FIRED,
            trigger_id="trigger-1",
            strength=SignalStrength.STRONG.value,
        )
    )

    assert repository.status_updates == [CandidateStatus.ACTIONABLE]


def test_rejected_decision_maps_to_supported_cancelled_lifecycle(monkeypatch) -> None:
    """Represent a rejected decision with the candidate model's terminal cancel state."""

    repository = AlphaCandidateRepository()
    statuses: list[CandidateStatus] = []

    def capture_status(candidate_id: str, status: CandidateStatus) -> AlphaCandidate:
        assert candidate_id == "candidate-1"
        statuses.append(status)
        return _candidate()

    monkeypatch.setattr(repository, "update_status", capture_status)

    assert repository.update_status_to_rejected("candidate-1")
    assert statuses == [CandidateStatus.CANCELLED]
