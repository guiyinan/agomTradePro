from datetime import date

from apps.macro.application.interface_services import (
    get_macro_data_page_snapshot,
    get_macro_indicator_data,
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
    def __init__(
        self,
        code: str,
        name_cn: str,
        default_unit: str,
        description: str = "",
        default_period_type: str = "M",
        extra: dict | None = None,
    ):
        self.code = code
        self.name_cn = name_cn
        self.default_unit = default_unit
        self.description = description
        self.default_period_type = default_period_type
        self.extra = extra or {}


class _FakeCatalogRepository:
    def list_active(self):
        return [
            _FakeCatalog("CN_GDP", "GDP", "亿元", "GDP总量", "Q"),
            _FakeCatalog("CN_M2", "M2", "万亿元", "广义货币", "M"),
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
        assert ascending is True
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
    monkeypatch.setattr(
        "apps.macro.application.interface_services.get_active_provider_id_by_source",
        lambda source_type: 7 if source_type == "akshare" else None,
    )
    monkeypatch.setattr(
        "apps.macro.application.interface_services.load_macro_governance_payload",
        lambda: {"supported_sync_codes": ["CN_M2"]},
    )

    snapshot = get_macro_data_page_snapshot()

    assert snapshot["selected_indicator"] == "CN_M2"
    assert snapshot["stats"]["total_indicators"] == 2
    assert snapshot["stats"]["synced_indicators"] == 1
    assert snapshot["stats"]["sync_supported_indicators"] == 1
    assert snapshot["stats"]["sync_unsupported_indicators"] == 1
    assert snapshot["refresh_provider_id"] == 7
    assert snapshot["indicator_map"]["CN_GDP"]["has_data"] is False
    assert snapshot["indicator_map"]["CN_GDP"]["sync_supported"] is False
    assert snapshot["indicator_map"]["CN_GDP"]["unit"] == "亿元"
    assert snapshot["indicator_map"]["CN_GDP"]["refresh_start"].isoformat() == "2010-01-01"
    assert snapshot["indicator_map"]["CN_M2"]["has_data"] is True
    assert snapshot["indicator_map"]["CN_M2"]["sync_supported"] is True
    assert snapshot["indicator_map"]["CN_M2"]["latest_value"] == 325.4
    assert snapshot["indicator_map"]["CN_M2"]["refresh_start"] == date(2025, 4, 1)
    assert snapshot["sync_supported_indicator_count"] == 1
    assert snapshot["sync_unsupported_indicator_count"] == 1
    assert snapshot["bulk_refresh_indicator_codes"] == ["CN_M2"]
    assert len(snapshot["history"]) == 1


def test_get_macro_indicator_data_requests_chronological_series(monkeypatch):
    class _CapturingReadRepository:
        def __init__(self) -> None:
            self.called_with_ascending: bool | None = None

        def get_indicator_rows(
            self,
            *,
            code: str,
            start_date: date | None = None,
            end_date: date | None = None,
            limit: int = 500,
            ascending: bool = True,
        ):
            assert code == "CN_IMPORT_YOY"
            self.called_with_ascending = ascending
            if ascending:
                return [
                    {
                        "id": 1,
                        "code": code,
                        "value": 1.2,
                        "unit": "%",
                        "display_value": 1.2,
                        "display_unit": "%",
                        "original_unit": "%",
                        "reporting_period": date(2025, 6, 1),
                        "observed_at": date(2025, 6, 1),
                        "published_at": date(2025, 6, 1),
                        "period_type": "M",
                        "period_type_display": "月度",
                        "source": "akshare",
                        "revision_number": 1,
                        "publication_lag_days": 0,
                    },
                    {
                        "id": 2,
                        "code": code,
                        "value": 27.8,
                        "unit": "%",
                        "display_value": 27.8,
                        "display_unit": "%",
                        "original_unit": "%",
                        "reporting_period": date(2026, 3, 1),
                        "observed_at": date(2026, 3, 1),
                        "published_at": date(2026, 3, 1),
                        "period_type": "M",
                        "period_type_display": "月度",
                        "source": "akshare",
                        "revision_number": 1,
                        "publication_lag_days": 0,
                    },
                ]
            raise AssertionError("UI helper must request ascending=True")

    repository = _CapturingReadRepository()
    monkeypatch.setattr(
        "apps.macro.application.interface_services.get_macro_read_repository",
        lambda: repository,
    )

    rows = get_macro_indicator_data(code="CN_IMPORT_YOY")

    assert repository.called_with_ascending is True
    assert rows[0]["reporting_period"] == "2025-06-01"
    assert rows[-1]["reporting_period"] == "2026-03-01"


class _FakeGdpReadRepository:
    def list_distinct_codes(self) -> list[str]:
        return ["CN_GDP", "CN_GDP_YOY"]

    def get_latest_indicator(self, code: str) -> dict | None:
        payloads = {
            "CN_GDP": {
                "code": "CN_GDP",
                "value": 31846640000000.0,
                "display_value": 318466.4,
                "display_unit": "亿元",
                "unit": "元",
                "reporting_period": date(2025, 3, 1),
                "period_type": "Q",
            },
            "CN_GDP_YOY": {
                "code": "CN_GDP_YOY",
                "value": 5.4,
                "display_value": 5.4,
                "display_unit": "%",
                "unit": "%",
                "reporting_period": date(2025, 3, 1),
                "period_type": "Q",
            },
        }
        return payloads.get(code)

    def get_indicator_rows(self, *, code: str, ascending: bool = True):
        assert code == "CN_GDP_YOY"
        assert ascending is True
        return [
            {
                "id": 11,
                "code": "CN_GDP_YOY",
                "value": 5.4,
                "unit": "%",
                "display_value": 5.4,
                "display_unit": "%",
                "original_unit": "%",
                "reporting_period": date(2025, 3, 1),
                "observed_at": date(2025, 3, 1),
                "published_at": date(2025, 4, 18),
                "period_type": "Q",
                "period_type_display": "季",
                "source": "akshare",
                "revision_number": 1,
                "publication_lag_days": 48,
            }
        ]

    def get_storage_summary(self) -> dict[str, object]:
        return {
            "total_indicators": 2,
            "total_records": 8,
            "latest_date": date(2025, 3, 1),
            "min_date": date(2024, 3, 1),
            "max_date": date(2025, 3, 1),
        }


class _FakeGdpCatalogRepository:
    def list_active(self):
        return [
            _FakeCatalog("CN_GDP", "GDP 国内生产总值累计值", "亿元", "累计值口径", "Q"),
            _FakeCatalog("CN_GDP_YOY", "GDP同比增速", "%", "同比口径", "Q"),
        ]


def test_get_macro_data_page_snapshot_prefers_gdp_yoy_over_cumulative_level(monkeypatch):
    monkeypatch.setattr(
        "apps.macro.application.interface_services.get_macro_read_repository",
        lambda: _FakeGdpReadRepository(),
    )
    monkeypatch.setattr(
        "apps.macro.application.interface_services.get_indicator_catalog_repository",
        lambda: _FakeGdpCatalogRepository(),
    )
    monkeypatch.setattr(
        "apps.macro.application.interface_services.IndicatorService.get_indicator_metadata_map",
        classmethod(
            lambda cls: {
                "CN_GDP": {
                    "name": "GDP（国内生产总值累计值）",
                    "unit": "亿元",
                    "description": "累计值口径",
                    "series_semantics": "cumulative_level",
                    "paired_indicator_code": "CN_GDP_YOY",
                    "chart_policy": "yearly_reset_bar",
                    "display_priority": 20,
                },
                "CN_GDP_YOY": {
                    "name": "GDP同比增速",
                    "unit": "%",
                    "description": "同比口径",
                    "series_semantics": "yoy_rate",
                    "paired_indicator_code": "CN_GDP",
                    "display_priority": 120,
                },
            }
        ),
    )
    monkeypatch.setattr(
        "apps.macro.application.interface_services.get_active_provider_id_by_source",
        lambda source_type: 7 if source_type == "akshare" else None,
    )
    monkeypatch.setattr(
        "apps.macro.application.interface_services.load_macro_governance_payload",
        lambda: {"supported_sync_codes": ["CN_GDP", "CN_GDP_YOY"]},
    )

    snapshot = get_macro_data_page_snapshot()

    assert snapshot["selected_indicator"] == "CN_GDP_YOY"
    assert snapshot["indicator_map"]["CN_GDP"]["sync_supported"] is True
    assert snapshot["indicator_map"]["CN_GDP_YOY"]["sync_supported"] is True
    assert snapshot["indicator_map"]["CN_GDP"]["chart_policy"] == "yearly_reset_bar"
    assert snapshot["bulk_refresh_indicator_codes"] == ["CN_GDP", "CN_GDP_YOY"]
    assert snapshot["indicator_map"]["CN_GDP"]["latest_period"] == "2025-Q1"
    assert snapshot["history"][0]["reporting_period_label"] == "2025-Q1"
