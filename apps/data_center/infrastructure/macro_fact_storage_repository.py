"""Canonical macro fact time-series persistence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time

from django.db.models import Q

from apps.data_center.domain.control_plane import PublicationFactReference
from apps.data_center.domain.entities import MacroFact
from apps.data_center.domain.enums import DataQualityStatus
from apps.data_center.infrastructure.macro_fact_selection import (
    configured_macro_source,
    select_macro_fact_series,
)
from apps.data_center.infrastructure.models import IndicatorCatalogModel, MacroFactModel
from apps.data_center.infrastructure.orm_retry import retry_macro_fact_upsert


@dataclass
class _MacroFactModelCandidate:
    """Typed domain-selection projection retaining its originating model."""

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
    def from_model(cls, model: MacroFactModel) -> _MacroFactModelCandidate:
        """Project ORM field values into the domain selection protocol."""

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


class MacroFactRepository:
    """ORM-backed repository for macro-economic fact time-series."""

    REQUIRED_GOVERNANCE_FIELDS = frozenset(
        {
            "source_type",
            "original_unit",
            "display_unit",
            "dimension_key",
            "multiplier_to_storage",
            "matched_rule_id",
            "period_type",
        }
    )

    @staticmethod
    def _from_model(model: MacroFactModel) -> MacroFact:
        """Map one canonical ORM row to the domain fact."""

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

    def get_series(
        self,
        indicator_code: str,
        start: date | None = None,
        end: date | None = None,
        limit: int = 500,
        *,
        use_pit: bool = False,
        fact_pks: Sequence[str] | None = None,
    ) -> list[MacroFact]:
        """Return a governed, source-consistent macro series."""

        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive integer")
        queryset = MacroFactModel.objects.filter(indicator_code=indicator_code)
        if fact_pks is not None:
            queryset = queryset.filter(pk__in=list(fact_pks))
        if start:
            queryset = queryset.filter(reporting_period__gte=start)
        if end:
            queryset = queryset.filter(reporting_period__lte=end)
            if use_pit:
                queryset = queryset.filter(
                    Q(published_at__lte=end)
                    | Q(published_at__isnull=True, reporting_period__lte=end)
                )
        models = list(queryset.order_by("-reporting_period", "-id")[: max(limit * 4, limit)])
        catalog = IndicatorCatalogModel.objects.filter(code=indicator_code).only("extra").first()
        selection = select_macro_fact_series(
            [_MacroFactModelCandidate.from_model(model) for model in models],
            preferred_source=configured_macro_source(catalog.extra if catalog else {}),
        )
        if not selection.is_consistent:
            return []
        return [
            self._from_model(candidate.model) for candidate in reversed(selection.facts[-limit:])
        ]

    def list_by_original_unit(
        self,
        original_unit: str,
        *,
        limit: int = 100_000,
    ) -> list[MacroFact]:
        """List canonical facts retaining one original source unit."""

        normalized_unit = str(original_unit or "").strip()
        if not normalized_unit:
            raise ValueError("original_unit must be non-empty")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100_000:
            raise ValueError("limit must be an integer between 1 and 100000")
        rows = MacroFactModel.objects.filter(
            extra__original_unit__icontains=normalized_unit
        ).order_by("indicator_code", "reporting_period", "source", "revision_number", "id")[:limit]
        return [self._from_model(model) for model in rows]

    def get_latest(self, indicator_code: str) -> MacroFact | None:
        """Return the selected fact for the latest reporting period."""

        latest_period = (
            MacroFactModel.objects.filter(indicator_code=indicator_code)
            .order_by("-reporting_period")
            .values_list("reporting_period", flat=True)
            .first()
        )
        if latest_period is None:
            return None
        models = list(
            MacroFactModel.objects.filter(
                indicator_code=indicator_code,
                reporting_period=latest_period,
            )
        )
        catalog = IndicatorCatalogModel.objects.filter(code=indicator_code).only("extra").first()
        selection = select_macro_fact_series(
            [_MacroFactModelCandidate.from_model(model) for model in models],
            preferred_source=configured_macro_source(catalog.extra if catalog else {}),
        )
        return (
            self._from_model(selection.facts[-1].model)
            if selection.is_consistent and selection.facts
            else None
        )

    @classmethod
    def _validate_governance(cls, fact: MacroFact) -> None:
        """Reject writes that bypass canonical macro governance normalization."""

        extra = dict(fact.extra or {})
        missing = sorted(
            key for key in cls.REQUIRED_GOVERNANCE_FIELDS if key not in extra or extra[key] is None
        )
        if fact.published_at is not None and "publication_lag_days" not in extra:
            missing.append("publication_lag_days")
        if missing:
            raise ValueError(
                f"MacroFact {fact.indicator_code} is missing governance metadata: "
                + ", ".join(missing)
            )
        if str(extra["source_type"]).strip() != fact.source:
            raise ValueError(
                f"MacroFact {fact.indicator_code} source does not match extra.source_type"
            )

    def bulk_upsert(self, facts: list[MacroFact]) -> int:
        """Validate and upsert canonical macro facts."""

        for fact in facts:
            self._validate_governance(fact)
        for fact in facts:
            retry_macro_fact_upsert(MacroFactModel.objects, fact)
        return len(facts)

    def list_publication_candidates(
        self, facts: Sequence[MacroFact]
    ) -> list[PublicationFactReference]:
        """Resolve exact macro facts and require source publication dates."""

        references: list[PublicationFactReference] = []
        seen_fact_pks: set[str] = set()
        for fact in facts:
            row = (
                MacroFactModel._default_manager.filter(
                    indicator_code=fact.indicator_code,
                    reporting_period=fact.reporting_period,
                    source=fact.source,
                    revision_number=fact.revision_number,
                )
                .order_by("id")
                .first()
            )
            if row is None or row.published_at is None or str(row.pk) in seen_fact_pks:
                continue
            fact_pk = str(row.pk)
            seen_fact_pks.add(fact_pk)
            natural_key = (
                f"{row.indicator_code}:{row.reporting_period.isoformat()}:{row.source}:"
                f"{row.revision_number}"
            )
            references.append(
                PublicationFactReference(
                    natural_key=natural_key,
                    source=row.source,
                    source_record_id=row.source_record_id or natural_key,
                    fact_table="data_center_macro_fact",
                    fact_pk=fact_pk,
                    observed_at=datetime.combine(row.published_at, time.min, tzinfo=UTC),
                    raw_payload_hash=row.raw_payload_hash or _macro_payload_hash(row),
                    quality_status=row.quality_status,
                    revision_number=row.revision_number,
                )
            )
        return references


def _macro_payload_hash(row: MacroFactModel) -> str:
    """Return deterministic evidence for one persisted macro fact."""

    payload = {
        "indicator_code": row.indicator_code,
        "reporting_period": row.reporting_period.isoformat(),
        "value": str(row.value),
        "unit": row.unit,
        "source": row.source,
        "revision_number": row.revision_number,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "quality": row.quality,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


__all__ = ["MacroFactRepository"]
