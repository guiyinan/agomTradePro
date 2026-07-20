"""Adapters from frozen decision_rhythm valuation tables to the valuation owner."""

from __future__ import annotations

from datetime import date
from typing import Any

from django.utils import timezone

from apps.valuation.domain.entities import ValuationSnapshot
from apps.valuation.domain.rules import ValuationPayloadPolicy


class DecisionRhythmSnapshotSource:
    """Expose legacy ORM storage through the valuation application port."""

    def list_recent_payloads(self, security_code: str) -> list[dict[str, Any]]:
        """Return up to ten recent persisted snapshot payloads."""
        from .models import ValuationSnapshotModel

        snapshots = ValuationSnapshotModel.objects.filter(
            security_code=security_code,
        ).order_by(
            "-calculated_at"
        )[:10]
        return [
            {
                "fair_value": float(item.fair_value),
                "entry_price_low": float(item.entry_price_low),
                "entry_price_high": float(item.entry_price_high),
                "target_price_low": float(item.target_price_low),
                "target_price_high": float(item.target_price_high),
                "stop_loss_price": float(item.stop_loss_price),
                "valuation_method": item.valuation_method,
                "valuation_source": "decision_rhythm_snapshot",
                "valuation_snapshot_id": item.snapshot_id,
                "calculated_at": item.calculated_at,
                "is_legacy": item.is_legacy,
                "input_parameters": item.input_parameters or {},
            }
            for item in snapshots
        ]

    def get_today_fallback(
        self,
        security_code: str,
        today: date,
    ) -> ValuationSnapshot | None:
        """Return today's positive FALLBACK snapshot when one already exists."""
        from .models import ValuationSnapshotModel

        latest = (
            ValuationSnapshotModel.objects.filter(
                security_code=security_code,
                valuation_method="FALLBACK",
            )
            .order_by("-calculated_at")
            .first()
        )
        if latest is None or timezone.localdate(latest.calculated_at) != today:
            return None
        snapshot = latest.to_domain()
        payload = ValuationPayloadPolicy.snapshot_to_payload(snapshot, valuation_source="")
        return snapshot if ValuationPayloadPolicy.has_positive_price_contract(payload) else None

    def save_fallback(self, snapshot: ValuationSnapshot) -> ValuationSnapshot:
        """Persist a fallback through the frozen legacy repository."""
        from .repositories import ValuationSnapshotRepository

        return ValuationSnapshotRepository().save(snapshot)
