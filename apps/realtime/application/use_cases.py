"""Realtime application use cases."""

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any

from apps.realtime.application.dtos import PriceAlertDTO, PriceSubscriptionDTO
from apps.realtime.application.price_polling_service import PricePollingService, PricePollingUseCase
from apps.realtime.domain.entities import (
    AlertCondition,
    AlertStatus,
    PriceAlert,
    normalize_asset_code,
)
from apps.realtime.domain.protocols import (
    PriceAlertRepositoryProtocol,
    PriceSubscriptionRepositoryProtocol,
    RealtimeChannelNotifierProtocol,
)


class SubscriptionLimitExceeded(ValueError):
    """Raised when an owner exceeds the active subscription bound."""


class RealtimeAlertService:
    """Orchestrate owner-scoped alert CRUD through an injected repository."""

    def __init__(self, repository: PriceAlertRepositoryProtocol) -> None:
        self.repository = repository

    def list(self, owner_id: int) -> list[PriceAlertDTO]:
        """List alerts belonging to one owner."""

        return [PriceAlertDTO.from_domain(item) for item in self.repository.list_for_owner(owner_id)]

    def get(self, owner_id: int, alert_id: int) -> PriceAlertDTO | None:
        """Get one owner-scoped alert."""

        alert = self.repository.get_for_owner(owner_id, alert_id)
        return PriceAlertDTO.from_domain(alert) if alert is not None else None

    def create(
        self,
        owner_id: int,
        *,
        asset_code: str,
        condition: str,
        threshold: Decimal,
        message: str = "",
    ) -> PriceAlertDTO:
        """Create a durable active price alert."""

        created = self.repository.create(
            PriceAlert(
                owner_id=owner_id,
                asset_code=asset_code,
                condition=AlertCondition(condition),
                threshold=threshold,
                message=message,
            )
        )
        return PriceAlertDTO.from_domain(created)

    def update(
        self,
        owner_id: int,
        alert_id: int,
        changes: dict[str, Any],
    ) -> PriceAlertDTO | None:
        """Apply a bounded owner-scoped alert update."""

        current = self.repository.get_for_owner(owner_id, alert_id)
        if current is None:
            return None
        values = dict(changes)
        if "condition" in values:
            values["condition"] = AlertCondition(values["condition"])
        if "status" in values:
            values["status"] = AlertStatus(values["status"])
            if values["status"] is AlertStatus.ACTIVE:
                values["triggered_price"] = None
                values["triggered_at"] = None
        updated = self.repository.update(replace(current, **values))
        return PriceAlertDTO.from_domain(updated) if updated is not None else None

    def delete(self, owner_id: int, alert_id: int) -> bool:
        """Delete one owner-scoped alert."""

        return self.repository.delete(owner_id, alert_id)


@dataclass(frozen=True)
class SubscriptionCommandResult:
    """Subscription result with idempotent creation evidence."""

    subscription: PriceSubscriptionDTO
    created: bool


class RealtimeSubscriptionService:
    """Orchestrate bounded durable subscriptions."""

    MAX_ACTIVE_ASSETS = 100

    def __init__(
        self,
        repository: PriceSubscriptionRepositoryProtocol,
        notifier: RealtimeChannelNotifierProtocol | None = None,
    ) -> None:
        self.repository = repository
        self.notifier = notifier

    def list(self, owner_id: int) -> list[PriceSubscriptionDTO]:
        """List active subscriptions belonging to one owner."""

        return [
            PriceSubscriptionDTO.from_domain(item)
            for item in self.repository.list_for_owner(owner_id)
        ]

    def subscribe(self, owner_id: int, asset_code: str) -> SubscriptionCommandResult:
        """Create, reactivate, or return an existing subscription."""

        canonical = normalize_asset_code(asset_code)
        existing = {
            item.asset_code: item for item in self.repository.list_for_owner(owner_id)
        }
        if canonical in existing:
            return SubscriptionCommandResult(
                PriceSubscriptionDTO.from_domain(existing[canonical]),
                created=False,
            )
        if self.repository.count_active(owner_id) >= self.MAX_ACTIVE_ASSETS:
            raise SubscriptionLimitExceeded("active subscription limit is 100")
        subscription = self.repository.subscribe(owner_id, canonical)
        if self.notifier is not None:
            self.notifier.subscriptions_changed(owner_id)
        return SubscriptionCommandResult(
            PriceSubscriptionDTO.from_domain(subscription),
            created=True,
        )

    def unsubscribe(self, owner_id: int, asset_code: str) -> bool:
        """Deactivate a subscription and signal connected clients."""

        removed = self.repository.unsubscribe(owner_id, asset_code)
        if removed and self.notifier is not None:
            self.notifier.subscriptions_changed(owner_id)
        return removed

__all__ = [
    "PricePollingService",
    "PricePollingUseCase",
    "RealtimeAlertService",
    "RealtimeSubscriptionService",
    "SubscriptionCommandResult",
    "SubscriptionLimitExceeded",
]
