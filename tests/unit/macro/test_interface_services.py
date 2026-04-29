from datetime import date

from apps.macro.application.interface_services import (
    get_macro_data_page_snapshot,
    get_supported_macro_indicators,
)


class _FakeAdapter:
    SUPPORTED_INDICATORS = {
        "CN_GDP": "GDP",
        "CN_M2": "M2",
    }


class _FakeSyncUseCase:
    def __init__(self):
        self.adapters = {"akshare": _FakeAdapter()}


class _FakeCatalog:
    def __init__(self, code: str, name_cn: str, default_unit: str, description: str = ""):
        self.code = code
        self.name_cn = name_cn
        self.default_unit = default_unit
        self.description = description


class _FakeCatalogRepository:
    def list_active(self):
        return [
            _FakeCatalog("CN_GDP", "GDP", "亿元", "GDP总量"),
            _FakeCatalog("CN_M2", "M2", "万亿元", "广义货币"),
        ]


class _FakeMacroReadRepository:
    def list_distinct_codes(self) -> list[str]:
        return ["CN_M2"]

    def get_latest_indicator(self, code: str) -> dict | None:
        if code != "CN_M2":
            return None
        return {
            "code": "CN_M2",
            "value": 325.4,
            "display_value": 325.4,
            "display_unit": "万亿元",
            "unit": "元",
            "reporting_period": date(2026, 4, 1),
            "period_type": "M",
        }

    def get_indicator_rows(self, *, code: str, ascending: bool = True):
        assert code == "CN_M2"
        return [
            {
                "id": 1,
                "code": "CN_M2",
                "value": 325.4,
                "unit": "元",
                "display_value": 325.4,
                "display_unit": "万亿元",
                "original_unit": "万亿元",
                "reporting_period": date(2026, 4, 1),
                "observed_at": date(2026, 4, 1),
                "published_at": date(2026, 4, 15),
                "period_type": "M",
                "period_type_display": "月度",
                "source": "akshare",
                "revision_number": 1,
                "publication_lag_days": 15,
            }
        ]

    def get_storage_summary(self) -> dict[str, object]:
        return {
            "total_indicators": 1,
            "total_records": 12,
            "latest_date": date(2026, 4, 1),
            "min_date": date(2025, 5, 1),
            "max_date": date(2026, 4, 1),
        }


def test_get_supported_macro_indicators_prefers_indicator_metadata(monkeypatch):
    monkeypatch.setattr(
        "apps.macro.application.interface_services.build_sync_macro_data_use_case",
        lambda source="akshare": _FakeSyncUseCase(),
    )
    monkeypatch.setattr(
        "apps.macro.application.interface_services.IndicatorService.get_indicator_metadata_map",
        classmethod(
            lambda cls: {
                "CN_GDP": {"name": "GDP（国内生产总值累计值）"},
                "CN_M2": {"name": "M2（广义货币供应量余额）"},
            }
        ),
    )

    indicators = get_supported_macro_indicators()

    assert indicators == [
        {"code": "CN_GDP", "name": "GDP（国内生产总值累计值）"},
        {"code": "CN_M2", "name": "M2（广义货币供应量余额）"},
    ]


def test_get_macro_data_page_snapshot_lists_catalog_indicators_without_facts(monkeypatch):
    monkeypatch.setattr(
        "apps.macro.application.interface_services.get_macro_read_repository",
        lambda: _FakeMacroReadRepository(),
    )
    monkeypatch.setattr(
        "apps.macro.application.interface_services.get_indicator_catalog_repository",
        lambda: _FakeCatalogRepository(),
    )
    monkeypatch.setattr(
        "apps.macro.application.interface_services.IndicatorService.get_indicator_metadata_map",
        classmethod(
            lambda cls: {
                "CN_GDP": {
                    "name": "GDP（国内生产总值累计值）",
                    "unit": "亿元",
                    "description": "GDP总量",
                },
                "CN_M2": {
                    "name": "M2（广义货币供应量余额）",
                    "unit": "万亿元",
                    "description": "广义货币",
                },
            }
        ),
    )

    snapshot = get_macro_data_page_snapshot()

    assert snapshot["selected_indicator"] == "CN_M2"
    assert snapshot["stats"]["total_indicators"] == 2
    assert snapshot["stats"]["synced_indicators"] == 1
    assert snapshot["indicator_map"]["CN_GDP"]["has_data"] is False
    assert snapshot["indicator_map"]["CN_GDP"]["unit"] == "亿元"
    assert snapshot["indicator_map"]["CN_M2"]["has_data"] is True
    assert snapshot["indicator_map"]["CN_M2"]["latest_value"] == 325.4
    assert len(snapshot["history"]) == 1
