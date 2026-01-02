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
        level: str = 'SW1'
    ) -> pd.DataFrame:
        """获取申万行业分类

        Args:
            level: 行业级别（SW1=一级, SW2=二级, SW3=三级）

        Returns:
            DataFrame with columns:
            - sector_code: 行业代码
            - sector_name: 行业名称
            - level: 级别
            - parent_code: 父级代码

        Examples:
            >>> adapter = AKShareSectorAdapter()
            >>> df = adapter.fetch_sw_industry_classify(level='SW1')
            >>> print(df.head())
        """
        try:
            if level == 'SW1':
                # 申万一级行业
                df = self.ak.sw_index_cons(symbol="申万一级")
            elif level == 'SW2':
                # 申万二级行业
                df = self.ak.sw_index_cons(symbol="申万二级")
            elif level == 'SW3':
                # 申万三级行业
                df = self.ak.sw_index_cons(symbol="申万三级")
            else:
                raise ValueError(f"不支持的级别: {level}")

            if df is not None and not df.empty:
                # 重命名列
                df.rename(columns={
                    '指数代码': 'sector_code',
                    '行业名称': 'sector_name'
                }, inplace=True)

                # 添加级别字段
                df['level'] = level

                # 提取父级代码（对于二、三级行业）
                df['parent_code'] = None
                if level in ['SW2', 'SW3']:
                    # 申万二、三级代码的前 4 位是一级代码
                    df['parent_code'] = df['sector_code'].str[:4] + '00'

            return df

        except Exception as e:
            print(f"AKShare 获取申万行业分类失败: {e}")
            return pd.DataFrame()

    def fetch_sector_index_daily(
        self,
        sector_code: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """获取板块指数日线数据

        Args:
            sector_code: 板块代码（如 '801010'）
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
            >>> df = adapter.fetch_sector_index_daily('801010', '2024-01-01', '2024-12-31')
            >>> print(df.head())
        """
        try:
            # AKShare 的申万指数接口
            df = self.ak.sw_index_daily(
                symbol=sector_code,
                start_date=start_date,
                end_date=end_date
            )

            if df is not None and not df.empty:
                # 重命名列
                df.rename(columns={
                    'date': 'trade_date',
                    'open': 'open_price',
                    'volume': 'volume',
                    'amount': 'amount',
                    'turnover': 'turnover_rate'
                }, inplace=True)

                # 转换日期格式
                df['trade_date'] = pd.to_datetime(df['trade_date'])

                # 计算涨跌幅
                df['change_pct'] = df['close'].pct_change() * 100
                df['change_pct'].fillna(0, inplace=True)

                # 选择需要的列
                columns = [
                    'trade_date', 'open_price', 'high', 'low', 'close',
                    'volume', 'amount', 'change_pct'
                ]
                if 'turnover_rate' in df.columns:
                    columns.append('turnover_rate')

                df = df[columns]

            return df

        except Exception as e:
            print(f"AKShare 获取板块 {sector_code} 指数数据失败: {e}")
            return pd.DataFrame()

    def fetch_sector_constituents(
        self,
        sector_code: str,
        date: Optional[str] = None
    ) -> pd.DataFrame:
        """获取板块成分股

        Args:
            sector_code: 板块代码
            date: 查询日期（'2024-01-01'），默认为最新

        Returns:
            DataFrame with columns:
            - stock_code: 成分股代码
            - stock_name: 成分股名称

        Examples:
            >>> adapter = AKShareSectorAdapter()
            >>> df = adapter.fetch_sector_constituents('801010')
            >>> print(df.head())
        """
        try:
            # AKShare 获取申万行业成分股
            # 先获取板块成分股代码列表
            df = self.ak.sw_index_cons(symbol=f"申万{sector_code[:2]}")

            if df is not None and not df.empty:
                # 重命名列
                df.rename(columns={
                    '股票代码': 'stock_code',
                    '股票名称': 'stock_name'
                }, inplace=True)

                # 选择需要的列
                df = df[['stock_code', 'stock_name']]

            return df

        except Exception as e:
            print(f"AKShare 获取板块 {sector_code} 成分股失败: {e}")
            return pd.DataFrame()

    def fetch_all_sector_codes(self, level: str = 'SW1') -> List[str]:
        """获取所有板块代码列表

        Args:
            level: 行业级别

        Returns:
            板块代码列表

        Examples:
            >>> adapter = AKShareSectorAdapter()
            >>> codes = adapter.fetch_all_sector_codes(level='SW1')
            >>> print(codes[:10])
        """
        df = self.fetch_sw_industry_classify(level=level)

        if df is not None and not df.empty:
            return df['sector_code'].tolist()

        return []
