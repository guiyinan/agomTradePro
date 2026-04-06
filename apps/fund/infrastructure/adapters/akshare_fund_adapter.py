"""
Legacy AKShare fund adapter backed by internal facts.

The adapter API is kept for existing callers, but data is now served from
data_center and local fund tables instead of direct AKShare imports.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from apps.data_center.infrastructure.repositories import (
    FundNavRepository as DataCenterFundNavRepository,
)
from apps.fund.infrastructure.models import (
    FundHoldingModel,
    FundInfoModel,
    FundNetValueModel,
    FundSectorAllocationModel,
)


class AkShareFundAdapter:
    """Compatibility adapter for fund reads after data-center cutover."""

    def __init__(self):
        self._dc_nav_repo = DataCenterFundNavRepository()

    def fetch_fund_list_em(self) -> pd.DataFrame:
        rows = list(
            FundInfoModel._default_manager.filter(is_active=True)
            .values(
                "fund_code",
                "fund_name",
                "fund_type",
                "investment_style",
                "management_company",
                "fund_scale",
            )
            .order_by("fund_code")
        )
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        return df.rename(
            columns={
                "fund_code": "代码",
                "fund_name": "名称",
                "fund_type": "基金类型",
                "investment_style": "投资风格",
                "management_company": "基金公司",
                "fund_scale": "基金规模",
            }
        )

    def fetch_fund_info_em(self, fund_code: str) -> pd.DataFrame:
        rows = list(
            FundInfoModel._default_manager.filter(fund_code=fund_code, is_active=True).values(
                "fund_code",
                "fund_name",
                "fund_type",
                "investment_style",
                "setup_date",
                "management_company",
                "custodian",
                "fund_scale",
            )
        )
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        return df.rename(
            columns={
                "fund_code": "基金代码",
                "fund_name": "基金名称",
                "fund_type": "基金类型",
                "investment_style": "投资风格",
                "setup_date": "成立日期",
                "management_company": "管理人",
                "custodian": "托管人",
                "fund_scale": "基金规模",
            }
        )

    def fetch_fund_nav_em(self, fund_code: str) -> pd.DataFrame:
        facts = self._dc_nav_repo.get_series(fund_code)
        if facts:
            return pd.DataFrame(
                [
                    {
                        "nav_date": fact.nav_date,
                        "unit_nav": fact.nav,
                        "accum_nav": fact.acc_nav,
                        "daily_return": fact.daily_return,
                        "source": fact.source,
                    }
                    for fact in reversed(facts)
                ]
            )

        rows = list(
            FundNetValueModel._default_manager.filter(fund_code=fund_code)
            .values("nav_date", "unit_nav", "accum_nav", "daily_return")
            .order_by("nav_date")
        )
        return pd.DataFrame(rows) if rows else pd.DataFrame()

    def fetch_fund_portfolio_em(self, fund_code: str, year: int, quarter: int) -> pd.DataFrame:
        month = quarter * 3
        cutoff = date(year, month, 1)
        rows = list(
            FundHoldingModel._default_manager.filter(fund_code=fund_code, report_date__year=year)
            .values(
                "stock_code",
                "stock_name",
                "holding_amount",
                "holding_value",
                "holding_ratio",
                "report_date",
            )
            .order_by("-report_date", "-holding_ratio")
        )
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        if "report_date" in df.columns:
            df = df[df["report_date"] <= cutoff]
        return df.rename(
            columns={
                "stock_code": "股票代码",
                "stock_name": "股票名称",
                "holding_amount": "持有数量",
                "holding_value": "持仓市值",
                "holding_ratio": "占净值比例",
            }
        )

    def fetch_fund_rank_em(self, indicator: str = "收益率") -> pd.DataFrame:
        if indicator == "规模":
            return self.fetch_fund_scale_rank()
        return pd.DataFrame()

    def fetch_fund_sector_allocation(self, fund_code: str, year: int, quarter: int) -> pd.DataFrame:
        rows = list(
            FundSectorAllocationModel._default_manager.filter(
                fund_code=fund_code,
                report_date__year=year,
            )
            .values("sector_name", "allocation_ratio", "report_date")
            .order_by("-report_date", "-allocation_ratio")
        )
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).rename(
            columns={
                "sector_name": "行业名称",
                "allocation_ratio": "配置比例",
                "report_date": "报告期",
            }
        )

    def fetch_fund_scale_rank(self) -> pd.DataFrame:
        rows = list(
            FundInfoModel._default_manager.filter(is_active=True)
            .exclude(fund_scale__isnull=True)
            .values("fund_code", "fund_name", "fund_scale")
            .order_by("-fund_scale")
        )
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).rename(
            columns={
                "fund_code": "基金代码",
                "fund_name": "基金名称",
                "fund_scale": "基金规模",
            }
        )
