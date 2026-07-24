"""Application orchestration tests for Alpha Trigger lifecycle use cases."""

from __future__ import annotations

from datetime import UTC, datetime

from apps.alpha_trigger.application.use_cases import (
    CheckInvalidationRequest,
    CheckTriggerInvalidationUseCase,
    CreateAlphaTriggerUseCase,
    CreateTriggerRequest,
    EvaluateAlphaTriggerUseCase,
    EvaluateTriggerRequest,
    GenerateCandidateRequest,
    GenerateCandidateUseCase,
)
from apps.alpha_trigger.domain.entities import (
    AlphaCandidate,
    AlphaTrigger,
    SignalStrength,
    TriggerStatus,
    TriggerType,
)


class _TriggerRepo:
    def __init__(self, trigger: AlphaTrigger | None = None) -> None:
        self.trigger = trigger
        self.updates: list[TriggerStatus] = []

    def save(self, trigger: AlphaTrigger) -> AlphaTrigger:
        self.trigger = trigger
        return trigger

    def get_by_id(self, trigger_id: str) -> AlphaTrigger | None:
        return self.trigger if self.trigger and self.trigger.trigger_id == trigger_id else None

    def update_status(
        self,
        trigger_id: str,
        status: TriggerStatus,
        **kwargs: object,
    ) -> AlphaTrigger:
        assert self.trigger is not None
        self.updates.append(status)
        values = self.trigger.to_dict()
        values["status"] = status.value
        values.update(
            {
                key: value.isoformat() if isinstance(value, datetime) else value
                for key, value in kwargs.items()
            }
        )
        self.trigger = AlphaTrigger.from_dict(values)
        return self.trigger


class _CandidateRepo:
    def __init__(self) -> None:
        self.saved: AlphaCandidate | None = None

    def save(self, candidate: AlphaCandidate) -> AlphaCandidate:
        self.saved = candidate
        return candidate


class _Bus:
    def __init__(self) -> None:
        self.events: list[object] = []

    def publish(self, event: object) -> None:
        self.events.append(event)


def _trigger(*, status: TriggerStatus = TriggerStatus.ACTIVE) -> AlphaTrigger:
    return AlphaTrigger(
        trigger_id="trigger-app",
        trigger_type=TriggerType.MOMENTUM_SIGNAL,
        asset_code="000001.SZ",
        asset_class="a_股票",
        direction="LONG",
        trigger_condition={"momentum_pct": 0.05},
        invalidation_conditions=[],
        strength=SignalStrength.STRONG,
        confidence=0.8,
        created_at=datetime.now(UTC),
        status=status,
        thesis="momentum contract",
    )


def test_create_trigger_validates_persists_and_publishes() -> None:
    """Creation rejects malformed requests and publishes valid persisted triggers."""
    repo = _TriggerRepo()
    bus = _Bus()
    use_case = CreateAlphaTriggerUseCase(repo, event_bus=bus)
    invalid = CreateTriggerRequest(
        trigger_type=TriggerType.MOMENTUM_SIGNAL,
        asset_code="",
        asset_class="a_股票",
        direction="BAD",
        trigger_condition={},
        invalidation_conditions=[],
        confidence=2,
    )
    assert use_case.execute(invalid).success is False

    valid = CreateTriggerRequest(
        trigger_type=TriggerType.MOMENTUM_SIGNAL,
        asset_code="000001.SZ",
        asset_class="a_股票",
        direction="LONG",
        trigger_condition={"momentum_pct": 0.05},
        invalidation_conditions=[],
        confidence=0.8,
        expires_in_days=5,
        thesis="contract",
    )
    response = use_case.execute(valid)
    assert response.success is True
    assert repo.trigger is response.trigger
    assert response.trigger is not None and response.trigger.expires_at is not None
    assert len(bus.events) == 1


def test_evaluate_and_invalidate_cover_missing_false_and_transition_paths() -> None:
    """Evaluation and invalidation distinguish missing, unmet, and state-changing paths."""
    missing_repo = _TriggerRepo()
    assert (
        EvaluateAlphaTriggerUseCase(missing_repo)
        .execute(EvaluateTriggerRequest("missing", {}))
        .success
        is False
    )
    assert (
        CheckTriggerInvalidationUseCase(missing_repo)
        .execute(CheckInvalidationRequest("missing", {}))
        .success
        is False
    )

    repo = _TriggerRepo(_trigger())
    bus = _Bus()
    not_fired = EvaluateAlphaTriggerUseCase(repo, event_bus=bus).execute(
        EvaluateTriggerRequest("trigger-app", {"momentum": 0.01})
    )
    assert not_fired.success is True and not not_fired.should_trigger

    fired = EvaluateAlphaTriggerUseCase(repo, event_bus=bus).execute(
        EvaluateTriggerRequest("trigger-app", {"momentum": 0.08})
    )
    assert fired.should_trigger is True
    assert repo.updates[-1] == TriggerStatus.TRIGGERED
    assert bus.events

    valid = CheckTriggerInvalidationUseCase(repo, event_bus=bus).execute(
        CheckInvalidationRequest("trigger-app", {"PMI": 52})
    )
    assert valid.success is True and not valid.is_invalidated


def test_candidate_generation_requires_fired_trigger_and_publishes_candidate() -> None:
    """Candidate generation is gated by trigger state and emits evidence on success."""
    candidates = _CandidateRepo()
    assert (
        GenerateCandidateUseCase(_TriggerRepo(), candidates)
        .execute(GenerateCandidateRequest("missing"))
        .success
        is False
    )
    assert (
        GenerateCandidateUseCase(_TriggerRepo(_trigger()), candidates)
        .execute(GenerateCandidateRequest("trigger-app"))
        .success
        is False
    )

    bus = _Bus()
    response = GenerateCandidateUseCase(
        _TriggerRepo(_trigger(status=TriggerStatus.TRIGGERED)),
        candidates,
        event_bus=bus,
    ).execute(GenerateCandidateRequest("trigger-app", time_window_days=30))
    assert response.success is True
    assert response.candidate is candidates.saved
    assert len(bus.events) == 1
