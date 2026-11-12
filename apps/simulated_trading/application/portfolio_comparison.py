"""Application orchestration for read-only two-portfolio comparison."""

from datetime import date
from typing import Protocol

from apps.simulated_trading.domain.entities import PerformanceReport, ValuationTimelinePoint
from apps.simulated_trading.domain.portfolio_comparison import (
    PortfolioComparisonAccount,
    PortfolioComparisonHolding,
    PortfolioComparisonResult,
    compare_portfolio_data,
)


class PortfolioComparisonReadRepository(Protocol):
    """Read account identity and current holdings without exposing ORM."""

    def get_account(self, account_id: int) -> PortfolioComparisonAccount | None:
        """Return one comparison account when it exists."""
        ...

    def list_holdings(self, account_id: int) -> list[PortfolioComparisonHolding]:
        """Return current positive holdings with explicit valuation/classification gaps."""
        ...


class PortfolioComparisonPerformanceProvider(Protocol):
    """Reuse the canonical account performance and timeline use cases."""

    def get_report(self, account_id: int, start_date: date, end_date: date) -> PerformanceReport:
        """Return one account's cash-flow-aware performance report."""
        ...

    def get_timeline(
        self, account_id: int, start_date: date, end_date: date
    ) -> list[ValuationTimelinePoint]:
        """Return one account's historical valuation timeline."""
        ...


class CompareInvestmentPortfoliosUseCase:
    """Compare two authorized accounts through injected read-only ports."""

    def __init__(
        self,
        *,
        read_repository: PortfolioComparisonReadRepository,
        performance_provider: PortfolioComparisonPerformanceProvider,
    ) -> None:
        self._read_repository = read_repository
        self._performance_provider = performance_provider

    def execute(
        self,
        *,
        left_account_id: int,
        right_account_id: int,
        start_date: date,
        end_date: date,
    ) -> PortfolioComparisonResult:
        """Build one common-period comparison without mutating financial records."""

        if left_account_id <= 0 or right_account_id <= 0:
            raise ValueError("投资组合 ID 必须为正整数")
        if left_account_id == right_account_id:
            raise ValueError("请选择两个不同的投资组合")
        if start_date >= end_date:
            raise ValueError("结束日期必须晚于开始日期")
        left_account = self._read_repository.get_account(left_account_id)
        right_account = self._read_repository.get_account(right_account_id)
        if left_account is None or right_account is None:
            raise ValueError("投资组合不存在")

        left_report = self._performance_provider.get_report(left_account_id, start_date, end_date)
        right_report = self._performance_provider.get_report(right_account_id, start_date, end_date)
        left_timeline = self._performance_provider.get_timeline(
            left_account_id, start_date, end_date
        )
        right_timeline = self._performance_provider.get_timeline(
            right_account_id, start_date, end_date
        )
        return compare_portfolio_data(
            left_account=left_account,
            right_account=right_account,
            left_report=left_report,
            right_report=right_report,
            left_timeline=left_timeline,
            right_timeline=right_timeline,
            left_holdings=self._read_repository.list_holdings(left_account_id),
            right_holdings=self._read_repository.list_holdings(right_account_id),
        )
