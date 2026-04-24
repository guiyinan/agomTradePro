from datetime import date

from apps.macro.application.indicator_service import (
    IndicatorService,
    IndicatorUnitService,
    UnitDisplayService,
    get_available_indicators_for_frontend,
)


class _FakeAccountConfigSummaryService:
    def __init__(self, metadata_map: dict[str, dict]):
        self._metadata_map = metadata_map

    def get_runtime_macro_index_metadata_map(self) -> dict[str, dict]:
        return self._metadata_map


class _FakeIndicatorReadRepository:
    def list_distinct_codes(self) -> list[str]:
        return ["CN_GDP_YOY"]

    def get_latest_indicator(self, code: str) -> dict | None:
        if code != "CN_GDP_YOY":
            return None
        return {
            "code": code,
            "value": 5.2,
            "unit": "%",
            "original_unit": "%",
            "reporting_period": date(2026, 4, 1),
            "period_type": "M",
        }

    def get_indicator_stats(self, code: str, start_date: date) -> dict[str, float | None]:
        assert code == "CN_GDP_YOY"
        return {
            "avg_value": 4.8,
            "max_value": 5.6,
            "min_value": 4.2,
        }

    def get_indicator_history(
        self,
        code: str,
        *,
        start_date: date,
        end_date: date,
        limit: int,
    ) -> list[dict]:
        return [
            {
                "value": 5.2,
                "unit": "%",
                "original_unit": "%",
                "reporting_period": date(2026, 4, 1),
                "period_type": "M",
            }
        ][:limit]

    def get_latest_values_by_codes(self, codes: list[str]) -> list[dict]:
        assert "CN_GDP" in codes
        return [
            {"code": "CN_GDP", "value": 5.2},
            {"code": "CN_GDP_YOY", "value": 5.1},
        ]

    def get_indicator_unit_config(
        self,
        indicator_code: str,
        source: str | None = None,
    ) -> dict | None:
        if indicator_code == "RUNTIME_ONLY":
            return {"original_unit": "亿元"}
        return None


def test_indicator_unit_service_uses_account_application_service(monkeypatch):
    monkeypatch.setattr(
        "apps.macro.application.indicator_service.get_account_config_summary_service",
        lambda: _FakeAccountConfigSummaryService({"RUNTIME_CODE": {"unit": "亿元"}}),
    )

    assert IndicatorUnitService.get_unit_for_indicator("RUNTIME_CODE") == "亿元"


def test_indicator_service_get_available_indicators_uses_read_repository(monkeypatch):
    monkeypatch.setattr(IndicatorService, "read_repository", _FakeIndicatorReadRepository())
    monkeypatch.setattr(
        IndicatorService,
        "get_indicator_metadata_map",
        classmethod(
            lambda cls: {
                "CN_GDP_YOY": {
                    "name": "GDP同比",
                    "name_en": "GDP YoY",
                    "category": "增长",
                    "unit": "%",
                    "description": "国内生产总值同比",
                    "threshold_bullish": 5.0,
                }
            }
        ),
    )

    indicators = IndicatorService.get_available_indicators(include_stats=True)

    assert indicators == [
        {
            "code": "CN_GDP_YOY",
            "name": "GDP同比",
            "name_en": "GDP YoY",
            "category": "增长",
            "unit": "%",
            "description": "国内生产总值同比",
            "latest_value": 5.2,
            "latest_date": "2026-04-01",
            "period_type": "M",
            "threshold_bullish": 5.0,
            "threshold_bearish": None,
            "avg_value": 4.8,
            "max_value": 5.6,
            "min_value": 4.2,
        }
    ]


def test_get_available_indicators_for_frontend_uses_batch_projection(monkeypatch):
    fake_repo = _FakeIndicatorReadRepository()
    monkeypatch.setattr(IndicatorService, "read_repository", fake_repo)
    monkeypatch.setattr(UnitDisplayService, "read_repository", fake_repo)
    monkeypatch.setattr(
        IndicatorService,
        "get_indicator_metadata_map",
        classmethod(
            lambda cls: {
                "CN_GDP_YOY": {
                    "name": "GDP同比",
                    "category": "增长",
                    "threshold_bullish": 5.0,
                }
            }
        ),
    )

    indicators = get_available_indicators_for_frontend(include_stats=False)

    assert indicators == [
        {
            "code": "CN_GDP_YOY",
            "name": "GDP同比",
            "category": "增长",
            "latest_value": 5.2,
            "suggested_threshold": 5.0,
        }
    ]
