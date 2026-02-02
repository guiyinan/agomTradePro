"""
板块数据 - AKShare 适配器

遵循项目架构约束：
- 封装 AKShare API 调用
- 返回 Pandas DataFrame
- 作为 Tushare 的补充数据源
"""

import pandas as pd
from typing import Optional, List
from datetime import datetime, date


class AKShareSectorAdapter:
    """AKShare 板块数据适配器

    职责：
    1. 获取申万行业分类
    2. 获取申万行业指数日线
    3. 获取板块成分股
    """

    def __init__(self):
        """初始化适配器"""
        try:
            import akshare as ak
            self.ak = ak
        except ImportError:
            raise ImportError("请安装 akshare: pip install akshare")

    def fetch_sw_industry_classify(
        self,
        level: str = 'L1'
    ) -> pd.DataFrame:
        """获取申万行业分类

        Args:
            level: 行业级别（L1=一级行业, L2=二级行业, L3=三级行业）

        Returns:
            DataFrame with columns:
            - sector_code: 行业代码
            - sector_name: 行业名称
            - level: 级别
            - parent_code: 父级代码

        Examples:
            >>> adapter = AKShareSectorAdapter()
            >>> df = adapter.fetch_sw_industry_classify(level='L1')
            >>> print(df.head())
        """
        try:
            # 使用东方财富行业板块接口
            df = self.ak.stock_board_industry_name_em()

            if df is not None and not df.empty:
                # 重命名列
                df = df.rename(columns={
                    '板块名称': 'sector_name',
                    '板块代码': 'sector_code'
                })

                # 添加级别字段
                df['level'] = level
                df['parent_code'] = None

                return df

        except Exception as e:
            print(f"AKShare 获取行业分类失败: {e}")

        return pd.DataFrame()

    def fetch_sector_list(self) -> pd.DataFrame:
        """获取板块/行业列表

        Returns:
            DataFrame with columns: sector_code, sector_name
        """
        return self.fetch_sw_industry_classify(level='L1')

    def fetch_sector_index_daily(
        self,
        sector_code: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """获取板块指数日线数据

        Args:
            sector_code: 板块代码（如 'BK0459'）
            start_date: 开始日期（'2024-01-01'）
            end_date: 结束日期（'2024-12-31'）

        Returns:
            DataFrame with columns:
            - trade_date: 交易日期
            - open: 开盘价
            - high: 最高价
            - low: 最低价
            - close: 收盘价
            - volume: 成交量（手）
            - amount: 成交额（元）
            - change_pct: 涨跌幅（%）

        Examples:
            >>> adapter = AKShareSectorAdapter()
            >>> df = adapter.fetch_sector_index_daily('BK0459', '2024-01-01', '2024-12-31')
            >>> print(df.head())
        """
        try:
            # 使用东方财富板块历史数据接口
            df = self.ak.stock_board_industry_hist_em(
                symbol=sector_code,
                period="daily",
                start_date=start_date.replace('-', ''),
                end_date=end_date.replace('-', '')
            )

            if df is not None and not df.empty:
                # 重命名列
                df = df.rename(columns={
                    '日期': 'trade_date',
                    '开盘': 'open',
                    '收盘': 'close',
                    '最高': 'high',
                    '最低': 'low',
                    '成交量': 'volume',
                    '成交额': 'amount',
                    '涨跌幅': 'change_pct',
                })

                # 转换日期格式
                df['trade_date'] = pd.to_datetime(df['trade_date'])

                return df

        except Exception as e:
            print(f"AKShare 获取板块 {sector_code} 指数数据失败: {e}")

        return pd.DataFrame()

    def fetch_sector_constituents(
        self,
        sector_name: str
    ) -> pd.DataFrame:
        """获取板块成分股

        Args:
            sector_name: 板块名称（如 '银行'）

        Returns:
            DataFrame with columns:
            - stock_code: 成分股代码
            - stock_name: 成分股名称

        Examples:
            >>> adapter = AKShareSectorAdapter()
            >>> df = adapter.fetch_sector_constituents('银行')
            >>> print(df.head())
        """
        try:
            # 使用东方财富板块成分股接口
            df = self.ak.stock_board_industry_cons_em(symbol=sector_name)

            if df is not None and not df.empty:
                # 查找代码和名称列
                code_col = None
                name_col = None
                for col in df.columns:
                    if '代码' in col or 'code' in col.lower():
                        code_col = col
                    if '名称' in col or 'name' in col.lower():
                        name_col = col

                if code_col and name_col:
                    df = df.rename(columns={
                        code_col: 'stock_code',
                        name_col: 'stock_name'
                    })

                    return df[['stock_code', 'stock_name']]

        except Exception as e:
            print(f"AKShare 获取板块 {sector_name} 成分股失败: {e}")

        return pd.DataFrame()

    def fetch_all_sector_codes(self, level: str = 'L1') -> List[str]:
        """获取所有板块代码列表

        Args:
            level: 行业级别

        Returns:
            板块代码列表

        Examples:
            >>> adapter = AKShareSectorAdapter()
            >>> codes = adapter.fetch_all_sector_codes(level='L1')
            >>> print(codes[:10])
        """
        df = self.fetch_sw_industry_classify(level=level)

        if df is not None and not df.empty:
            return df['sector_code'].tolist()

        return []

    def fetch_industry_stocks(self, industry_name: str) -> List[str]:
        """获取行业成分股列表

        Args:
            industry_name: 行业名称

        Returns:
            List[str]: 股票代码列表
        """
        df = self.fetch_sector_constituents(industry_name)

        if df is not None and not df.empty:
            return df['stock_code'].tolist()

        return []
