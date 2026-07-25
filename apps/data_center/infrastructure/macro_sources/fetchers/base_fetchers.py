"""
Data Center 基础指标数据获取器。

包含 PMI、CPI、PPI、M2 等核心宏观经济指标的获取逻辑。
"""

import logging
import re
from calendar import monthrange
from collections.abc import Callable
from datetime import date
from typing import Any

import pandas as pd  # type: ignore[import-untyped]

from ..base import DataValidationError, MacroDataPoint
from .common import parse_required_float, resolve_indicator_units

logger = logging.getLogger(__name__)


ValidateDataPoint = Callable[[MacroDataPoint], None]
SortAndDeduplicate = Callable[[list[MacroDataPoint]], list[MacroDataPoint]]


def parse_chinese_date(date_value: object) -> str:
    """解析中文月份格式为期末日期（如: '2024年1月' -> '2024-01-31'）。"""
    date_text = str(date_value)
    if "年" in date_text and "月" in date_text:
        match = re.fullmatch(r"\s*(\d{4})年(\d{1,2})月份?\s*", date_text)
        if match:
            year, month = match.groups()
            year_int = int(year)
            month_int = int(month)
            if not 1 <= month_int <= 12:
                return date_text
            last_day = monthrange(year_int, month_int)[1]
            return f"{year}-{month.zfill(2)}-{last_day:02d}"
    return date_text


def _require_column(
    dataframe: Any,
    candidates: tuple[str, ...],
    *,
    indicator_code: str,
) -> str:
    """Resolve a semantic source column without positional guessing."""

    for candidate in candidates:
        if candidate in dataframe.columns:
            return candidate
    raise DataValidationError(
        f"{indicator_code} 数据缺少必需列 {list(candidates)}，" f"当前列: {list(dataframe.columns)}"
    )


