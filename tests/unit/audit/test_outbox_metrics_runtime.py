"""Runtime composition tests for the read-only audit outbox metrics projection."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from django.http import HttpRequest

from apps.audit.application import repository_provider
from apps.audit.application.system_audit_outbox_observability import (
    SystemAuditOutboxBacklogSnapshot,
)

NOW = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)


def _snapshot() -> SystemAuditOutboxBacklogSnapshot:
    """Build one deterministic, valid backlog observation."""

    return SystemAuditOutboxBacklogSnapshot(
        as_of=NOW,
        pending_count=2,
        due_pending_count=1,
        claimed_count=1,
        expired_claimed_count=1,
        failed_count=3,
        delivered_count=4,
        oldest_backlog_at=NOW - timedelta(seconds=30),
        oldest_claimed_at=NOW - timedelta(seconds=10),
    )


def test_provider_projects_default_alias_snapshot_at_aware_clock(
    monkeypatch,
) -> None:
    """The provider fixes the alias/cutoff and forwards the exact snapshot."""

    snapshot = _snapshot()
    observed: list[datetime] = []

    class Reader:
        def get_backlog_snapshot(self, *, as_of: datetime) -> SystemAuditOutboxBacklogSnapshot:
            observed.append(as_of)
            return snapshot

    reader_kwargs: list[dict[str, str]] = []

    def get_reader(**kwargs: str) -> Reader:
        reader_kwargs.append(kwargs)
        return Reader()

    projected: list[SystemAuditOutboxBacklogSnapshot] = []
    monkeypatch.setattr(repository_provider.timezone, "now", lambda: NOW)
    monkeypatch.setattr(repository_provider, "get_audit_outbox_repository", get_reader)

    def record(snapshot_value: SystemAuditOutboxBacklogSnapshot) -> None:
        projected.append(snapshot_value)

    monkeypatch.setattr(
        "apps.audit.infrastructure.metrics.record_system_audit_outbox_backlog",
        record,
    )

    assert repository_provider.project_audit_outbox_backlog_metrics() is True
    assert reader_kwargs == [{"using": "default"}]
    assert observed == [NOW]
    assert observed[0].tzinfo is not None
    assert projected == [snapshot]


def test_provider_reader_failure_is_fail_safe_and_redacted(
    monkeypatch,
    caplog,
) -> None:
    """Reader/codec failures return false without leaking connection details."""

    class BrokenReader:
        def get_backlog_snapshot(self, *, as_of: datetime) -> SystemAuditOutboxBacklogSnapshot:
            del as_of
            raise RuntimeError("postgres://user:secret@db.internal/audit")

    monkeypatch.setattr(
        repository_provider,
        "get_audit_outbox_repository",
        lambda **kwargs: BrokenReader(),
    )
    with caplog.at_level(logging.WARNING, logger="apps.audit.application.repository_provider"):
        assert repository_provider.project_audit_outbox_backlog_metrics() is False

    assert "RuntimeError" in caplog.text
    assert "secret" not in caplog.text
    assert "db.internal" not in caplog.text


def test_metrics_view_projects_once_and_keeps_generic_response(
    monkeypatch,
) -> None:
    """The shared endpoint lazily calls the facade and still serves metrics."""

    from core import urls

    calls: list[None] = []

    def project() -> bool:
        calls.append(None)
        return True

    monkeypatch.setattr(repository_provider, "project_audit_outbox_backlog_metrics", project)
    monkeypatch.setattr(urls, "generate_latest", lambda: b"# HELP generic_metric\n")

    response = urls.metrics_view(HttpRequest())

    assert response.status_code == 200
    assert response.content == b"# HELP generic_metric\n"
    assert calls == [None]


def test_metrics_view_projection_exception_does_not_break_scrape(
    monkeypatch,
    caplog,
) -> None:
    """A lazy projection exception is reduced to a type-only warning."""

    from core import urls

    def fail() -> bool:
        raise RuntimeError("postgres://user:secret@db.internal/audit")

    monkeypatch.setattr(repository_provider, "project_audit_outbox_backlog_metrics", fail)
    monkeypatch.setattr(urls, "generate_latest", lambda: b"# TYPE generic_metric gauge\n")

    with caplog.at_level(logging.WARNING, logger="core.urls"):
        response = urls.metrics_view(HttpRequest())

    assert response.status_code == 200
    assert response.content == b"# TYPE generic_metric gauge\n"
    assert "RuntimeError" in caplog.text
    assert "secret" not in caplog.text
    assert "db.internal" not in caplog.text
