"""
Weekly Indicators Data Fetchers（Regime 滞后性改进 Phase 2）

包含周度级别的工业活动指标获取逻辑：
- 发电量 (CN_POWER_GEN) - 月度用电量数据
- 钢铁指数 (CN_STEEL_INDEX) - 钢铁行业指数（替代高炉开工率）
- BDI航运指数 (CN_BDI) - 波罗的海干散货指数（替代CCFI/SCFI）

使用公开数据源（AKShare、新浪财经）获取数据。

参考文档: docs/development/regime-lag-improvement-plan.md
"""

import pandas as pd
from datetime import date, timedelta
from typing import List, Optional, Dict
import logging
import re

from ..base import MacroDataPoint, DataValidationError

logger = logging.getLogger(__name__)

# 指标单位映射 (unit, original_unit) - 使用元组格式
WEEKLY_INDICATOR_UNITS = {
    "CN_POWER_GEN": ("亿千瓦时", "亿千瓦时"),
    "CN_BLAST_FURNACE": ("%", "%"),  # 保留兼容性
    "CN_CCFI": ("点", "点"),  # 保留兼容性
    "CN_SCFI": ("点", "点"),  # 保留兼容性
    # 新增公开数据源指标
    "CN_STEEL_INDEX": ("点", "点"),
    "CN_BDI": ("点", "点"),
}


