"""Governed realtime management capability contracts."""

from types import SimpleNamespace

import pytest

from agomtradepro import ServerError
from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader

EXPECTED_REALTIME_MANAGEMENT_KEYS = {
    "realtime.read.alerts",
    "realtime.read.alert",
    "realtime.create.price_alert",
    "realtime.update.price_alert",
    "realtime.delete.price_alert",
    "realtime.read.price_subscriptions",
    "realtime.create.price_subscription",
    "realtime.delete.price_subscription",
}


def test_realtime_management_manifests_are_governed() -> None:
    registry = CapabilityRegistryLoader().build_registry()

    assert EXPECTED_REALTIME_MANAGEMENT_KEYS <= set(registry)
    for key in EXPECTED_REALTIME_MANAGEMENT_KEYS:
        manifest = registry[key]
        assert manifest.owner_app == "realtime"
        if ".read." in key:
            assert manifest.risk_level == "low"
            continue
        assert manifest.risk_level == "high"
        assert manifest.requires_confirmation is True
        assert manifest.idempotency == "required"
        assert manifest.confirmation_preview_arguments == {"preview_only": True}
        assert manifest.confirmation_commit_arguments == {"preview_only": False}
        assert "mcp:write" in manifest.audit_tags


def test_realtime_read_capabilities_use_sdk_backed_core_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read capabilities retain core-only and native-handler execution evidence."""

    import agomtradepro_mcp.server as server_module

    class _Realtime:
        @staticmethod
        def list_alerts(status=None, limit=100):
            return [{"id": 1, "status": status or "active", "limit": limit}]

        @staticmethod
        def get_alert(alert_id):
            return {"id": alert_id, "asset_code": "510300.SH"}

        @staticmethod
        def get_subscriptions():
            return [{"asset_code": "510300.SH"}]

    monkeypatch.setattr(
        "agomtradepro.AgomTradeProClient",
        lambda: SimpleNamespace(realtime=_Realtime()),
    )
    assert "list_price_alerts" in server_module.INTERNAL_LEGACY_TOOL_FALLBACKS
    assert "realtime_get_price_alert" in server_module.INTERNAL_GOVERNED_HANDLERS
    agom_capability_call = server_module.CORE_DISPATCHER.call

    alerts = agom_capability_call(
        capability_key="realtime.read.alerts",
        arguments={"status": "active", "limit": 10},
    )
    alert = agom_capability_call(
        capability_key="realtime.read.alert",
        arguments={"alert_id": 1},
    )
    subscriptions = agom_capability_call(
        capability_key="realtime.read.price_subscriptions",
        arguments={},
    )

    assert alerts["result"]["total_count"] == 1
    assert alert["result"]["id"] == 1
    assert subscriptions["result"]["total_count"] == 1


@pytest.mark.parametrize(
    (
        "state",
        "results",
        "count",
        "scope_available",
        "requested",
        "qualified",
        "unavailable",
        "rankable",
        "unrankable",
        "reason",
    ),
    [
        (
            "partial",
            [{"asset_code": "510300.SH", "current_price": 3.5, "change_pct": 1.2}],
            1,
            True,
            4,
            1,
            3,
            1,
            0,
            "monitored_cached_prices_incomplete",
        ),
        ("blocked", [], 0, True, 0, 0, 0, 0, 0, "monitored_asset_scope_empty"),
        (
            "blocked",
            [],
            0,
            False,
            None,
            None,
            None,
            None,
            None,
            "monitored_price_scope_unavailable",
        ),
    ],
    ids=["partial-results", "resolved-empty-blocked", "unknown-scope"],
)
def test_realtime_top_movers_capability_preserves_full_scope_contract(
    monkeypatch: pytest.MonkeyPatch,
    state: str,
    results: list[dict[str, object]],
    count: int,
    scope_available: bool,
    requested: int | None,
    qualified: int | None,
    unavailable: int | None,
    rankable: int | None,
    unrankable: int | None,
    reason: str,
) -> None:
    import agomtradepro_mcp.server as server_module

    payload: dict[str, object] = {
        "results": results,
        "count": count,
        "source": "cached_monitored_prices",
        "scope": "all_monitored_assets",
        "scope_available": scope_available,
        "requested": requested,
        "qualified": qualified,
        "unavailable": unavailable,
        "rankable": rankable,
        "unrankable": unrankable,
        "outcome": state,
        "is_reliable": False,
        "is_stale": None,
        "must_not_use_for_decision": True,
        "blocked_reason": reason,
    }
    calls: list[tuple[str, int]] = []

    class _Realtime:
        @staticmethod
        def get_top_movers_payload(direction: str, limit: int) -> dict[str, object]:
            calls.append((direction, limit))
            if payload["scope_available"] is False:
                raise ServerError(status_code=503, response=payload)
            return payload

    monkeypatch.setattr(
        "agomtradepro.AgomTradeProClient",
        lambda: SimpleNamespace(realtime=_Realtime()),
    )

    response = server_module.CORE_DISPATCHER.call(
        capability_key="realtime.read.top_movers",
        arguments={"direction": "down", "limit": 5},
    )

    expected = {
        **payload,
        "movers": results,
        "total_count": count,
    }
    assert response["result"] == expected
    assert response["result"]["must_not_use_for_decision"] is True
    assert response["result"]["outcome"] == state
    assert calls == [("down", 5)]

    manifest = CapabilityRegistryLoader().build_registry()["realtime.read.top_movers"]
    assert set(expected) <= set(manifest.output_schema["properties"])
    assert set(expected) <= set(manifest.output_schema["required"])


@pytest.mark.parametrize(
    "missing_field",
    ["requested", "qualified", "unavailable", "rankable", "unrankable", "is_stale"],
)
def test_realtime_top_movers_503_rejects_missing_nullable_scope_field(
    monkeypatch: pytest.MonkeyPatch,
    missing_field: str,
) -> None:
    """Preserve malformed 503 errors when any nullable scope field is absent."""

    import agomtradepro_mcp.server as server_module
    from agomtradepro_mcp.registry.runtime_handlers.owners.realtime import (
        _fallback_realtime_read_top_movers,
    )

    payload: dict[str, object] = {
        "results": [],
        "count": 0,
        "source": "cached_monitored_prices",
        "scope": "all_monitored_assets",
        "scope_available": False,
        "requested": None,
        "qualified": None,
        "unavailable": None,
        "rankable": None,
        "unrankable": None,
        "outcome": "blocked",
        "is_reliable": False,
        "is_stale": None,
        "must_not_use_for_decision": True,
        "blocked_reason": "monitored_price_scope_unavailable",
    }
    del payload[missing_field]
    failure = ServerError(status_code=503, response=payload)

    class _Realtime:
        @staticmethod
        def get_top_movers_payload(direction: str, limit: int) -> dict[str, object]:
            raise failure

    monkeypatch.setattr(
        "agomtradepro.AgomTradeProClient",
        lambda: SimpleNamespace(realtime=_Realtime()),
    )

    with pytest.raises(ServerError) as raised:
        _fallback_realtime_read_top_movers(direction="down", limit=5)

    assert raised.value is failure
    assert raised.value.response == payload

    dispatcher_response = server_module.CORE_DISPATCHER.call(
        capability_key="realtime.read.top_movers",
        arguments={"direction": "down", "limit": 5},
    )
    assert dispatcher_response["ok"] is False
    assert dispatcher_response["status"] == "error"
    assert "result" not in dispatcher_response
    error = dispatcher_response["error"]
    assert isinstance(error, dict)
    assert error["upstream_status_code"] == 503
    assert error["blocked_reason"] == "monitored_price_scope_unavailable"
    assert error["must_not_use_for_decision"] is True
    assert failure.response == payload


def test_realtime_alert_create_previews_then_commits_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agomtradepro_mcp.server as server_module

    calls: list[tuple[str, object]] = []

    class _Realtime:
        @staticmethod
        def create_alert(asset_code, condition, threshold, message=None):
            calls.append(("create", (asset_code, condition, threshold, message)))
            return {"id": 7, "asset_code": asset_code, "status": "active"}

    monkeypatch.setattr(
        "agomtradepro.AgomTradeProClient",
        lambda: SimpleNamespace(realtime=_Realtime()),
    )
    arguments = {
        "asset_code": "510300.SH",
        "condition": "cross_up",
        "threshold": 3.5,
        "message": "突破",
        "idempotency_key": "realtime-create-7",
    }

    preview = server_module.CORE_DISPATCHER.call(
        capability_key="realtime.create.price_alert",
        arguments=arguments,
    )

    assert preview["status"] == "confirmation_required"
    assert preview["preview_result"]["preview_only"] is True
    assert preview["preview_result"]["alert_summary"]["asset_code"] == "510300.SH"
    assert calls == []

    committed = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview["confirmation_token"],
        approve=True,
    )
    assert committed["status"] == "completed"
    assert calls == [("create", ("510300.SH", "cross_up", 3.5, "突破"))]

    replay = server_module.CORE_DISPATCHER.call(
        capability_key="realtime.create.price_alert",
        arguments=arguments,
    )
    assert replay["status"] == "idempotent_replay"
    assert len(calls) == 1


def test_realtime_update_delete_and_subscription_handlers_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agomtradepro_mcp.server as server_module

    calls: list[tuple[str, object]] = []

    class _Realtime:
        @staticmethod
        def get_alert(alert_id):
            return {"id": alert_id, "asset_code": "510300.SH", "status": "active"}

        @staticmethod
        def update_alert(alert_id, **updates):
            calls.append(("update", (alert_id, updates)))
            return {"id": alert_id, **updates}

        @staticmethod
        def delete_alert(alert_id):
            calls.append(("delete", alert_id))

        @staticmethod
        def get_subscriptions():
            return [{"asset_code": "510300.SH"}]

        @staticmethod
        def subscribe_price(asset_code):
            calls.append(("subscribe", asset_code))
            return {"asset_code": asset_code}

        @staticmethod
        def unsubscribe_price(asset_code):
            calls.append(("unsubscribe", asset_code))

    monkeypatch.setattr(
        "agomtradepro.AgomTradeProClient",
        lambda: SimpleNamespace(realtime=_Realtime()),
    )
    handlers = server_module.INTERNAL_GOVERNED_HANDLERS

    update = handlers["realtime_update_price_alert"](
        alert_id=7,
        status="inactive",
        preview_only=True,
        idempotency_key="update-7",
    )
    delete = handlers["realtime_delete_price_alert"](
        alert_id=7,
        preview_only=True,
        idempotency_key="delete-7",
    )
    subscribe = handlers["realtime_create_price_subscription"](
        asset_code="000001.SZ",
        preview_only=True,
        idempotency_key="subscribe-1",
    )
    unsubscribe = handlers["realtime_delete_price_subscription"](
        asset_code="510300.SH",
        preview_only=True,
        idempotency_key="unsubscribe-1",
    )

    assert update["current_alert"]["id"] == 7
    assert update["update_summary"] == {"status": "inactive"}
    assert delete["alert_summary"]["asset_code"] == "510300.SH"
    assert subscribe["already_subscribed"] is False
    assert unsubscribe["currently_subscribed"] is True
    assert calls == []
