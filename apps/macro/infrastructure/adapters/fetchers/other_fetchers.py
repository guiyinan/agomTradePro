"""
其他指标数据获取器。

包含就业、房产、价格等其他指标的获取逻辑。
"""

import logging
import re
from datetime import date
from typing import List

import pandas as pd

from ..base import DataValidationError, MacroDataPoint
from .common import pick_column, resolve_indicator_units, safe_float

logger = logging.getLogger(__name__)

# 指标单位 fallback，仅在 runtime metadata / unit rule 不可用时生效。
INDICATOR_UNITS = {
    "CN_UNEMPLOYMENT": ("%", "%"),
    "CN_NEW_HOUSE_PRICE": ("%", "%"),
    "CN_OIL_PRICE": ("元/升", "元/升"),
}


def _safe_percent_point(value, default=0.0):
    """Return percentage-style source values in percentage points."""
    try:
        return safe_float(value)
    except ValueError:
        return default


def parse_chinese_date(date_str: str) -> str:
    """解析中文日期格式"""
    if '年' in str(date_str) and '月' in str(date_str):
        match = re.match(r'(\d{4})年(\d{1,2})月', str(date_str))
        if match:
            year, month = match.groups()
            return f"{year}-{month.zfill(2)}"
    return date_str


class OtherIndicatorFetcher:
    """其他指标获取器"""

    def __init__(self, ak, source_name: str, validate_fn, sort_dedup_fn):
        self.ak = ak
        self.source_name = source_name
        self._validate = validate_fn
        self._sort_and_deduplicate = sort_dedup_fn

    def fetch_unemployment(
        self,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """获取中国城镇调查失业率数据"""
        try:
            df = self.ak.macro_china_urban_unemployment()
            if df.empty:
                logger.warning("失业率数据为空")
                return []

            date_col = pick_column(df, ['月份', '日期'], 0)
            value_col = pick_column(df, ['城镇调查失业率', '今值'], 1)

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
                "CN_UNEMPLOYMENT",
                *INDICATOR_UNITS.get("CN_UNEMPLOYMENT", ("%", "%")),
            )
            for _, row in df.iterrows():
                try:
                    value_decimal = _safe_percent_point(row['value'])
                    point = MacroDataPoint(
                        code="CN_UNEMPLOYMENT",
                        value=value_decimal,
                        observed_at=row['observed_at'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效失业率数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.warning(f"获取失业率数据失败，跳过该指标: {e}")
            return []

    def fetch_new_house_price(
        self,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """获取中国新房价格指数数据"""
        try:
            df = self.ak.macro_china_new_house_price()
            if df.empty:
                logger.warning("新房价格指数数据为空")
                return []

            date_col_idx = 0
            region_col_idx = 1
            value_col_idx = 2

            df_filtered = df[df.iloc[:, region_col_idx] == '北京'].copy()
            if df_filtered.empty:
                logger.warning("新房价格指数中北京数据为空")
                return []

            df_filtered['observed_at'] = pd.to_datetime(df_filtered.iloc[:, date_col_idx], format='mixed', errors='coerce')
            df_filtered['value'] = pd.to_numeric(df_filtered.iloc[:, value_col_idx], errors='coerce')
            df_filtered = df_filtered[['observed_at', 'value']].dropna()
            df_filtered = df_filtered[
                (df_filtered['observed_at'].dt.date >= start_date) &
                (df_filtered['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = resolve_indicator_units(
                "CN_NEW_HOUSE_PRICE",
                *INDICATOR_UNITS.get("CN_NEW_HOUSE_PRICE", ("%", "%")),
            )
            for _, row in df_filtered.iterrows():
                try:
                    value_yoy = safe_float(row['value']) - 100.0
                    point = MacroDataPoint(
                        code="CN_NEW_HOUSE_PRICE",
                        value=value_yoy,
                        observed_at=row['observed_at'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效新房价格指数数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取新房价格指数数据失败: {e}")
            raise

    def fetch_oil_price(
        self,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """获取中国成品油价格数据"""
        try:
            df = self.ak.energy_oil_hist()
            if df.empty:
                logger.warning("成品油价格数据为空")
                return []

            date_col = '调价日期' if '调价日期' in df.columns else df.columns[0]
            value_col = '汽油最高零售价' if '汽油最高零售价' in df.columns else df.columns[1]

            df['date'] = pd.to_datetime(df[date_col], format='mixed', errors='coerce')
            df = df[['date', value_col]].dropna()
            df.columns = ['observed_at', 'value']
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = resolve_indicator_units(
                "CN_OIL_PRICE",
                *INDICATOR_UNITS.get("CN_OIL_PRICE", ("元/升", "元/升")),
            )
            for _, row in df.iterrows():
                try:
                    # 原始数据单位是元/吨，转换为元/升
                    # 假设汽油密度约为 0.735 kg/L，即 1 吨 ≈ 1360 升
                    value_in_yuan_per_liter = float(row['value']) / 1360
                    point = MacroDataPoint(
                        code="CN_OIL_PRICE",
                        value=value_in_yuan_per_liter,
                        observed_at=row['observed_at'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效成品油价格数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取成品油价格数据失败: {e}")
            raise
