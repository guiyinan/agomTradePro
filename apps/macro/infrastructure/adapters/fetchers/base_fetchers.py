"""
基础指标数据获取器。

包含 PMI、CPI、PPI、M2 等核心宏观经济指标的获取逻辑。
"""

import logging
import re
from calendar import monthrange
from datetime import date
from typing import List

import pandas as pd

from ..base import DataValidationError, MacroDataPoint
from .common import resolve_indicator_units, safe_float

logger = logging.getLogger(__name__)

# 指标单位 fallback，仅在 runtime metadata / unit rule 不可用时生效。
INDICATOR_UNITS = {
    "CN_PMI": ("指数", "指数"),
    "CN_NON_MAN_PMI": ("指数", "指数"),
    "CN_CPI": ("指数", "指数"),
    "CN_CPI_NATIONAL_YOY": ("%", "%"),
    "CN_CPI_NATIONAL_MOM": ("%", "%"),
    "CN_CPI_URBAN_YOY": ("%", "%"),
    "CN_CPI_URBAN_MOM": ("%", "%"),
    "CN_CPI_RURAL_YOY": ("%", "%"),
    "CN_CPI_RURAL_MOM": ("%", "%"),
    "CN_PPI": ("指数", "指数"),
    "CN_PPI_YOY": ("%", "%"),
    "CN_M2": ("万亿元", "万亿元"),
    "CN_M2_YOY": ("%", "%"),
}


def parse_chinese_date(date_str: str) -> str:
    """解析中文月份格式为期末日期（如: '2024年1月' -> '2024-01-31'）。"""
    if '年' in str(date_str) and '月' in str(date_str):
        match = re.match(r'(\d{4})年(\d{1,2})月', str(date_str))
        if match:
            year, month = match.groups()
            year_int = int(year)
            month_int = int(month)
            last_day = monthrange(year_int, month_int)[1]
            return f"{year}-{month.zfill(2)}-{last_day:02d}"
    return date_str


