"""
Tushare 基金数据适配器

功能：
1. 获取基金基本信息
2. 获取基金净值数据
3. 获取基金持仓数据
"""

from datetime import date, datetime
from typing import List, Optional

import pandas as pd

from shared.config.secrets import get_secrets


class TushareFundAdapter:
    """Tushare 基金数据适配器"""

    def __init__(self):
        """延迟初始化（避免启动时必须有 token）"""
        self.pro = None

    def _ensure_initialized(self):
        """确保已初始化"""
        if self.pro is None:
            import tushare as ts

            token = get_secrets().data_sources.tushare_token
            if not token:
                raise ValueError("Tushare token 未配置")
            self.pro = ts.pro_api(token)

    def fetch_fund_list(
        self,
        market: str = 'E'
    ) -> pd.DataFrame:
        """获取基金列表

        Args:
            market: 市场类型
                - 'E': 场内基金（ETF、LOF等）
                - 'O': 场外基金

        Returns:
            DataFrame with columns: ts_code, name, fund_type, list_date, etc.
        """
        self._ensure_initialized()

        df = self.pro.fund_basic(
            market=market,
            status='L',  # 上市状态
            fields='ts_code,name,management,custodian,fund_type,setup_date,list_date,issue_date,delist_date,issue_amount,m_fee,realm'
        )

        # 转换日期格式
        if df is not None and not df.empty:
            if 'setup_date' in df.columns:
                df['setup_date'] = pd.to_datetime(df['setup_date'], format='%Y%m%d', errors='coerce')
            if 'list_date' in df.columns:
                df['list_date'] = pd.to_datetime(df['list_date'], format='%Y%m%d', errors='coerce')

        return df

    def fetch_fund_daily(
        self,
        fund_code: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """获取基金净值数据

        Args:
            fund_code: 基金代码（如 '110011.OF'）
            start_date: 开始日期（'20240101'）
            end_date: 结束日期（'20241231'）

        Returns:
            DataFrame with columns: trade_date, unit_nav, accum_nav, etc.
        """
        self._ensure_initialized()

        df = self.pro.fund_nav(
            ts_code=fund_code,
            start_date=start_date,
            end_date=end_date,
            fields='trade_date,unit_nav,accum_nav'
        )

        # 转换日期格式
        if df is not None and not df.empty:
            df['trade_date'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')

        return df

    def fetch_fund_portfolio(
        self,
        fund_code: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """获取基金持仓数据

        Args:
            fund_code: 基金代码
            start_date: 开始报告期（'20220331'）
            end_date: 结束报告期（'20241231'）

        Returns:
            DataFrame with columns: end_date, ts_code, name, amount, ratio_mv, etc.
        """
        self._ensure_initialized()

        df = self.pro.fund_portfolio(
            ts_code=fund_code,
            start_date=start_date,
            end_date=end_date,
            fields='end_date,ts_code,name,amount,ratio_mv'
        )

        # 转换日期格式
        if df is not None and not df.empty:
            df['end_date'] = pd.to_datetime(df['end_date'], format='%Y%m%d')

        return df

    def fetch_fund_daily_basic(
        self,
        fund_code: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """获取基金日线基本信息（涨跌幅、换手率等）

        Args:
            fund_code: 基金代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            DataFrame with columns: trade_date, pct_chg, turnover, etc.
        """
        self._ensure_initialized()

        df = self.pro.fund_daily(
            ts_code=fund_code,
            start_date=start_date,
            end_date=end_date,
            fields='trade_date,pre_close,open,high,low,close,change,pct_chg,vol,amount'
        )

        # 转换日期格式
        if df is not None and not df.empty:
            df['trade_date'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')

        return df

    def fetch_fund_manager(self, fund_code: str) -> pd.DataFrame:
        """获取基金经理信息

        Args:
            fund_code: 基金代码

        Returns:
            DataFrame with columns: ts_code, name, gender, birth_year, start_date, end_date, etc.
        """
        self._ensure_initialized()

        df = self.pro.fund_manager(
            ts_code=fund_code,
            fields='ts_code,ann_date,name,gender,birth_year,start_date,end_date,return_total,tenure_date'
        )

        # 转换日期格式
        if df is not None and not df.empty:
            df['start_date'] = pd.to_datetime(df['start_date'], format='%Y%m%d', errors='coerce')
            df['end_date'] = pd.to_datetime(df['end_date'], format='%Y%m%d', errors='coerce')

        return df

    def fetch_fund_holdings_detail(
        self,
        fund_code: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """获取基金持仓详情（包含更多字段）

        Args:
            fund_code: 基金代码
            start_date: 开始报告期
            end_date: 结束报告期

        Returns:
            DataFrame with columns: end_date, ts_code, name, amount, ratio_mv, etc.
        """
        self._ensure_initialized()

        # 使用 fund_portfolio 接口
        df = self.pro.fund_portfolio(
            ts_code=fund_code,
            start_date=start_date,
            end_date=end_date
        )

        # 转换日期格式
        if df is not None and not df.empty:
            df['end_date'] = pd.to_datetime(df['end_date'], format='%Y%m%d', errors='coerce')

        return df
