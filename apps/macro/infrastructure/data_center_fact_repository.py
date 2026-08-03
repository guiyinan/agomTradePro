"""Macro-domain compatibility facade over Data Center Application ports.

The macro app owns the ``MacroIndicator`` projection and analytical aliases,
but it no longer imports Data Center ORM models.  Persistence, unit-rule
resolution and administrative projections are owned by Data Center and are
reached through the stable public port.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from apps.data_center.application.public import (
    MacroProjectionRepositoryProtocol,
    get_macro_projection_repository_port,
)
from apps.data_center.domain.entities import MacroFact as CanonicalMacroFact
from apps.macro.domain.entities import MacroIndicator, PeriodType


def _repository() -> MacroProjectionRepositoryProtocol:
    """Return the typed Data Center Application Public Port."""

    return get_macro_projection_repository_port()


def _to_indicator(fact: CanonicalMacroFact) -> MacroIndicator:
    """Convert a canonical macro fact to the macro-domain projection."""

    period_value = str((fact.extra or {}).get("period_type") or "D")
    try:
        period_type = PeriodType(period_value)
    except ValueError:
        period_type = PeriodType.DAY
    original_unit = str((fact.extra or {}).get("original_unit") or fact.unit or "")
    return MacroIndicator(
        code=fact.indicator_code,
        value=float(fact.value),
        reporting_period=fact.reporting_period,
        period_type=period_type,
        unit=fact.unit,
        original_unit=original_unit,
        published_at=fact.published_at,
        source=fact.source,
    )


class DataCenterMacroRepository:
    """Backward-compatible macro repository backed exclusively by Data Center."""

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

    def save_indicator(
        self,
        indicator: MacroIndicator,
        revision_number: int = 1,
        period_type_override: str | None = None,
    ) -> MacroIndicator:
        """Normalize and save one macro indicator through the canonical port."""

        rule = _repository().get_indicator_unit_config(indicator.code, indicator.source)
        if rule is None:
            raise ValueError(f"Indicator unit rule missing for {indicator.code}@{indicator.source}")
        period_type = period_type_override or indicator.period_type.value
        multiplier = float(rule.get("multiplier_to_storage") or 1.0)
        original_unit = indicator.original_unit or indicator.unit
        published_at = indicator.published_at
        extra = {
            "original_unit": original_unit,
            "display_unit": str(rule.get("display_unit") or indicator.unit),
            "dimension_key": str(rule.get("dimension_key") or ""),
            "multiplier_to_storage": multiplier,
            "matched_rule_id": rule.get("id"),
            "source_type": indicator.source,
            "period_type": period_type,
            "publication_lag_days": (
                max((published_at - indicator.reporting_period).days, 0) if published_at else 0
            ),
        }
        fact = CanonicalMacroFact(
            indicator_code=indicator.code,
            reporting_period=indicator.reporting_period,
            value=float(indicator.value) * multiplier,
            unit=str(rule.get("storage_unit") or indicator.unit),
            source=indicator.source,
            revision_number=revision_number,
            published_at=published_at,
            extra=extra,
        )
        return _to_indicator(_repository().save_indicator(fact))

    def save_indicators_batch(
        self,
        indicators: list[MacroIndicator],
        revision_number: int = 1,
    ) -> list[MacroIndicator]:
        """Save a batch while retaining the historical return shape."""

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
        """Read one canonical observation by natural key."""

        facts = _repository().get_series(code, end_date=observed_at)
        candidates = [fact for fact in facts if fact.reporting_period == observed_at]
        if revision_number is not None:
            candidates = [fact for fact in candidates if fact.revision_number == revision_number]
        return _to_indicator(candidates[-1]) if candidates else None

    def get_series(
        self,
        code: str,
        start_date: date | None = None,
        end_date: date | None = None,
        use_pit: bool = False,
        source: str | None = None,
    ) -> list[MacroIndicator]:
        """Read a governed canonical series."""

        return [
            _to_indicator(fact)
            for fact in _repository().get_series(
                code,
                start_date=start_date,
                end_date=end_date,
                use_pit=use_pit,
                source=source,
            )
        ]

    @staticmethod
    def _normalize_cpi_value(code: str, value: float) -> float:
        """Normalize the legacy CPI index representation."""

        return float(value) - 100.0 if code == "CN_CPI" else float(value)

    def get_growth_series(
        self,
        indicator_code: str = "PMI",
        start_date: date | None = None,
        end_date: date | None = None,
        use_pit: bool = False,
        source: str | None = None,
    ) -> list[float]:
        """Return values for a growth indicator alias."""

        return [
            indicator.value
            for indicator in self.get_growth_series_full(
                indicator_code, start_date, end_date, use_pit, source
            )
        ]

    def get_growth_series_full(
        self,
        indicator_code: str = "PMI",
        start_date: date | None = None,
        end_date: date | None = None,
        use_pit: bool = False,
        source: str | None = None,
    ) -> list[MacroIndicator]:
        """Return the full canonical growth series."""

        return self.get_series(
            self.GROWTH_INDICATORS.get(indicator_code, indicator_code),
            start_date,
            end_date,
            use_pit,
            source,
        )

    def get_inflation_series(
        self,
        indicator_code: str = "CPI",
        start_date: date | None = None,
        end_date: date | None = None,
        use_pit: bool = False,
        source: str | None = None,
    ) -> list[float]:
        """Return inflation values for an alias."""

        return [
            self._normalize_cpi_value(indicator.code, indicator.value)
            for indicator in self.get_inflation_series_full(
                indicator_code, start_date, end_date, use_pit, source
            )
        ]

    def get_inflation_series_full(
        self,
        indicator_code: str = "CPI",
        start_date: date | None = None,
        end_date: date | None = None,
        use_pit: bool = False,
        source: str | None = None,
    ) -> list[MacroIndicator]:
        """Return the full canonical inflation series with legacy CPI fallback."""

        code = self.INFLATION_INDICATORS.get(indicator_code, indicator_code)
        indicators = self.get_series(code, start_date, end_date, use_pit, source)
        if indicator_code == "CPI" and not indicators and code == "CN_CPI_NATIONAL_YOY":
            indicators = self.get_series("CN_CPI", start_date, end_date, use_pit, source)
        return indicators

    def get_latest_observation_date(self, code: str, as_of_date: date | None = None) -> date | None:
        """Return the newest observed date."""

        return _repository().get_latest_observation_date(code, as_of_date)

    def get_latest_observation(
        self, code: str, before_date: date | None = None
    ) -> MacroIndicator | None:
        """Return the newest observation before an optional boundary."""

        fact = _repository().get_latest_observation(code, before_date)
        return _to_indicator(fact) if fact is not None else None

    def get_available_dates(
        self,
        codes: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[date]:
        """Return distinct available reporting periods."""

        return _repository().get_available_dates(codes, start_date, end_date)

    def delete_indicator(
        self, code: str, observed_at: date, revision_number: int | None = None
    ) -> bool:
        """Delete one natural-key scope through the canonical owner."""

        return _repository().delete_indicator(code, observed_at, revision_number)

    def get_indicator_count(self, code: str | None = None) -> int:
        """Return canonical row count."""

        return _repository().get_indicator_count(code)

    def delete_by_conditions(
        self,
        indicator_code: str | None = None,
        source: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> int:
        """Delete an explicitly bounded administrative scope."""

        return _repository().delete_by_conditions(indicator_code, source, start_date, end_date)

    def get_record_by_id(self, record_id: int) -> dict[str, Any] | None:
        """Return one serialized canonical row."""

        return _repository().get_record_by_id(record_id)

    def create_record(self, **kwargs: Any) -> dict[str, Any]:
        """Create one administrative canonical row."""

        return _repository().create_record(**kwargs)

    def update_record(self, record_id: int, **updates: Any) -> dict[str, Any] | None:
        """Update one administrative canonical row."""

        return _repository().update_record(record_id, **updates)

    def delete_record_by_id(self, record_id: int) -> bool:
        """Delete one row by primary key."""

        return _repository().delete_record_by_id(record_id)

    def delete_records_by_ids(self, record_ids: list[int]) -> int:
        """Delete a bounded set of rows."""

        return _repository().delete_records_by_ids(record_ids)

    def count_records_before_date(self, cutoff_date: date) -> int:
        """Count rows before a retention boundary."""

        return _repository().count_records_before_date(cutoff_date)

    def get_statistics(self) -> dict[str, Any]:
        """Return canonical macro statistics."""

        return _repository().get_statistics()

    def get_recent_syncs(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return recent canonical sync evidence."""

        return _repository().get_recent_syncs(limit)

    def get_indicator_unit_config(
        self, indicator_code: str, source: str | None = None
    ) -> dict[str, Any] | None:
        """Return the active unit rule for a code/source pair."""

        return _repository().get_indicator_unit_config(indicator_code, source)

    def list_distinct_codes(self) -> list[str]:
        """Return all canonical indicator codes."""

        return _repository().list_distinct_codes()

    def get_storage_summary(self) -> dict[str, Any]:
        """Return canonical macro storage summary."""

        return _repository().get_storage_summary()

    def list_indicator_rollups(self) -> list[dict[str, Any]]:
        """Return per-indicator rollups."""

        return _repository().list_indicator_rollups()

    def list_source_rollups(self) -> list[dict[str, Any]]:
        """Return per-source rollups."""

        return _repository().list_source_rollups()

    def get_indicator_rows(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Return serialized rows for an indicator."""

        return _repository().get_indicator_rows(**kwargs)

    def count_table_rows(self, **kwargs: Any) -> int:
        """Count rows matching table filters."""

        return _repository().count_table_rows(**kwargs)

    def get_table_rows(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Return table rows matching filters."""

        return _repository().get_table_rows(**kwargs)

    def get_latest_indicator(self, code: str) -> dict[str, Any] | None:
        """Return latest serialized indicator row."""

        return _repository().get_latest_indicator(code)

    def get_indicator_stats(self, code: str, start_date: date) -> dict[str, float | None]:
        """Return aggregate indicator statistics."""

        return _repository().get_indicator_stats(code, start_date)

    def get_indicator_history(self, code: str, **kwargs: Any) -> list[dict[str, Any]]:
        """Return compact indicator history."""

        return _repository().get_indicator_history(code, **kwargs)

    def get_latest_values_by_codes(self, codes: list[str]) -> list[dict[str, Any]]:
        """Return latest values for a bounded code list."""

        return _repository().get_latest_values_by_codes(codes)


class DataCenterMacroReadRepository(DataCenterMacroRepository):
    """Compatibility name for read-only callers during migration."""


__all__ = ["DataCenterMacroReadRepository", "DataCenterMacroRepository"]
