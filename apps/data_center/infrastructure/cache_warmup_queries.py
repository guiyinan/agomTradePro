"""Infrastructure queries for deployment cache warmup."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime

from django.db.models import OuterRef, Subquery

from apps.data_center.domain.entities import MacroFact
from apps.data_center.domain.enums import DataQualityStatus
from apps.data_center.infrastructure.macro_fact_selection import (
    configured_macro_source,
    select_macro_fact_series,
)
from apps.data_center.infrastructure.models import IndicatorCatalogModel, MacroFactModel


@dataclass
class _MacroFactWarmupCandidate:
    """Typed canonical-selection projection retaining its ORM model."""

    model: MacroFactModel
    indicator_code: str
    reporting_period: date
    value: float
    source: str
    revision_number: int
    published_at: date | None
    fetched_at: datetime
    extra: Mapping[str, object]

    @classmethod
    def from_model(cls, model: MacroFactModel) -> _MacroFactWarmupCandidate:
        """Project ORM values into the domain selection protocol."""

        return cls(
            model=model,
            indicator_code=model.indicator_code,
            reporting_period=model.reporting_period,
            value=float(model.value),
            source=model.source,
            revision_number=model.revision_number,
            published_at=model.published_at,
            fetched_at=model.fetched_at,
            extra=dict(model.extra or {}),
        )


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
            extra=dict(model.extra or {}),
        )

    def list_latest_by_indicator(self, *, limit: int = 50) -> list[MacroFact]:
        """Return the latest fact for each indicator, capped for cache warmup."""

        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("limit must be an integer")
        if limit <= 0:
            return []
        indicator_codes = list(
            MacroFactModel.objects.order_by("indicator_code")
            .values_list("indicator_code", flat=True)
            .distinct()[:limit]
        )
        if not indicator_codes:
            return []

        latest_period_query = (
            MacroFactModel.objects.filter(indicator_code=OuterRef("indicator_code"))
            .order_by("-reporting_period")
            .values("reporting_period")[:1]
        )
        models_by_code: dict[str, list[MacroFactModel]] = defaultdict(list)
        for model in MacroFactModel.objects.filter(
            indicator_code__in=indicator_codes,
            reporting_period=Subquery(latest_period_query),
        ):
            models_by_code[model.indicator_code].append(model)
        catalogs = {
            catalog.code: catalog
            for catalog in IndicatorCatalogModel.objects.filter(code__in=indicator_codes).only(
                "code",
                "extra",
            )
        }

        latest_facts: list[MacroFact] = []
        for indicator_code in indicator_codes:
            catalog = catalogs.get(indicator_code)
            selection = select_macro_fact_series(
                [
                    _MacroFactWarmupCandidate.from_model(model)
                    for model in models_by_code[indicator_code]
                ],
                preferred_source=configured_macro_source(catalog.extra if catalog else {}),
            )
            if selection.is_consistent and selection.facts:
                latest_facts.append(self._from_model(selection.facts[-1].model))
        return latest_facts
