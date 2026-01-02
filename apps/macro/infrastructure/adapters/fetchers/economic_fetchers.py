"""
经济活动指标数据获取器。

包含工业增加值、社会消费品零售总额、GDP 等经济活动指标的获取逻辑。
"""

import pandas as pd
from datetime import date
from typing import List
import logging
import re

from ..base import MacroDataPoint, DataValidationError

logger = logging.getLogger(__name__)

# 指标单位映射 (unit, original_unit)
INDICATOR_UNITS = {
    "CN_VALUE_ADDED": ("%", "%"),
    "CN_RETAIL_SALES": ("%", "%"),
    "CN_GDP": ("亿元", "亿元"),
}


def parse_chinese_date(date_str: str) -> str:
    """解析中文日期格式"""
    if '年' in str(date_str) and '月' in str(date_str):
        match = re.match(r'(\d{4})年(\d{1,2})月', str(date_str))
        if match:
            year, month = match.groups()
            return f"{year}-{month.zfill(2)}"
    return date_str


def parse_chinese_quarter(date_str: str) -> str:
    """处理中文季度格式 (如: '2024年第1季度')"""
    date_str = str(date_str)
    match = re.match(r'(\d{4})年[第](\d+)[季度季度]', date_str)
    if match:
        year, quarter = match.groups()
        quarter_to_month = {'1': '03', '2': '06', '3': '09', '4': '12'}
        return f"{year}-{quarter_to_month.get(quarter, '12')}-01"

    match = re.match(r'(\d{4})年(\d+)-(\d+)月', date_str)
    if match:
        year = match.group(1)
        end_month = match.group(3)
        return f"{year}-{end_month.zfill(2)}-01"

    return date_str


class EconomicIndicatorFetcher:
    """经济活动指标获取器"""

    def __init__(self, ak, source_name: str, validate_fn, sort_dedup_fn):
        self.ak = ak
        self.source_name = source_name
        self._validate = validate_fn
        self._sort_and_deduplicate = sort_dedup_fn

    def fetch_value_added(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """获取工业增加值数据"""
        try:
            df = self.ak.macro_china_gyzjz()
            if df.empty:
                logger.warning("工业增加值数据为空")
                return []

            date_col_idx = 0
            value_col_idx = 1

            df = df.copy()
            df['observed_at'] = pd.to_datetime(df.iloc[:, date_col_idx].apply(parse_chinese_date), format='mixed', errors='coerce')
            df['value'] = pd.to_numeric(df.iloc[:, value_col_idx], errors='coerce')
            df = df[['observed_at', 'value']].dropna()
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = INDICATOR_UNITS.get("CN_VALUE_ADDED", ("%", "%"))
            for _, row in df.iterrows():
                try:
                    point = MacroDataPoint(
                        code="CN_VALUE_ADDED",
                        value=float(row['value']),
                        observed_at=row['observed_at'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效工业增加值数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取工业增加值数据失败: {e}")
            raise

    def fetch_retail_sales(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """获取社会消费品零售总额数据"""
        try:
            df = self.ak.macro_china_consumer_goods_retail()
            if df.empty:
                logger.warning("社零数据为空")
                return []

            date_col_idx = 0
            value_col_idx = 2

            df = df.copy()
            df['observed_at'] = pd.to_datetime(df.iloc[:, date_col_idx].apply(parse_chinese_date), format='mixed', errors='coerce')
            df['value'] = pd.to_numeric(df.iloc[:, value_col_idx], errors='coerce')
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]
            df = df[['observed_at', 'value']].dropna()

            data_points = []
            unit, original_unit = INDICATOR_UNITS.get("CN_RETAIL_SALES", ("%", "%"))
            for _, row in df.iterrows():
                try:
                    point = MacroDataPoint(
                        code="CN_RETAIL_SALES",
                        value=float(row['value']),
                        observed_at=row['observed_at'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效社零数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取社零数据失败: {e}")
            raise

    def fetch_gdp(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """获取中国 GDP 数据

        注意：akshare返回的GDP数据单位是"亿元"
        """
        try:
            df = self.ak.macro_china_gdp()
            if df.empty:
                logger.warning("GDP 数据为空")
                return []

            date_col_idx = 0
            value_col_idx = 1

            df = df.copy()
            df['observed_at'] = pd.to_datetime(df.iloc[:, date_col_idx].apply(parse_chinese_quarter), format='mixed', errors='coerce')
            df['value'] = pd.to_numeric(df.iloc[:, value_col_idx], errors='coerce')
            df = df[['observed_at', 'value']].dropna()
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = INDICATOR_UNITS.get("CN_GDP", ("亿元", "亿元"))
            for _, row in df.iterrows():
                try:
                    # akshare的GDP数据单位是"亿元"
                    original_value = float(row['value'])
                    point = MacroDataPoint(
                        code="CN_GDP",
                        value=original_value,  # 保持原始值（亿元）
                        observed_at=row['observed_at'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 GDP 数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 GDP 数据失败: {e}")
            raise
