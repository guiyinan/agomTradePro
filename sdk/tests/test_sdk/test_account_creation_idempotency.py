"""Account SDK aliases preserve caller-owned creation keys at the transport boundary."""

from unittest.mock import Mock, patch

import pytest

from agomtradepro import AgomTradeProClient
from agomtradepro.exceptions import ValidationError


@pytest.mark.parametrize("module_name", ["account", "simulated_trading"])
def test_account_creation_retries_keep_key_in_header_and_preserve_account_result(module_name):
    client = AgomTradeProClient(base_url="http://test.invalid", api_token="test-token")
    account = {"account_id": 9, "account_name": "owned"}
    responses = [
        Mock(
            status_code=201,
            json=Mock(return_value={"success": True, "account": account, "replayed": False}),
        ),
        Mock(
            status_code=200,
            json=Mock(return_value={"success": True, "account": account, "replayed": True}),
        ),
    ]
    with patch.object(client._session, "request", side_effect=responses) as transport:
        module = getattr(client, module_name)
        for _ in range(2):
            assert (
                module.create_account(
                    name="owned", initial_capital=100000.0, idempotency_key="one-submission"
                )
                == account
            )
    assert transport.call_count == 2
    for call in transport.call_args_list:
        assert call.kwargs["headers"]["Idempotency-Key"] == "one-submission"
        assert "idempotency_key" not in call.kwargs["json"]


@pytest.mark.parametrize("key", ["", "bad key", "a" * 193])
def test_invalid_key_is_rejected_before_network_access(key):
    client = AgomTradeProClient(base_url="http://test.invalid", api_token="test-token")
    with patch.object(client._session, "request") as transport:
        with pytest.raises(ValidationError):
            client.post("/api/account/accounts/", json={}, idempotency_key=key)
    transport.assert_not_called()
