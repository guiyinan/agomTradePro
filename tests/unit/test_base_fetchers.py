from datetime import date

import pandas as pd
import pytest

from apps.data_center.infrastructure.macro_sources.base import (
    BaseMacroAdapter,
    DataValidationError,
)
from apps.data_center.infrastructure.macro_sources.fetchers.base_fetchers import (
    BaseIndicatorFetcher,
)
from apps.data_center.infrastructure.macro_sources.fetchers.common import (
    resolve_indicator_units,
)


class _UnitRuleRepository:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available

    def resolve_active_rule(
        self,
        indicator_code: str,
        *,
        source_type: str = "",
        original_unit: str | None = None,
    ) -> object | None:
        if (
            self.available
            and indicator_code == "CN_M2"
            and source_type == "akshare"
            and original_unit == "亿元"
        ):
            return object()
        return None


class _CoreMacroAK:
    def macro_china_pmi(self):
        return pd.DataFrame(
            {
                "月份": ["2025年03月份"],
                "制造业-指数": [50.2],
                "制造业-同比增长": [-0.4],
                "非制造业-指数": [50.8],
            }
        )

    def macro_china_cpi(self):
        return pd.DataFrame(
            {
                "月份": ["2025年03月份"],
                "全国-当月": [100.4],
                "全国-同比增长": [0.4],
                "全国-环比增长": [-0.1],
                "城市-当月": [100.3],
                "城市-同比增长": [0.3],
                "城市-环比增长": [-0.2],
                "农村-当月": [100.6],
                "农村-同比增长": [0.6],
                "农村-环比增长": [0.1],
            }
        )

    def macro_china_ppi(self):
        return pd.DataFrame(
            {
                "月份": ["2025年03月份"],
                "当月": [99.1],
                "当月同比增长": [-0.9],
                "累计": [99.3],
            }
        )

    def macro_china_money_supply(self):
        return pd.DataFrame(
            {
                "月份": ["2025年03月份"],
                "货币和准货币(M2)-数量(亿元)": [3_261_300.0],
                "货币和准货币(M2)-同比增长": [7.0],
            }
        )

    def macro_china_non_man_pmi(self):
        return pd.DataFrame(
            {
                "商品": ["中国官方非制造业PMI报告"],
                "日期": ["2025-03-31"],
                "今值": [50.5],
                "预测值": [50.2],
            }
        )


def _validate(point) -> None:
    BaseMacroAdapter()._validate_data_point(point)


def _sort(points):
    return points


@pytest.fixture(autouse=True)
def governed_core_macro_metadata(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.data_center.infrastructure.macro_sources.fetchers.common.get_runtime_macro_index_metadata_map",
        lambda: {
            "CN_PMI": {"default_unit": "指数", "governance_scope": "macro_console"},
            "CN_CPI": {"default_unit": "指数", "governance_scope": "macro_console"},
            "CN_CPI_NATIONAL_YOY": {
                "default_unit": "%",
                "governance_scope": "macro_console",
            },
            "CN_CPI_NATIONAL_MOM": {
                "default_unit": "%",
                "governance_scope": "macro_console",
            },
            "CN_CPI_URBAN_YOY": {
                "default_unit": "%",
                "governance_scope": "macro_console",
            },
            "CN_CPI_URBAN_MOM": {
                "default_unit": "%",
                "governance_scope": "macro_console",
            },
            "CN_CPI_RURAL_YOY": {
                "default_unit": "%",
                "governance_scope": "macro_console",
            },
            "CN_CPI_RURAL_MOM": {
                "default_unit": "%",
                "governance_scope": "macro_console",
            },
            "CN_PPI": {"default_unit": "指数", "governance_scope": "macro_console"},
            "CN_PPI_YOY": {"default_unit": "%", "governance_scope": "macro_console"},
            "CN_M2": {"default_unit": "万亿元", "governance_scope": "macro_console"},
            "CN_M2_YOY": {"default_unit": "%", "governance_scope": "macro_console"},
            "CN_NON_MAN_PMI": {
                "default_unit": "指数",
                "governance_scope": "macro_console",
            },
        },
    )
    monkeypatch.setattr(
        "apps.data_center.composition.get_indicator_unit_rule_repository",
        lambda: _UnitRuleRepository(),
    )


@pytest.fixture
def fetcher() -> BaseIndicatorFetcher:
    return BaseIndicatorFetcher(_CoreMacroAK(), "akshare", _validate, _sort)


