"""Infrastructure queries for deployment cache warmup."""

from __future__ import annotations

from apps.data_center.domain.entities import DataQualityStatus, MacroFact
from apps.data_center.infrastructure.models import MacroFactModel


class MacroFactCacheWarmupRepository:
    """Read macro fact rows needed by deployment cache warmup."""

    @staticmethod
    def _from_model(model: MacroFactModel) -> MacroFact:
        return MacroFact(
            indicator_code=model.indicator_code,
            reporting_period=model.reporting_period,
            value=float(model.value),
            unit=model.unit,
            source=model.source,
            revision_number=model.revision_number,
            published_at=model.published_at,
            quality=DataQualityStatus(model.quality),
            fetched_at=model.fetched_at,
            extra=model.extra or {},
        )

    def list_latest_by_indicator(self, *, limit: int = 50) -> list[MacroFact]:
        """Return the latest fact for each indicator, capped for cache warmup."""

        if limit <= 0:
            return []
        indicator_codes = list(
            MacroFactModel.objects.order_by("indicator_code")
            .values_list("indicator_code", flat=True)
            .distinct()[:limit]
        )
        latest_facts: list[MacroFact] = []
        for indicator_code in indicator_codes:
            model = (
                MacroFactModel.objects.filter(indicator_code=indicator_code)
                .order_by("-reporting_period", "-revision_number")
                .first()
            )
            if model is not None:
                latest_facts.append(self._from_model(model))
        return latest_facts
