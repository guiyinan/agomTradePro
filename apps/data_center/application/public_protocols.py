"""Typed contracts re-exported by the stable Data Center public boundary."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any, Protocol

from apps.data_center.domain.entities import MacroFact


class AlphaPriceCoverageReportProtocol(Protocol):
    """Minimum report contract exposed to Alpha maintenance commands."""

    def to_dict(self) -> dict[str, object]: ...


class AlphaPriceCoverageSyncProtocol(Protocol):
    """Public contract for Alpha cache price-coverage maintenance."""

    def sync_from_alpha_cache(
        self,
        *,
        start_date: date,
        end_date: date,
        include_remote: bool = True,
        extra_codes: Iterable[str] = (),
    ) -> AlphaPriceCoverageReportProtocol: ...


class MacroProjectionRepositoryProtocol(Protocol):
    """Canonical macro administration and compatibility projection port."""

    def save_indicator(self, fact: MacroFact) -> MacroFact: ...

    def get_series(
        self,
        code: str,
        start_date: date | None = None,
        end_date: date | None = None,
        use_pit: bool = False,
        source: str | None = None,
    ) -> list[MacroFact]: ...

    def get_by_code_and_date(
        self,
        code: str,
        observed_at: date,
        revision_number: int | None = None,
    ) -> MacroFact | None: ...

    def get_latest_observation_date(
        self,
        code: str,
        as_of_date: date | None = None,
    ) -> date | None: ...

    def get_latest_observation(
        self,
        code: str,
        before_date: date | None = None,
    ) -> MacroFact | None: ...

    def get_available_dates(
        self,
        codes: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[date]: ...

    def delete_indicator(
        self,
        code: str,
        observed_at: date,
        revision_number: int | None = None,
    ) -> bool: ...

    def get_indicator_count(self, code: str | None = None) -> int: ...

    def delete_by_conditions(
        self,
        indicator_code: str | None = None,
        source: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> int: ...

    def get_record_by_id(self, record_id: int) -> dict[str, Any] | None: ...

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
    ) -> dict[str, Any]: ...

    def update_record(self, record_id: int, **updates: Any) -> dict[str, Any] | None: ...

    def delete_record_by_id(self, record_id: int) -> bool: ...

    def delete_records_by_ids(self, record_ids: list[int]) -> int: ...

    def count_records_before_date(self, cutoff_date: date) -> int: ...

    def get_statistics(self) -> dict[str, Any]: ...

    def get_recent_syncs(self, limit: int = 10) -> list[dict[str, Any]]: ...

    def get_indicator_unit_config(
        self,
        indicator_code: str,
        source: str | None = None,
    ) -> dict[str, Any] | None: ...

    def list_distinct_codes(self) -> list[str]: ...

    def get_storage_summary(self) -> dict[str, Any]: ...

    def list_indicator_rollups(self) -> list[dict[str, Any]]: ...

    def list_source_rollups(self) -> list[dict[str, Any]]: ...

    def get_indicator_rows(
        self,
        *,
        code: str,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int | None = None,
        ascending: bool = True,
    ) -> list[dict[str, Any]]: ...

    def count_table_rows(
        self,
        *,
        code_filter: str = "",
        source_filter: str = "",
        period_type_filter: str = "",
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> int: ...

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
    ) -> list[dict[str, Any]]: ...

    def get_latest_indicator(self, code: str) -> dict[str, Any] | None: ...

    def get_indicator_stats(self, code: str, start_date: date) -> dict[str, float | None]: ...

    def get_indicator_history(
        self,
        code: str,
        *,
        start_date: date,
        end_date: date,
        limit: int,
    ) -> list[dict[str, Any]]: ...

    def get_latest_values_by_codes(self, codes: list[str]) -> list[dict[str, Any]]: ...


__all__ = [
    "AlphaPriceCoverageReportProtocol",
    "AlphaPriceCoverageSyncProtocol",
    "MacroProjectionRepositoryProtocol",
]
