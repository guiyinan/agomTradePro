"""
板块数据 - Tushare 适配器

遵循项目架构约束：
- 封装 Tushare API 调用
- 延迟初始化（避免启动时必须有 token）
- 返回 Pandas DataFrame
"""

from datetime import date, datetime
from typing import Optional

import pandas as pd

from shared.config.secrets import get_secrets
from shared.infrastructure.tushare_client import create_tushare_pro_client


class TushareSectorAdapter:
    """Tushare 板块数据适配器

    职责：
    1. 获取申万行业分类
    2. 获取申万行业指数日线
    3. 获取板块成分股
    """

    def __init__(self):
        """延迟初始化（避免启动时必须有 token）"""
        self.pro = None

    def _ensure_initialized(self):
        """确保已初始化"""
        if self.pro is None:
            try:
                import tushare as ts
            except ImportError:
                raise ImportError("请安装 tushare: pip install tushare")

            token = get_secrets().data_sources.tushare_token
            if not token:
                raise ValueError("Tushare token 未配置")
            self.pro = create_tushare_pro_client(token=token)

    def fetch_sw_industry_classify(
        self,
        level: str = 'L1'
    ) -> pd.DataFrame:
        """获取申万行业分类

        Args:
            level: 行业级别（L1=一级, L2=二级, L3=三级）

        Returns:
            DataFrame with columns:
            - index_code: 行业代码
            - industry_name: 行业名称
            - level: 级别
            - parent_code: 父级代码

        Examples:
            >>> adapter = TushareSectorAdapter()
            >>> df = adapter.fetch_sw_industry_classify(level='L1')
            >>> print(df.head())
        """
        self._ensure_initialized()

        try:
            df = self.pro.index_classify(
                level='L1' if level == 'SW1' else ('L2' if level == 'SW2' else 'L3'),
                src='SW2021'
            )
        except Exception as e:
            # 如果新接口失败，尝试旧接口
            df = self.pro.index_classify(level=level, src='SW')

        if df is not None and not df.empty:
            # 重命名列以统一命名
            df.rename(columns={
                'index_code': 'sector_code',
                'industry_name': 'sector_name'
            }, inplace=True)

            # 映射级别名称
            level_map = {'L1': 'SW1', 'L2': 'SW2', 'L3': 'SW3'}
            df['level'] = level_map.get(level, level)

        return df

    def fetch_sector_index_daily(
        self,
        sector_code: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """获取板块指数日线数据

        Args:
            sector_code: 板块代码（如 '801010.SI'）
            start_date: 开始日期（'20240101'）
            end_date: 结束日期（'20241231'）

        Returns:
            DataFrame with columns:
            - trade_date: 交易日期
            - open: 开盘价
            - high: 最高价
            - low: 最低价
            - close: 收盘价
            - vol: 成交量（手）
            - amount: 成交额（元）
            - change_pct: 涨跌幅（%）

        Examples:
            >>> adapter = TushareSectorAdapter()
            >>> df = adapter.fetch_sector_index_daily('801010.SI', '20240101', '20241231')
            >>> print(df.head())
        """
        self._ensure_initialized()

        # 确保代码格式正确（申万指数需要加 .SI 后缀）
        ts_code = sector_code if '.SI' in sector_code else f"{sector_code}.SI"

        df = self.pro.daily(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            fields='trade_date,open,high,low,close,vol,amount'
        )

        if df is not None and not df.empty:
            # 计算涨跌幅
            df['change_pct'] = df['close'].pct_change() * 100
            df['change_pct'].fillna(0, inplace=True)

            # 转换日期格式
            df['trade_date'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')

            # 重命名列
            df.rename(columns={
                'vol': 'volume',
                'open': 'open_price'
            }, inplace=True)

        return df

    def fetch_sector_constituents(
        self,
        sector_code: str
    ) -> pd.DataFrame:
        """获取板块成分股

        Args:
            sector_code: 板块代码

        Returns:
            DataFrame with columns:
            - con_code: 成分股代码
            - con_name: 成分股名称
            - in_date: 纳入日期
            - out_date: 剔除日期

        Examples:
            >>> adapter = TushareSectorAdapter()
            >>> df = adapter.fetch_sector_constituents('801010.SI')
            >>> print(df.head())
        """
        self._ensure_initialized()

        # Tushare 没有直接的板块成分股接口
        # 需要通过 index_member 接口获取
        # 这部分功能暂时留空，后续可以通过 AKShare 实现

        raise NotImplementedError(
            "Tushare 暂不提供板块成分股接口，请使用 AKShare 适配器"
        )

    def fetch_all_sector_index_daily(
        self,
        sector_codes: list,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """批量获取多个板块的日线数据

        Args:
            sector_codes: 板块代码列表
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            DataFrame with columns:
            - sector_code: 板块代码
            - trade_date: 交易日期
            - open: 开盘价
            - high: 最高价
            - low: 最低价
            - close: 收盘价
            - vol: 成交量
            - amount: 成交额
            - change_pct: 涨跌幅
        """
        all_data = []

        for sector_code in sector_codes:
            try:
                df = self.fetch_sector_index_daily(
                    sector_code, start_date, end_date
                )
                if df is not None and not df.empty:
                    df['sector_code'] = sector_code.replace('.SI', '')
                    all_data.append(df)
            except Exception as e:
                # 单个板块获取失败不影响其他板块
                print(f"获取板块 {sector_code} 数据失败: {e}")
                continue

        if all_data:
            result = pd.concat(all_data, ignore_index=True)
            return result

        return pd.DataFrame()
