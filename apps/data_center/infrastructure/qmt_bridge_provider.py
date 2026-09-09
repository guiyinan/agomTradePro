"""Server-side QMT provider backed exclusively by authenticated bridge facts."""

from datetime import date, timedelta

from django.utils import timezone

from apps.data_center.domain.entities import PriceBar, QuoteSnapshot

from .models import PriceBarModel, QuoteSnapshotModel
from .price_bar_repository import PriceBarRepository
from .qmt_bridge_models import QmtBridgeBindingModel
from .quote_snapshot_repository import QuoteSnapshotRepository


class QmtBridgeProvider:
    """Reuse provider routing without loading the Windows SDK on the server."""

    def __init__(self, binding_id: str, provider_id: int | None) -> None:
        self.binding_id = binding_id
        self.provider_id = provider_id

    def _binding(self) -> QmtBridgeBindingModel | None:
        return QmtBridgeBindingModel.objects.filter(
            pk=self.binding_id,
            provider_id=self.provider_id,
            provider__is_active=True,
            enabled=True,
            revoked=False,
            owner__is_active=True,
        ).first()

    def quotes(self, assets: list[str]) -> list[QuoteSnapshot]:
        """Return fresh observations only; stale/missing data permits fallback."""
        binding = self._binding()
        if binding is None:
            return []
        now = timezone.now()
        rows = QuoteSnapshotModel.objects.filter(
            source=f"qmt-bridge:{binding.pk.hex}",
            asset_code__in=assets,
            snapshot_at__gte=now - timedelta(seconds=binding.freshness_seconds),
            snapshot_at__lte=now,
        ).order_by("asset_code", "-snapshot_at")
        found: dict[str, QuoteSnapshot] = {}
        for row in rows:
            if row.asset_code not in found:
                found[row.asset_code] = QuoteSnapshotRepository._from_model(row)
        return list(found.values())

    def bars(self, asset: str, start: date, end: date) -> list[PriceBar]:
        """Return source-dated unadjusted history for existing provider consumers."""
        binding = self._binding()
        if binding is None:
            return []
        rows = PriceBarModel.objects.filter(
            source=f"qmt-bridge:{binding.pk.hex}",
            asset_code=asset,
            bar_date__gte=start,
            bar_date__lte=end,
            freq="1d",
            adjustment="none",
        ).order_by("bar_date")
        return [PriceBarRepository._from_model(row) for row in rows]
