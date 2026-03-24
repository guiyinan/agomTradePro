"""
金融指标数据获取器。

包含外汇储备、LPR、SHIBOR、存款准备金率、信贷数据等金融指标的获取逻辑。
"""

import logging
import re
from datetime import date
from typing import List

import pandas as pd

from ..base import DataValidationError, MacroDataPoint

logger = logging.getLogger(__name__)

# 指标单位映射 (unit, original_unit)
INDICATOR_UNITS = {
    "CN_FX_RESERVES": ("万亿美元", "万亿美元"),
    "CN_LPR": ("%", "%"),
    "CN_SHIBOR": ("%", "%"),
    "CN_RRR": ("%", "%"),
    "CN_NEW_CREDIT": ("亿元", "亿元"),
    "CN_RMB_DEPOSIT": ("亿元", "亿元"),
    "CN_RMB_LOAN": ("亿元", "亿元"),
    "CN_DR007": ("%", "%"),
    "CN_PBOC_NET_INJECTION": ("亿元", "亿元"),
}


def parse_chinese_date(date_str: str) -> str:
    """解析中文日期格式"""
    if '年' in str(date_str) and '月' in str(date_str):
        match = re.match(r'(\d{4})年(\d{1,2})月', str(date_str))
        if match:
            year, month = match.groups()
            return f"{year}-{month.zfill(2)}"
    return date_str


def parse_chinese_full_date(date_str: str) -> str:
    """解析完整中文日期格式 (YYYY年MM月DD日)"""
    if '年' in str(date_str) and '月' in str(date_str) and '日' in str(date_str):
        match = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日', str(date_str))
        if match:
            year, month, day = match.groups()
            return f'{year}-{month.zfill(2)}-{day.zfill(2)}'
    return date_str


def _safe_float(value, default=0.0):
    """安全地将值转换为 float，处理 None、空字符串、非数字值。"""
    if value in (None, ""):
        return default
    try:
        if isinstance(value, str):
            value = value.replace(',', '').replace('%', '').strip()
        return float(value)
    except (TypeError, ValueError):
        return default


