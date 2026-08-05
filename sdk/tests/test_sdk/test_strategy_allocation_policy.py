"""SDK contracts for Strategy allocation-policy queries."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agomtradepro import AgomTradeProClient


@pytest.fixture
def client() -> AgomTradeProClient:
    """Build an SDK client with deterministic transport configuration."""

    return AgomTradeProClient(base_url="http://test.com", api_token="test_token")


def test_sdk_reads_active_allocation_policy(client: AgomTradeProClient) -> None:
    """The SDK uses the canonical authenticated active-policy endpoint."""

    expected = {
        "policy_key": "strategic_asset_allocation",
        "version": 2,
        "status": "active",
    }
    with patch.object(client, "_request", return_value=expected) as request:
        result = client.strategy.get_active_allocation_policy()

    assert result == expected
    request.assert_called_once_with(
        "GET",
        "/api/strategy/allocation-policies/active/",
        params={"policy_key": "strategic_asset_allocation"},
    )


def test_sdk_lists_and_reads_specific_policy_versions(
    client: AgomTradeProClient,
) -> None:
    """Version list and detail calls preserve the explicit policy identity."""

    version_rows = [{"version": 2}, {"version": 1}]
    with patch.object(
        client,
        "_request",
        side_effect=[
            {"count": 2, "results": version_rows},
            {"version": 1, "status": "superseded"},
        ],
    ) as request:
        versions = client.strategy.list_allocation_policy_versions()
        detail = client.strategy.get_allocation_policy_version(1)

    assert versions == version_rows
    assert detail["status"] == "superseded"
    assert request.call_args_list[0].args == (
        "GET",
        "/api/strategy/allocation-policies/versions/",
    )
    assert request.call_args_list[1].args == (
        "GET",
        "/api/strategy/allocation-policies/versions/1/",
    )
    assert request.call_args_list[0].kwargs["params"] == {
        "policy_key": "strategic_asset_allocation"
    }


@pytest.mark.parametrize(
    ("method_name", "arguments"),
    [
        ("get_active_allocation_policy", {"policy_key": "../unsafe"}),
        ("list_allocation_policy_versions", {"policy_key": "UPPER_CASE"}),
        ("get_allocation_policy_version", {"version": 0}),
        ("get_allocation_policy_version", {"version": True}),
    ],
)
def test_sdk_rejects_invalid_policy_identity_before_transport(
    client: AgomTradeProClient,
    method_name: str,
    arguments: dict[str, object],
) -> None:
    """Invalid keys and versions never reach the HTTP transport."""

    method = getattr(client.strategy, method_name)
    with patch.object(client, "_request") as request:
        with pytest.raises(ValueError):
            method(**arguments)

    request.assert_not_called()
