"""Pure contract tests for the read-only R6 manual-activation preflight."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import pytest

from apps.research.application.r6_manual_activation_preflight import (
    EvaluateR6ManualActivationPreflight,
    EvaluateR6ManualActivationPreflightCommand,
    R6ManualActivationBlockerCode,
    R6ManualActivationPreflightStatus,
    R6ManualActivationUnavailable,
)
from apps.research.application.state_model_monitoring import (
    ActiveR6QualificationEvidence,
)
from apps.research.domain.state_model_activation import (
    R6ActivationApprovalRef,
    R6ActivationScope,
    R6MonitoringActivationEvidence,
    R6MonitoringActivationStatus,
)
from apps.research.domain.state_model_qualification_lifecycle import (
    R6QualificationRef,
)

NOW = datetime(2026, 8, 11, 4, 0, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


class _Uow:
    unit_of_work_key = "django:test"

    def atomic(self):
        return nullcontext()

    def server_now(self) -> datetime:
        return NOW


class _ScopeProvider:
    unit_of_work_key = "django:test"

    def __init__(self, scope: R6ActivationScope | None) -> None:
        self.scope = scope
        self.calls: list[tuple[str, datetime]] = []

    def get_exact(self, *, scope_id: str, as_of: datetime) -> R6ActivationScope | None:
        self.calls.append((scope_id, as_of))
        return self.scope


class _QualificationProvider:
    unit_of_work_key = "django:test"

    def __init__(self, value: ActiveR6QualificationEvidence | None) -> None:
        self.value = value
        self.calls = 0

    def get_latest_active(
        self,
        *,
        scope: R6ActivationScope,
        as_of: datetime,
    ) -> ActiveR6QualificationEvidence | None:
        self.calls += 1
        return self.value


class _MonitoringProvider:
    unit_of_work_key = "django:test"

    def __init__(self, value: R6MonitoringActivationEvidence | None) -> None:
        self.value = value
        self.calls = 0

    def get_latest_complete(
        self,
        *,
        scope: R6ActivationScope,
        qualification: ActiveR6QualificationEvidence,
        as_of: datetime,
    ) -> R6MonitoringActivationEvidence | None:
        self.calls += 1
        return self.value


class _ActivationStateProvider:
    unit_of_work_key = "django:test"

    def __init__(self, value: R6ActivationApprovalRef | None = None) -> None:
        self.value = value
        self.calls = 0

    def get_active_approval_ref(
        self,
        *,
        scope: R6ActivationScope,
        as_of: datetime,
    ) -> R6ActivationApprovalRef | None:
        self.calls += 1
        return self.value


def _scope() -> R6ActivationScope:
    return R6ActivationScope(
        scope_id="r6-state-model-advisory",
        scope_version="v1",
        purpose="manual-activation-review",
        label_protocol_version="labels-v1",
    )


def _qualification() -> ActiveR6QualificationEvidence:
    return ActiveR6QualificationEvidence(
        qualification_ref=R6QualificationRef("qualification-1", HASH_A),
        candidate_id="candidate-1",
        candidate_version="v1",
        assessed_at=NOW - timedelta(days=3),
        known_at=NOW - timedelta(days=2),
        research_only=True,
        must_not_use_for_decision=True,
        must_not_replace_regime=True,
    )


def _monitoring(
    qualification: ActiveR6QualificationEvidence,
    *,
    status: R6MonitoringActivationStatus = R6MonitoringActivationStatus.HEALTHY,
) -> R6MonitoringActivationEvidence:
    return R6MonitoringActivationEvidence(
        assessment_id="monitoring-1",
        assessment_hash=HASH_B,
        qualification_ref=qualification.qualification_ref,
        policy_id="monitoring-policy",
        policy_version="v1",
        policy_hash=HASH_C,
        label_protocol_version="labels-v1",
        label_set_hash=HASH_A,
        status=status,
        evaluated_at=NOW - timedelta(hours=2),
        recorded_at=NOW - timedelta(hours=1),
        valid_until=NOW + timedelta(hours=1),
        owner="research",
        evidence_ref="research:r6-monitoring:monitoring-1",
        retirement_review_required=(
            status is R6MonitoringActivationStatus.RETIREMENT_REVIEW_REQUIRED
        ),
    )


def _service(
    *,
    scope: R6ActivationScope | None = None,
    qualification: ActiveR6QualificationEvidence | None = None,
    monitoring: R6MonitoringActivationEvidence | None = None,
) -> tuple[
    EvaluateR6ManualActivationPreflight,
    _ScopeProvider,
    _QualificationProvider,
    _MonitoringProvider,
    _ActivationStateProvider,
]:
    actual_scope = _scope() if scope is None else scope
    actual_qualification = _qualification() if qualification is None else qualification
    actual_monitoring = _monitoring(actual_qualification) if monitoring is None else monitoring
    scope_provider = _ScopeProvider(actual_scope)
    qualification_provider = _QualificationProvider(actual_qualification)
    monitoring_provider = _MonitoringProvider(actual_monitoring)
    activation_provider = _ActivationStateProvider()
    return (
        EvaluateR6ManualActivationPreflight(
            scope_provider=scope_provider,
            qualification_provider=qualification_provider,
            monitoring_provider=monitoring_provider,
            activation_state_provider=activation_provider,
            unit_of_work=_Uow(),
        ),
        scope_provider,
        qualification_provider,
        monitoring_provider,
        activation_provider,
    )


def test_preflight_server_selects_and_double_reads_only_owner_evidence() -> None:
    service, scope_source, qualification_source, monitoring_source, activation_source = _service()

    result = service.execute(
        EvaluateR6ManualActivationPreflightCommand(
            scope_id="r6-state-model-advisory",
            as_of=NOW,
        )
    )

    assert result.status is R6ManualActivationPreflightStatus.ELIGIBLE_FOR_MANUAL_ACTIVATION_REVIEW
    assert result.blocker_codes == ()
    assert result.research_only is True
    assert result.must_not_publish_current is True
    assert result.must_not_use_for_decision is True
    assert result.must_not_replace_regime is True
    assert result.must_not_execute is True
    assert scope_source.calls == [
        ("r6-state-model-advisory", NOW),
        ("r6-state-model-advisory", NOW),
    ]
    assert qualification_source.calls == 2
    assert monitoring_source.calls == 2
    assert activation_source.calls == 2


def test_preflight_blocks_when_canonical_scope_owner_is_unavailable() -> None:
    service, scope_source, qualification_source, monitoring_source, activation_source = _service(
        scope=None
    )
    scope_source.scope = None

    result = service.execute(
        EvaluateR6ManualActivationPreflightCommand(
            scope_id="r6-state-model-advisory",
            as_of=NOW,
        )
    )

    assert result.status is R6ManualActivationPreflightStatus.BLOCKED
    assert result.blocker_codes == (R6ManualActivationBlockerCode.SCOPE_OWNER_UNAVAILABLE,)
    assert qualification_source.calls == 0
    assert monitoring_source.calls == 0
    assert activation_source.calls == 0


@pytest.mark.parametrize(
    ("monitoring_status", "expected_blocker"),
    (
        (
            R6MonitoringActivationStatus.BREACHED,
            R6ManualActivationBlockerCode.LATEST_MONITORING_BREACHED,
        ),
        (
            R6MonitoringActivationStatus.RETIREMENT_REVIEW_REQUIRED,
            R6ManualActivationBlockerCode.LATEST_MONITORING_REQUIRES_RETIREMENT_REVIEW,
        ),
        (
            R6MonitoringActivationStatus.BLOCKED,
            R6ManualActivationBlockerCode.LATEST_MONITORING_BLOCKED,
        ),
    ),
)
def test_preflight_never_interprets_nonhealthy_monitoring_as_eligible(
    monitoring_status: R6MonitoringActivationStatus,
    expected_blocker: R6ManualActivationBlockerCode,
) -> None:
    qualification = _qualification()
    service, _, _, _, _ = _service(
        qualification=qualification,
        monitoring=_monitoring(qualification, status=monitoring_status),
    )

    result = service.execute(
        EvaluateR6ManualActivationPreflightCommand(
            scope_id="r6-state-model-advisory",
            as_of=NOW,
        )
    )

    assert result.status is R6ManualActivationPreflightStatus.BLOCKED
    assert result.blocker_codes == (expected_blocker,)


def test_preflight_blocks_when_owner_graph_changes_between_reads() -> None:
    qualification = _qualification()

    class _DriftingMonitoring(_MonitoringProvider):
        def get_latest_complete(self, **kwargs):
            value = super().get_latest_complete(**kwargs)
            if self.calls == 1:
                self.value = _monitoring(
                    qualification,
                    status=R6MonitoringActivationStatus.BREACHED,
                )
            return value

    scope_provider = _ScopeProvider(_scope())
    qualification_provider = _QualificationProvider(qualification)
    monitoring_provider = _DriftingMonitoring(_monitoring(qualification))
    service = EvaluateR6ManualActivationPreflight(
        scope_provider=scope_provider,
        qualification_provider=qualification_provider,
        monitoring_provider=monitoring_provider,
        activation_state_provider=_ActivationStateProvider(),
        unit_of_work=_Uow(),
    )

    result = service.execute(
        EvaluateR6ManualActivationPreflightCommand(
            scope_id="r6-state-model-advisory",
            as_of=NOW,
        )
    )

    assert result.blocker_codes == (
        R6ManualActivationBlockerCode.OWNER_GRAPH_CHANGED_DURING_PREFLIGHT,
    )


def test_preflight_blocks_tampered_owner_seal_and_existing_activation() -> None:
    service, _, _, monitoring_provider, activation_provider = _service()
    assert monitoring_provider.value is not None
    object.__setattr__(monitoring_provider.value, "content_hash", HASH_C)

    tampered = service.execute(
        EvaluateR6ManualActivationPreflightCommand(
            scope_id="r6-state-model-advisory",
            as_of=NOW,
        )
    )

    assert tampered.blocker_codes == (R6ManualActivationBlockerCode.OWNER_PROVIDER_UNAVAILABLE,)

    service, _, _, _, activation_provider = _service()
    activation_provider.value = R6ActivationApprovalRef("approval-1", "v1", HASH_A)
    already_active = service.execute(
        EvaluateR6ManualActivationPreflightCommand(
            scope_id="r6-state-model-advisory",
            as_of=NOW,
        )
    )
    assert already_active.blocker_codes == (
        R6ManualActivationBlockerCode.ACTIVATION_ALREADY_PRESENT,
    )
    assert already_active.active_approval_hash == HASH_A


def test_preflight_rejects_future_or_malformed_commands_and_split_uow() -> None:
    service, scope_provider, qualification_provider, monitoring_provider, activation_provider = (
        _service()
    )
    with pytest.raises(R6ManualActivationUnavailable, match="future"):
        service.execute(
            EvaluateR6ManualActivationPreflightCommand(
                scope_id="r6-state-model-advisory",
                as_of=NOW + timedelta(microseconds=1),
            )
        )

    malformed = EvaluateR6ManualActivationPreflightCommand(
        scope_id="r6-state-model-advisory",
        as_of=NOW,
    )
    object.__setattr__(malformed, "as_of", datetime(2026, 8, 11, 4, 0))
    with pytest.raises(R6ManualActivationUnavailable, match="malformed"):
        service.execute(malformed)

    scope_provider.unit_of_work_key = "django:other"
    with pytest.raises(R6ManualActivationUnavailable, match="different unit"):
        EvaluateR6ManualActivationPreflight(
            scope_provider=scope_provider,
            qualification_provider=qualification_provider,
            monitoring_provider=monitoring_provider,
            activation_state_provider=activation_provider,
            unit_of_work=_Uow(),
        )
