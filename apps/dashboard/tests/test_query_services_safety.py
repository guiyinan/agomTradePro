"""Input-boundary tests for Dashboard TUI/runtime query services."""

from types import SimpleNamespace

import pytest

from apps.dashboard.application.query_services import (
    build_auto_advisor_notifications_payload,
    build_auto_advisor_weekly_report_history_payload,
)


@pytest.mark.parametrize("account_id", ["abc", "1.5", "0", "-1", "2147483648"])
@pytest.mark.parametrize(
    "builder",
    [
        build_auto_advisor_weekly_report_history_payload,
        build_auto_advisor_notifications_payload,
    ],
)
def test_auto_advisor_history_inputs_reject_invalid_account_before_repository(
    monkeypatch,
    builder,
    account_id: str,
) -> None:
    """Malformed account scopes must not reach shared Dashboard repositories."""

    def fail_repository() -> object:
        raise AssertionError("repository must not be resolved for invalid input")

    monkeypatch.setattr(
        "apps.dashboard.application.query_services.get_auto_advisor_report_repository",
        fail_repository,
    )

    with pytest.raises(ValueError, match="positive integer"):
        builder(
            user=SimpleNamespace(id=7, is_authenticated=True),
            account_id=account_id,
        )


def test_auto_advisor_history_normalizes_blank_account_to_unscoped(monkeypatch) -> None:
    """Whitespace-only optional account scope is equivalent to no account filter."""

    captured: dict[str, object] = {}

    class Repository:
        def list_recent_reports(self, **kwargs):
            captured.update(kwargs)
            return []

    monkeypatch.setattr(
        "apps.dashboard.application.query_services.get_auto_advisor_report_repository",
        lambda: Repository(),
    )

    payload = build_auto_advisor_weekly_report_history_payload(
        user=SimpleNamespace(id=7, is_authenticated=True),
        account_id="   ",
    )

    assert payload["count"] == 0
    assert captured["account_id"] is None
