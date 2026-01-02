"""
Tushare 个股数据适配器

遵循四层架构规范：
- Infrastructure 层允许导入外部库（tushare、pandas）
- 负责与外部 API 交互
"""

from typing import Optional, Dict, Any
import pandas as pd

from shared.config.secrets import get_secrets


class TushareStockAdapter:
    """Tushare 个股数据适配器"""

    def __init__(self):
        """延迟初始化（避免启动时必须有 token）"""
        self._pro = None

    @property
    def pro(self):
        """延迟初始化 Tushare Pro API"""
        if self._pro is None:
            token = get_secrets().data_sources.tushare_token
            if not token:
                raise ValueError("Tushare token 未配置，请在 secrets.json 中配置")
            import tushare as ts
            self._pro = ts.pro_api(token)
        return self._pro

    def fetch_stock_list(self) -> pd.DataFrame:
        """
        获取全部 A 股列表

        Returns:
            DataFrame with columns:
                ts_code: 股票代码（如 '000001.SZ'）
                symbol: 股票代码（如 '000001'）
                name: 股票名称
                area: 地域
                industry: 行业
                list_date: 上市日期
        """
        # 获取上交所、深交所、北交所股票
        df_list = []
        for market in ['SSE', 'SZSE', 'BSE']:
            df = self.pro.stock_basic(
                exchange=market,
                list_status='L',  # 上市状态
                fields='ts_code,symbol,name,area,industry,list_date'
            )
            df_list.append(df)

        result = pd.concat(df_list, ignore_index=True)
        return result

    def fetch_daily_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """
        获取日线数据

        Args:
            stock_code: 股票代码（如 '000001.SZ'）
            start_date: 开始日期（'20240101'）
            end_date: 结束日期（'20241231'）

        Returns:
            DataFrame with columns:
                trade_date: 交易日期
                open: 开盘价
                high: 最高价
                low: 最低价
                close: 收盘价
                vol: 成交量（手）
                amount: 成交额（元）
        """
        df = self.pro.daily(
            ts_code=stock_code,
            start_date=start_date,
            end_date=end_date,
            fields='trade_date,open,high,low,close,vol,amount'
        )

        if df.empty:
            return df

        # 转换日期格式
        df['trade_date'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')

        return df

    def fetch_financial_data(
        self,
        stock_code: str,
        start_period: str,
        end_period: str
    ) -> pd.DataFrame:
        """
        获取财务数据（合并利润表、资产负债表、现金流量表）

        Args:
            stock_code: 股票代码
            start_period: 开始报告期（'20220331'）
            end_period: 结束报告期（'20241231'）

        Returns:
            DataFrame with columns:
                end_date: 报告期
                revenue: 营业收入
                n_income: 净利润
                n_income_attr_p: 归母净利润
                total_assets: 总资产
                total_liab: 总负债
                total_hldr_eqy_inc_min_int: 股东权益
                roe: 净资产收益率
                roa: 总资产收益率
                debt_to_assets: 资产负债率
                or_yoy: 营收增长率
                n_income_attr_p_yoy: 净利润增长率
        """
        # 1. 利润表
        income = self.pro.income(
            ts_code=stock_code,
            start_date=start_period,
            end_date=end_period,
            fields='ts_code,end_date,revenue,n_income,n_income_attr_p'
        )

        # 2. 资产负债表
        balance = self.pro.balancesheet(
            ts_code=stock_code,
            start_date=start_period,
            end_date=end_period,
            fields='ts_code,end_date,total_assets,total_liab,total_hldr_eqy_inc_min_int'
        )

        # 3. 财务指标（ROE 等）
        indicators = self.pro.fina_indicator(
            ts_code=stock_code,
            start_date=start_period,
            end_date=end_period,
            fields='ts_code,end_date,roe,roa,debt_to_assets,or_yoy,n_income_attr_p_yoy'
        )

        # 合并数据
        if income.empty or balance.empty or indicators.empty:
            return pd.DataFrame()

        merged = income.merge(balance, on=['ts_code', 'end_date'], how='outer')
        merged = merged.merge(indicators, on=['ts_code', 'end_date'], how='outer')

        # 转换日期格式
        merged['end_date'] = pd.to_datetime(merged['end_date'], format='%Y%m%d')

        return merged

    def fetch_valuation_data(
        self,
        stock_code: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """
        获取估值数据

        Args:
            stock_code: 股票代码
            start_date: 开始日期（'20240101'）
            end_date: 结束日期（'20241231'）

        Returns:
            DataFrame with columns:
                trade_date: 交易日期
                pe: 市盈率（动态）
                pe_ttm: 市盈率（TTM）
                pb: 市净率
                ps: 市销率
                total_mv: 总市值（元）
                circ_mv: 流通市值（元）
                dv_ratio: 股息率（%）
        """
        df = self.pro.daily_basic(
            ts_code=stock_code,
            start_date=start_date,
            end_date=end_date,
            fields='trade_date,pe,pe_ttm,pb,ps,total_mv,circ_mv,dv_ratio'
        )

        if df.empty:
            return df

        # 转换日期格式
        df['trade_date'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')

        return df

    def fetch_stock_info(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """
        获取单只股票的基本信息

        Args:
            stock_code: 股票代码

        Returns:
            字典，包含股票基本信息，如果不存在则返回 None
        """
        df = self.pro.stock_basic(
            ts_code=stock_code,
            fields='ts_code,symbol,name,area,industry,list_date'
        )

        if df.empty:
            return None

        return df.iloc[0].to_dict()
