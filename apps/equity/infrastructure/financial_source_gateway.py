"""
财务数据外部来源网关。

使用 Tushare Pro API 获取财务数据。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import List, Optional

from shared.infrastructure.tushare_client import create_tushare_pro_client

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FinancialRecord:
    """财务数据记录"""
    stock_code: str
    report_date: date
    report_type: str
    revenue: Decimal
    net_profit: Decimal
    revenue_growth: float | None
    net_profit_growth: float | None
    total_assets: Decimal
    total_liabilities: Decimal
    equity: Decimal
    roe: float
    roa: float | None
    debt_ratio: float


@dataclass
class FinancialSyncBatch:
    source_provider: str
    stock_code: str
    records: list[FinancialRecord]


class TushareFinancialGateway:
    """Tushare 财务数据网关"""

    def __init__(self, token: str, http_url: str | None = None):
        self.token = token
        self.http_url = http_url

    def fetch(self, stock_code: str, periods: int = 8) -> FinancialSyncBatch:
        """
        获取财务数据

        Args:
            stock_code: 股票代码（如 000001.SZ）
            periods: 获取最近几个报告期（默认 8 个，约 2 年）

        Returns:
            FinancialSyncBatch
        """
        import pandas as pd
        pro = create_tushare_pro_client(token=self.token, http_url=self.http_url)

        # 1. 获取利润表
        income_df = pro.income(
            ts_code=stock_code,
            fields='ts_code,ann_date,f_ann_date,end_date,revenue,n_income',
        )

        # 2. 获取资产负债表
        balance_df = pro.balancesheet(
            ts_code=stock_code,
            fields='ts_code,end_date,total_assets,total_liab,total_hldr_eqy_exc_min_int',
        )

        # 3. 获取财务指标
        indicator_df = pro.fina_indicator(
            ts_code=stock_code,
            fields='ts_code,end_date,roe,roa,dt_eps_yoy,or_yoy',
        )

        if income_df is None or income_df.empty:
            return FinancialSyncBatch(source_provider="tushare", stock_code=stock_code, records=[])

        # 合并数据
        income_df['end_date'] = pd.to_datetime(income_df['end_date']).dt.date
        balance_df['end_date'] = pd.to_datetime(balance_df['end_date']).dt.date
        indicator_df['end_date'] = pd.to_datetime(indicator_df['end_date']).dt.date

        # 取最近 periods 个报告期
        income_df = income_df.sort_values('end_date', ascending=False).head(periods)

        records: list[FinancialRecord] = []

        for _, row in income_df.iterrows():
            report_date = row['end_date']

            # 查找对应的资产负债表数据
            balance_row = balance_df[balance_df['end_date'] == report_date]
            indicator_row = indicator_df[indicator_df['end_date'] == report_date]

            total_assets = balance_row['total_assets'].iloc[0] if not balance_row.empty else 0
            total_liab = balance_row['total_liab'].iloc[0] if not balance_row.empty else 0
            equity = balance_row['total_hldr_eqy_exc_min_int'].iloc[0] if not balance_row.empty else 0

            roe = indicator_row['roe'].iloc[0] if not indicator_row.empty else None
            roa = indicator_row['roa'].iloc[0] if not indicator_row.empty else None
            revenue_growth = indicator_row['or_yoy'].iloc[0] if not indicator_row.empty else None
            profit_growth = indicator_row['dt_eps_yoy'].iloc[0] if not indicator_row.empty else None

            # 计算资产负债率
            debt_ratio = (total_liab / total_assets * 100) if total_assets and total_assets > 0 else 0

            # 确定报告类型
            month = report_date.month
            if month == 3:
                report_type = '1Q'
            elif month == 6:
                report_type = '2Q'
            elif month == 9:
                report_type = '3Q'
            else:
                report_type = '4Q'

            records.append(FinancialRecord(
                stock_code=stock_code,
                report_date=report_date,
                report_type=report_type,
                revenue=Decimal(str(row['revenue'] or 0)),
                net_profit=Decimal(str(row['n_income'] or 0)),
                revenue_growth=float(revenue_growth) if revenue_growth == revenue_growth else None,
                net_profit_growth=float(profit_growth) if profit_growth == profit_growth else None,
                total_assets=Decimal(str(total_assets or 0)),
                total_liabilities=Decimal(str(total_liab or 0)),
                equity=Decimal(str(equity or 0)),
                roe=float(roe) if roe == roe else 0.0,
                roa=float(roa) if roa == roa else None,
                debt_ratio=float(debt_ratio) if debt_ratio == debt_ratio else 0.0,
            ))

        return FinancialSyncBatch(source_provider="tushare", stock_code=stock_code, records=records)


class AKShareFinancialGateway:
    """AKShare 财务数据网关（免费）"""

    def fetch(self, stock_code: str, periods: int = 8) -> FinancialSyncBatch:
        """
        获取财务数据

        使用新浪财经接口获取资产负债表，计算财务指标
        """
        import akshare as ak
        import pandas as pd

        symbol = stock_code.split('.')[0]
        # 转换为新浪格式（sh600000 或 sz000001）
        market = stock_code.split('.')[1] if '.' in stock_code else 'SZ'
        sina_code = f"{'sh' if market == 'SH' else 'sz'}{symbol}"

        try:
            # 获取资产负债表
            balance_df = ak.stock_financial_report_sina(stock=sina_code, symbol='资产负债表')

            if balance_df is None or balance_df.empty:
                return FinancialSyncBatch(source_provider="akshare", stock_code=stock_code, records=[])

            # 取最近 periods 个报告期
            balance_df = balance_df.head(periods)
            records: list[FinancialRecord] = []

            for _, row in balance_df.iterrows():
                # 解析日期（格式：20250930）
                try:
                    date_str = str(row.get('报告日', ''))
                    if len(date_str) == 8:
                        report_date = date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
                    else:
                        continue
                except Exception:
                    continue

                month = report_date.month
                if month == 3:
                    report_type = '1Q'
                elif month == 6:
                    report_type = '2Q'
                elif month == 9:
                    report_type = '3Q'
                else:
                    report_type = '4Q'

                # 提取财务数据
                total_assets = self._safe_decimal(row.get('资产总计'))
                total_liab = self._safe_decimal(row.get('负债合计'))
                equity = self._safe_decimal(row.get('归属于母公司股东的权益', row.get('股东权益', row.get('负债及股东权益总计'))))

                # 计算资产负债率
                debt_ratio = float(total_liab / total_assets * 100) if total_assets and total_assets > 0 else 0.0

                records.append(FinancialRecord(
                    stock_code=stock_code,
                    report_date=report_date,
                    report_type=report_type,
                    revenue=Decimal('0'),  # 需要利润表
                    net_profit=Decimal('0'),
                    revenue_growth=None,
                    net_profit_growth=None,
                    total_assets=total_assets,
                    total_liabilities=total_liab,
                    equity=equity,
                    roe=0.0,  # 需要利润表计算
                    roa=None,
                    debt_ratio=debt_ratio,
                ))

            # 尝试获取利润表补充数据
            try:
                income_df = ak.stock_financial_report_sina(stock=sina_code, symbol='利润表')
                if income_df is not None and not income_df.empty:
                    income_df['报告日'] = income_df['报告日'].astype(str)
                    for record in records:
                        match = income_df[income_df['报告日'].str.startswith(record.report_date.strftime('%Y%m'))]
                        if not match.empty:
                            row = match.iloc[0]
                            # 更新收入和利润
                            object.__setattr__(record, 'revenue', self._safe_decimal(row.get('营业总收入', row.get('营业收入'))))
                            object.__setattr__(record, 'net_profit', self._safe_decimal(row.get('归属于母公司股东的净利润', row.get('净利润'))))
                            # 计算 ROE
                            if record.equity and record.equity > 0 and record.net_profit:
                                annualized_profit = record.net_profit * (4 if record.report_type == '1Q' else 2 if record.report_type == '2Q' else 4/3 if record.report_type == '3Q' else 1)
                                roe = float(annualized_profit / record.equity * 100)
                                object.__setattr__(record, 'roe', roe)
            except Exception as e:
                logger.warning(f"Failed to fetch income statement for {stock_code}: {e}")

            return FinancialSyncBatch(source_provider="akshare", stock_code=stock_code, records=records)

        except Exception as e:
            logger.error(f"AKShare financial fetch failed for {stock_code}: {e}")
            return FinancialSyncBatch(source_provider="akshare", stock_code=stock_code, records=[])

    def _safe_float(self, value) -> float | None:
        import pandas as pd
        try:
            if value is None or value == '' or (isinstance(value, float) and pd.isna(value)):
                return None
            return float(value)
        except:
            return None

    def _safe_decimal(self, value) -> Decimal:
        import pandas as pd
        try:
            if value is None or value == '' or (isinstance(value, float) and pd.isna(value)):
                return Decimal('0')
            return Decimal(str(value))
        except:
            return Decimal('0')
