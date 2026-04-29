"""Compatibility repositories that proxy macro reads/writes to data_center facts."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Avg, Count, Max, Min

from apps.data_center.infrastructure.models import (
    IndicatorCatalogModel,
    IndicatorUnitRuleModel,
    MacroFactModel,
    RawAuditModel,
)
from apps.macro.domain.entities import MacroIndicator, PeriodType


def _get_period_type_display(period_type: str) -> str:
    period_labels = {
        "D": "日",
        "W": "周",
        "M": "月",
        "Q": "季",
        "H": "半",
        "Y": "年",
        "2W": "双周",
        "2M": "双月",
        "10D": "旬",
        "3M": "3月期",
        "6M": "6月期",
        "1Y": "1年期",
        "5Y": "5年期",
        "10Y": "10年期",
        "20Y": "20年期",
        "30Y": "30年期",
    }
    return period_labels.get(period_type, period_type)


def _safe_float(value: Any) -> float:
    if isinstance(value, Decimal):
        return float(value)
    return float(value or 0.0)


def _get_indicator_catalog(code: str) -> IndicatorCatalogModel | None:
    return IndicatorCatalogModel.objects.filter(code=code).first()


def _get_indicator_unit_rule(
    indicator_code: str,
    source_type: str | None = None,
    original_unit: str | None = None,
) -> dict[str, Any] | None:
    queryset = IndicatorUnitRuleModel._default_manager.filter(
        indicator_code=indicator_code,
        is_active=True,
    )
    if original_unit is not None:
        queryset = queryset.filter(original_unit=original_unit)

    if source_type:
        config = queryset.filter(source_type=source_type).values(
            "indicator_code",
            "source_type",
            "dimension_key",
            "original_unit",
            "storage_unit",
            "display_unit",
            "multiplier_to_storage",
            "priority",
            "description",
        ).first()
        if config:
            return config

    config = queryset.filter(source_type="").values(
        "indicator_code",
        "source_type",
        "dimension_key",
        "original_unit",
        "storage_unit",
        "display_unit",
        "multiplier_to_storage",
        "priority",
        "description",
    ).first()
    return config


def _resolve_indicator_unit_rule(
    indicator_code: str,
    *,
    source_type: str | None = None,
    original_unit: str | None = None,
) -> dict[str, Any]:
    rule = _get_indicator_unit_rule(
        indicator_code,
        source_type=source_type,
        original_unit=original_unit,
    )
    if rule:
        return rule
    raise ValueError(
        f"Indicator unit rule missing for {indicator_code}@{source_type or 'default'}"
        f" unit={original_unit!r}"
    )


def _resolve_period_type(
    fact: MacroFactModel,
    catalog: IndicatorCatalogModel | None = None,
) -> str:
    extra = fact.extra or {}
    period_type = extra.get("period_type")
    if isinstance(period_type, str) and period_type:
        return period_type
    if catalog and catalog.default_period_type:
        return str(catalog.default_period_type)
    return "M"


def _resolve_original_unit_from_fact(
    fact: MacroFactModel,
    catalog: IndicatorCatalogModel | None = None,
) -> str:
    extra = fact.extra or {}
    original_unit = extra.get("original_unit")
    if isinstance(original_unit, str) and original_unit:
        return original_unit
    matched_rule = _get_indicator_unit_rule(
        fact.indicator_code,
        source_type=str(extra.get("source_type") or ""),
    )
    if matched_rule and matched_rule.get("original_unit"):
        return str(matched_rule["original_unit"])
    if catalog and catalog.default_unit:
        return str(catalog.default_unit)
    return fact.unit or ""


def _resolve_publication_lag_days(
    fact: MacroFactModel,
    extra: dict[str, Any] | None = None,
) -> int:
    payload = extra if extra is not None else (fact.extra or {})
    lag_value = payload.get("publication_lag_days")
    if lag_value is not None:
        try:
            return int(lag_value)
        except (TypeError, ValueError):
            pass
    if fact.published_at is None:
        return 0
    return max((fact.published_at - fact.reporting_period).days, 0)


def _resolve_display_fields(
    fact: MacroFactModel,
    catalog: IndicatorCatalogModel | None = None,
) -> tuple[float, str, str, float]:
    extra = fact.extra or {}
    original_unit = _resolve_original_unit_from_fact(fact, catalog)
    display_unit = str(extra.get("display_unit") or original_unit or fact.unit or "")
    try:
        multiplier_to_storage = float(extra.get("multiplier_to_storage") or 1.0)
    except (TypeError, ValueError):
        multiplier_to_storage = 1.0

    if (not display_unit or not original_unit) and fact.indicator_code:
        matched_rule = _get_indicator_unit_rule(
            fact.indicator_code,
            source_type=str(extra.get("source_type") or ""),
            original_unit=original_unit or None,
        )
        if matched_rule:
            original_unit = original_unit or str(matched_rule.get("original_unit") or "")
            display_unit = display_unit or str(matched_rule.get("display_unit") or original_unit)
            try:
                multiplier_to_storage = float(matched_rule.get("multiplier_to_storage") or 1.0)
            except (TypeError, ValueError):
                multiplier_to_storage = 1.0

    display_value = _safe_float(fact.value)
    if multiplier_to_storage:
        display_value = display_value / multiplier_to_storage
    return display_value, display_unit or fact.unit or "", original_unit, multiplier_to_storage


def _serialize_fact_row(
    fact: MacroFactModel,
    catalog: IndicatorCatalogModel | None = None,
) -> dict[str, Any]:
    resolved_catalog = catalog or _get_indicator_catalog(fact.indicator_code)
    period_type = _resolve_period_type(fact, resolved_catalog)
    display_value, display_unit, original_unit, multiplier_to_storage = _resolve_display_fields(
        fact,
        resolved_catalog,
    )
    extra = fact.extra or {}
    return {
        "id": fact.id,
        "code": fact.indicator_code,
        "value": _safe_float(fact.value),
        "unit": fact.unit or (resolved_catalog.default_unit if resolved_catalog else ""),
        "display_value": display_value,
        "display_unit": display_unit,
        "original_unit": original_unit,
        "dimension_key": extra.get("dimension_key", ""),
        "multiplier_to_storage": multiplier_to_storage,
        "reporting_period": fact.reporting_period,
        "period_type": period_type,
        "period_type_display": _get_period_type_display(period_type),
        "observed_at": fact.reporting_period,
        "published_at": fact.published_at,
        "source": fact.source,
        "revision_number": fact.revision_number,
        "publication_lag_days": _resolve_publication_lag_days(fact, extra),
    }


def _fact_to_entity(fact: MacroFactModel) -> MacroIndicator:
    catalog = _get_indicator_catalog(fact.indicator_code)
    original_unit = _resolve_original_unit_from_fact(fact, catalog)
    return MacroIndicator(
        code=fact.indicator_code,
        value=_safe_float(fact.value),
        reporting_period=fact.reporting_period,
        period_type=_resolve_period_type(fact, catalog),
        unit=fact.unit or "",
        original_unit=original_unit,
        published_at=fact.published_at,
        source=fact.source,
    )


def _apply_period_type_filter(
    rows: list[dict[str, Any]],
    period_type_filter: str,
) -> list[dict[str, Any]]:
    if not period_type_filter:
        return rows
    return [row for row in rows if row["period_type"] == period_type_filter]


def _sort_rows(rows: list[dict[str, Any]], sort_field: str) -> list[dict[str, Any]]:
    reverse = sort_field.startswith("-")
    field_name = sort_field[1:] if reverse else sort_field
    field_map = {
        "code": "code",
        "value": "value",
        "source": "source",
        "period_type": "period_type",
        "reporting_period": "reporting_period",
        "revision_number": "revision_number",
        "published_at": "published_at",
    }
    resolved_field = field_map.get(field_name, "reporting_period")
    return sorted(
        rows,
        key=lambda row: (
            row.get(resolved_field) is None,
            row.get(resolved_field),
            row.get("revision_number", 0),
        ),
        reverse=reverse,
    )


class DjangoMacroRepository:
    """Compatibility write repository backed by data_center macro facts."""

    @transaction.atomic
    def save_indicator(
        self,
        indicator: MacroIndicator,
        revision_number: int = 1,
        period_type_override: str | None = None,
    ) -> MacroIndicator:
        period_type = period_type_override or (
            indicator.period_type.value
            if isinstance(indicator.period_type, PeriodType)
            else str(indicator.period_type)
        )
        original_unit = indicator.original_unit or indicator.unit
        rule = _resolve_indicator_unit_rule(
            indicator.code,
            source_type=indicator.source,
            original_unit=original_unit,
        )
        storage_value = float(indicator.value) * float(rule["multiplier_to_storage"])
        storage_unit = str(rule["storage_unit"] or indicator.unit)
        lag_days = (
            max((indicator.published_at - indicator.reporting_period).days, 0)
            if indicator.published_at
            else 0
        )
        defaults = {
            "value": storage_value,
            "unit": storage_unit or indicator.unit,
            "published_at": indicator.published_at,
            "quality": "valid",
            "extra": {
                "original_unit": original_unit,
                "display_unit": rule["display_unit"],
                "dimension_key": rule["dimension_key"],
                "multiplier_to_storage": float(rule["multiplier_to_storage"]),
                "source_type": indicator.source,
                "period_type": period_type,
                "publication_lag_days": lag_days,
            },
        }
        fact, _ = MacroFactModel.objects.update_or_create(
            indicator_code=indicator.code,
            reporting_period=indicator.reporting_period,
            source=indicator.source,
            revision_number=revision_number,
            defaults=defaults,
        )
        return _fact_to_entity(fact)

    def save_indicators_batch(
        self,
        indicators: list[MacroIndicator],
        revision_number: int = 1,
    ) -> list[MacroIndicator]:
        with transaction.atomic():
            return [
                self.save_indicator(indicator, revision_number=revision_number)
                for indicator in indicators
            ]

    def get_by_code_and_date(
        self,
        code: str,
        observed_at: date,
        revision_number: int | None = None,
    ) -> MacroIndicator | None:
        queryset = MacroFactModel.objects.filter(
            indicator_code=code,
            reporting_period=observed_at,
        )
        if revision_number is not None:
            queryset = queryset.filter(revision_number=revision_number)
        else:
            queryset = queryset.order_by("-revision_number", "-id")
        fact = queryset.first()
        return _fact_to_entity(fact) if fact else None

    def get_series(
        self,
        code: str,
        start_date: date | None = None,
        end_date: date | None = None,
        use_pit: bool = False,
        source: str | None = None,
    ) -> list[MacroIndicator]:
        queryset = MacroFactModel.objects.filter(indicator_code=code)
        if start_date:
            queryset = queryset.filter(reporting_period__gte=start_date)
        if end_date:
            queryset = queryset.filter(reporting_period__lte=end_date)
        if source:
            queryset = queryset.filter(source=source)
        if use_pit:
            # data_center facts are already revision-aware; keep latest revision per period.
            rows: list[MacroIndicator] = []
            seen_periods: set[date] = set()
            for fact in queryset.order_by("-reporting_period", "-revision_number", "-id"):
                if fact.reporting_period in seen_periods:
                    continue
                seen_periods.add(fact.reporting_period)
                rows.append(_fact_to_entity(fact))
            return list(reversed(rows))
        return [_fact_to_entity(fact) for fact in queryset.order_by("reporting_period", "revision_number")]

    def get_latest_observation_date(
        self,
        code: str,
        as_of_date: date | None = None,
    ) -> date | None:
        queryset = MacroFactModel.objects.filter(indicator_code=code)
        if as_of_date:
            queryset = queryset.filter(published_at__lte=as_of_date)
        fact = queryset.order_by("-reporting_period", "-revision_number").first()
        return fact.reporting_period if fact else None

    def get_latest_observation(
        self,
        code: str,
        before_date: date | None = None,
    ) -> MacroIndicator | None:
        queryset = MacroFactModel.objects.filter(indicator_code=code)
        if before_date:
            queryset = queryset.filter(reporting_period__lt=before_date)
        fact = queryset.order_by("-reporting_period", "-revision_number").first()
        return _fact_to_entity(fact) if fact else None

    def get_available_dates(
        self,
        codes: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[date]:
        queryset = MacroFactModel.objects.all()
        if codes:
            queryset = queryset.filter(indicator_code__in=codes)
        if start_date:
            queryset = queryset.filter(reporting_period__gte=start_date)
        if end_date:
            queryset = queryset.filter(reporting_period__lte=end_date)
        return list(
            queryset.values_list("reporting_period", flat=True).distinct().order_by("reporting_period")
        )

    def delete_indicator(
        self,
        code: str,
        observed_at: date,
        revision_number: int | None = None,
    ) -> bool:
        queryset = MacroFactModel.objects.filter(
            indicator_code=code,
            reporting_period=observed_at,
        )
        if revision_number is not None:
            queryset = queryset.filter(revision_number=revision_number)
        deleted_count, _ = queryset.delete()
        return deleted_count > 0

    def get_indicator_count(self, code: str | None = None) -> int:
        queryset = MacroFactModel.objects.all()
        if code:
            queryset = queryset.filter(indicator_code=code)
        return queryset.count()

    def delete_by_conditions(
        self,
        indicator_code: str | None = None,
        source: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> int:
        queryset = MacroFactModel.objects.all()
        if indicator_code:
            queryset = queryset.filter(indicator_code=indicator_code)
        if source:
            queryset = queryset.filter(source=source)
        if start_date:
            queryset = queryset.filter(reporting_period__gte=start_date)
        if end_date:
            queryset = queryset.filter(reporting_period__lte=end_date)
        deleted_count, _ = queryset.delete()
        return deleted_count

    def get_record_by_id(self, record_id: int) -> dict[str, Any] | None:
        fact = MacroFactModel.objects.filter(id=record_id).first()
        if fact is None:
            return None
        return _serialize_fact_row(fact)

    def create_record(
        self,
        *,
        code: str,
        value: float,
        reporting_period: date,
        period_type: str = "D",
        published_at: date | None = None,
        source: str = "manual",
        revision_number: int = 1,
    ) -> dict[str, Any]:
        rule = _resolve_indicator_unit_rule(code, source_type=source)
        original_unit = str(rule["original_unit"] or "")
        storage_value = float(value) * float(rule["multiplier_to_storage"])
        storage_unit = str(rule["storage_unit"] or "")
        lag_days = max((published_at - reporting_period).days, 0) if published_at else 0
        fact = MacroFactModel.objects.create(
            indicator_code=code,
            value=storage_value,
            unit=storage_unit,
            source=source,
            reporting_period=reporting_period,
            revision_number=revision_number,
            published_at=published_at,
            quality="valid",
            extra={
                "original_unit": original_unit,
                "display_unit": rule["display_unit"],
                "dimension_key": rule["dimension_key"],
                "multiplier_to_storage": float(rule["multiplier_to_storage"]),
                "source_type": source,
                "period_type": period_type,
                "publication_lag_days": lag_days,
            },
        )
        return _serialize_fact_row(fact)

    def update_record(self, record_id: int, **updates: Any) -> dict[str, Any] | None:
        fact = MacroFactModel.objects.filter(id=record_id).first()
        if fact is None:
            return None

        next_code = str(updates.get("code", fact.indicator_code))
        next_source = str(updates.get("source", fact.source))
        next_period_type = str(
            updates.get("period_type")
            or (fact.extra or {}).get("period_type")
            or _resolve_period_type(fact)
        )
        next_published_at = updates.get("published_at", fact.published_at)

        if any(field in updates for field in ("value", "code", "source")):
            current_extra = dict(fact.extra or {})
            next_original_unit = str(current_extra.get("original_unit") or "")
            if "original_unit" in updates and updates["original_unit"] is not None:
                next_original_unit = str(updates["original_unit"])
            rule = _resolve_indicator_unit_rule(
                next_code,
                source_type=next_source,
                original_unit=next_original_unit or None,
            )
            next_original_unit = str(rule["original_unit"] or next_original_unit)
            next_value = float(updates.get("value", _safe_float(fact.value)))
            fact.value = next_value * float(rule["multiplier_to_storage"])
            fact.unit = str(rule["storage_unit"] or "")
            extra = dict(fact.extra or {})
            extra["original_unit"] = next_original_unit
            extra["display_unit"] = rule["display_unit"]
            extra["dimension_key"] = rule["dimension_key"]
            extra["multiplier_to_storage"] = float(rule["multiplier_to_storage"])
            extra["source_type"] = next_source
            extra["period_type"] = next_period_type
            extra["publication_lag_days"] = (
                max((next_published_at - updates.get("reporting_period", fact.reporting_period)).days, 0)
                if next_published_at
                else 0
            )
            fact.extra = extra

        if "code" in updates:
            fact.indicator_code = next_code
        if "reporting_period" in updates:
            fact.reporting_period = updates["reporting_period"]
        if "source" in updates:
            fact.source = next_source
        if "revision_number" in updates and updates["revision_number"] is not None:
            fact.revision_number = int(updates["revision_number"])
        if "published_at" in updates:
            fact.published_at = next_published_at
        if "period_type" in updates:
            extra = dict(fact.extra or {})
            extra["period_type"] = next_period_type
            extra["publication_lag_days"] = (
                max((fact.published_at - fact.reporting_period).days, 0)
                if fact.published_at
                else 0
            )
            fact.extra = extra

        fact.save()
        fact.refresh_from_db()
        return _serialize_fact_row(fact)

    def delete_record_by_id(self, record_id: int) -> bool:
        deleted_count, _ = MacroFactModel.objects.filter(id=record_id).delete()
        return deleted_count > 0

    def delete_records_by_ids(self, record_ids: list[int]) -> int:
        deleted_count, _ = MacroFactModel.objects.filter(id__in=record_ids).delete()
        return deleted_count

    def count_records_before_date(self, cutoff_date: date) -> int:
        return MacroFactModel.objects.filter(reporting_period__lt=cutoff_date).count()

    def get_statistics(self) -> dict[str, Any]:
        aggregates = MacroFactModel.objects.aggregate(
            latest=Max("reporting_period"),
            total_records=Count("id"),
        )
        source_stats = []
        for row in (
            MacroFactModel.objects.values("source")
            .annotate(record_count=Count("id"), last_sync=Max("reporting_period"))
            .order_by("-record_count", "source")
        ):
            source_stats.append(
                {
                    "name": row["source"],
                    "type": row["source"],
                    "priority": 0,
                    "is_active": True,
                    "last_sync": row["last_sync"],
                    "record_count": row["record_count"],
                }
            )
        return {
            "total_indicators": MacroFactModel.objects.values("indicator_code").distinct().count(),
            "total_records": aggregates["total_records"] or 0,
            "latest_date": aggregates["latest"],
            "sources": source_stats,
        }

    def get_recent_syncs(self, limit: int = 10) -> list[dict[str, Any]]:
        audits = list(
            RawAuditModel.objects.filter(capability="macro")
            .order_by("-fetched_at")[:limit]
            .values("request_params", "provider_name", "fetched_at", "status")
        )
        if audits:
            return [
                {
                    "indicator": (row["request_params"] or {}).get("indicator_code", ""),
                    "source": row["provider_name"],
                    "sync_time": row["fetched_at"],
                    "status": row["status"],
                }
                for row in audits
            ]

        recent_facts = MacroFactModel.objects.order_by("-fetched_at")[:limit]
        return [
            {
                "indicator": fact.indicator_code,
                "source": fact.source,
                "sync_time": fact.published_at or fact.reporting_period,
                "status": "success",
            }
            for fact in recent_facts
        ]


class MacroIndicatorReadRepository:
    """Compatibility read repository backed by data_center macro facts."""

    def get_indicator_unit_config(
        self,
        indicator_code: str,
        source: str | None = None,
    ) -> dict | None:
        return _get_indicator_unit_rule(indicator_code, source_type=source)

    def list_distinct_codes(self) -> list[str]:
        return list(
            MacroFactModel._default_manager.values_list("indicator_code", flat=True)
            .distinct()
            .order_by("indicator_code")
        )

    def get_storage_summary(self) -> dict[str, Any]:
        queryset = MacroFactModel._default_manager.all()
        aggregates = queryset.aggregate(
            latest_date=Max("reporting_period"),
            min_date=Min("reporting_period"),
            max_date=Max("reporting_period"),
        )
        return {
            "total_indicators": queryset.values("indicator_code").distinct().count(),
            "total_records": queryset.count(),
            "latest_date": aggregates["latest_date"],
            "min_date": aggregates["min_date"],
            "max_date": aggregates["max_date"],
        }

    def list_indicator_rollups(self) -> list[dict[str, Any]]:
        return [
            {
                "code": row["indicator_code"],
                "count": row["count"],
                "latest": row["latest"],
            }
            for row in (
                MacroFactModel._default_manager.values("indicator_code")
                .annotate(count=Count("id"), latest=Max("reporting_period"))
                .order_by("indicator_code")
            )
        ]

    def list_source_rollups(self) -> list[dict[str, Any]]:
        return [
            {
                "source": row["source"],
                "count": row["count"],
            }
            for row in (
                MacroFactModel._default_manager.values("source")
                .annotate(count=Count("id"))
                .order_by("-count", "source")
            )
        ]

    def _build_serialized_rows(
        self,
        *,
        code: str | None = None,
        code_filter: str = "",
        source_filter: str = "",
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        queryset = MacroFactModel._default_manager.all()
        if code:
            queryset = queryset.filter(indicator_code=code)
        if code_filter:
            queryset = queryset.filter(indicator_code__icontains=code_filter)
        if source_filter:
            queryset = queryset.filter(source=source_filter)
        if start_date:
            queryset = queryset.filter(reporting_period__gte=start_date)
        if end_date:
            queryset = queryset.filter(reporting_period__lte=end_date)

        code_set = list(queryset.values_list("indicator_code", flat=True).distinct())
        catalogs = {
            item.code: item
            for item in IndicatorCatalogModel.objects.filter(code__in=code_set)
        }
        return [_serialize_fact_row(fact, catalogs.get(fact.indicator_code)) for fact in queryset]

    def get_indicator_rows(
        self,
        *,
        code: str,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int | None = None,
        ascending: bool = True,
    ) -> list[dict[str, Any]]:
        rows = self._build_serialized_rows(
            code=code,
            start_date=start_date,
            end_date=end_date,
        )
        rows = _sort_rows(rows, "reporting_period" if ascending else "-reporting_period")
        if ascending:
            rows = sorted(rows, key=lambda row: (row["reporting_period"], row["revision_number"]))
        else:
            rows = sorted(
                rows,
                key=lambda row: (row["reporting_period"], row["revision_number"]),
                reverse=True,
            )
        if limit is not None:
            rows = rows[:limit]
        return rows

    def count_table_rows(
        self,
        *,
        code_filter: str = "",
        source_filter: str = "",
        period_type_filter: str = "",
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> int:
        rows = self._build_serialized_rows(
            code_filter=code_filter,
            source_filter=source_filter,
            start_date=start_date,
            end_date=end_date,
        )
        return len(_apply_period_type_filter(rows, period_type_filter))

    def get_table_rows(
        self,
        *,
        code_filter: str = "",
        source_filter: str = "",
        period_type_filter: str = "",
        start_date: date | None = None,
        end_date: date | None = None,
        sort_field: str = "-reporting_period",
        offset: int = 0,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        rows = self._build_serialized_rows(
            code_filter=code_filter,
            source_filter=source_filter,
            start_date=start_date,
            end_date=end_date,
        )
        rows = _apply_period_type_filter(rows, period_type_filter)
        rows = _sort_rows(rows, sort_field)
        return rows[offset : offset + limit]

    def get_latest_indicator(self, code: str) -> dict[str, Any] | None:
        fact = (
            MacroFactModel._default_manager.filter(indicator_code=code)
            .order_by("-reporting_period", "-revision_number", "-id")
            .first()
        )
        if fact is None:
            return None
        return _serialize_fact_row(fact)

    def get_indicator_stats(self, code: str, start_date: date) -> dict[str, float | None]:
        stats = (
            MacroFactModel._default_manager.filter(
                indicator_code=code,
                reporting_period__gte=start_date,
            ).aggregate(
                avg_value=Avg("value"),
                max_value=Max("value"),
                min_value=Min("value"),
            )
        )
        return {
            "avg_value": float(stats["avg_value"]) if stats["avg_value"] is not None else None,
            "max_value": float(stats["max_value"]) if stats["max_value"] is not None else None,
            "min_value": float(stats["min_value"]) if stats["min_value"] is not None else None,
        }

    def get_indicator_history(
        self,
        code: str,
        *,
        start_date: date,
        end_date: date,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows = self.get_indicator_rows(
            code=code,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            ascending=False,
        )
        return [
            {
                "value": row["value"],
                "unit": row["unit"],
                "original_unit": row["original_unit"],
                "reporting_period": row["reporting_period"],
                "period_type": row["period_type"],
            }
            for row in rows
        ]

    def get_latest_values_by_codes(self, codes: list[str]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for code in codes:
            latest = self.get_latest_indicator(code)
            if latest is None:
                continue
            rows.append({"code": code, "value": latest["value"]})
        return rows