class BaseIndicatorFetcher:
    """基础指标获取器基类"""

    def __init__(self, ak, source_name: str, validate_fn, sort_dedup_fn):
        self.ak = ak
        self.source_name = source_name
        self._validate = validate_fn
        self._sort_and_deduplicate = sort_dedup_fn

    def fetch_pmi(
        self,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """获取中国 PMI 数据"""
        try:
            df = self.ak.macro_china_pmi()
            if df.empty:
                logger.warning("PMI 数据为空")
                return []

            date_col = '月份' if '月份' in df.columns else df.columns[0]
            value_col = '制造业-指数' if '制造业-指数' in df.columns else df.columns[1]

            df['date'] = pd.to_datetime(df[date_col].apply(parse_chinese_date), format='mixed')
            df = df[['date', value_col]].dropna()
            df.columns = ['observed_at', 'value']
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = resolve_indicator_units(
                "CN_PMI",
                *INDICATOR_UNITS.get("CN_PMI", ("", "")),
            )
            for _, row in df.iterrows():
                try:
                    point = MacroDataPoint(
                        code="CN_PMI",
                        value=float(row['value']),
                        observed_at=row['observed_at'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 PMI 数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 PMI 数据失败: {e}")
            raise

    def fetch_cpi(
        self,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """获取中国 CPI 数据"""
        try:
            df = self.ak.macro_china_cpi()
            if df.empty:
                logger.warning("CPI 数据为空")
                return []

            date_col = '月份' if '月份' in df.columns else df.columns[0]
            value_col = '全国-当月' if '全国-当月' in df.columns else df.columns[1]

            df['date'] = pd.to_datetime(df[date_col].apply(parse_chinese_date), format='mixed')
            df = df[['date', value_col]].dropna()
            df.columns = ['observed_at', 'value']
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = resolve_indicator_units(
                "CN_CPI",
                *INDICATOR_UNITS.get("CN_CPI", ("", "")),
            )
            for _, row in df.iterrows():
                try:
                    point = MacroDataPoint(
                        code="CN_CPI",
                        value=float(row['value']),
                        observed_at=row['observed_at'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit
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
        self,
        start_date: date,
        end_date: date,
        indicator_code: str
    ) -> list[MacroDataPoint]:
        """获取中国 CPI 细分数据"""
        try:
            df = self.ak.macro_china_cpi()
            if df.empty:
                logger.warning("CPI 细分数据为空")
                return []

            column_index_mapping = {
                "CN_CPI_NATIONAL_YOY": 2,
                "CN_CPI_NATIONAL_MOM": 3,
                "CN_CPI_URBAN_YOY": 6,
                "CN_CPI_URBAN_MOM": 7,
                "CN_CPI_RURAL_YOY": 10,
                "CN_CPI_RURAL_MOM": 11,
            }

            value_col_idx = column_index_mapping.get(indicator_code)
            if value_col_idx is None or value_col_idx >= len(df.columns):
                return []

            df['date'] = pd.to_datetime(df.iloc[:, 0].apply(parse_chinese_date), format='mixed', errors='coerce')
            df = df[['date', df.columns[value_col_idx]]].copy()
            df.columns = ['observed_at', 'value']
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = resolve_indicator_units(
                indicator_code,
                *INDICATOR_UNITS.get(indicator_code, ("", "")),
            )
            for _, row in df.iterrows():
                try:
                    value_raw = row['value']
                    if isinstance(value_raw, str):
                        value = float(value_raw.replace('%', '')) / 100
                    else:
                        value = float(value_raw)

                    point = MacroDataPoint(
                        code=indicator_code,
                        value=value,
                        observed_at=row['observed_at'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 CPI 细分数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 CPI 细分数据失败: {e}")
            raise

    def fetch_ppi(
        self,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """获取中国 PPI 数据"""
        try:
            df = self.ak.macro_china_ppi()
            if df.empty:
                logger.warning("PPI 数据为空")
                return []

            date_col = '月份' if '月份' in df.columns else df.columns[0]
            value_col = '当月' if '当月' in df.columns else df.columns[1]

            df['date'] = pd.to_datetime(df[date_col].apply(parse_chinese_date), format='mixed')
            df = df[['date', value_col]].dropna()
            df.columns = ['observed_at', 'value']
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = resolve_indicator_units(
                "CN_PPI",
                *INDICATOR_UNITS.get("CN_PPI", ("", "")),
            )
            for _, row in df.iterrows():
                try:
                    point = MacroDataPoint(
                        code="CN_PPI",
                        value=float(row['value']),
                        observed_at=row['observed_at'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 PPI 数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 PPI 数据失败: {e}")
            raise

    def fetch_ppi_yoy(
        self,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """获取中国 PPI 同比数据"""
        try:
            df = self.ak.macro_china_ppi()
            if df.empty:
                logger.warning("PPI同比数据为空")
                return []

            date_col = '月份' if '月份' in df.columns else df.columns[0]
            value_col_idx = 2

            df['date'] = pd.to_datetime(df[date_col].apply(parse_chinese_date), format='mixed', errors='coerce')
            df = df[['date', df.columns[value_col_idx]]].copy()
            df.columns = ['observed_at', 'value']
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = resolve_indicator_units(
                "CN_PPI_YOY",
                *INDICATOR_UNITS.get("CN_PPI_YOY", ("", "")),
            )
            for _, row in df.iterrows():
                try:
                    point = MacroDataPoint(
                        code="CN_PPI_YOY",
                        value=float(row['value']),
                        observed_at=row['observed_at'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效PPI同比数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取PPI同比数据失败: {e}")
            raise

    def fetch_m2(
        self,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """获取中国 M2 货币供应量数据"""
        try:
            df = self.ak.macro_china_money_supply()
            if df.empty:
                logger.warning("M2 数据为空")
                return []

            date_col = '月份' if '月份' in df.columns else df.columns[0]
            value_col = 'M2' if 'M2' in df.columns else df.columns[1]

            df['date'] = pd.to_datetime(df[date_col].apply(parse_chinese_date), format='mixed')
            df = df[['date', value_col]].dropna()
            df.columns = ['observed_at', 'value']
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = resolve_indicator_units(
                "CN_M2",
                *INDICATOR_UNITS.get("CN_M2", ("万亿元", "万亿元")),
            )
            for _, row in df.iterrows():
                try:
                    value_in_trillion = float(row['value']) / 10000
                    point = MacroDataPoint(
                        code="CN_M2",
                        value=value_in_trillion,
                        observed_at=row['observed_at'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 M2 数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 M2 数据失败: {e}")
            raise

    def fetch_m2_yoy(
        self,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """获取中国 M2 同比数据"""
        try:
            df = self.ak.macro_china_money_supply()
            if df.empty:
                logger.warning("M2同比数据为空")
                return []

            date_col = '月份' if '月份' in df.columns else df.columns[0]
            value_col = (
                '货币和准货币(M2)-同比增长'
                if '货币和准货币(M2)-同比增长' in df.columns
                else df.columns[2]
            )

            df['date'] = pd.to_datetime(
                df[date_col].apply(parse_chinese_date),
                format='mixed',
                errors='coerce',
            )
            df = df[['date', value_col]].dropna()
            df.columns = ['observed_at', 'value']
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = resolve_indicator_units(
                "CN_M2_YOY",
                *INDICATOR_UNITS.get("CN_M2_YOY", ("%", "%")),
            )
            for _, row in df.iterrows():
                try:
                    point = MacroDataPoint(
                        code="CN_M2_YOY",
                        value=float(row['value']),
                        observed_at=row['observed_at'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 M2同比数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 M2同比数据失败: {e}")
            raise

    def fetch_non_man_pmi(
        self,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """获取中国非制造业PMI数据"""
        try:
            df = self.ak.macro_china_non_man_pmi()
            if df.empty:
                logger.warning("非制造业PMI 数据为空")
                return []

            date_col = '日期' if '日期' in df.columns else df.columns[1]
            value_col = '今值' if '今值' in df.columns else df.columns[2]

            df['date'] = pd.to_datetime(df[date_col], format='mixed', errors='coerce')
            df = df[['date', value_col]].dropna()
            df.columns = ['observed_at', 'value']
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = resolve_indicator_units(
                "CN_NON_MAN_PMI",
                *INDICATOR_UNITS.get("CN_NON_MAN_PMI", ("指数", "指数")),
            )
            for _, row in df.iterrows():
                try:
                    point = MacroDataPoint(
                        code="CN_NON_MAN_PMI",
                        value=safe_float(row['value']),
                        observed_at=row['observed_at'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效非制造业PMI数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取非制造业PMI数据失败: {e}")
            raise
