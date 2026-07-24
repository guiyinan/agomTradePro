"""Signal scheduled-task and notification delivery contracts."""

from __future__ import annotations

from types import SimpleNamespace

from apps.signal.application import tasks


def test_signal_tasks_check_cleanup_and_daily_summary(monkeypatch) -> None:
    """Scheduled tasks preserve invalidation evidence and repository counts."""
    from apps.signal.application import invalidation_checker

    monkeypatch.setattr(
        invalidation_checker,
        "check_and_invalidate_signals",
        lambda: {
            "checked": 3,
            "invalidated": 1,
            "rejected": 1,
            "invalidated_ids": [1],
            "rejected_ids": [2],
        },
    )
    checked = tasks.check_all_signal_invalidations.run()
    assert checked["checked"] == 3

    check_result = SimpleNamespace(is_invalidated=True, reason="threshold breached")
    monkeypatch.setattr(
        invalidation_checker,
        "InvalidationCheckService",
        lambda **kwargs: SimpleNamespace(check_signal=lambda signal_id: check_result),
    )
    repo = SimpleNamespace(
        get_old_invalidated_signals=lambda days: [7, 8],
        count_by_status=lambda status: 4,
        get_signals_created_between=lambda start, end: [{"asset_code": "000001.SZ"}],
        get_signals_invalidated_between=lambda start, end: [
            {"id": 2, "asset_code": "000002.SZ", "invalidation_details": {"reason": "PMI"}}
        ],
    )
    monkeypatch.setattr(tasks, "get_signal_repository", lambda: repo)
    single = tasks.check_single_signal_invalidation.run(7)
    assert single["is_invalidated"] is True
    assert tasks.cleanup_old_invalidated_signals.run(30)["signal_ids"] == [7, 8]

    sent: list[dict[str, object]] = []
    monkeypatch.setattr(
        tasks,
        "_send_signal_summary_notification",
        lambda summary, new, invalidated: sent.append(summary) or True,
    )
    summary = tasks.send_daily_signal_summary.run()
    assert summary["new_signals"] == 1
    assert summary["invalidated_signals"] == 1
    assert sent == [summary]


def test_signal_notification_formats_details_and_handles_delivery_outcomes(monkeypatch) -> None:
    """Email delivery includes bounded detail rows and reports provider outcomes."""
    captured: dict[str, object] = {}
    service = SimpleNamespace(
        send_email=lambda **kwargs: (captured.update(kwargs) or [SimpleNamespace(success=True)])
    )
    monkeypatch.setattr(
        "shared.infrastructure.notification_service.get_notification_service",
        lambda: service,
    )
    monkeypatch.setattr(tasks, "_get_signal_notification_recipients", lambda: ["ops@example.test"])
    summary = {
        "date": "2026-07-24",
        "new_signals": 1,
        "invalidated_signals": 1,
        "total_approved": 3,
    }
    new = [{"asset_code": "000001.SZ", "logic_desc": "recovery"}]
    invalidated = [
        {
            "id": 2,
            "asset_code": "000002.SZ",
            "invalidation_details": {"reason": "PMI below threshold"},
        }
    ]
    assert tasks._send_signal_summary_notification(summary, new, invalidated) is True
    assert "000001.SZ" in str(captured["body"])
    assert "PMI below threshold" in str(captured["html_body"])

    monkeypatch.setattr(tasks, "_get_signal_notification_recipients", lambda: [])
    assert tasks._send_signal_summary_notification(summary, [], []) is True


def test_signal_notification_recipient_merge_and_deduplication(monkeypatch, settings) -> None:
    """Configured and staff recipients are merged, validated, and deduplicated."""
    settings.SIGNAL_NOTIFICATION_EMAILS = ["ops@example.test", "", "invalid"]
    monkeypatch.setattr(
        tasks,
        "get_user_repository",
        lambda: SimpleNamespace(
            get_staff_emails=lambda: ["ops@example.test", "admin@example.test"]
        ),
    )
    assert set(tasks._get_signal_notification_recipients()) == {
        "ops@example.test",
        "admin@example.test",
    }
