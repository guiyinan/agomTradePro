"""
贸易指标数据获取器。

包含出口、进口、贸易差额等贸易指标的获取逻辑。
"""

import pandas as pd
from datetime import date
from typing import List
import logging

from ..base import MacroDataPoint, DataValidationError

logger = logging.getLogger(__name__)

# 指标单位映射 (unit, original_unit)
INDICATOR_UNITS = {
    "CN_EXPORTS": ("%", "%"),
    "CN_IMPORTS": ("%", "%"),
    "CN_TRADE_BALANCE": ("亿美元", "亿美元"),
}


class TradeIndicatorFetcher:
    """贸易指标获取器"""

    def __init__(self, ak, source_name: str, validate_fn, sort_dedup_fn):
        self.ak = ak
        self.source_name = source_name
        self._validate = validate_fn
        self._sort_and_deduplicate = sort_dedup_fn

    def fetch_exports(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """获取中国出口数据"""
        try:
            df = self.ak.macro_china_exports_yoy()
            if df.empty:
                logger.warning("出口数据为空")
                return []

            date_col = '日期' if '日期' in df.columns else df.columns[1]
            value_col = '值' if '值' in df.columns else df.columns[2]

            df['date'] = pd.to_datetime(df[date_col], format='mixed', errors='coerce')
            df = df[['date', value_col]].dropna()
            df.columns = ['observed_at', 'value']
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = INDICATOR_UNITS.get("CN_EXPORTS", ("%", "%"))
            for _, row in df.iterrows():
                try:
                    point = MacroDataPoint(
                        code="CN_EXPORTS",
                        value=float(row['value']),
                        observed_at=row['observed_at'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效出口数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取出口数据失败: {e}")
            raise

    def fetch_imports(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """获取中国进口数据"""
        try:
            df = self.ak.macro_china_imports_yoy()
            if df.empty:
                logger.warning("进口数据为空")
                return []

            date_col = '日期' if '日期' in df.columns else df.columns[1]
            value_col = '值' if '值' in df.columns else df.columns[2]

            df['date'] = pd.to_datetime(df[date_col], format='mixed', errors='coerce')
            df = df[['date', value_col]].dropna()
            df.columns = ['observed_at', 'value']
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = INDICATOR_UNITS.get("CN_IMPORTS", ("%", "%"))
            for _, row in df.iterrows():
                try:
                    point = MacroDataPoint(
                        code="CN_IMPORTS",
                        value=float(row['value']),
                        observed_at=row['observed_at'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效进口数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取进口数据失败: {e}")
            raise

    def fetch_trade_balance(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """获取中国贸易差额数据"""
        try:
            df = self.ak.macro_china_trade_balance()
            if df.empty:
                logger.warning("贸易差额数据为空")
                return []

            date_col = '日期' if '日期' in df.columns else df.columns[1]
            value_col = '值' if '值' in df.columns else df.columns[2]

            df['date'] = pd.to_datetime(df[date_col], format='mixed', errors='coerce')
            df = df[['date', value_col]].dropna()
            df.columns = ['observed_at', 'value']
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = INDICATOR_UNITS.get("CN_TRADE_BALANCE", ("亿美元", "亿美元"))
            for _, row in df.iterrows():
                try:
                    # 原始数据单位是万美元，转换为亿美元
                    value_in_100m_usd = float(row['value']) / 10000
                    point = MacroDataPoint(
                        code="CN_TRADE_BALANCE",
                        value=value_in_100m_usd,
                        observed_at=row['observed_at'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效贸易差额数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取贸易差额数据失败: {e}")
            raise
