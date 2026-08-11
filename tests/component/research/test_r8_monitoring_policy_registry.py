"""Component proof for the independent Research R8 monitoring policy owner."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import connection, transaction

from apps.portfolio.application.governed_optimization_monitoring import (
    EvaluateGovernedOptimizationMonitoringCommand,
)
from apps.portfolio.application.governed_optimization_monitoring_persistence import (
    GovernedOptimizationMonitoringPersistenceUnavailable,
)
from apps.portfolio.domain.governed_optimization_monitoring import (
    MonitoringAssessmentStatus,
    MonitoringBlockerCode,
)
from apps.research.application.r8_monitoring_policy_registry import (
    R8MonitoringPolicyRegistryUnavailable,
)
from apps.research.domain.r8_monitoring_policy_registry import (
    R8MonitoringPolicySourceReceipt,
)
from apps.research.infrastructure.r8_monitoring_policy_models import (
    R8MonitoringPolicyRegistryModel,
)
from apps.research.infrastructure.r8_monitoring_policy_repository import (
    R8MonitoringPolicyRepositoryConflict,
    R8MonitoringPolicyRepositoryCorruption,
)
from apps.research.r8_governed_optimization_monitoring_composition import (
    _build_django_r8_phase_a_b_runtime,
)
from apps.research.r8_monitoring_policy_composition import (
    _build_django_r8_monitoring_policy_registration_runtime,
    build_django_r8_monitoring_policy_registry_runtime,
)
from tests.unit.portfolio.test_governed_optimization_monitoring import NOW
from tests.unit.research.test_r8_monitoring_policy_registry import (
    _Clock,
    _command,
    _definition,
    _Provider,
    _source,
)


def _runtime(*, source: object | None = None):  # type: ignore[no-untyped-def]
    return _build_django_r8_monitoring_policy_registration_runtime(
        definition_provider=_Provider(_definition()),
        source_provider=_Provider(_source() if source is None else source),
        clock=_Clock(),
    )


@pytest.mark.django_db(transaction=True)
def test_policy_registry_round_trip_winner_pit_and_guards() -> None:
    """Private registration appends once; public exact PIT reads remain immutable."""

    runtime = _runtime()
    policy = runtime.register.execute(_command())
    assert runtime.register.execute(_command()) == policy
    assert R8MonitoringPolicyRegistryModel._default_manager.count() == 1
    cutoff = NOW + timedelta(hours=4)
    assert (
        runtime.policy_provider.get_exact(
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            expected_policy_hash=policy.content_hash,
            as_of=cutoff,
        )
        == policy
    )
    assert (
        runtime.policy_provider.get_exact(
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            expected_policy_hash=policy.content_hash,
            as_of=cutoff - timedelta(microseconds=1),
        )
        is None
    )
    with pytest.raises(R8MonitoringPolicyRepositoryCorruption, match="substituted"):
        runtime.policy_provider.get_exact(
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            expected_policy_hash="0" * 64,
            as_of=cutoff,
        )

    row = R8MonitoringPolicyRegistryModel._default_manager.get()
    with pytest.raises(ValidationError):
        row.save()
    with pytest.raises(ValidationError):
        row.delete()
    with pytest.raises(ValidationError):
        R8MonitoringPolicyRegistryModel._default_manager.update(policy_id="forbidden")
    with pytest.raises(ValidationError):
        R8MonitoringPolicyRegistryModel._default_manager.all().delete()
    with pytest.raises(ValidationError):
        R8MonitoringPolicyRegistryModel(policy_id="forbidden").save(force_insert=True)


@pytest.mark.django_db(transaction=True)
def test_policy_registry_missing_fork_and_outer_rollback_are_zero_write() -> None:
    """Missing sources, forks, and outer rollback never create a second winner."""

    missing = _runtime(source=False)
    with pytest.raises(R8MonitoringPolicyRegistryUnavailable):
        missing.register.execute(_command())
    assert R8MonitoringPolicyRegistryModel._default_manager.count() == 0

    with pytest.raises(RuntimeError, match="outer rollback"):
        with transaction.atomic():
            _runtime().register.execute(_command())
            raise RuntimeError("outer rollback")
    assert R8MonitoringPolicyRegistryModel._default_manager.count() == 0

    _runtime().register.execute(_command())
    source = _source()
    fork = R8MonitoringPolicySourceReceipt.create(
        source_receipt_id=source.source_receipt_id,
        source_receipt_version=source.source_receipt_version,
        policy_id=source.policy_id,
        policy_version=source.policy_version,
        definition_hash=source.definition_hash,
        available_at=source.available_at,
        valid_until=source.valid_until,
        evidence_ref="research:r8-monitoring-policy:fork",
    )
    with pytest.raises(R8MonitoringPolicyRegistryUnavailable) as raised:
        _runtime(source=fork).register.execute(_command())
    assert isinstance(raised.value.__cause__, R8MonitoringPolicyRepositoryConflict)
    assert R8MonitoringPolicyRegistryModel._default_manager.count() == 1


@pytest.mark.django_db(transaction=True)
def test_policy_registry_detects_tamper_and_public_registration_is_inert() -> None:
    """Header substitution fails closed and public composition cannot append."""

    policy = _runtime().register.execute(_command())
    table = connection.ops.quote_name(R8MonitoringPolicyRegistryModel._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {table} SET calendar_id = %s WHERE policy_hash = %s",
            ["tampered", policy.content_hash],
        )
    public = build_django_r8_monitoring_policy_registry_runtime()
    with pytest.raises(R8MonitoringPolicyRepositoryCorruption):
        public.policy_provider.get_exact(
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            expected_policy_hash=policy.content_hash,
            as_of=NOW + timedelta(hours=4),
        )
    with pytest.raises(R8MonitoringPolicyRegistryUnavailable):
        public.register.execute(_command())
    assert R8MonitoringPolicyRegistryModel._default_manager.count() == 1


@pytest.mark.django_db(transaction=True)
def test_private_phase_a_b_empty_state_is_blocked_and_zero_write() -> None:
    """Absent owner rows return stable BLOCKED while Phase B retains no writer."""

    runtime = _build_django_r8_phase_a_b_runtime()
    command = EvaluateGovernedOptimizationMonitoringCommand(
        policy_id="r8-monitoring-policy:missing:v1",
        policy_version="governed-optimization-monitoring-policy.v1",
        expected_policy_hash="0" * 64,
        as_of=NOW,
    )
    assessment = runtime.evaluate.execute(command)
    assert assessment.status is MonitoringAssessmentStatus.BLOCKED
    assert assessment.blocker_codes == (MonitoringBlockerCode.POLICY_UNAVAILABLE,)
    with pytest.raises(GovernedOptimizationMonitoringPersistenceUnavailable):
        runtime.register.execute(command)
    assert R8MonitoringPolicyRegistryModel._default_manager.count() == 0
