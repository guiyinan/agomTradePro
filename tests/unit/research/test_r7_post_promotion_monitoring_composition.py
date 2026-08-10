"""Production R7 monitoring composition stays inert without canonical owners."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.research.application.r7_post_promotion_monitoring import (
    EvaluateR7PostPromotionMonitoringCommand,
)
from apps.research.application.r7_post_promotion_monitoring_persistence import (
    AuditR7MonitoringAssessmentsCommand,
    R7MonitoringPersistenceUnavailable,
)
from apps.research.r7_post_promotion_monitoring_composition import (
    build_django_r7_monitoring_runtime,
)


def test_production_runtime_has_inert_write_and_audit_capabilities() -> None:
    runtime = build_django_r7_monitoring_runtime()
    command = EvaluateR7PostPromotionMonitoringCommand(
        policy_id="r7-monitoring-policy:missing",
        policy_version="r7-post-promotion-monitoring-policy.v1",
        expected_policy_hash="a" * 64,
        as_of=datetime(2026, 8, 10, tzinfo=UTC),
    )

    with pytest.raises(R7MonitoringPersistenceUnavailable, match="owner providers"):
        runtime.register.execute(command)
    with pytest.raises(R7MonitoringPersistenceUnavailable, match="audit persistence"):
        runtime.audit.execute(AuditR7MonitoringAssessmentsCommand(as_of=command.as_of))

    assert not hasattr(runtime, "repository")
    assert not hasattr(runtime.register, "_writer")
    assert not hasattr(runtime.register, "_repository")
    assert not hasattr(runtime.audit, "_repository")


def test_production_inert_facades_normalize_malformed_commands() -> None:
    runtime = build_django_r7_monitoring_runtime()

    with pytest.raises(R7MonitoringPersistenceUnavailable, match="malformed"):
        runtime.register.execute(object())
    with pytest.raises(R7MonitoringPersistenceUnavailable, match="malformed"):
        runtime.audit.execute(object())
