"""Infrastructure queries for deployment cache warmup."""

from __future__ import annotations

from apps.data_center.domain.entities import DataQualityStatus, MacroFact
from apps.data_center.infrastructure.macro_fact_selection import (
    configured_macro_source,
    select_macro_fact_series,
)
from apps.data_center.infrastructure.models import IndicatorCatalogModel, MacroFactModel


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
            latest_period = (
                MacroFactModel.objects.filter(indicator_code=indicator_code)
                .order_by("-reporting_period")
                .values_list("reporting_period", flat=True)
                .first()
            )
            if latest_period is None:
                continue
            models = list(
                MacroFactModel.objects.filter(
                    indicator_code=indicator_code,
                    reporting_period=latest_period,
                )
            )
            catalog = IndicatorCatalogModel.objects.filter(code=indicator_code).only("extra").first()
            selection = select_macro_fact_series(
                models,
                preferred_source=configured_macro_source(catalog.extra if catalog else {}),
            )
            if selection.is_consistent and selection.facts:
                latest_facts.append(self._from_model(selection.facts[-1]))
        return latest_facts
