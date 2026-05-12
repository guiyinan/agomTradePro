"""
贸易指标数据获取器。

包含出口、进口、贸易差额等贸易指标的获取逻辑。
"""

import logging
import re
from datetime import date

import pandas as pd

from ..base import DataValidationError, MacroDataPoint
from .common import pick_column, resolve_indicator_units, safe_float

logger = logging.getLogger(__name__)


def parse_trade_month(date_str: object) -> str:
    """解析中文月份格式。"""
    raw = str(date_str)
    match = re.match(r"(\d{4})年(\d{1,2})月", raw)
    if match:
        year, month = match.groups()
        return f"{year}-{month.zfill(2)}"
    return raw


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
    ) -> list[MacroDataPoint]:
        """获取中国当月出口额数据。"""
        try:
            df = self.ak.macro_china_hgjck()
            if df.empty:
                logger.warning("出口数据为空")
                return []

            date_col = pick_column(df, ['月份'], 0)
            value_col = pick_column(df, ['当月出口额-金额'], 1)

            df['date'] = pd.to_datetime(df[date_col].apply(parse_trade_month), format='mixed', errors='coerce')
            df = df[['date', value_col]].dropna()
            df.columns = ['observed_at', 'raw_value']
            # AKShare 当前原始值量级需换算到“亿美元”后才与海关月度规模相符。
            df['value'] = df['raw_value'].apply(safe_float) / 100000.0
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = resolve_indicator_units("CN_EXPORTS")
            for _, row in df.iterrows():
                try:
                    point = MacroDataPoint(
                        code="CN_EXPORTS",
                        value=safe_float(row['value']),
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

    def fetch_export_yoy(
        self,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """获取中国当月出口额同比增速。"""
        try:
            df = self.ak.macro_china_hgjck()
            if df.empty:
                logger.warning("出口同比数据为空")
                return []

            date_col = pick_column(df, ['月份'], 0)
            value_col = pick_column(df, ['当月出口额-同比增长'], 2)

            df['date'] = pd.to_datetime(df[date_col].apply(parse_trade_month), format='mixed', errors='coerce')
            df = df[['date', value_col]].dropna()
            df.columns = ['observed_at', 'value']
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = resolve_indicator_units("CN_EXPORT_YOY")
            for _, row in df.iterrows():
                try:
                    point = MacroDataPoint(
                        code="CN_EXPORT_YOY",
                        value=safe_float(row['value']),
                        observed_at=row['observed_at'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效出口同比数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取出口同比数据失败: {e}")
            raise

    def fetch_imports(
        self,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """获取中国当月进口额数据。"""
        try:
            df = self.ak.macro_china_hgjck()
            if df.empty:
                logger.warning("进口数据为空")
                return []

            date_col = pick_column(df, ['月份'], 0)
            value_col = pick_column(df, ['当月进口额-金额'], 4)

            df['date'] = pd.to_datetime(df[date_col].apply(parse_trade_month), format='mixed', errors='coerce')
            df = df[['date', value_col]].dropna()
            df.columns = ['observed_at', 'raw_value']
            df['value'] = df['raw_value'].apply(safe_float) / 100000.0
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = resolve_indicator_units("CN_IMPORTS")
            for _, row in df.iterrows():
                try:
                    point = MacroDataPoint(
                        code="CN_IMPORTS",
                        value=safe_float(row['value']),
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

    def fetch_import_yoy(
        self,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """获取中国当月进口额同比增速。"""
        try:
            df = self.ak.macro_china_hgjck()
            if df.empty:
                logger.warning("进口同比数据为空")
                return []

            date_col = pick_column(df, ['月份'], 0)
            value_col = pick_column(df, ['当月进口额-同比增长'], 5)

            df['date'] = pd.to_datetime(df[date_col].apply(parse_trade_month), format='mixed', errors='coerce')
            df = df[['date', value_col]].dropna()
            df.columns = ['observed_at', 'value']
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = resolve_indicator_units("CN_IMPORT_YOY")
            for _, row in df.iterrows():
                try:
                    point = MacroDataPoint(
                        code="CN_IMPORT_YOY",
                        value=safe_float(row['value']),
                        observed_at=row['observed_at'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效进口同比数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取进口同比数据失败: {e}")
            raise

    def fetch_trade_balance(
        self,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """获取中国贸易差额数据"""
        try:
            df = self.ak.macro_china_trade_balance()
            if df.empty:
                logger.warning("贸易差额数据为空")
                return []

            date_col = pick_column(df, ['日期'], 1)
            value_col = pick_column(df, ['今值', '值'], 2)

            df['date'] = pd.to_datetime(df[date_col], format='mixed', errors='coerce')
            df = df[['date', value_col]].dropna()
            df.columns = ['observed_at', 'value']
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = resolve_indicator_units("CN_TRADE_BALANCE")
            for _, row in df.iterrows():
                try:
                    point = MacroDataPoint(
                        code="CN_TRADE_BALANCE",
                        value=safe_float(row['value']),
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
