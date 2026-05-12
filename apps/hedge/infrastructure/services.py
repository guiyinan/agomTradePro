"""
Hedge Module Infrastructure Layer - Integration Service

Integration service that coordinates data fetching, domain services,
and persistence for hedge portfolio management.
"""

from datetime import date

from apps.hedge.domain.entities import (
    CorrelationMetric,
    HedgeAlert,
    HedgePair,
    HedgePortfolio,
)
from apps.hedge.domain.services import (
    CorrelationMonitor,
    HedgeContext,
    HedgePortfolioService,
    HedgeRatioCalculator,
)
from apps.hedge.infrastructure.adapters import get_hedge_adapter
from apps.hedge.infrastructure.repositories import (
    CorrelationHistoryRepository,
    HedgeAlertRepository,
    HedgePairRepository,
    HedgePerformanceRepository,
    HedgePortfolioRepository,
)


class HedgeIntegrationService:
    """
    Integration service for hedge module.

    Bridges between domain services (pure business logic) and
    external dependencies (database, APIs).
    """

    def __init__(self):
        self.pair_repo = HedgePairRepository()
        self.correlation_repo = CorrelationHistoryRepository()
        self.portfolio_repo = HedgePortfolioRepository()
        self.alert_repo = HedgeAlertRepository()
        self.performance_repo = HedgePerformanceRepository()
        self.price_adapter = get_hedge_adapter()

    def _create_domain_context(self, calc_date: date) -> HedgeContext:
        """Create domain context with data accessors"""
        # Get all hedge pairs
        hedge_pairs = self.pair_repo.get_all(active_only=True)

        # Create price accessor function
        def get_asset_prices(asset_code: str, end_date: date, days: int) -> list[float] | None:
            return self.price_adapter.get_asset_prices(asset_code, end_date, days)

        # Create asset name accessor function
        def get_asset_name(asset_code: str) -> str | None:
            # Could be enhanced to fetch from database
            asset_names = {
                '510300': '沪深300ETF',
                '510500': '中证500ETF',
                '159915': '创业板ETF',
                '512100': '红利ETF',
                '511260': '10年国债ETF',
                '511880': '银行间国债ETF',
                '159985': '商品ETF',
            }
            return asset_names.get(asset_code, asset_code)

        return HedgeContext(
            calc_date=calc_date,
            hedge_pairs=hedge_pairs,
            get_asset_prices=get_asset_prices,
            get_asset_name=get_asset_name,
        )

    # ========================================================================
    # Correlation Monitoring
    # ========================================================================

    def calculate_correlation(
        self,
        asset1: str,
        asset2: str,
        calc_date: date | None = None,
        window_days: int = 60
    ) -> CorrelationMetric | None:
        """
        Calculate correlation between two assets.

        Args:
            asset1: First asset code
            asset2: Second asset code
            calc_date: Calculation date (default: today)
            window_days: Lookback window

        Returns:
            CorrelationMetric with correlation statistics
        """
        if calc_date is None:
            calc_date = date.today()

        context = self._create_domain_context(calc_date)
        monitor = CorrelationMonitor(context)

        metric = monitor.calculate_correlation(asset1, asset2, window_days)

        # Save to database if calculation succeeded
        if metric:
            self.correlation_repo.save(metric)

        return metric

    def get_correlation_matrix(
        self,
        asset_codes: list[str],
        calc_date: date | None = None,
        window_days: int = 60
    ) -> dict[str, dict[str, float]]:
        """
        Get correlation matrix for multiple assets.

        Args:
            asset_codes: List of asset codes
            calc_date: Calculation date
            window_days: Lookback window

        Returns:
            {asset1: {asset2: correlation}}
        """
        if calc_date is None:
            calc_date = date.today()

        context = self._create_domain_context(calc_date)
        service = HedgePortfolioService(context)

        return service.get_correlation_matrix(asset_codes, window_days)

    def monitor_hedge_pairs(
        self,
        calc_date: date | None = None
    ) -> list[HedgeAlert]:
        """
        Monitor all hedge pairs and generate alerts.

        Args:
            calc_date: Calculation date

        Returns:
            List of alerts for any issues found
        """
        if calc_date is None:
            calc_date = date.today()

        context = self._create_domain_context(calc_date)
        monitor = CorrelationMonitor(context)

        alerts = monitor.monitor_hedge_pairs()

        # Save alerts to database
        for alert in alerts:
            self.alert_repo.save_alert(alert)

        return alerts

    # ========================================================================
    # Hedge Portfolio Management
    # ========================================================================

    def update_hedge_portfolio(
        self,
        pair_name: str,
        calc_date: date | None = None
    ) -> HedgePortfolio | None:
        """
        Update hedge portfolio state for a pair.

        Args:
            pair_name: Hedge pair name
            calc_date: Calculation date

        Returns:
            HedgePortfolio with current state
        """
        if calc_date is None:
            calc_date = date.today()

        # Get hedge pair configuration
        pair = self.pair_repo.get_by_name(pair_name)
        if not pair:
            return None

        context = self._create_domain_context(calc_date)
        service = HedgePortfolioService(context)

        portfolio = service.update_hedge_portfolio(pair)

        if portfolio:
            # Save to database
            self.portfolio_repo.save_portfolio(portfolio)

        return portfolio

    def update_all_portfolios(
        self,
        calc_date: date | None = None
    ) -> list[HedgePortfolio]:
        """Update all active hedge portfolios"""
        if calc_date is None:
            calc_date = date.today()

        portfolios = []
        pairs = self.pair_repo.get_all(active_only=True)

        for pair in pairs:
            portfolio = self.update_hedge_portfolio(pair.name, calc_date)
            if portfolio:
                portfolios.append(portfolio)

        return portfolios

    def get_hedge_portfolio(self, pair_name: str) -> HedgePortfolio | None:
        """Get latest hedge portfolio state"""
        return self.portfolio_repo.get_latest_portfolio(pair_name)

    # ========================================================================
    # Hedge Effectiveness
    # ========================================================================

    def check_hedge_effectiveness(
        self,
        pair_name: str,
        calc_date: date | None = None
    ) -> dict | None:
        """
        Check effectiveness of a hedge pair.

        Args:
            pair_name: Hedge pair name
            calc_date: Calculation date

        Returns:
            Dictionary with effectiveness metrics
        """
        if calc_date is None:
            calc_date = date.today()

        pair = self.pair_repo.get_by_name(pair_name)
        if not pair:
            return None

        context = self._create_domain_context(calc_date)
        service = HedgePortfolioService(context)

        return service.check_hedge_effectiveness(pair)

    def get_all_effectiveness(
        self,
        calc_date: date | None = None
    ) -> list[dict]:
        """Get effectiveness for all active hedge pairs"""
        if calc_date is None:
            calc_date = date.today()

        results = []
        pairs = self.pair_repo.get_all(active_only=True)

        for pair in pairs:
            effectiveness = self.check_hedge_effectiveness(pair.name, calc_date)
            if effectiveness:
                results.append(effectiveness)

        return results

    # ========================================================================
    # Hedge Ratio Calculation
    # ========================================================================

    def calculate_hedge_ratio(
        self,
        pair_name: str,
        calc_date: date | None = None
    ) -> tuple[float, dict] | None:
        """
        Calculate optimal hedge ratio for a pair.

        Args:
            pair_name: Hedge pair name
            calc_date: Calculation date

        Returns:
            Tuple of (hedge_ratio, details_dict)
        """
        if calc_date is None:
            calc_date = date.today()

        pair = self.pair_repo.get_by_name(pair_name)
        if not pair:
            return None

        context = self._create_domain_context(calc_date)
        calculator = HedgeRatioCalculator(context)

        return calculator.calculate_hedge_ratio(pair)

    # ========================================================================
    # Alert Management
    # ========================================================================

    def get_active_alerts(
        self,
        pair_name: str | None = None
    ) -> list[HedgeAlert]:
        """Get active (unresolved) alerts"""
        return self.alert_repo.get_active_alerts(pair_name)

    def get_recent_alerts(
        self,
        days: int = 7,
        pair_name: str | None = None
    ) -> list[HedgeAlert]:
        """Get alerts from recent days"""
        return self.alert_repo.get_recent_alerts(days, pair_name)

    def resolve_alert(self, alert_id: int) -> HedgeAlert | None:
        """Mark an alert as resolved"""
        return self.alert_repo.resolve_alert(alert_id)

    # ========================================================================
    # Performance Tracking
    # ========================================================================

    def calculate_performance(
        self,
        pair_name: str,
        calc_date: date | None = None
    ) -> dict | None:
        """
        Calculate performance metrics for a hedge pair.

        Args:
            pair_name: Hedge pair name
            calc_date: Calculation date

        Returns:
            Performance metrics
        """
        if calc_date is None:
            calc_date = date.today()

        pair = self.pair_repo.get_by_name(pair_name)
        if not pair:
            return None

        context = self._create_domain_context(calc_date)

        # Get price data
        long_prices = context.get_asset_prices(
            pair.long_asset,
            calc_date,
            60
        )
        hedge_prices = context.get_asset_prices(
            pair.hedge_asset,
            calc_date,
            60
        )

        if not long_prices or not hedge_prices:
            return None

        # Calculate metrics
        portfolio_returns = self._calculate_portfolio_returns(
            long_prices,
            hedge_prices,
            pair.target_long_weight,
            pair.target_hedge_weight
        )

        volatility = self._calculate_volatility(portfolio_returns)
        sharpe_ratio = self._calculate_sharpe_ratio(portfolio_returns)
        max_drawdown = self._calculate_max_drawdown(portfolio_returns)

        # Get hedge effectiveness
        effectiveness_result = self.check_hedge_effectiveness(pair_name, calc_date)
        hedge_effectiveness = effectiveness_result.get('effectiveness', 0) if effectiveness_result else 0

        # Save to database
        self.performance_repo.save_performance(
            pair_name=pair_name,
            trade_date=calc_date,
            returns=portfolio_returns[-1] if portfolio_returns else 0,
            volatility=volatility,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            hedge_effectiveness=hedge_effectiveness
        )

        return {
            'pair_name': pair_name,
            'trade_date': calc_date,
            'daily_return': portfolio_returns[-1] if portfolio_returns else 0,
            'volatility': volatility,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown': max_drawdown,
            'hedge_effectiveness': hedge_effectiveness,
        }

    def _calculate_portfolio_returns(
        self,
        long_prices: list[float],
        hedge_prices: list[float],
        long_weight: float,
        hedge_weight: float
    ) -> list[float]:
        """Calculate portfolio returns from price series"""
        if not long_prices or not hedge_prices or len(long_prices) < 2:
            return []

        returns = []
        for i in range(1, len(long_prices)):
            long_ret = (long_prices[i] - long_prices[i-1]) / long_prices[i-1]
            hedge_ret = (hedge_prices[i] - hedge_prices[i-1]) / hedge_prices[i-1]

            portfolio_ret = long_ret * long_weight + hedge_ret * hedge_weight
            returns.append(portfolio_ret)

        return returns

    def _calculate_volatility(self, returns: list[float]) -> float:
        """Calculate annualized volatility"""
        if not returns:
            return 0.0

        import math
        mean_ret = sum(returns) / len(returns)
        variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
        return math.sqrt(variance) * math.sqrt(252)

    def _calculate_sharpe_ratio(
        self,
        returns: list[float],
        risk_free_rate: float = 0.03
    ) -> float:
        """Calculate Sharpe ratio"""
        if not returns:
            return 0.0

        volatility = self._calculate_volatility(returns)
        if volatility == 0:
            return 0.0

        mean_return = sum(returns) / len(returns) * 252  # Annualize
        excess_return = mean_return - risk_free_rate

        return excess_return / volatility

    def _calculate_max_drawdown(self, returns: list[float]) -> float:
        """Calculate maximum drawdown"""
        if not returns:
            return 0.0

        # Calculate cumulative returns
        cumulative = [1.0]
        for ret in returns:
            cumulative.append(cumulative[-1] * (1 + ret))

        # Find max drawdown
        peak = cumulative[0]
        max_dd = 0.0

        for value in cumulative:
            if value > peak:
                peak = value
            drawdown = (peak - value) / peak
            if drawdown > max_dd:
                max_dd = drawdown

        return max_dd

    # ========================================================================
    # Configuration Management
    # ========================================================================

    def get_all_pairs(self, active_only: bool = True) -> list[HedgePair]:
        """Get all hedge pair configurations"""
        return self.pair_repo.get_all(active_only)

    def get_pair_by_name(self, name: str) -> HedgePair | None:
        """Get hedge pair by name"""
        return self.pair_repo.get_by_name(name)

    def create_pair(self, pair: HedgePair) -> HedgePair | None:
        """Create new hedge pair configuration"""
        return self.pair_repo.create(pair)

    def update_pair(self, pair: HedgePair) -> HedgePair | None:
        """Update existing hedge pair configuration"""
        return self.pair_repo.update(pair)
