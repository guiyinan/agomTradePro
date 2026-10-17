"""Regression coverage for empty and default simulated auto-trading scopes."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _isolate_dispatcher(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server: object,
) -> None:
    """Use the governed core dispatcher with deterministic authorization and audit."""
    import agomtradepro_mcp.server as server_module

    monkeypatch.setattr(server_module.CORE_DISPATCHER, "_role_provider", lambda: "staff")
    monkeypatch.setattr(
        server_module.CORE_DISPATCHER,
        "_audit_logger",
        SimpleNamespace(log_governed_capability_event=lambda **_kwargs: "test-audit-log"),
    )


@pytest.mark.parametrize(
    ("account_ids", "expected_read", "expected_resolved"),
    [
        pytest.param(None, "list", 2, id="default-scope"),
        pytest.param([], None, 0, id="explicit-empty-scope"),
        pytest.param([7], "get", 1, id="single-account-scope"),
        pytest.param([8, 7], "get", 2, id="ordered-account-scope"),
    ],
)
@pytest.mark.parametrize("outcome", ["partial", "failed"])
def test_simulated_auto_trading_preserves_none_empty_and_explicit_scopes(
    monkeypatch: pytest.MonkeyPatch,
    account_ids: list[int] | None,
    expected_read: str | None,
    expected_resolved: int,
    outcome: str,
) -> None:
    """Preview and confirmation preserve the caller's scope through the SDK fallback."""
    import agomtradepro
    import agomtradepro_mcp.server as server_module
    from agomtradepro import AgomTradeProClient
    from agomtradepro.config import AuthConfig, ClientConfig
    from agomtradepro.transport import use_request_transport

    fallback_result: dict[str, Any] = {
        "success": outcome == "partial",
        "outcome": outcome,
        "stored": None,
        "counts_unavailable": True,
        "future_result_field": {"preserved": True},
    }

    class _FakeResponse:
        def __init__(self, payload: dict[str, Any]) -> None:
            self.status_code = 200
            self._payload = payload

        def json(self) -> dict[str, Any]:
            return self._payload

    class _FakeTransport:
        def __init__(self) -> None:
            self.requests: list[dict[str, Any]] = []

        def request(
            self,
            *,
            method: str,
            url: str,
            headers: dict[str, str],
            params: dict[str, Any] | None,
            data: dict[str, Any] | None,
            json: dict[str, Any] | None,
            files: dict[str, Any] | None,
            timeout: int,
        ) -> _FakeResponse:
            del headers, data, files, timeout
            path = url.removeprefix("https://mcp.test")
            request: dict[str, Any] = {
                "method": method,
                "path": path,
                "params": params,
                "json": json,
            }
            self.requests.append(request)

            if method == "GET" and path == "/api/simulated-trading/accounts/":
                return _FakeResponse(
                    {
                        "accounts": [
                            {
                                "id": 7,
                                "name": "Sim 7",
                                "status": "active",
                                "account_type": "simulated",
                            },
                            {
                                "id": 8,
                                "name": "Sim 8",
                                "status": "active",
                                "account_type": "simulated",
                            },
                        ]
                    }
                )
            if method == "GET" and path.startswith("/api/simulated-trading/accounts/"):
                account_id = int(path.rstrip("/").rsplit("/", 1)[-1])
                return _FakeResponse(
                    {
                        "account": {
                            "id": account_id,
                            "name": f"Sim {account_id}",
                            "status": "active",
                            "account_type": "simulated",
                        }
                    }
                )
            if method == "POST" and path == "/api/simulated-trading/auto-trading/run/":
                return _FakeResponse(fallback_result)
            raise AssertionError(f"Unexpected SDK request: {method} {path}")

    transport = _FakeTransport()
    config = ClientConfig(
        base_url="https://mcp.test",
        auth=AuthConfig(api_token="synthetic-test-token"),
        max_retries=0,
    )
    monkeypatch.setattr(
        agomtradepro,
        "AgomTradeProClient",
        lambda: AgomTradeProClient(config=config),
    )

    audit_events: list[dict[str, Any]] = []
    monkeypatch.setattr(
        server_module.CORE_DISPATCHER,
        "_audit_logger",
        SimpleNamespace(
            log_governed_capability_event=lambda **kwargs: audit_events.append(dict(kwargs))
            or "test-audit-log"
        ),
    )

    arguments: dict[str, Any] = {
        "trade_date": "2026-10-17",
        "idempotency_key": (
            f"sim-auto-scope-{expected_read or 'empty'}-{expected_resolved}-{outcome}"
        ),
    }
    if account_ids is not None:
        arguments["account_ids"] = account_ids

    with use_request_transport(transport):
        preview = server_module.CORE_DISPATCHER.call(
            capability_key="trading.start.simulated_auto_trading",
            arguments=arguments,
        )

        assert preview["status"] == "confirmation_required"
        preview_result = preview["preview_result"]
        assert preview_result["account_ids"] == account_ids
        assert preview_result["account_scope_summary"]["requested_account_count"] == len(
            account_ids or []
        )
        assert (
            preview_result["account_scope_summary"]["resolved_account_count"] == expected_resolved
        )
        if expected_read is None:
            assert transport.requests == []
        elif expected_read == "list":
            assert [request["method"] for request in transport.requests] == ["GET"]
            assert transport.requests[0]["path"] == "/api/simulated-trading/accounts/"
        else:
            assert [request["path"] for request in transport.requests] == [
                f"/api/simulated-trading/accounts/{account_id}/" for account_id in account_ids or []
            ]

        result = server_module.CORE_DISPATCHER.resume_confirmation(
            confirmation_token=preview["confirmation_token"],
            approve=True,
        )

    assert result["status"] == "completed"
    assert result["result"] == fallback_result
    assert result["result"]["outcome"] == outcome
    assert result["result"]["stored"] is None
    assert result["result"]["counts_unavailable"] is True
    assert result["result"]["future_result_field"] == {"preserved": True}
    expected_json: dict[str, Any] = {"trade_date": "2026-10-17"}
    if account_ids is not None:
        expected_json["account_ids"] = account_ids
    assert transport.requests[-1] == {
        "method": "POST",
        "path": "/api/simulated-trading/auto-trading/run/",
        "params": None,
        "json": expected_json,
    }
    assert audit_events[0]["event_type"] == "preview_staged"
    if account_ids is None:
        assert "account_count" not in audit_events[0]["affected_objects"]
    else:
        assert audit_events[0]["affected_objects"]["account_count"] == len(account_ids)
    assert audit_events[-1]["event_type"] == "confirmation_completed"
