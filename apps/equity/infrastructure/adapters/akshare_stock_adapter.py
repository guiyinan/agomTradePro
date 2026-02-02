"""
AKShare 个股数据适配器

功能：
1. 获取 A 股股票列表
2. 获取股票日线行情数据
3. 获取股票实时行情
4. 获取股票财务数据

AKShare 不需要 token，适合作为默认数据源。
"""

import pandas as pd
from typing import Optional, List
from datetime import datetime, date


class AKShareStockAdapter:
    """AKShare 个股数据适配器"""

    def __init__(self):
        """初始化适配器"""
        try:
            import akshare as ak
            self.ak = ak
        except ImportError:
            raise ImportError("请安装 akshare: pip install akshare")

    def fetch_stock_list_a(self) -> pd.DataFrame:
        """获取全部 A 股列表

        Returns:
            DataFrame with columns:
                stock_code: 股票代码（如 '000001'）
                name: 股票名称
                industry: 所属行业
                area: 地域
                market: 市场（沪市/深市/北交所）
        """
        try:
            # 获取 A 股实时行情数据（包含股票列表）
            df = self.ak.stock_zh_a_spot_em()

            if df is not None and not df.empty:
                # 重命名列以匹配系统格式
                df = df.rename(columns={
                    '代码': 'stock_code',
                    '名称': 'name',
                    '最新价': 'price',
                    '涨跌幅': 'change_pct',
                    '涨跌额': 'change_amount',
                    '成交量': 'volume',
                    '成交额': 'amount',
                    '振幅': 'amplitude',
                    '最高': 'high',
                    '最低': 'low',
                    '今开': 'open',
                    '昨收': 'pre_close',
                    '换手率': 'turnover_rate',
                    '市盈率-动态': 'pe_ttm',
                    '市净率': 'pb',
                })

                # 添加市场标识
                df['market'] = df['stock_code'].apply(self._get_market_from_code)

                return df

        except Exception as e:
            print(f"AKShare 获取 A 股列表失败: {e}")

        return pd.DataFrame()

    def _get_market_from_code(self, code: str) -> str:
        """根据股票代码判断市场"""
        if code.startswith('6'):
            return 'SH'  # 上交所
        elif code.startswith(('0', '3')):
            return 'SZ'  # 深交所
        elif code.startswith('8') or code.startswith('4'):
            return 'BJ'  # 北交所
        return 'UNKNOWN'

    def fetch_stock_info(self, stock_code: str) -> dict:
        """获取单个股票详细信息

        Args:
            stock_code: 股票代码（如 '000001'，不需要后缀）

        Returns:
            dict with keys: name, industry, list_date, etc.
        """
        try:
            # 获取个股信息
            df = self.ak.stock_individual_info_em(symbol=stock_code)

            if df is not None and not df.empty:
                info = {}
                for _, row in df.iterrows():
                    key = row['item']
                    value = row['value']
                    info[key] = value

                return info

        except Exception as e:
            print(f"AKShare 获取股票 {stock_code} 信息失败: {e}")

        return {}

    def fetch_daily_data(
        self,
        stock_code: str,
        start_date: str = None,
        end_date: str = None
    ) -> pd.DataFrame:
        """获取日线数据

        Args:
            stock_code: 股票代码（如 '000001'）
            start_date: 开始日期（'20240101'）可选
            end_date: 结束日期（'20241231'）可选

        Returns:
            DataFrame with columns:
                date: 交易日期
                open: 开盘价
                high: 最高价
                low: 最低价
                close: 收盘价
                volume: 成交量
                amount: 成交额
                turnover_rate: 换手率
        """
        try:
            # 添加市场后缀（AKShare需要）
            full_code = self._format_code(stock_code)

            # 获取历史行情数据
            if start_date and end_date:
                # 有日期范围，使用历史数据接口
                df = self.ak.stock_zh_a_hist(
                    symbol=stock_code,
                    period="daily",
                    start_date=start_date.replace('-', ''),
                    end_date=end_date.replace('-', ''),
                    adjust=""
                )
            else:
                # 无日期范围，获取近期数据
                df = self.ak.stock_zh_a_hist(
                    symbol=stock_code,
                    period="daily",
                    adjust=""
                )

            if df is not None and not df.empty:
                # 重命名列
                df = df.rename(columns={
                    '日期': 'date',
                    '开盘': 'open',
                    '收盘': 'close',
                    '最高': 'high',
                    '最低': 'low',
                    '成交量': 'volume',
                    '成交额': 'amount',
                    '换手率': 'turnover_rate',
                })

                # 转换日期格式
                df['date'] = pd.to_datetime(df['date'])

                return df

        except Exception as e:
            print(f"AKShare 获取股票 {stock_code} 历史数据失败: {e}")

        return pd.DataFrame()

    def _format_code(self, code: str) -> str:
        """格式化股票代码（添加市场后缀）"""
        market = self._get_market_from_code(code)
        if market == 'SH':
            return f"{code}.SH"
        elif market == 'SZ':
            return f"{code}.SZ"
        elif market == 'BJ':
            return f"{code}.BJ"
        return code

    def fetch_realtime_data(self, stock_code: str) -> dict:
        """获取实时行情数据

        Args:
            stock_code: 股票代码

        Returns:
            dict with keys: price, change_pct, volume, amount, etc.
        """
        try:
            df = self.ak.stock_zh_a_spot_em()

            if df is not None and not df.empty:
                row = df[df['代码'] == stock_code]

                if not row.empty:
                    return {
                        'price': row['最新价'].values[0],
                        'change_pct': row['涨跌幅'].values[0],
                        'change_amount': row['涨跌额'].values[0],
                        'open': row['今开'].values[0],
                        'high': row['最高'].values[0],
                        'low': row['最低'].values[0],
                        'pre_close': row['昨收'].values[0],
                        'volume': row['成交量'].values[0],
                        'amount': row['成交额'].values[0],
                        'turnover_rate': row['换手率'].values[0],
                        'amplitude': row['振幅'].values[0],
                    }

        except Exception as e:
            print(f"AKShare 获取股票 {stock_code} 实时数据失败: {e}")

        return {}

    def fetch_index_data(self, index_code: str = '000001') -> pd.DataFrame:
        """获取指数数据

        Args:
            index_code: 指数代码（'000001'=上证指数, '399001'=深证成指）

        Returns:
            DataFrame with columns: date, open, high, low, close, volume, amount
        """
        try:
            if index_code == '000001':
                # 上证指数
                df = self.ak.index_zh_a_hist(symbol="上证指数", period="daily")
            elif index_code == '399001':
                # 深证成指
                df = self.ak.index_zh_a_hist(symbol="深证成指", period="daily")
            else:
                return pd.DataFrame()

            if df is not None and not df.empty:
                df = df.rename(columns={
                    '日期': 'date',
                    '开盘': 'open',
                    '收盘': 'close',
                    '最高': 'high',
                    '最低': 'low',
                    '成交量': 'volume',
                    '成交额': 'amount',
                })

                df['date'] = pd.to_datetime(df['date'])

                return df

        except Exception as e:
            print(f"AKShare 获取指数 {index_code} 数据失败: {e}")

        return pd.DataFrame()

    def fetch_financial_indicator(
        self,
        stock_code: str,
        indicator: str = '主要指标'
    ) -> pd.DataFrame:
        """获取财务指标数据

        Args:
            stock_code: 股票代码
            indicator: 指标类型（'主要指标', '盈利能力', '偿债能力', etc.）

        Returns:
            DataFrame with columns: date, various financial metrics
        """
        try:
            # AKShare 获取财务指标
            if indicator == '主要指标':
                df = self.ak.stock_financial_analysis_indicator(symbol=stock_code)
            else:
                df = self.ak.stock_financial_analysis_indicator(symbol=stock_code)

            if df is not None and not df.empty:
                return df

        except Exception as e:
            print(f"AKShare 获取股票 {stock_code} 财务指标失败: {e}")

        return pd.DataFrame()

    def fetch_industry_stocks(self, industry_name: str) -> List[str]:
        """获取行业成分股列表

        Args:
            industry_name: 行业名称

        Returns:
            List[str]: 股票代码列表
        """
        try:
            # 获取申万行业成分股
            df = self.ak.sw_stock_cons(symbol=industry_name)

            if df is not None and not df.empty:
                return df['股票代码'].tolist()

        except Exception as e:
            print(f"AKShare 获取行业 {industry_name} 成分股失败: {e}")

        return []

    def fetch_sector_list(self) -> pd.DataFrame:
        """获取板块/行业列表

        Returns:
            DataFrame with columns: sector_code, sector_name
        """
        try:
            # 获取申万一级行业
            df = self.ak.sw_index_cons(symbol="申万一级")

            if df is not None and not df.empty:
                df = df.rename(columns={
                    '指数代码': 'sector_code',
                    '行业名称': 'sector_name'
                })
                return df

        except Exception as e:
            print(f"AKShare 获取板块列表失败: {e}")

        return pd.DataFrame()
