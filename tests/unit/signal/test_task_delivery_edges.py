"""Signal scheduled-task and notification delivery contracts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.signal.application import tasks
from core.exceptions import BusinessLogicError, DataFetchError


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
    new = [
        {
            "asset_code": "000001.SZ",
            "logic_desc": "<script>alert('x')</script>",
        }
    ]
    invalidated = [
        {
            "id": 2,
            "asset_code": "000002.SZ",
            "invalidation_details": {"reason": "<b>PMI below threshold</b>"},
        }
    ]
    assert tasks._send_signal_summary_notification(summary, new, invalidated) is True
    assert "000001.SZ" in str(captured["body"])
    assert "PMI below threshold" in str(captured["html_body"])
    assert "<script>" not in str(captured["html_body"])
    assert "&lt;script&gt;" in str(captured["html_body"])
    assert "<b>PMI" not in str(captured["html_body"])

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


@pytest.mark.parametrize(
    "result",
    [
        None,
        {},
        {
            "checked": 1,
            "invalidated": 1,
            "rejected": 0,
            "invalidated_ids": [],
            "rejected_ids": [],
        },
        {
            "checked": 0,
            "invalidated": 1,
            "rejected": 0,
            "invalidated_ids": [1],
            "rejected_ids": [],
        },
    ],
)
def test_invalidation_batch_result_rejects_false_success(
    result: object,
) -> None:
    with pytest.raises(BusinessLogicError):
        tasks._validated_batch_result(result)


@pytest.mark.parametrize("signal_id", [0, -1, True])
def test_single_invalidation_rejects_invalid_signal_id(
    signal_id: int,
) -> None:
    with pytest.raises(BusinessLogicError, match="signal_id"):
        tasks.check_single_signal_invalidation.run(signal_id)


@pytest.mark.parametrize("days", [0, -1, 3651, True])
def test_cleanup_rejects_unbounded_days(days: int) -> None:
    with pytest.raises(BusinessLogicError, match="days"):
        tasks.cleanup_old_invalidated_signals.run(days)


def test_daily_summary_fails_when_notification_is_not_delivered(
    monkeypatch,
) -> None:
    repository = SimpleNamespace(
        count_by_status=lambda _status: 4,
        get_signals_created_between=lambda _start, _end: [],
        get_signals_invalidated_between=lambda _start, _end: [],
    )
    monkeypatch.setattr(tasks, "get_signal_repository", lambda: repository)
    monkeypatch.setattr(
        tasks,
        "_send_signal_summary_notification",
        lambda _summary, _new, _invalidated: False,
    )

    with pytest.raises(DataFetchError, match="delivery failed"):
        tasks.send_daily_signal_summary.run()


def test_recipient_string_is_treated_as_one_address(
    monkeypatch,
    settings,
) -> None:
    settings.SIGNAL_NOTIFICATION_EMAILS = "OPS@EXAMPLE.TEST"
    monkeypatch.setattr(
        tasks,
        "get_user_repository",
        lambda: SimpleNamespace(get_staff_emails=lambda: []),
    )

    assert tasks._get_signal_notification_recipients() == ["ops@example.test"]
