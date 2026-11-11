"""Public account paths cannot bypass or poison protected credential continuations."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.terminal.application.tui_workbench_execution import TuiWorkbenchExecutionMixin


def _exchange(*, payload_account=1, requested_account=1, continuation_account="1", leaked=False):
    action = {
        "key": "simulated-trading.corporate-action-consent-withdraw-prepare",
        "result_continuation": {
            "target_action_key": "simulated-trading.corporate-action-consent-withdraw",
            "field_map": {"account_id": "account_id", "withdrawal_token": "withdrawal_token"},
        },
    }
    payload = {
        "account_id": payload_account,
        "outcome": "success",
        "grant_version": "1",
        "withdrawal_token": None,
        "continuation": {
            "action_key": "simulated-trading.corporate-action-consent-withdraw",
            "input": {"account_id": continuation_account, "withdrawal_token": "private-locator"},
            "expires_at": (timezone.now() + timedelta(minutes=1)).isoformat(),
        },
    }
    if leaked:
        payload["debug"] = {"nested": ["private-locator"]}
    return TuiWorkbenchExecutionMixin()._validate_owner_result_continuation(
        action=action,
        payload=payload,
        status_code=200,
        requested_params={"account_id": requested_account},
    )


def test_account_one_does_not_treat_public_grant_version_one_as_a_secret_leak():
    safe, continuation, error = _exchange()
    assert error is None and continuation is not None
    assert safe["account_id"] == 1 and safe["grant_version"] == "1"
    assert "continuation" not in safe
    assert continuation["input"] == {"account_id": "1", "withdrawal_token": "private-locator"}


@pytest.mark.parametrize(
    "changes",
    [
        {"payload_account": 2},
        {"requested_account": 2},
        {"continuation_account": "2"},
        {"payload_account": True},
        {"requested_account": True},
        {"requested_account": "01"},
    ],
)
def test_three_way_account_mismatch_never_stores_a_continuation(changes):
    _, continuation, error = _exchange(**changes)
    assert continuation is None and error == "tui_result_continuation_invalid"


def test_real_credential_remains_protected_in_nested_display_data():
    _, continuation, error = _exchange(leaked=True)
    assert continuation is None and error == "tui_result_continuation_leaked"