class FinancialIndicatorFetcher:
    """金融指标获取器"""

    def __init__(self, ak, source_name: str, validate_fn, sort_dedup_fn):
        self.ak = ak
        self.source_name = source_name
        self._validate = validate_fn
        self._sort_and_deduplicate = sort_dedup_fn

    def fetch_fx_reserves(
        self,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """获取中国外汇储备数据"""
        try:
            df = self.ak.macro_china_fx_gold()
            if df.empty:
                logger.warning("外汇储备数据为空")
                return []

            date_col = '月份' if '月份' in df.columns else df.columns[0]
            value_col = '外汇储备-期末值' if '外汇储备-期末值' in df.columns else df.columns[4]

            df['date'] = pd.to_datetime(df[date_col].apply(parse_chinese_date), format='mixed', errors='coerce')
            df = df[['date', value_col]].dropna()
            df.columns = ['observed_at', 'value']
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = INDICATOR_UNITS.get("CN_FX_RESERVES", ("万亿美元", "万亿美元"))
            for _, row in df.iterrows():
                try:
                    # 原始单位是万美元，转换为万亿美元
                    value = _safe_float(row['value'])
                    value_in_trillions = value / 10000
                    point = MacroDataPoint(
                        code="CN_FX_RESERVES",
                        value=value_in_trillions,
                        observed_at=row['observed_at'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效外汇储备数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取外汇储备数据失败: {e}")
            raise

    def fetch_lpr(
        self,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """获取中国 LPR 数据"""
        try:
            df = self.ak.macro_china_lpr()
            if df.empty:
                logger.warning("LPR 数据为空")
                return []

            date_col = '日期' if '日期' in df.columns else df.columns[0]
            value_col = '1年期' if '1年期' in df.columns else df.columns[1]

            df['date'] = pd.to_datetime(df[date_col], format='mixed')
            df = df[['date', value_col]].dropna()
            df.columns = ['observed_at', 'value']
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = INDICATOR_UNITS.get("CN_LPR", ("%", "%"))
            for _, row in df.iterrows():
                try:
                    value_decimal = float(row['value']) / 100 if float(row['value']) > 1 else float(row['value'])
                    point = MacroDataPoint(
                        code="CN_LPR",
                        value=value_decimal,
                        observed_at=row['observed_at'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 LPR 数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 LPR 数据失败: {e}")
            raise

    def fetch_shibor(
        self,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """获取中国 SHIBOR 数据"""
        try:
            df = self.ak.macro_china_shibor_all()
            if df.empty:
                logger.warning("SHIBOR 数据为空")
                return []

            date_col = '日期' if '日期' in df.columns else df.columns[0]
            value_col = '隔夜' if '隔夜' in df.columns else df.columns[1]

            df['date'] = pd.to_datetime(df[date_col], format='mixed')
            df = df[['date', value_col]].dropna()
            df.columns = ['observed_at', 'value']
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = INDICATOR_UNITS.get("CN_SHIBOR", ("%", "%"))
            for _, row in df.iterrows():
                try:
                    value_decimal = float(row['value']) / 100 if float(row['value']) > 1 else float(row['value'])
                    point = MacroDataPoint(
                        code="CN_SHIBOR",
                        value=value_decimal,
                        observed_at=row['observed_at'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 SHIBOR 数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 SHIBOR 数据失败: {e}")
            raise

    def fetch_rrr(
        self,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """获取中国存款准备金率数据"""
        try:
            df = self.ak.macro_china_reserve_requirement_ratio()
            if df.empty:
                logger.warning("存款准备金率数据为空")
                return []

            date_col_idx = 0
            value_col_idx = 2

            df = df.copy()
            df['observed_at'] = pd.to_datetime(df.iloc[:, date_col_idx].apply(parse_chinese_full_date), format='mixed', errors='coerce')
            df['value'] = pd.to_numeric(df.iloc[:, value_col_idx], errors='coerce')
            df = df[['observed_at', 'value']].dropna()
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = INDICATOR_UNITS.get("CN_RRR", ("%", "%"))
            for _, row in df.iterrows():
                try:
                    value_decimal = float(row['value']) / 100 if float(row['value']) > 1 else float(row['value'])
                    point = MacroDataPoint(
                        code="CN_RRR",
                        value=value_decimal,
                        observed_at=row['observed_at'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效存款准备金率数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取存款准备金率数据失败: {e}")
            raise

    def fetch_new_credit(
        self,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """获取中国新增信贷数据"""
        try:
            df = self.ak.macro_china_new_financial_credit()
            if df.empty:
                logger.warning("新增信贷数据为空")
                return []

            date_col = '月份' if '月份' in df.columns else df.columns[0]
            value_col_idx = 1

            df['date'] = pd.to_datetime(df[date_col].apply(parse_chinese_date), format='mixed', errors='coerce')
            df = df[['date', df.columns[value_col_idx]]].copy()
            df.columns = ['observed_at', 'value']
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = INDICATOR_UNITS.get("CN_NEW_CREDIT", ("亿元", "亿元"))
            for _, row in df.iterrows():
                try:
                    # 原始数据已经是亿元
                    value = _safe_float(row['value'])
                    point = MacroDataPoint(
                        code="CN_NEW_CREDIT",
                        value=value,
                        observed_at=row['observed_at'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效新增信贷数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取新增信贷数据失败: {e}")
            raise

    def fetch_rmb_deposit(
        self,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """获取人民币存款余额数据"""
        try:
            df = self.ak.macro_rmb_deposit()
            if df.empty:
                logger.warning("人民币存款数据为空")
                return []

            date_col = '月份' if '月份' in df.columns else df.columns[0]
            value_col = '住户存款-当月值' if '住户存款-当月值' in df.columns else df.columns[2]

            df['date'] = pd.to_datetime(df[date_col].apply(parse_chinese_date), format='mixed', errors='coerce')
            df = df[['date', value_col]].dropna()
            df.columns = ['observed_at', 'value']
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = INDICATOR_UNITS.get("CN_RMB_DEPOSIT", ("亿元", "亿元"))
            for _, row in df.iterrows():
                try:
                    value_str = row['value']
                    if isinstance(value_str, str):
                        value_str = value_str.replace('%', '').replace(',', '')
                    # 原始数据已经是亿元
                    value = float(value_str)
                    point = MacroDataPoint(
                        code="CN_RMB_DEPOSIT",
                        value=value,
                        observed_at=row['observed_at'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效人民币存款数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取人民币存款数据失败: {e}")
            raise

    def fetch_rmb_loan(
        self,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """获取人民币贷款余额数据"""
        try:
            df = self.ak.macro_rmb_loan()
            if df.empty:
                logger.warning("人民币贷款数据为空")
                return []

            date_col = '月份' if '月份' in df.columns else df.columns[0]
            value_col_idx = 1

            df['date'] = pd.to_datetime(df[date_col].apply(parse_chinese_date), format='mixed', errors='coerce')
            df = df[['date', df.columns[value_col_idx]]].copy()
            df.columns = ['observed_at', 'value']
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = INDICATOR_UNITS.get("CN_RMB_LOAN", ("亿元", "亿元"))
            for _, row in df.iterrows():
                try:
                    value_str = row['value']
                    if isinstance(value_str, str):
                        value_str = value_str.replace('%', '').replace(',', '')
                    # 原始数据已经是亿元
                    value = float(value_str)
                    point = MacroDataPoint(
                        code="CN_RMB_LOAN",
                        value=value,
                        observed_at=row['observed_at'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效人民币贷款数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取人民币贷款数据失败: {e}")
            raise

    def fetch_dr007(
        self,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """获取 DR007 数据"""
        try:
            if not hasattr(self.ak, 'repo_rate_hist'):
                logger.warning("当前 akshare 版本不支持 repo_rate_hist, 无法获取 DR007")
                return []
            
            # 使用 ak.repo_rate_hist 替代假定的宏观利率函数
            df = self.ak.repo_rate_hist()
            if df.empty:
                logger.warning("DR007 数据为空")
                return []

            date_col = 'date' if 'date' in df.columns else df.columns[0]
            # DR007 对应的回购利率列名可能是 DR007 或别的，根据实际情况适配
            value_col = 'DR007' if 'DR007' in df.columns else df.columns[2]

            df['date'] = pd.to_datetime(df[date_col], format='mixed', errors='coerce')
            df = df[['date', value_col]].dropna()
            df.columns = ['observed_at', 'value']
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = INDICATOR_UNITS.get("CN_DR007", ("%", "%"))
            for _, row in df.iterrows():
                try:
                    value = _safe_float(row['value'])
                    value_decimal = value / 100 if value > 1 else value
                    point = MacroDataPoint(
                        code="CN_DR007",
                        value=value_decimal,
                        observed_at=row['observed_at'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 DR007 数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 DR007 数据失败: {e}")
            raise

    def fetch_pboc_open_market(
        self,
        start_date: date,
        end_date: date
    ) -> list[MacroDataPoint]:
        """获取央行公开市场操作净投放数据"""
        try:
            if not hasattr(self.ak, 'macro_china_pboc_open_market'):
                logger.warning("当前 akshare 版本不支持 macro_china_pboc_open_market, 无法获取央行公开市场操作数据")
                return []

            df = self.ak.macro_china_pboc_open_market()
            if df.empty:
                logger.warning("央行公开市场操作数据为空")
                return []

            date_col = '日期' if '日期' in df.columns else df.columns[0]
            value_col = '净投放' if '净投放' in df.columns else (df.columns[-1] if len(df.columns) > 0 else None)
            
            if not value_col:
                return []

            df['date'] = pd.to_datetime(df[date_col], format='mixed', errors='coerce')
            df = df[['date', value_col]].dropna()
            df.columns = ['observed_at', 'value']
            df = df[
                (df['observed_at'].dt.date >= start_date) &
                (df['observed_at'].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = INDICATOR_UNITS.get("CN_PBOC_NET_INJECTION", ("亿元", "亿元"))
            for _, row in df.iterrows():
                try:
                    value_str = str(row['value']).replace('亿', '').replace('元', '').replace(',', '')
                    value = _safe_float(value_str)
                    
                    point = MacroDataPoint(
                        code="CN_PBOC_NET_INJECTION",
                        value=value,
                        observed_at=row['observed_at'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效央行公开市场操作数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取央行公开市场操作数据失败: {e}")
            raise
