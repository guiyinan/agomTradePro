"""Canonical macro compatibility projections owned by Data Center.

This repository contains the remaining administrative/read projection helpers
that were historically implemented in ``apps.macro``.  It is intentionally
Data Center-owned: the macro app receives only domain objects and serialized
DTOs through application ports.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from django.db.models import Avg, Count, Max, Min
from django.utils import timezone

from apps.data_center.domain.entities import MacroFact
from apps.data_center.infrastructure.macro_fact_repositories import MacroFactRepository
from apps.data_center.infrastructure.models import (
    IndicatorUnitRuleModel,
    MacroFactModel,
    RawAuditModel,
)
from shared.numeric import safe_float


def _period_display(value: str) -> str:
    """Return a stable human-readable period label."""

    return {
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
    }.get(value, value)


def _unit_rule(
    code: str,
    *,
    source: str | None = None,
    original_unit: str | None = None,
) -> dict[str, Any] | None:
    """Resolve one active unit rule through the canonical catalog."""

    queryset = IndicatorUnitRuleModel._default_manager.filter(
        indicator_code=code,
        is_active=True,
    )
    if original_unit is not None:
        queryset = queryset.filter(original_unit=original_unit)
    if source:
        row = queryset.filter(source_type=source).values().first()
        if row:
            return dict(row)
    row = queryset.filter(source_type="").values().first()
    return dict(row) if row else None


def _serialize(model: MacroFactModel) -> dict[str, Any]:
    """Serialize one canonical macro fact without replacing missing values."""

    extra = dict(model.extra or {})
    period_type = str(extra.get("period_type") or "M")
    original_unit = str(extra.get("original_unit") or model.unit or "")
    display_unit = str(extra.get("display_unit") or original_unit)
    multiplier = safe_float(extra.get("multiplier_to_storage"), default=1.0)
    value = safe_float(model.value)
    if value is None:
        raise ValueError(f"Macro fact {model.pk} has a non-finite canonical value")
    return {
        "id": model.id,
        "code": model.indicator_code,
        "value": value,
        "unit": model.unit,
        "display_value": value / multiplier if multiplier else value,
        "display_unit": display_unit,
        "original_unit": original_unit,
        "dimension_key": extra.get("dimension_key", ""),
        "multiplier_to_storage": multiplier,
        "reporting_period": model.reporting_period,
        "period_type": period_type,
        "period_type_display": _period_display(period_type),
        "observed_at": model.reporting_period,
        "published_at": model.published_at,
        "source": model.source,
        "revision_number": model.revision_number,
        "publication_lag_days": int(extra.get("publication_lag_days", 0) or 0),
    }


class MacroProjectionRepository:
    """Data Center-owned macro facts and compatibility read projections."""

    GROWTH_INDICATORS = {
        "PMI": "CN_PMI",
        "工业增加值": "CN_VALUE_ADDED",
        "社会消费品零售": "CN_RETAIL_SALES",
    }
    INFLATION_INDICATORS = {
        "CPI": "CN_CPI_NATIONAL_YOY",
        "PPI": "CN_PPI",
        "GDP平减指数": "CN_GDP_DEFLATOR",
    }

    def __init__(self) -> None:
        self._facts = MacroFactRepository()

    def save_indicator(self, fact: MacroFact) -> MacroFact:
        """Persist one validated canonical fact."""

        self._facts.bulk_upsert([fact])
        latest = self._facts.get_latest(fact.indicator_code)
        return latest or fact

    def save_indicators_batch(self, facts: list[MacroFact]) -> list[MacroFact]:
        """Persist a validated canonical batch and return latest rows."""

        self._facts.bulk_upsert(facts)
        return [self._facts.get_latest(fact.indicator_code) or fact for fact in facts]

    def get_series(
        self,
        code: str,
        start_date: date | None = None,
        end_date: date | None = None,
        use_pit: bool = False,
        source: str | None = None,
    ) -> list[MacroFact]:
        """Read a governed canonical series."""

        if not isinstance(use_pit, bool):
            raise ValueError("use_pit must be a boolean")
        if use_pit and end_date is None:
            raise ValueError("end_date is required when use_pit is enabled")
        facts = self._facts.get_series(
            code,
            start=start_date,
            end=end_date,
            use_pit=use_pit,
        )
        if use_pit and end_date is not None:
            # A point-in-time decision view cannot use facts whose release
            # timestamp is unknown; historical reporting dates are not
            # evidence that the observation was available at the boundary.
            facts = [
                fact
                for fact in facts
                if fact.published_at is not None and fact.published_at <= end_date
            ]
        selected = [fact for fact in facts if source is None or fact.source == source]
        return sorted(selected, key=lambda fact: (fact.reporting_period, fact.revision_number))

    def get_latest_observation_date(self, code: str, as_of_date: date | None = None) -> date | None:
        """Return latest governed observation date."""

        series = self.get_series(code, end_date=as_of_date, use_pit=as_of_date is not None)
        return series[-1].reporting_period if series else None

    def get_latest_observation(self, code: str, before_date: date | None = None) -> MacroFact | None:
        """Return latest governed fact before an optional boundary."""

        series = self.get_series(code, end_date=before_date)
        if before_date is not None:
            series = [item for item in series if item.reporting_period < before_date]
        return series[-1] if series else None

    def get_available_dates(
        self,
        codes: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[date]:
        """Return distinct canonical reporting periods."""

        queryset = MacroFactModel._default_manager.all()
        if codes:
            queryset = queryset.filter(indicator_code__in=codes)
        if start_date:
            queryset = queryset.filter(reporting_period__gte=start_date)
        if end_date:
            queryset = queryset.filter(reporting_period__lte=end_date)
        return list(queryset.values_list("reporting_period", flat=True).distinct().order_by("reporting_period"))

    def delete_indicator(self, code: str, observed_at: date, revision_number: int | None = None) -> bool:
        """Delete facts for one governed natural-key scope."""

        queryset = MacroFactModel._default_manager.filter(
            indicator_code=code,
            reporting_period=observed_at,
        )
        if revision_number is not None:
            queryset = queryset.filter(revision_number=revision_number)
        count, _ = queryset.delete()
        return count > 0

    def get_indicator_count(self, code: str | None = None) -> int:
        """Return canonical fact row count."""

        queryset = MacroFactModel._default_manager.all()
        return queryset.filter(indicator_code=code).count() if code else queryset.count()

    def delete_by_conditions(
        self,
        indicator_code: str | None = None,
        source: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> int:
        """Delete facts matching an explicit administrative scope."""

        queryset = MacroFactModel._default_manager.all()
        if indicator_code:
            queryset = queryset.filter(indicator_code=indicator_code)
        if source:
            queryset = queryset.filter(source=source)
        if start_date:
            queryset = queryset.filter(reporting_period__gte=start_date)
        if end_date:
            queryset = queryset.filter(reporting_period__lte=end_date)
        count, _ = queryset.delete()
        return count

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
        """Create one administrative row using the active unit rule."""

        rule = _unit_rule(code, source=source)
        if rule is None:
            raise ValueError(f"Indicator unit rule missing for {code}@{source}")
        multiplier = float(rule.get("multiplier_to_storage") or 1.0)
        extra = {
            "original_unit": str(rule.get("original_unit") or ""),
            "display_unit": str(rule.get("display_unit") or ""),
            "dimension_key": str(rule.get("dimension_key") or ""),
            "multiplier_to_storage": multiplier,
            "matched_rule_id": rule.get("id"),
            "source_type": source,
            "period_type": period_type,
            "publication_lag_days": max((published_at - reporting_period).days, 0) if published_at else 0,
        }
        model = MacroFactModel._default_manager.create(
            indicator_code=code,
            value=float(value) * multiplier,
            unit=str(rule.get("storage_unit") or ""),
            source=source,
            reporting_period=reporting_period,
            revision_number=revision_number,
            published_at=published_at,
            quality="valid",
            fetched_at=timezone.now(),
            extra=extra,
        )
        return _serialize(model)

    def get_record_by_id(self, record_id: int) -> dict[str, Any] | None:
        """Return one serialized fact row."""

        model = MacroFactModel._default_manager.filter(id=record_id).first()
        return _serialize(model) if model is not None else None

    def update_record(self, record_id: int, **updates: Any) -> dict[str, Any] | None:
        """Update mutable administrative fields and retain evidence metadata."""

        model = MacroFactModel._default_manager.filter(id=record_id).first()
        if model is None:
            return None
        for field_name in ("indicator_code", "source", "reporting_period", "published_at", "revision_number"):
            if field_name in updates:
                setattr(model, field_name, updates[field_name])
        if "value" in updates:
            model.value = float(updates["value"])
        if "period_type" in updates:
            extra = dict(model.extra or {})
            extra["period_type"] = str(updates["period_type"])
            model.extra = extra
        model.save()
        model.refresh_from_db()
        return _serialize(model)

    def delete_record_by_id(self, record_id: int) -> bool:
        """Delete one row by primary key."""

        count, _ = MacroFactModel._default_manager.filter(id=record_id).delete()
        return count > 0

    def delete_records_by_ids(self, record_ids: list[int]) -> int:
        """Delete a bounded set of rows."""

        count, _ = MacroFactModel._default_manager.filter(id__in=record_ids).delete()
        return count

    def count_records_before_date(self, cutoff_date: date) -> int:
        """Count rows older than a retention boundary."""

        return MacroFactModel._default_manager.filter(reporting_period__lt=cutoff_date).count()

    def get_statistics(self) -> dict[str, Any]:
        """Return canonical macro storage and source statistics."""

        aggregate = MacroFactModel._default_manager.aggregate(
            latest=Max("reporting_period"),
            total_records=Count("id"),
        )
        sources = [
            {
                "name": row["source"],
                "type": row["source"],
                "priority": 0,
                "is_active": True,
                "last_sync": row["last_sync"],
                "record_count": row["record_count"],
            }
            for row in MacroFactModel._default_manager.values("source")
            .annotate(record_count=Count("id"), last_sync=Max("reporting_period"))
            .order_by("-record_count", "source")
        ]
        return {
            "total_indicators": MacroFactModel._default_manager.values("indicator_code").distinct().count(),
            "total_records": aggregate["total_records"] or 0,
            "latest_date": aggregate["latest"],
            "sources": sources,
        }

    def get_recent_syncs(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return raw audit-backed sync summaries."""

        audits = list(
            RawAuditModel._default_manager.filter(capability="macro")
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
        return [
            {
                "indicator": model.indicator_code,
                "source": model.source,
                "sync_time": model.published_at or model.reporting_period,
                "status": "success",
            }
            for model in MacroFactModel._default_manager.order_by("-fetched_at")[:limit]
        ]

    def get_indicator_unit_config(self, indicator_code: str, source: str | None = None) -> dict[str, Any] | None:
        """Return one active unit rule."""

        return _unit_rule(indicator_code, source=source)

    def _rows(self, *, code: str | None = None, code_filter: str = "", source_filter: str = "", start_date: date | None = None, end_date: date | None = None) -> list[dict[str, Any]]:
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
        return [_serialize(model) for model in queryset.order_by("reporting_period", "id")]

    def list_distinct_codes(self) -> list[str]:
        """Return distinct canonical indicator codes."""

        return list(MacroFactModel._default_manager.values_list("indicator_code", flat=True).distinct().order_by("indicator_code"))

    def get_storage_summary(self) -> dict[str, Any]:
        """Return canonical macro storage bounds."""

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
        """Return per-indicator row counts and latest dates."""

        return [
            {"code": row["indicator_code"], "count": row["count"], "latest": row["latest"]}
            for row in MacroFactModel._default_manager.values("indicator_code")
            .annotate(count=Count("id"), latest=Max("reporting_period"))
            .order_by("indicator_code")
        ]

    def list_source_rollups(self) -> list[dict[str, Any]]:
        """Return per-source row counts."""

        return [
            {"source": row["source"], "count": row["count"]}
            for row in MacroFactModel._default_manager.values("source")
            .annotate(count=Count("id"))
            .order_by("-count", "source")
        ]

    def get_indicator_rows(self, *, code: str, start_date: date | None = None, end_date: date | None = None, limit: int | None = None, ascending: bool = True) -> list[dict[str, Any]]:
        """Return serialized rows for one indicator."""

        rows = self._rows(code=code, start_date=start_date, end_date=end_date)
        rows.sort(key=lambda row: (row["reporting_period"], row["revision_number"]), reverse=not ascending)
        return rows[:limit] if limit is not None else rows

    def count_table_rows(self, *, code_filter: str = "", source_filter: str = "", period_type_filter: str = "", start_date: date | None = None, end_date: date | None = None) -> int:
        """Count rows matching table filters."""

        rows = self._rows(code_filter=code_filter, source_filter=source_filter, start_date=start_date, end_date=end_date)
        if period_type_filter:
            rows = [row for row in rows if row["period_type"] == period_type_filter]
        return len(rows)

    def get_table_rows(self, *, code_filter: str = "", source_filter: str = "", period_type_filter: str = "", start_date: date | None = None, end_date: date | None = None, sort_field: str = "-reporting_period", offset: int = 0, limit: int = 50) -> list[dict[str, Any]]:
        """Return a bounded filtered table projection."""

        rows = self._rows(code_filter=code_filter, source_filter=source_filter, start_date=start_date, end_date=end_date)
        if period_type_filter:
            rows = [row for row in rows if row["period_type"] == period_type_filter]
        reverse = sort_field.startswith("-")
        key = sort_field[1:] if reverse else sort_field
        rows.sort(key=lambda row: (row.get(key) is None, row.get(key)), reverse=reverse)
        return rows[offset : offset + limit]

    def get_latest_indicator(self, code: str) -> dict[str, Any] | None:
        """Return the newest serialized row for a code."""

        rows = self.get_indicator_rows(code=code, ascending=False, limit=1)
        return rows[0] if rows else None

    def get_indicator_stats(self, code: str, start_date: date) -> dict[str, float | None]:
        """Return aggregate values for one indicator."""

        stats = MacroFactModel._default_manager.filter(
            indicator_code=code,
            reporting_period__gte=start_date,
        ).aggregate(avg_value=Avg("value"), max_value=Max("value"), min_value=Min("value"))
        return {
            "avg_value": float(stats["avg_value"]) if stats["avg_value"] is not None else None,
            "max_value": float(stats["max_value"]) if stats["max_value"] is not None else None,
            "min_value": float(stats["min_value"]) if stats["min_value"] is not None else None,
        }

    def get_indicator_history(self, code: str, *, start_date: date, end_date: date, limit: int) -> list[dict[str, Any]]:
        """Return compact history records for one indicator."""

        rows = self.get_indicator_rows(code=code, start_date=start_date, end_date=end_date, limit=limit, ascending=False)
        return [
            {key: row[key] for key in ("value", "unit", "original_unit", "reporting_period", "period_type")}
            for row in rows
        ]

    def get_latest_values_by_codes(self, codes: list[str]) -> list[dict[str, Any]]:
        """Return latest values for each requested code."""

        return [
            {"code": code, "value": latest["value"]}
            for code in codes
            if (latest := self.get_latest_indicator(code)) is not None
        ]


__all__ = ["MacroProjectionRepository"]
