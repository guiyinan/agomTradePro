"""
Data Source Adapters for Macro Data Collection.

Provides adapters for fetching macro economic data from various sources.
"""

import logging
from datetime import date, datetime
from typing import List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


class AKShareAdapter:
    """
    AKShare 数据源适配器

    从 AKShare 获取中国宏观经济数据。
    """

    # 指标代码映射
    INDICATOR_MAP = {
        'CN_PMI': 'pmi',
        'CN_NON_MAN_PMI': 'non_man_pmi',
        'CN_CPI': 'cpi',
        'CN_CPI_NATIONAL_YOY': 'cpi_yoy',
        'CN_CPI_NATIONAL_MOM': 'cpi_mom',
        'CN_PPI': 'ppi',
        'CN_PPI_YOY': 'ppi_yoy',
        'CN_M2': 'm2',
        'CN_VALUE_ADDED': 'value_added',
        'CN_RETAIL_SALES': 'retail_sales',
        'CN_GDP': 'gdp',
        'CN_EXPORTS': 'exports',
        'CN_IMPORTS': 'imports',
        'CN_TRADE_BALANCE': 'trade_balance',
        'CN_SHIBOR': 'shibor',
        'CN_LPR': 'lpr',
        'CN_RRR': 'rrr',
        'CN_NEW_CREDIT': 'new_credit',
    }

    def supports(self, indicator_code: str) -> bool:
        """检查是否支持该指标"""
        return indicator_code in self.INDICATOR_MAP

    def fetch(
        self,
        indicator_code: str,
        start_date: date,
        end_date: date
    ) -> list['MacroDataPoint']:
        """
        获取指标数据

        Args:
            indicator_code: 指标代码
            start_date: 起始日期
            end_date: 结束日期

        Returns:
            List[MacroDataPoint]: 数据点列表
        """
        from apps.macro.application.use_cases import MacroDataPoint

        if indicator_code not in self.INDICATOR_MAP:
            logger.warning(f"AKShare 不支持指标: {indicator_code}")
            return []

        try:
            import akshare as ak

            # 根据指标代码调用对应的 AKShare 接口
            if indicator_code == 'CN_PMI':
                return self._fetch_pmi(ak, start_date, end_date, indicator_code)
            elif indicator_code == 'CN_CPI':
                return self._fetch_cpi(ak, start_date, end_date, indicator_code)
            elif indicator_code == 'CN_CPI_NATIONAL_YOY':
                return self._fetch_cpi_yoy(ak, start_date, end_date, indicator_code)
            elif indicator_code == 'CN_M2':
                return self._fetch_m2(ak, start_date, end_date, indicator_code)
            elif indicator_code == 'CN_SHIBOR':
                return self._fetch_shibor(ak, start_date, end_date, indicator_code)
            elif indicator_code == 'CN_PPI':
                return self._fetch_ppi(ak, start_date, end_date, indicator_code)
            else:
                logger.warning(f"AKShare 适配器未实现 {indicator_code} 的抓取逻辑")
                return []

        except ImportError:
            logger.error("AKShare 未安装")
            return []
        except Exception as e:
            logger.error(f"AKShare 抓取 {indicator_code} 失败: {e}")
            return []

    def _fetch_pmi(
        self,
        ak,
        start_date: date,
        end_date: date,
        indicator_code: str
    ) -> list['MacroDataPoint']:
        """获取 PMI 数据"""
        from apps.macro.application.use_cases import MacroDataPoint

        df = ak.macro_china_pmi()
        data_points = []

        # AKShare 返回的列名: 月份, 制造业-指数, 制造业-同比增长, 非制造业-指数, 非制造业-同比增长
        # 需要解析日期并过滤
        for _, row in df.iterrows():
            try:
                # 解析月份 (格式: "2025年12月")
                month_str = str(row.iloc[0])
                if '年' in month_str and '月' in month_str:
                    year = int(month_str.split('年')[0])
                    month = int(month_str.split('年')[1].split('月')[0])
                    observed_at = date(year, month, 1)

                    # 检查日期范围
                    if observed_at < start_date or observed_at > end_date:
                        continue

                    value = float(row.iloc[1])  # 制造业-指数

                    data_points.append(MacroDataPoint(
                        code=indicator_code,
                        value=value,
                        observed_at=observed_at,
                        published_at=None,
                        source='akshare',
                        unit='指数'
                    ))
            except Exception as e:
                logger.warning(f"解析 PMI 数据行失败: {e}")
                continue

        return data_points

    def _fetch_cpi(
        self,
        ak,
        start_date: date,
        end_date: date,
        indicator_code: str
    ) -> list['MacroDataPoint']:
        """获取 CPI 数据"""
        from apps.macro.application.use_cases import MacroDataPoint

        df = ak.macro_china_cpi_yearly()
        data_points = []

        # AKShare 返回的列名包括: 月份, 全国-当月, 全国-同比增长, 等
        for _, row in df.iterrows():
            try:
                # 解析月份
                month_str = str(row.iloc[0])
                if '年' in month_str and '月' in month_str:
                    year = int(month_str.split('年')[0])
                    month = int(month_str.split('年')[1].split('月')[0])
                    observed_at = date(year, month, 1)

                    # 检查日期范围
                    if observed_at < start_date or observed_at > end_date:
                        continue

                    value = float(row.iloc[1])  # 全国-当月

                    data_points.append(MacroDataPoint(
                        code=indicator_code,
                        value=value,
                        observed_at=observed_at,
                        published_at=None,
                        source='akshare',
                        unit='指数'
                    ))
            except Exception as e:
                logger.warning(f"解析 CPI 数据行失败: {e}")
                continue

        return data_points

    def _fetch_cpi_yoy(
        self,
        ak,
        start_date: date,
        end_date: date,
        indicator_code: str
    ) -> list['MacroDataPoint']:
        """获取 CPI 同比增长数据（百分比形式）"""
        from apps.macro.application.use_cases import MacroDataPoint

        df = ak.macro_china_cpi_yearly()
        data_points = []

        # AKShare 返回的列名包括: 月份, 全国-当月, 全国-同比增长, 等
        # 全国-同比增长 是百分比形式的数据（如 0.8 表示 0.8%）
        for _, row in df.iterrows():
            try:
                # 解析月份
                month_str = str(row.iloc[0])
                if '年' in month_str and '月' in month_str:
                    year = int(month_str.split('年')[0])
                    month = int(month_str.split('年')[1].split('月')[0])
                    observed_at = date(year, month, 1)

                    # 检查日期范围
                    if observed_at < start_date or observed_at > end_date:
                        continue

                    # 使用全国-同比增长（第3列），百分比形式
                    value = float(row.iloc[2])  # 全国-同比增长

                    data_points.append(MacroDataPoint(
                        code=indicator_code,
                        value=value,
                        observed_at=observed_at,
                        published_at=None,
                        source='akshare',
                        unit='%'  # 百分比
                    ))
            except Exception as e:
                logger.warning(f"解析 CPI 同比数据行失败: {e}")
                continue

        return data_points

    def _fetch_m2(
        self,
        ak,
        start_date: date,
        end_date: date,
        indicator_code: str
    ) -> list['MacroDataPoint']:
        """获取 M2 数据"""
        from apps.macro.application.use_cases import MacroDataPoint

        df = ak.macro_china_m2_yearly()
        data_points = []

        # AKShare 返回格式: 统计日期, m2, etc.
        for _, row in df.iterrows():
            try:
                date_str = str(row.iloc[0])
                # 尝试解析日期 (可能是 YYYY-MM 格式)
                if '-' in date_str:
                    parts = date_str.split('-')
                    if len(parts) == 2:
                        year = int(parts[0])
                        month = int(parts[1])
                        observed_at = date(year, month, 1)
                    else:
                        continue
                else:
                    continue

                # 检查日期范围
                if observed_at < start_date or observed_at > end_date:
                    continue

                value = float(row.iloc[1])  # M2 值

                data_points.append(MacroDataPoint(
                    code=indicator_code,
                    value=value,
                    observed_at=observed_at,
                    published_at=None,
                    source='akshare',
                    unit='亿元'
                ))
            except Exception as e:
                logger.warning(f"解析 M2 数据行失败: {e}")
                continue

        return data_points

    def _fetch_shibor(
        self,
        ak,
        start_date: date,
        end_date: date,
        indicator_code: str
    ) -> list['MacroDataPoint']:
        """获取 SHIBOR 数据"""
        from apps.macro.application.use_cases import MacroDataPoint

        df = ak.macro_china_shibor()
        data_points = []

        # 转换日期格式
        start_str = start_date.strftime('%Y-%m-%d')
        end_str = end_date.strftime('%Y-%m-%d')

        df = df[(df.iloc[:, 0] >= start_str) & (df.iloc[:, 0] <= end_str)]

        for _, row in df.iterrows():
            try:
                date_str = str(row.iloc[0])
                observed_at = datetime.strptime(date_str, '%Y-%m-%d').date()

                # 使用隔夜利率
                value = float(row.iloc[1])

                data_points.append(MacroDataPoint(
                    code=indicator_code,
                    value=value,
                    observed_at=observed_at,
                    published_at=None,
                    source='akshare',
                    unit='%'
                ))
            except Exception as e:
                logger.warning(f"解析 SHIBOR 数据行失败: {e}")
                continue

        return data_points

    def _fetch_ppi(
        self,
        ak,
        start_date: date,
        end_date: date,
        indicator_code: str
    ) -> list['MacroDataPoint']:
        """获取 PPI 数据"""
        from apps.macro.application.use_cases import MacroDataPoint

        df = ak.macro_china_ppi_yearly()
        data_points = []

        for _, row in df.iterrows():
            try:
                month_str = str(row.iloc[0])
                if '年' in month_str and '月' in month_str:
                    year = int(month_str.split('年')[0])
                    month = int(month_str.split('年')[1].split('月')[0])
                    observed_at = date(year, month, 1)

                    if observed_at < start_date or observed_at > end_date:
                        continue

                    value = float(row.iloc[1])  # 当月

                    data_points.append(MacroDataPoint(
                        code=indicator_code,
                        value=value,
                        observed_at=observed_at,
                        published_at=None,
                        source='akshare',
                        unit='指数'
                    ))
            except Exception as e:
                logger.warning(f"解析 PPI 数据行失败: {e}")
                continue

        return data_points


class TushareAdapter:
    """
    Tushare 数据源适配器

    从 Tushare 获取宏观经济数据。
    """

    def __init__(self, token: str | None = None):
        """
        初始化 Tushare 适配器

        Args:
            token: Tushare API token
        """
        self.token = token
        self._pro = None

    def _get_pro(self):
        """获取 Tushare pro 接口"""
        if self._pro is None:
            try:
                import tushare as ts
                self._pro = ts.pro_api(self.token)
            except Exception as e:
                logger.error(f"Tushare 初始化失败: {e}")
        return self._pro

    def supports(self, indicator_code: str) -> bool:
        """检查是否支持该指标"""
        # Tushare 支持的指标列表
        return indicator_code in [
            'CN_PMI', 'CN_CPI', 'CN_PPI', 'CN_M2',
        ]

    def fetch(
        self,
        indicator_code: str,
        start_date: date,
        end_date: date
    ) -> list['MacroDataPoint']:
        """获取指标数据"""
        # 简化实现，暂不实现 Tushare
        logger.warning(f"Tushare 适配器未实现 {indicator_code}")
        return []