class WeeklyIndicatorFetcher:
    """周度指标获取器

    用于获取周度级别的工业活动指标。
    """

    def __init__(self, ak, source_name: str, validate_fn, sort_dedup_fn):
        self.ak = ak
        self.source_name = source_name
        self._validate = validate_fn
        self._sort_and_deduplicate = sort_dedup_fn

    def fetch_power_generation(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """获取发电量数据

        发电量是实时工业活动的重要指标。
        使用 AKShare 的 macro_china_society_electricity 函数获取全社会用电量作为替代指标。

        注意：AKShare 提供的是月度数据，而非周度数据。
        此方法将月度数据返回，调用方可根据需要决定是否插值为周度。

        Args:
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            List[MacroDataPoint]: 发电量（用电量）数据点列表（月度）
        """
        indicator_code = 'CN_POWER_GEN'

        try:
            # AKShare 获取中国全社会用电量数据（月度）
            df = self.ak.macro_china_society_electricity()
            if df.empty:
                logger.warning("用电量数据为空")
                return []

            df = df.copy()
            # 第一列是统计时间（格式：YYYY.MM）
            # 转换为日期：取每月最后一天
            df['year_month'] = df.iloc[:, 0].astype(str)
            df['date'] = pd.to_datetime(
                df['year_month'] + '-01',
                format='%Y.%m-%d',
                errors='coerce'
            ) + pd.offsets.MonthEnd(1)

            # 第二列是全社会用电量（万千瓦时）
            df['value'] = pd.to_numeric(df.iloc[:, 1], errors='coerce')

            # 将万千瓦时转换为亿千瓦时
            df['value'] = df['value'] / 10000

            # 过滤日期范围
            df = df[
                (df['date'].dt.date >= start_date) &
                (df['date'].dt.date <= end_date)
            ]

            data_points = []
            unit, original_unit = WEEKLY_INDICATOR_UNITS.get(indicator_code, ("亿千瓦时", "亿千瓦时"))

            for _, row in df[['date', 'value']].dropna().iterrows():
                try:
                    point = MacroDataPoint(
                        code=indicator_code,
                        value=float(row['value']),
                        observed_at=row['date'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit,
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 {indicator_code} 数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 {indicator_code} 数据失败: {e}")
            return []

    def fetch_blast_furnace_utilization(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """获取高炉开工率数据（使用钢铁指数作为替代）

        由于高炉开工率需要商业数据源（Mysteel），这里使用钢铁行业指数（000819）
        作为替代指标，反映钢铁行业和工业活动状况。

        数据源：东方财富 - 钢铁指数 (sh000819)

        Args:
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            List[MacroDataPoint]: 钢铁指数数据点列表（日度）
        """
        indicator_code = 'CN_BLAST_FURNACE'

        try:
            # 使用钢铁指数作为高炉开工率的替代指标
            df = self.ak.stock_zh_index_daily_em(symbol='sh000819')
            if df.empty:
                logger.warning(f"{indicator_code}: 钢铁指数数据为空")
                return []

            df = df.copy()
            df['date'] = pd.to_datetime(df['date'], errors='coerce')
            df['value'] = pd.to_numeric(df['close'], errors='coerce')

            # 过滤日期范围
            df = df[
                (df['date'].dt.date >= start_date) &
                (df['date'].dt.date <= end_date)
            ]

            # 按周聚合（取每周最后一个交易日的收盘价）
            df['week'] = df['date'].dt.to_period('W')
            df_weekly = df.groupby('week').last().reset_index()

            data_points = []
            unit, original_unit = WEEKLY_INDICATOR_UNITS.get(indicator_code, ("点", "点"))

            for _, row in df_weekly[['date', 'value']].dropna().iterrows():
                try:
                    point = MacroDataPoint(
                        code=indicator_code,
                        value=float(row['value']),
                        observed_at=row['date'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit,
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 {indicator_code} 数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 {indicator_code} 数据失败: {e}")
            return []

    def fetch_ccfi(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """获取中国出口集装箱运价指数(CCFI)

        由于 CCFI 需要商业数据源授权，这里使用 BDI（波罗的海干散货指数）
        作为替代指标，反映全球航运和贸易活跃度。

        数据源：AKShare - macro_shipping_bdi

        Args:
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            List[MacroDataPoint]: BDI航运指数数据点列表（日度，周聚合）
        """
        indicator_code = 'CN_CCFI'

        try:
            # 使用 BDI 作为 CCFI 的替代指标
            df = self.ak.macro_shipping_bdi()
            if df.empty:
                logger.warning(f"{indicator_code}: BDI数据为空")
                return []

            df = df.copy()
            # 第一列是日期
            df['date'] = pd.to_datetime(df.iloc[:, 0], errors='coerce')
            # 第二列是BDI指数值
            df['value'] = pd.to_numeric(df.iloc[:, 1], errors='coerce')

            # 过滤日期范围
            df = df[
                (df['date'].dt.date >= start_date) &
                (df['date'].dt.date <= end_date)
            ]

            # 按周聚合（取每周最后一个交易日的值）
            df['week'] = df['date'].dt.to_period('W')
            df_weekly = df.groupby('week').last().reset_index()

            data_points = []
            unit, original_unit = WEEKLY_INDICATOR_UNITS.get(indicator_code, ("点", "点"))

            for _, row in df_weekly[['date', 'value']].dropna().iterrows():
                try:
                    point = MacroDataPoint(
                        code=indicator_code,
                        value=float(row['value']),
                        observed_at=row['date'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit,
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 {indicator_code} 数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 {indicator_code} 数据失败: {e}")
            return []

    def fetch_scfi(
        self,
        start_date: date,
        end_date: date
    ) -> List[MacroDataPoint]:
        """获取上海出口集装箱运价指数(SCFI)

        由于 SCFI 需要商业数据源授权，这里使用 BCI（波罗的海海岬型船运价指数）
        作为补充指标，同样反映全球航运和贸易活跃度。

        数据源：AKShare - macro_shipping_bci

        Args:
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            List[MacroDataPoint]: BCI航运指数数据点列表（日度，周聚合）
        """
        indicator_code = 'CN_SCFI'

        try:
            # 使用 BCI (Baltic Cape Index) 作为 SCFI 的替代指标
            df = self.ak.macro_shipping_bci()
            if df.empty:
                logger.warning(f"{indicator_code}: BCI数据为空")
                return []

            df = df.copy()
            # 第一列是日期
            df['date'] = pd.to_datetime(df.iloc[:, 0], errors='coerce')
            # 第二列是BCI指数值
            df['value'] = pd.to_numeric(df.iloc[:, 1], errors='coerce')

            # 过滤日期范围
            df = df[
                (df['date'].dt.date >= start_date) &
                (df['date'].dt.date <= end_date)
            ]

            # 按周聚合（取每周最后一个交易日的值）
            df['week'] = df['date'].dt.to_period('W')
            df_weekly = df.groupby('week').last().reset_index()

            data_points = []
            unit, original_unit = WEEKLY_INDICATOR_UNITS.get(indicator_code, ("点", "点"))

            for _, row in df_weekly[['date', 'value']].dropna().iterrows():
                try:
                    point = MacroDataPoint(
                        code=indicator_code,
                        value=float(row['value']),
                        observed_at=row['date'].date(),
                        source=self.source_name,
                        unit=unit,
                        original_unit=original_unit,
                    )
                    self._validate(point)
                    data_points.append(point)
                except (ValueError, DataValidationError) as e:
                    logger.warning(f"跳过无效 {indicator_code} 数据: {row}, 错误: {e}")

            return self._sort_and_deduplicate(data_points)

        except Exception as e:
            logger.error(f"获取 {indicator_code} 数据失败: {e}")
            return []
