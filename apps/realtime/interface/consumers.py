"""Authenticated realtime price WebSocket consumer."""

from __future__ import annotations

from collections import deque
from time import monotonic
from typing import Any

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings

from apps.realtime.application.repository_provider import (
    get_realtime_subscription_service,
)
from apps.realtime.application.use_cases import SubscriptionLimitExceeded
from apps.realtime.domain.entities import normalize_asset_code


class RealtimePriceConsumer(AsyncJsonWebsocketConsumer):
    """Manage durable asset subscriptions and realtime event delivery."""

    MAX_COMMAND_ASSETS = 50
    MAX_COMMANDS_PER_WINDOW = 20
    COMMAND_WINDOW_SECONDS = 10.0

    async def connect(self) -> None:
        """Accept only enabled, authenticated, origin-validated connections."""

        if not settings.REALTIME_WEBSOCKET_ENABLED:
            await self.close(code=1013)
            return
        user = self.scope.get("user")
        if (
            self.scope.get("realtime_query_token_rejected")
            or user is None
            or not user.is_authenticated
        ):
            await self.close(code=4401)
            return
        self.owner_id = int(user.pk)
        self.command_times: deque[float] = deque()
        self.asset_groups: set[str] = set()
        await self.accept()
        await self.channel_layer.group_add(f"user.{self.owner_id}.control", self.channel_name)
        await self.channel_layer.group_add(f"user.{self.owner_id}.alerts", self.channel_name)
        subscriptions = await self._restore_asset_groups()
        await self.send_json(
            {"type": "connection.ready", "subscriptions": subscriptions}
        )

    async def disconnect(self, close_code: int) -> None:
        """Leave only groups joined by this authenticated connection."""

        owner_id = getattr(self, "owner_id", None)
        if owner_id is not None:
            await self.channel_layer.group_discard(
                f"user.{owner_id}.control",
                self.channel_name,
            )
            await self.channel_layer.group_discard(
                f"user.{owner_id}.alerts",
                self.channel_name,
            )
        for group in getattr(self, "asset_groups", set()):
            await self.channel_layer.group_discard(group, self.channel_name)

    async def receive_json(self, content: Any, **kwargs: Any) -> None:
        """Handle bounded subscription and heartbeat commands."""

        if not isinstance(content, dict):
            await self._error(None, "invalid_payload", "Object payload required.")
            return
        request_id = str(content.get("request_id") or "").strip()
        if not request_id:
            await self._error(None, "request_id_required", "request_id is required.")
            return
        if not self._within_rate_limit():
            await self._error(request_id, "rate_limited", "Command rate limit exceeded.")
            return
        action = str(content.get("action") or "").strip().lower()
        if action == "ping":
            await self.send_json({"type": "pong", "request_id": request_id})
            return
        if action == "list":
            await self._send_subscriptions(request_id)
            return
        if action not in {"subscribe", "unsubscribe"}:
            await self._error(request_id, "unknown_action", "Unsupported action.")
            return
        if not self.scope.get("realtime_token_allows_write", True):
            await self._error(request_id, "read_only_token", "Token is read-only.")
            return
        raw_codes = content.get("asset_codes")
        if not isinstance(raw_codes, list) or not raw_codes:
            await self._error(request_id, "asset_codes_required", "asset_codes is required.")
            return
        if len(raw_codes) > self.MAX_COMMAND_ASSETS:
            await self._error(
                request_id,
                "command_asset_limit",
                "At most 50 asset codes are allowed.",
            )
            return
        try:
            codes = sorted({normalize_asset_code(str(code)) for code in raw_codes})
        except ValueError as exc:
            await self._error(request_id, "invalid_asset_code", str(exc))
            return
        if action == "subscribe":
            await self._subscribe(request_id, codes)
        else:
            await self._unsubscribe(request_id, codes)

    async def _subscribe(self, request_id: str, codes: list[str]) -> None:
        service = get_realtime_subscription_service(notify_connected_clients=False)
        existing = await database_sync_to_async(service.list)(self.owner_id)
        existing_codes = {item.asset_code for item in existing}
        if len(existing_codes.union(codes)) > service.MAX_ACTIVE_ASSETS:
            await self._error(request_id, "subscription_limit", "Active limit is 100.")
            return
        try:
            for code in codes:
                await database_sync_to_async(service.subscribe)(self.owner_id, code)
        except SubscriptionLimitExceeded as exc:
            await self._error(request_id, "subscription_limit", str(exc))
            return
        await self._restore_asset_groups()
        await self._send_subscriptions(request_id)
        await self._notify_other_connections()

    async def _unsubscribe(self, request_id: str, codes: list[str]) -> None:
        service = get_realtime_subscription_service(notify_connected_clients=False)
        for code in codes:
            await database_sync_to_async(service.unsubscribe)(self.owner_id, code)
        await self._restore_asset_groups()
        await self._send_subscriptions(request_id)
        await self._notify_other_connections()

    async def _notify_other_connections(self) -> None:
        await self.channel_layer.group_send(
            f"user.{self.owner_id}.control",
            {
                "type": "subscriptions.changed",
                "exclude_channel": self.channel_name,
            },
        )

    async def _restore_asset_groups(self) -> list[str]:
        service = get_realtime_subscription_service()
        subscriptions = await database_sync_to_async(service.list)(self.owner_id)
        desired = {f"asset.{item.asset_code}" for item in subscriptions}
        for group in self.asset_groups - desired:
            await self.channel_layer.group_discard(group, self.channel_name)
        for group in desired - self.asset_groups:
            await self.channel_layer.group_add(group, self.channel_name)
        self.asset_groups = desired
        return sorted(item.asset_code for item in subscriptions)

    async def _send_subscriptions(self, request_id: str) -> None:
        subscriptions = await self._restore_asset_groups()
        await self.send_json(
            {
                "type": "subscription.updated",
                "request_id": request_id,
                "subscriptions": subscriptions,
            }
        )

    def _within_rate_limit(self) -> bool:
        now = monotonic()
        while self.command_times and now - self.command_times[0] > self.COMMAND_WINDOW_SECONDS:
            self.command_times.popleft()
        if len(self.command_times) >= self.MAX_COMMANDS_PER_WINDOW:
            return False
        self.command_times.append(now)
        return True

    async def _error(self, request_id: str | None, code: str, message: str) -> None:
        await self.send_json(
            {
                "type": "error",
                "request_id": request_id,
                "code": code,
                "message": message,
            }
        )

    async def subscriptions_changed(self, event: dict[str, Any]) -> None:
        """Restore database-backed groups after an external REST change."""

        if event.get("exclude_channel") == self.channel_name:
            return
        subscriptions = await self._restore_asset_groups()
        await self.send_json(
            {"type": "subscription.updated", "subscriptions": subscriptions}
        )

    async def price_update(self, event: dict[str, Any]) -> None:
        """Forward a price update to an authorized asset group member."""

        await self.send_json({"type": "price.update", **dict(event["payload"])})

    async def alert_triggered(self, event: dict[str, Any]) -> None:
        """Forward a claimed alert only to its owning user group."""

        await self.send_json({"type": "alert.triggered", **dict(event["payload"])})
