"""Channels-backed realtime price and alert delivery."""

from importlib import import_module
from typing import Any

from asgiref.sync import async_to_sync
from django.conf import settings

from apps.realtime.domain.entities import PriceAlert, RealtimePrice
from apps.realtime.domain.protocols import RealtimeChannelNotifierProtocol


def _get_channel_layer() -> Any:
    """Resolve the optional Channels layer at the infrastructure boundary."""

    channels_layers = import_module("channels.layers")
    return channels_layers.get_channel_layer()


class ChannelPriceNotifier(RealtimeChannelNotifierProtocol):
    """Publish owner- and asset-sharded events through the channel layer."""

    def _send(self, group: str, event: dict[str, Any]) -> None:
        if not settings.REALTIME_WEBSOCKET_ENABLED:
            return
        channel_layer = _get_channel_layer()
        if channel_layer is None:
            return
        async_to_sync(channel_layer.group_send)(group, event)

    def publish_price(self, price: RealtimePrice) -> None:
        """Publish a serializable price update to one asset group."""

        self._send(
            f"asset.{price.asset_code}",
            {
                "type": "price.update",
                "payload": {
                    "asset_code": price.asset_code,
                    "asset_type": price.asset_type.value,
                    "price": str(price.price),
                    "change": str(price.change) if price.change is not None else None,
                    "change_pct": (
                        str(price.change_pct) if price.change_pct is not None else None
                    ),
                    "volume": price.volume,
                    "timestamp": price.timestamp.isoformat(),
                    "source": price.source,
                },
            },
        )

    def publish_alert(self, alert: PriceAlert) -> None:
        """Publish a claimed alert only to its owning user group."""

        self._send(
            f"user.{alert.owner_id}.alerts",
            {
                "type": "alert.triggered",
                "payload": {
                    "id": alert.id,
                    "asset_code": alert.asset_code,
                    "condition": alert.condition.value,
                    "threshold": str(alert.threshold),
                    "status": alert.status.value,
                    "message": alert.message,
                    "triggered_price": (
                        str(alert.triggered_price)
                        if alert.triggered_price is not None
                        else None
                    ),
                    "triggered_at": (
                        alert.triggered_at.isoformat()
                        if alert.triggered_at is not None
                        else None
                    ),
                },
            },
        )

    def subscriptions_changed(self, owner_id: int) -> None:
        """Tell connected owner clients to reload durable subscriptions."""

        self._send(
            f"user.{owner_id}.control",
            {"type": "subscriptions.changed"},
        )
