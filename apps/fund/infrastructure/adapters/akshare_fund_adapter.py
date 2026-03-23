"""
AKShare 基金数据适配器

功能：
1. 获取基金基本信息
2. 获取基金净值数据
3. 获取基金持仓数据

AKShare 提供了更丰富的基金数据接口，适合作为 Tushare 的补充
"""

from datetime import date, datetime
from typing import List, Optional

import akshare as ak
import pandas as pd


class AkShareFundAdapter:
    """AKShare 基金数据适配器"""

    def __init__(self):
        """初始化适配器"""
        try:
            import akshare as ak

            self.ak = ak
        except ImportError:
            raise ImportError("请安装 akshare: pip install akshare")

    def fetch_fund_list_em(self) -> pd.DataFrame:
        """获取全部基金列表（东方财富）

        Returns:
            DataFrame with columns: 代码, 名称, 基金类型, etc.
        """
        try:
            # 使用新的API获取基金列表
            df = self.ak.fund_open_fund_info_em(
                symbol="710001", indicator="单位净值走势", period="日K"
            )
            return df
        except Exception as e:
            print(f"AKShare 获取基金列表失败: {e}")
            return pd.DataFrame()

    def fetch_fund_info_em(self, fund_code: str) -> pd.DataFrame:
        """获取单个基金详细信息（东方财富）

        Args:
            fund_code: 基金代码（如 '005827'）

        Returns:
            DataFrame with columns: 基金代码, 基金名称, 基金类型, etc.
        """
        try:
            df = self.ak.fund_open_fund_info_em(
                symbol=fund_code, indicator="单位净值走势", period="日K"
            )
            return df
        except Exception as e:
            print(f"AKShare 获取基金 {fund_code} 信息失败: {e}")
            return pd.DataFrame()

    def fetch_fund_nav_em(self, fund_code: str) -> pd.DataFrame:
        """获取基金净值历史数据（东方财富）

        Args:
            fund_code: 基金代码

        Returns:
            DataFrame with columns: 净值日期, 单位净值, etc.
        """
        try:
            df = self.ak.fund_open_fund_info_em(
                symbol=fund_code, indicator="单位净值走势", period="日K"
            )

            if df is not None and not df.empty:
                # 转换列名和日期格式
                # 查找日期列和净值列
                for col in df.columns:
                    if "日期" in col or "date" in col.lower():
                        date_col = col
                    if "净值" in col or "nav" in col.lower():
                        nav_col = col

                if date_col in df.columns and nav_col in df.columns:
                    df = df.rename(columns={date_col: "nav_date", nav_col: "unit_nav"})
                    df["nav_date"] = pd.to_datetime(df["nav_date"])

            return df
        except Exception as e:
            print(f"AKShare 获取基金 {fund_code} 净值失败: {e}")
            return pd.DataFrame()

    def fetch_fund_portfolio_em(self, fund_code: str, year: int, quarter: int) -> pd.DataFrame:
        """获取基金持仓数据（东方财富）

        Args:
            fund_code: 基金代码
            year: 年份
            quarter: 季度（1-4）

        Returns:
            DataFrame with columns: 股票代码, 股票名称, 持有数量, etc.
        """
        try:
            df = ak.fund_portfolio_hold(symbol=fund_code, year=year, quarter=quarter)
            return df
        except Exception as e:
            print(f"AKShare 获取基金 {fund_code} 持仓失败: {e}")
            return pd.DataFrame()

    def fetch_fund_rank_em(self, indicator: str = "收益率") -> pd.DataFrame:
        """获取基金排名数据（东方财富）

        Args:
            indicator: 排名指标
                - "收益率": 按收益率排名
                - "夏普": 按夏普比率排名

        Returns:
            DataFrame with columns: 代码, 名称, etc.
        """
        try:
            df = ak.fund_open_fund_rank_em(symbol="全部基金", indicator=indicator)
            return df
        except Exception as e:
            print(f"AKShare 获取基金排名失败: {e}")
            return pd.DataFrame()

    def fetch_fund_sector_allocation(self, fund_code: str, year: int, quarter: int) -> pd.DataFrame:
        """获取基金行业配置数据

        Args:
            fund_code: 基金代码
            year: 年份
            quarter: 季度

        Returns:
            DataFrame with columns: 行业名称, 配置比例, etc.
        """
        try:
            # AKShare 的 fund_portfolio_hold 包含行业信息
            df = ak.fund_portfolio_hold(symbol=fund_code, year=year, quarter=quarter)
            return df
        except Exception as e:
            print(f"AKShare 获取基金 {fund_code} 行业配置失败: {e}")
            return pd.DataFrame()

    def fetch_fund_scale_rank(self) -> pd.DataFrame:
        """获取基金规模排名

        Returns:
            DataFrame with columns: 基金代码, 基金名称, 基金规模, etc.
        """
        try:
            df = ak.fund_open_fund_rank_em(symbol="全部基金", indicator="规模")
            return df
        except Exception as e:
            print(f"AKShare 获取基金规模排名失败: {e}")
            return pd.DataFrame()
