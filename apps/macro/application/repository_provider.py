"""Repository providers for macro application consumers."""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol

from apps.macro.domain.entities import MacroIndicator


class MacroRepositoryProtocol(Protocol):
    """Persistence operations used by Macro application services."""

    def get_series(
        self,
        code: str,
        start_date: date | None = None,
        end_date: date | None = None,
        use_pit: bool = False,
        source: str | None = None,
    ) -> list[MacroIndicator]: ...

    def get_latest_observation_date(
        self,
        code: str,
        as_of_date: date | None = None,
    ) -> date | None: ...

    def get_by_code_and_date(
        self,
        code: str,
        observed_at: date,
        revision_number: int | None = None,
    ) -> MacroIndicator | None: ...

    def save_indicators_batch(
        self,
        indicators: list[MacroIndicator],
        revision_number: int = 1,
    ) -> list[MacroIndicator]: ...

    def delete_by_conditions(
        self,
        indicator_code: str | None = None,
        source: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> int: ...

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


class MacroReadRepositoryProtocol(Protocol):
    """Read-model operations used by Macro application and interface services."""

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

    def get_indicator_stats(
        self,
        code: str,
        start_date: date,
    ) -> dict[str, float | None]: ...

    def get_indicator_history(
        self,
        code: str,
        *,
        start_date: date,
        end_date: date,
        limit: int,
    ) -> list[dict[str, Any]]: ...

    def get_latest_values_by_codes(self, codes: list[str]) -> list[dict[str, Any]]: ...


def get_macro_repository() -> MacroRepositoryProtocol:
    """Return the configured macro repository implementation."""

    from apps.macro.infrastructure.data_center_fact_repository import DataCenterMacroRepository

    return DataCenterMacroRepository()


def get_macro_read_repository() -> MacroReadRepositoryProtocol:
    """Return the configured macro read repository implementation."""

    from apps.macro.infrastructure.data_center_fact_repository import DataCenterMacroReadRepository

    return DataCenterMacroReadRepository()
