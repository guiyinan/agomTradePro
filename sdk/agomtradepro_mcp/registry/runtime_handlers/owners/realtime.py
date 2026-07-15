"""realtime runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _fallback_get_realtime_price(asset_code: str) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.realtime.get_price(asset_code)


def _fallback_get_multiple_realtime_prices(
    asset_codes: list[str],
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    prices = client.realtime.get_multiple_prices(asset_codes)
    return {
        "prices": prices,
        "total_count": len(prices),
    }


def _fallback_get_market_summary() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.realtime.get_market_summary()


def _fallback_realtime_read_sector_performance() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    sectors = client.realtime.get_sector_performance()
    if not isinstance(sectors, list):
        raise ValueError("realtime.read.sector_performance returned an invalid payload")
    return {"sectors": sectors, "total_count": len(sectors)}


def _fallback_realtime_read_top_movers(
    direction: str = "up",
    limit: int = 10,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    movers = client.realtime.get_top_movers(direction=direction, limit=limit)
    return {"movers": movers, "total_count": len(movers)}


def _fallback_list_price_alerts(
    status: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    alerts = client.realtime.list_alerts(status=status, limit=limit)
    return {"alerts": alerts, "total_count": len(alerts)}


def _internal_handler_realtime_get_price_alert(alert_id: int) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    return AgomTradeProClient().realtime.get_alert(alert_id)


def _internal_handler_realtime_list_price_subscriptions() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    subscriptions = AgomTradeProClient().realtime.get_subscriptions()
    return {"subscriptions": subscriptions, "total_count": len(subscriptions)}


def _internal_handler_realtime_create_price_alert(
    asset_code: str,
    condition: str,
    threshold: float,
    message: str | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    canonical = asset_code.strip().upper()
    if preview_only:
        return {
            "success": True,
            "preview_only": True,
            "alert_summary": {
                "asset_code": canonical,
                "condition": condition,
                "threshold": threshold,
                "message": message,
            },
            "message": "Preview generated. Confirm to create this price alert.",
        }
    return AgomTradeProClient().realtime.create_alert(
        canonical,
        condition,
        threshold,
        message,
    )


def _internal_handler_realtime_update_price_alert(
    alert_id: int,
    condition: str | None = None,
    threshold: float | None = None,
    status: str | None = None,
    message: str | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    updates = {
        key: value
        for key, value in {
            "condition": condition,
            "threshold": threshold,
            "status": status,
            "message": message,
        }.items()
        if value is not None
    }
    if not updates:
        raise ValueError("At least one price alert update must be provided.")
    client = AgomTradeProClient()
    if preview_only:
        return {
            "success": True,
            "preview_only": True,
            "current_alert": client.realtime.get_alert(alert_id),
            "update_summary": updates,
            "message": "Preview generated. Confirm to update this price alert.",
        }
    return client.realtime.update_alert(alert_id, **updates)


def _internal_handler_realtime_delete_price_alert(
    alert_id: int,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    if preview_only:
        return {
            "success": True,
            "preview_only": True,
            "alert_summary": client.realtime.get_alert(alert_id),
            "message": "Preview generated. Confirm to delete this price alert.",
        }
    client.realtime.delete_alert(alert_id)
    return {"success": True, "alert_id": alert_id}


def _internal_handler_realtime_create_price_subscription(
    asset_code: str,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    canonical = asset_code.strip().upper()
    client = AgomTradeProClient()
    if preview_only:
        existing = {
            str(item.get("asset_code", "")).upper()
            for item in client.realtime.get_subscriptions()
        }
        return {
            "success": True,
            "preview_only": True,
            "asset_code": canonical,
            "already_subscribed": canonical in existing,
            "message": "Preview generated. Confirm to subscribe to price updates.",
        }
    return client.realtime.subscribe_price(canonical)


def _internal_handler_realtime_delete_price_subscription(
    asset_code: str,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    canonical = asset_code.strip().upper()
    client = AgomTradeProClient()
    if preview_only:
        existing = {
            str(item.get("asset_code", "")).upper()
            for item in client.realtime.get_subscriptions()
        }
        return {
            "success": True,
            "preview_only": True,
            "asset_code": canonical,
            "currently_subscribed": canonical in existing,
            "message": "Preview generated. Confirm to remove this subscription.",
        }
    client.realtime.unsubscribe_price(canonical)
    return {"success": True, "asset_code": canonical}


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "get_realtime_price": _fallback_get_realtime_price,
    "get_multiple_realtime_prices": _fallback_get_multiple_realtime_prices,
    "get_market_summary": _fallback_get_market_summary,
    "realtime_read_sector_performance": _fallback_realtime_read_sector_performance,
    "realtime_read_top_movers": _fallback_realtime_read_top_movers,
    "list_price_alerts": _fallback_list_price_alerts,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {
    "realtime_get_price_alert": _internal_handler_realtime_get_price_alert,
    "realtime_list_price_subscriptions": (
        _internal_handler_realtime_list_price_subscriptions
    ),
    "realtime_create_price_alert": _internal_handler_realtime_create_price_alert,
    "realtime_update_price_alert": _internal_handler_realtime_update_price_alert,
    "realtime_delete_price_alert": _internal_handler_realtime_delete_price_alert,
    "realtime_create_price_subscription": (
        _internal_handler_realtime_create_price_subscription
    ),
    "realtime_delete_price_subscription": (
        _internal_handler_realtime_delete_price_subscription
    ),
}
