"""Macro application and exchange-rate boundary contracts."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from apps.macro.application.data_management import (
    DeleteDataRequest,
    DeleteDataUseCase,
    FetchDataRequest,
    FetchDataUseCase,
    GetDataManagementSummaryUseCase,
    ScheduleDataFetchUseCase,
)
from apps.macro.application.indicator_service import (
    IndicatorService,
    IndicatorUnitRuleService,
    UnitDisplayService,
    get_available_indicators_for_frontend,
)
from apps.macro.infrastructure.exchange_rate_config import ExchangeRateService


class _MacroRepo:
    def __init__(self) -> None:
        self.latest: dict[str, date | None] = {}

    def delete_by_conditions(self, **kwargs: object) -> int:
        if kwargs.get("indicator_code") == "FAIL":
            raise RuntimeError("delete failed")
        return 3

    def get_statistics(self) -> dict[str, object]:
        return {
            "total_indicators": 2,
            "total_records": 8,
            "sources": [{"name": "akshare", "record_count": 8}],
        }

    def get_recent_syncs(self, limit: int) -> list[dict[str, object]]:
        return [{"status": "success"}]

    def get_latest_observation_date(
        self,
        indicator: str,
        check_date: date | None = None,
    ) -> date | None:
        return self.latest.get(indicator)


def test_exchange_rate_cache_database_environment_and_default(monkeypatch) -> None:
    """Exchange-rate lookup follows its auditable precedence order."""
    from apps.macro.infrastructure import exchange_rate_config

    values: dict[str, object] = {}
    monkeypatch.setattr(exchange_rate_config.cache, "get", lambda key: values.get(key))
    monkeypatch.setattr(
        exchange_rate_config.cache,
        "set",
        lambda key, value, timeout: values.__setitem__(key, value),
    )
    monkeypatch.setattr(
        exchange_rate_config.cache,
        "delete_pattern",
        lambda pattern: values.clear(),
        raising=False,
    )
    values["usd_cny_rate:latest"] = "7.15"
    assert ExchangeRateService.get_usd_cny_rate() == 7.15

    values.clear()
    monkeypatch.setenv("USD_CNY_EXCHANGE_RATE", "7.22")
    assert ExchangeRateService.get_usd_cny_rate(date(2026, 7, 1)) == 7.22
    monkeypatch.delenv("USD_CNY_EXCHANGE_RATE")
    values.clear()
    assert ExchangeRateService.get_usd_cny_rate(date(2026, 7, 2)) == 7.0
    ExchangeRateService.invalidate_cache()
    assert values == {}


def test_data_management_success_failure_summary_and_schedule_boundaries() -> None:
    """Macro orchestration reports failures and honors daily/monthly/quarterly calendars."""
    repo = _MacroRepo()
    success_sync = SimpleNamespace(
        execute=lambda request: SimpleNamespace(success=True, synced_count=4, errors=[])
    )
    failure_sync = SimpleNamespace(
        execute=lambda request: SimpleNamespace(success=False, synced_count=0, errors=["timeout"])
    )
    assert FetchDataUseCase(success_sync, repo).execute(FetchDataRequest()).synced_count == 4
    assert FetchDataUseCase(failure_sync, repo).execute(FetchDataRequest()).errors == [
        "macro_data_sync_failed"
    ]

    deleted = DeleteDataUseCase(repo).execute(DeleteDataRequest(indicator_code="PMI"))
    assert deleted.success and deleted.deleted_count == 3
    failed = DeleteDataUseCase(repo).execute(DeleteDataRequest(indicator_code="FAIL"))
    assert not failed.success and failed.deleted_count == 0

    summary = GetDataManagementSummaryUseCase(repo).execute()
    assert summary.total_records == 8
    assert summary.data_sources[0].name == "akshare"

    schedule = ScheduleDataFetchUseCase(repo)
    assert schedule._is_daily_due("DAILY", date(2026, 7, 24))
    repo.latest["DAILY"] = date(2026, 7, 24)
    assert not schedule._is_daily_due("DAILY", date(2026, 7, 24))
    assert not schedule._is_monthly_due("MONTHLY", date(2026, 7, 2), 5)
    assert schedule._is_monthly_due("MONTHLY", date(2026, 7, 5), 5)
    assert not schedule._is_quarterly_due("GDP", date(2026, 6, 15), 10, [1, 4, 7, 10])
    assert schedule._is_quarterly_due("GDP", date(2026, 7, 15), 10, [1, 4, 7, 10])
    assert schedule._get_previous_month_end(date(2026, 1, 10)) == date(2025, 12, 31)


def test_indicator_metadata_alias_units_history_and_frontend_projection(monkeypatch) -> None:
    """Indicator services preserve units and block incompatible alias semantics."""

    class _ReadRepo:
        @staticmethod
        def list_distinct_codes() -> list[str]:
            return ["PMI", "M2"]

        @staticmethod
        def get_latest_indicator(code: str) -> dict[str, object] | None:
            if code == "MISSING":
                return None
            return {
                "value": 50.5,
                "display_value": 50.5,
                "display_unit": "指数" if code == "PMI" else "亿元",
                "reporting_period": date(2026, 7, 1),
                "period_type": "monthly",
            }

        @staticmethod
        def get_indicator_stats(**kwargs: object) -> dict[str, float]:
            return {"avg_value": 50.0, "max_value": 52.0, "min_value": 48.0}

        @staticmethod
        def get_indicator_history(*args: object, **kwargs: object) -> list[dict[str, object]]:
            return [
                {
                    "value": 49.0,
                    "unit": "指数",
                    "reporting_period": date(2026, 6, 1),
                    "period_type": "monthly",
                }
            ]

        @staticmethod
        def get_indicator_unit_config(code: str, source: str | None) -> dict[str, str] | None:
            return {"original_unit": "亿元"} if code == "M2" else None

    monkeypatch.setattr(IndicatorService, "read_repository", _ReadRepo())
    monkeypatch.setattr(UnitDisplayService, "read_repository", _ReadRepo())
    metadata = {
        "PMI": {
            "name": "PMI",
            "category": "增长",
            "unit": "指数",
            "series_semantics": "index_level",
        },
        "M2": {"name": "M2", "category": "货币", "unit": "亿元", "series_semantics": "level"},
        "PMI_ALIAS": {"alias_of_indicator_code": "PMI", "series_semantics": "index_level"},
        "BAD_ALIAS": {"alias_of_indicator_code": "PMI", "series_semantics": "level"},
    }
    monkeypatch.setattr(IndicatorService, "get_indicator_metadata_map", lambda: metadata)
    assert IndicatorService.get_code_candidates("PMI") == ["PMI", "PMI_ALIAS"]
    assert IndicatorService.get_indicator_by_code("MISSING") is None
    assert IndicatorService.get_indicator_by_code("PMI")["unit"] == "指数"
    assert IndicatorService.get_indicator_history("PMI")[0]["date"] == "2026-06-01"
    indicators = IndicatorService.get_available_indicators()
    assert [item["code"] for item in indicators] == ["PMI", "M2"]
    assert get_available_indicators_for_frontend()[0]["latest_value"] == 50.5
    assert UnitDisplayService.get_original_unit("M2") == "亿元"
    assert UnitDisplayService.get_original_unit("PMI") == ""
    assert UnitDisplayService.format_for_display(100_000_000, "元", "亿元") == "1.00 亿元"

    monkeypatch.setattr(IndicatorUnitRuleService, "_get_default_rule", lambda code: None)
    assert IndicatorUnitRuleService.get_unit_for_indicator("NONE") == ""
    assert IndicatorUnitRuleService.get_normalized_unit_and_value("NONE", 2.0) == (2.0, "")
    monkeypatch.setattr(
        IndicatorUnitRuleService,
        "_get_default_rule",
        lambda code: {"display_unit": "亿元", "storage_unit": "元", "multiplier_to_storage": 1e8},
    )
    assert IndicatorUnitRuleService.get_unit_for_indicator("M2") == "亿元"
    assert IndicatorUnitRuleService.get_normalized_unit_and_value("M2", 2.0) == (2e8, "元")
