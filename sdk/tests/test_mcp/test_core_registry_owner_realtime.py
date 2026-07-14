"""Governed realtime management capability contracts."""

from types import SimpleNamespace

import pytest

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