@pytest.mark.parametrize(
    ("method_name", "code", "expected_value", "expected_unit"),
    [
        ("fetch_pmi", "CN_PMI", 50.2, "指数"),
        ("fetch_cpi", "CN_CPI", 100.4, "指数"),
        ("fetch_ppi", "CN_PPI", 99.1, "指数"),
        ("fetch_ppi_yoy", "CN_PPI_YOY", -0.9, "%"),
        ("fetch_m2_yoy", "CN_M2_YOY", 7.0, "%"),
        ("fetch_non_man_pmi", "CN_NON_MAN_PMI", 50.5, "指数"),
    ],
)
def test_core_fetchers_use_named_semantic_columns(
    fetcher,
    method_name,
    code,
    expected_value,
    expected_unit,
) -> None:
    points = getattr(fetcher, method_name)(
        date(2025, 1, 1),
        date(2025, 12, 31),
    )

    assert len(points) == 1
    assert points[0].code == code
    assert points[0].value == expected_value
    assert points[0].unit == expected_unit


@pytest.mark.parametrize(
    ("indicator_code", "expected_value"),
    [
        ("CN_CPI_NATIONAL_YOY", 0.4),
        ("CN_CPI_NATIONAL_MOM", -0.1),
        ("CN_CPI_URBAN_YOY", 0.3),
        ("CN_CPI_URBAN_MOM", -0.2),
        ("CN_CPI_RURAL_YOY", 0.6),
        ("CN_CPI_RURAL_MOM", 0.1),
    ],
)
def test_cpi_detail_fetcher_uses_declared_column_mapping(
    fetcher,
    indicator_code,
    expected_value,
) -> None:
    points = fetcher.fetch_cpi_detailed(
        date(2025, 1, 1),
        date(2025, 12, 31),
        indicator_code,
    )

    assert len(points) == 1
    assert points[0].code == indicator_code
    assert points[0].value == expected_value
    assert points[0].unit == "%"


def test_m2_fetcher_emits_raw_hundred_million_yuan_without_hardcoded_scaling(
    fetcher,
) -> None:
    points = fetcher.fetch_m2(date(2025, 1, 1), date(2025, 12, 31))

    assert len(points) == 1
    assert points[0].value == 3_261_300.0
    assert points[0].unit == "亿元"
    assert points[0].original_unit == "亿元"


def test_core_fetcher_rejects_schema_drift_instead_of_guessing_position() -> None:
    class _DriftedAK(_CoreMacroAK):
        def macro_china_pmi(self):
            return pd.DataFrame(
                {
                    "unknown_period": ["2025年03月份"],
                    "unknown_value": [50.2],
                }
            )

    fetcher = BaseIndicatorFetcher(_DriftedAK(), "akshare", _validate, _sort)

    with pytest.raises(DataValidationError, match="CN_PMI 数据缺少必需列"):
        fetcher.fetch_pmi(date(2025, 1, 1), date(2025, 12, 31))


def test_pmi_skips_invalid_dates_and_keeps_valid_rows() -> None:
    class _MixedDateAK(_CoreMacroAK):
        def macro_china_pmi(self):
            return pd.DataFrame(
                {
                    "月份": ["2025年13月份", "2025年03月份"],
                    "制造业-指数": [99.0, 50.2],
                }
            )

    fetcher = BaseIndicatorFetcher(_MixedDateAK(), "akshare", _validate, _sort)

    points = fetcher.fetch_pmi(date(2025, 1, 1), date(2025, 12, 31))

    assert [(point.observed_at, point.value) for point in points] == [(date(2025, 3, 31), 50.2)]


def test_cpi_detail_rejects_unknown_indicator_code(fetcher) -> None:
    with pytest.raises(DataValidationError, match="不支持的 CPI 细分指标"):
        fetcher.fetch_cpi_detailed(
            date(2025, 1, 1),
            date(2025, 12, 31),
            "CN_CPI_UNKNOWN",
        )


def test_source_unit_resolution_fails_closed_without_exact_rule(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.data_center.composition.get_indicator_unit_rule_repository",
        lambda: _UnitRuleRepository(available=False),
    )

    with pytest.raises(ValueError, match="missing an active unit rule"):
        resolve_indicator_units(
            "CN_M2",
            source_type="akshare",
            source_unit="亿元",
        )
