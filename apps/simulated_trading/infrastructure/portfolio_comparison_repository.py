"""Concrete read adapters for two-portfolio comparison."""

from datetime import date

from apps.data_center.application.dtos import ResolveAssetRequest
from apps.data_center.application.public import get_asset_repository_port
from apps.data_center.application.query_use_cases import ResolveAssetUseCase
from apps.simulated_trading.application.performance_use_cases import (
    GetAccountPerformanceReportUseCase,
    ListAccountValuationTimelineUseCase,
)
from apps.simulated_trading.application.repository_provider import (
    get_simulated_account_repository,
    get_simulated_position_repository,
)
from apps.simulated_trading.domain.entities import PerformanceReport, ValuationTimelinePoint
from apps.simulated_trading.domain.portfolio_comparison import (
    PortfolioComparisonAccount,
    PortfolioComparisonHolding,
)
from shared.numeric import safe_float


class DjangoPortfolioComparisonReadRepository:
    """Read existing account, position and canonical asset-master contracts."""

    def __init__(self) -> None:
        self._industry_by_code: dict[str, str | None] = {}

    def get_account(self, account_id: int) -> PortfolioComparisonAccount | None:
        """Return one existing account's comparison identity."""

        account = get_simulated_account_repository().get_by_id(account_id)
        if account is None:
            return None
        return PortfolioComparisonAccount(
            account_id=account.account_id,
            account_name=account.account_name,
        )

    def list_holdings(self, account_id: int) -> list[PortfolioComparisonHolding]:
        """Return current positive holdings with unknown values kept nullable."""

        positions = get_simulated_position_repository().get_by_account(account_id)
        return [
            PortfolioComparisonHolding(
                asset_code=position.asset_code,
                asset_name=position.asset_name,
                industry=self._industry(position.asset_code),
                market_value=(
                    safe_float(position.market_value) if position.valuation_known is True else None
                ),
            )
            for position in positions
            if position.quantity > 0
        ]

    def _industry(self, asset_code: str) -> str | None:
        if asset_code not in self._industry_by_code:
            asset = ResolveAssetUseCase(get_asset_repository_port()).execute(
                ResolveAssetRequest(code=asset_code)
            )
            self._industry_by_code[asset_code] = (
                asset.industry.strip() if asset is not None and asset.industry.strip() else None
            )
        return self._industry_by_code[asset_code]


class DjangoPortfolioComparisonPerformanceProvider:
    """Adapt the canonical performance use cases to the comparison port."""

    def __init__(
        self,
        *,
        report_use_case: GetAccountPerformanceReportUseCase,
        timeline_use_case: ListAccountValuationTimelineUseCase,
    ) -> None:
        self._report_use_case = report_use_case
        self._timeline_use_case = timeline_use_case

    def get_report(self, account_id: int, start_date: date, end_date: date) -> PerformanceReport:
        """Return the canonical account performance report."""

        return self._report_use_case.execute(account_id, start_date, end_date)

    def get_timeline(
        self, account_id: int, start_date: date, end_date: date
    ) -> list[ValuationTimelinePoint]:
        """Return the canonical account valuation timeline."""

        return self._timeline_use_case.execute(account_id, start_date, end_date)
