"""Contract tests for the scheduled System Audit authority renewal guard."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from apps.audit.application.system_audit_authority_renewal_guard import (
    SystemAuditAuthorityLease,
    SystemAuditAuthorityRenewalGuardDependencies,
    run_system_audit_authority_renewal_guard,
)

NOW = datetime(2026, 9, 24, 8, 0, tzinfo=UTC)


def test_guard_reports_healthy_authority_without_writing() -> None:
    """A healthy lease is a noop and cannot invoke the renewal writer."""

    calls: list[str] = []
    dependencies = SystemAuditAuthorityRenewalGuardDependencies(
        read_lease=lambda: SystemAuditAuthorityLease(
            mode="required",
            outbox_enabled=True,
            valid_until=NOW + timedelta(days=1),
        ),
        execute_renewal=lambda: calls.append("renew") or {"outcome": "success"},
        publish_alert=lambda *_args: calls.append("alert"),
        clock=lambda: NOW,
    )

    result = run_system_audit_authority_renewal_guard(dependencies)

    assert result["outcome"] == "noop"
    assert result["block_reason_code"] == "authority_window_healthy"
    assert calls == []


def test_guard_blocks_and_alerts_when_runtime_is_disabled() -> None:
    """An explicitly disabled runtime remains operator-controlled."""

    alerts: list[tuple[str, str, dict[str, object]]] = []
    dependencies = SystemAuditAuthorityRenewalGuardDependencies(
        read_lease=lambda: SystemAuditAuthorityLease(
            mode="off",
            outbox_enabled=False,
            valid_until=None,
            reason_code="audit_runtime_disabled",
        ),
        execute_renewal=lambda: {"outcome": "success"},
        publish_alert=lambda level, title, metadata: alerts.append((level, title, metadata)),
        clock=lambda: NOW,
    )

    result = run_system_audit_authority_renewal_guard(dependencies)

    assert result["outcome"] == "blocked"
    assert result["block_reason_code"] == "audit_runtime_disabled"
    assert len(alerts) == 1
    assert alerts[0][0] == "critical"
    assert alerts[0][2]["reason_code"] == "audit_runtime_disabled"


def test_guard_blocks_invalid_renewal_result() -> None:
    """A renewal writer cannot turn an unrecognised payload into success."""

    alerts: list[dict[str, object]] = []
    dependencies = SystemAuditAuthorityRenewalGuardDependencies(
        read_lease=lambda: SystemAuditAuthorityLease(
            mode="required",
            outbox_enabled=True,
            valid_until=NOW + timedelta(minutes=30),
        ),
        execute_renewal=lambda: {"outcome": "unexpected"},
        publish_alert=lambda _level, _title, metadata: alerts.append(metadata),
        clock=lambda: NOW,
        renewal_window=timedelta(hours=1),
    )

    result = run_system_audit_authority_renewal_guard(dependencies)

    assert result["outcome"] == "blocked"
    assert result["block_reason_code"] == "authority_renewal_result_invalid"
    assert alerts[0]["reason_code"] == "authority_renewal_result_invalid"