class BaseIndicatorFetcher:
    """基础指标获取器基类"""

    def __init__(
        self,
        ak: Any,
        source_name: str,
        validate_fn: ValidateDataPoint,
        sort_dedup_fn: SortAndDeduplicate,
    ) -> None:
        self.ak = ak
        self.source_name = source_name
        self._validate = validate_fn
        self._sort_and_deduplicate = sort_dedup_fn

    def fetch_pmi(self, start_date: date, end_date: date) -> list[MacroDataPoint]:
        """获取中国 PMI 数据"""
        try:
            df = self.ak.macro_china_pmi()
            if df.empty:
                logger.warning("PMI 数据为空")
                return []

            date_col = _require_column(
                df,
                ("月份",),
                indicator_code="CN_PMI",
            )
            value_col = _require_column(
                df,
                ("制造业-指数",),
                indicator_code="CN_PMI",
            )

            df = df.copy()
            df["date"] = pd.to_datetime(
                df[date_col].apply(parse_chinese_date),
                format="mixed",
                errors="coerce",
            )
            df = df[["date", value_col]].dropna()
            df.columns = ["observed_at", "value"]
            df = df[
                (df["observed_at"].dt.date >= start_date) & (df["observed_at"].dt.date <= end_date)
            ]

            data_points: list[MacroDataPoint] = []
            unit, original_unit = resolve_indicator_units("CN_PMI")
            for _, row in df.iterrows():
                try:
                    point = MacroDataPoint(
                        code="CN_PMI",
                        value=parse_required_float(row["value"]),
                        observed_at=row["observed_at"].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit,
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 PMI 数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 PMI 数据失败: {e}")
            raise

    def fetch_cpi(self, start_date: date, end_date: date) -> list[MacroDataPoint]:
        """获取中国 CPI 数据"""
        try:
            df = self.ak.macro_china_cpi()
            if df.empty:
                logger.warning("CPI 数据为空")
                return []

            date_col = _require_column(
                df,
                ("月份",),
                indicator_code="CN_CPI",
            )
            value_col = _require_column(
                df,
                ("全国-当月",),
                indicator_code="CN_CPI",
            )

            df = df.copy()
            df["date"] = pd.to_datetime(
                df[date_col].apply(parse_chinese_date),
                format="mixed",
                errors="coerce",
            )
            df = df[["date", value_col]].dropna()
            df.columns = ["observed_at", "value"]
            df = df[
                (df["observed_at"].dt.date >= start_date) & (df["observed_at"].dt.date <= end_date)
            ]

            data_points: list[MacroDataPoint] = []
            unit, original_unit = resolve_indicator_units("CN_CPI")
            for _, row in df.iterrows():
                try:
                    point = MacroDataPoint(
                        code="CN_CPI",
                        value=parse_required_float(row["value"]),
                        observed_at=row["observed_at"].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit,
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 CPI 数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 CPI 数据失败: {e}")
            raise

    def fetch_cpi_detailed(
        self, start_date: date, end_date: date, indicator_code: str
    ) -> list[MacroDataPoint]:
        """获取中国 CPI 细分数据"""
        try:
            df = self.ak.macro_china_cpi()
            if df.empty:
                logger.warning("CPI 细分数据为空")
                return []

            column_mapping = {
                "CN_CPI_NATIONAL_YOY": "全国-同比增长",
                "CN_CPI_NATIONAL_MOM": "全国-环比增长",
                "CN_CPI_URBAN_YOY": "城市-同比增长",
                "CN_CPI_URBAN_MOM": "城市-环比增长",
                "CN_CPI_RURAL_YOY": "农村-同比增长",
                "CN_CPI_RURAL_MOM": "农村-环比增长",
            }

            value_column_name = column_mapping.get(indicator_code)
            if value_column_name is None:
                raise DataValidationError(f"不支持的 CPI 细分指标: {indicator_code}")
            date_col = _require_column(
                df,
                ("月份",),
                indicator_code=indicator_code,
            )
            value_col = _require_column(
                df,
                (value_column_name,),
                indicator_code=indicator_code,
            )

            df = df.copy()
            df["date"] = pd.to_datetime(
                df[date_col].apply(parse_chinese_date),
                format="mixed",
                errors="coerce",
            )
            df = df[["date", value_col]].dropna()
            df.columns = ["observed_at", "value"]
            df = df[
                (df["observed_at"].dt.date >= start_date) & (df["observed_at"].dt.date <= end_date)
            ]

            data_points: list[MacroDataPoint] = []
            unit, original_unit = resolve_indicator_units(indicator_code)
            for _, row in df.iterrows():
                try:
                    value_raw = row["value"]
                    value = parse_required_float(value_raw)

                    point = MacroDataPoint(
                        code=indicator_code,
                        value=value,
                        observed_at=row["observed_at"].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit,
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 CPI 细分数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 CPI 细分数据失败: {e}")
            raise

    def fetch_ppi(self, start_date: date, end_date: date) -> list[MacroDataPoint]:
        """获取中国 PPI 数据"""
        try:
            df = self.ak.macro_china_ppi()
            if df.empty:
                logger.warning("PPI 数据为空")
                return []

            date_col = _require_column(
                df,
                ("月份",),
                indicator_code="CN_PPI",
            )
            value_col = _require_column(
                df,
                ("当月",),
                indicator_code="CN_PPI",
            )

            df = df.copy()
            df["date"] = pd.to_datetime(
                df[date_col].apply(parse_chinese_date),
                format="mixed",
                errors="coerce",
            )
            df = df[["date", value_col]].dropna()
            df.columns = ["observed_at", "value"]
            df = df[
                (df["observed_at"].dt.date >= start_date) & (df["observed_at"].dt.date <= end_date)
            ]

            data_points: list[MacroDataPoint] = []
            unit, original_unit = resolve_indicator_units("CN_PPI")
            for _, row in df.iterrows():
                try:
                    point = MacroDataPoint(
                        code="CN_PPI",
                        value=parse_required_float(row["value"]),
                        observed_at=row["observed_at"].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit,
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 PPI 数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 PPI 数据失败: {e}")
            raise

    def fetch_ppi_yoy(self, start_date: date, end_date: date) -> list[MacroDataPoint]:
        """获取中国 PPI 同比数据"""
        try:
            df = self.ak.macro_china_ppi()
            if df.empty:
                logger.warning("PPI同比数据为空")
                return []

            date_col = _require_column(
                df,
                ("月份",),
                indicator_code="CN_PPI_YOY",
            )
            value_col = _require_column(
                df,
                ("当月同比增长",),
                indicator_code="CN_PPI_YOY",
            )

            df = df.copy()
            df["date"] = pd.to_datetime(
                df[date_col].apply(parse_chinese_date),
                format="mixed",
                errors="coerce",
            )
            df = df[["date", value_col]].dropna()
            df.columns = ["observed_at", "value"]
            df = df[
                (df["observed_at"].dt.date >= start_date) & (df["observed_at"].dt.date <= end_date)
            ]

            data_points: list[MacroDataPoint] = []
            unit, original_unit = resolve_indicator_units("CN_PPI_YOY")
            for _, row in df.iterrows():
                try:
                    point = MacroDataPoint(
                        code="CN_PPI_YOY",
                        value=parse_required_float(row["value"]),
                        observed_at=row["observed_at"].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit,
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效PPI同比数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取PPI同比数据失败: {e}")
            raise

    def fetch_m2(self, start_date: date, end_date: date) -> list[MacroDataPoint]:
        """获取中国 M2 货币供应量数据"""
        try:
            df = self.ak.macro_china_money_supply()
            if df.empty:
                logger.warning("M2 数据为空")
                return []

            date_col = _require_column(
                df,
                ("月份",),
                indicator_code="CN_M2",
            )
            value_col = _require_column(
                df,
                ("货币和准货币(M2)-数量(亿元)",),
                indicator_code="CN_M2",
            )

            df = df.copy()
            df["date"] = pd.to_datetime(
                df[date_col].apply(parse_chinese_date),
                format="mixed",
                errors="coerce",
            )
            df = df[["date", value_col]].dropna()
            df.columns = ["observed_at", "value"]
            df = df[
                (df["observed_at"].dt.date >= start_date) & (df["observed_at"].dt.date <= end_date)
            ]

            data_points: list[MacroDataPoint] = []
            unit, original_unit = resolve_indicator_units(
                "CN_M2",
                source_type=self.source_name,
                source_unit="亿元",
            )
            for _, row in df.iterrows():
                try:
                    point = MacroDataPoint(
                        code="CN_M2",
                        value=parse_required_float(row["value"]),
                        observed_at=row["observed_at"].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit,
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 M2 数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 M2 数据失败: {e}")
            raise

    def fetch_m2_yoy(self, start_date: date, end_date: date) -> list[MacroDataPoint]:
        """获取中国 M2 同比数据"""
        try:
            df = self.ak.macro_china_money_supply()
            if df.empty:
                logger.warning("M2同比数据为空")
                return []

            date_col = _require_column(
                df,
                ("月份",),
                indicator_code="CN_M2_YOY",
            )
            value_col = _require_column(
                df,
                ("货币和准货币(M2)-同比增长",),
                indicator_code="CN_M2_YOY",
            )

            df = df.copy()
            df["date"] = pd.to_datetime(
                df[date_col].apply(parse_chinese_date),
                format="mixed",
                errors="coerce",
            )
            df = df[["date", value_col]].dropna()
            df.columns = ["observed_at", "value"]
            df = df[
                (df["observed_at"].dt.date >= start_date) & (df["observed_at"].dt.date <= end_date)
            ]

            data_points: list[MacroDataPoint] = []
            unit, original_unit = resolve_indicator_units("CN_M2_YOY")
            for _, row in df.iterrows():
                try:
                    point = MacroDataPoint(
                        code="CN_M2_YOY",
                        value=parse_required_float(row["value"]),
                        observed_at=row["observed_at"].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit,
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 M2同比数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 M2同比数据失败: {e}")
            raise

    def fetch_non_man_pmi(self, start_date: date, end_date: date) -> list[MacroDataPoint]:
        """获取中国非制造业PMI数据"""
        try:
            df = self.ak.macro_china_non_man_pmi()
            if df.empty:
                logger.warning("非制造业PMI 数据为空")
                return []

            date_col = _require_column(
                df,
                ("日期",),
                indicator_code="CN_NON_MAN_PMI",
            )
            value_col = _require_column(
                df,
                ("今值",),
                indicator_code="CN_NON_MAN_PMI",
            )

            df = df.copy()
            df["date"] = pd.to_datetime(
                df[date_col],
                format="mixed",
                errors="coerce",
            )
            df = df[["date", value_col]].dropna()
            df.columns = ["observed_at", "value"]
            df = df[
                (df["observed_at"].dt.date >= start_date) & (df["observed_at"].dt.date <= end_date)
            ]

            data_points: list[MacroDataPoint] = []
            unit, original_unit = resolve_indicator_units("CN_NON_MAN_PMI")
            for _, row in df.iterrows():
                try:
                    point = MacroDataPoint(
                        code="CN_NON_MAN_PMI",
                        value=parse_required_float(row["value"]),
                        observed_at=row["observed_at"].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit,
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效非制造业PMI数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取非制造业PMI数据失败: {e}")
            raise
