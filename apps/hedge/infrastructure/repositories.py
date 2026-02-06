"""
Hedge Module Infrastructure Layer - Repositories

Data access layer for hedge portfolio management.
Provides clean separation between domain logic and data persistence.
"""

from datetime import date
from typing import List, Optional

from django.db.models import Q

from apps.hedge.domain.entities import (
    HedgePair,
    HedgeMethod,
    CorrelationMetric,
    HedgePortfolio,
    HedgeAlert,
    HedgeAlertType,
)
from apps.hedge.infrastructure.models import (
    HedgePairModel,
    CorrelationHistoryModel,
    HedgePortfolioHoldingModel,
    HedgeAlertModel,
    HedgePerformanceModel,
)


class HedgePairRepository:
    """Repository for HedgePair entities"""

    def get_all(self, active_only: bool = True) -> List[HedgePair]:
        """Get all hedge pairs"""
        queryset = HedgePairModel.objects.all()
        if active_only:
            queryset = queryset.filter(is_active=True)

        return [model.to_domain() for model in queryset]

    def get_by_name(self, name: str) -> Optional[HedgePair]:
        """Get hedge pair by name"""
        try:
            model = HedgePairModel.objects.get(name=name)
            return model.to_domain()
        except HedgePairModel.DoesNotExist:
            return None

    def get_by_id(self, pair_id: int) -> Optional[HedgePair]:
        """Get hedge pair by ID"""
        try:
            model = HedgePairModel.objects.get(id=pair_id)
            return model.to_domain()
        except HedgePairModel.DoesNotExist:
            return None

    def get_by_assets(self, long_asset: str, hedge_asset: str) -> Optional[HedgePair]:
        """Get hedge pair by asset codes"""
        try:
            model = HedgePairModel.objects.get(
                long_asset=long_asset,
                hedge_asset=hedge_asset
            )
            return model.to_domain()
        except HedgePairModel.DoesNotExist:
            return None

    def create(self, pair: HedgePair) -> HedgePair:
        """Create new hedge pair"""
        model = HedgePairModel(
            name=pair.name,
            long_asset=pair.long_asset,
            hedge_asset=pair.hedge_asset,
            hedge_method=pair.hedge_method.value,
            target_long_weight=pair.target_long_weight,
            target_hedge_weight=pair.target_hedge_weight,
            correlation_window=pair.correlation_window,
            min_correlation=pair.min_correlation,
            max_correlation=pair.max_correlation,
            correlation_alert_threshold=pair.correlation_alert_threshold,
            rebalance_trigger=pair.rebalance_trigger,
            beta_target=pair.beta_target,
            is_active=True,
        )
        model.save()
        return model.to_domain()

    def update(self, pair: HedgePair) -> Optional[HedgePair]:
        """Update existing hedge pair"""
        model = HedgePairModel.objects.filter(name=pair.name).first()
        if not model:
            return None

        model.target_long_weight = pair.target_long_weight
        model.target_hedge_weight = pair.target_hedge_weight
        model.correlation_window = pair.correlation_window
        model.min_correlation = pair.min_correlation
        model.max_correlation = pair.max_correlation
        model.correlation_alert_threshold = pair.correlation_alert_threshold
        model.rebalance_trigger = pair.rebalance_trigger
        model.beta_target = pair.beta_target
        model.save()

        return model.to_domain()


class CorrelationHistoryRepository:
    """Repository for correlation history data"""

    def get_latest(
        self,
        asset1: str,
        asset2: str,
        window_days: int = 60
    ) -> Optional[CorrelationMetric]:
        """Get latest correlation metric for a pair"""
        model = CorrelationHistoryModel.objects.filter(
            asset1=asset1,
            asset2=asset2,
            window_days=window_days
        ).order_by('-calc_date').first()

        if model:
            return model.to_domain()
        return None

    def get_history(
        self,
        asset1: str,
        asset2: str,
        start_date: date,
        end_date: Optional[date] = None,
        window_days: int = 60
    ) -> List[CorrelationMetric]:
        """Get correlation history for a date range"""
        queryset = CorrelationHistoryModel.objects.filter(
            asset1=asset1,
            asset2=asset2,
            window_days=window_days,
            calc_date__gte=start_date
        )

        if end_date:
            queryset = queryset.filter(calc_date__lte=end_date)

        return [model.to_domain() for model in queryset.order_by('calc_date')]

    def save(self, metric: CorrelationMetric) -> CorrelationMetric:
        """Save correlation metric"""
        model, created = CorrelationHistoryModel.objects.get_or_create(
            asset1=metric.asset1,
            asset2=metric.asset2,
            calc_date=metric.calc_date,
            window_days=metric.window_days,
            defaults={
                'correlation': metric.correlation,
                'covariance': metric.covariance,
                'beta': metric.beta,
            }
        )

        if not created:
            model.correlation = metric.correlation
            model.covariance = metric.covariance
            model.beta = metric.beta
            model.save()

        return model.to_domain()

    def get_all_recent(
        self,
        days: int = 30,
        window_days: int = 60
    ) -> List[CorrelationMetric]:
        """Get all recent correlation metrics"""
        from datetime import timedelta
        cutoff_date = date.today() - timedelta(days=days)

        queryset = CorrelationHistoryModel.objects.filter(
            calc_date__gte=cutoff_date,
            window_days=window_days
        ).order_by('-calc_date')

        return [model.to_domain() for model in queryset]


class HedgePortfolioRepository:
    """Repository for hedge portfolio holdings"""

    def save_portfolio(self, portfolio: HedgePortfolio) -> HedgePortfolio:
        """Save hedge portfolio state"""
        pair_model = HedgePairModel.objects.filter(name=portfolio.pair_name).first()
        if not pair_model:
            raise ValueError(f"Hedge pair not found: {portfolio.pair_name}")

        model, created = HedgePortfolioHoldingModel.objects.get_or_create(
            config=pair_model,
            trade_date=portfolio.trade_date,
            defaults={
                'long_weight': portfolio.long_weight,
                'hedge_weight': portfolio.hedge_weight,
                'current_correlation': portfolio.current_correlation,
                'portfolio_beta': portfolio.portfolio_beta,
            }
        )

        if not created:
            model.long_weight = portfolio.long_weight
            model.hedge_weight = portfolio.hedge_weight
            model.current_correlation = portfolio.current_correlation
            model.portfolio_beta = portfolio.portfolio_beta
            model.save()

        return portfolio

    def get_latest_portfolio(self, pair_name: str) -> Optional[HedgePortfolio]:
        """Get latest portfolio state for a pair"""
        model = HedgePortfolioHoldingModel.objects.filter(
            config__name=pair_name
        ).order_by('-trade_date').first()

        if model:
            return model.to_domain()
        return None

    def get_portfolio_history(
        self,
        pair_name: str,
        start_date: date,
        end_date: Optional[date] = None
    ) -> List[HedgePortfolio]:
        """Get portfolio history for a date range"""
        queryset = HedgePortfolioHoldingModel.objects.filter(
            config__name=pair_name,
            trade_date__gte=start_date
        )

        if end_date:
            queryset = queryset.filter(trade_date__lte=end_date)

        return [model.to_domain() for model in queryset.order_by('trade_date')]


class HedgeAlertRepository:
    """Repository for hedge alerts"""

    def get_active_alerts(self, pair_name: Optional[str] = None) -> List[HedgeAlert]:
        """Get all active (unresolved) alerts"""
        queryset = HedgeAlertModel.objects.filter(is_resolved=False)

        if pair_name:
            queryset = queryset.filter(pair_name=pair_name)

        return [model.to_domain() for model in queryset.order_by('-alert_date')]

    def get_recent_alerts(
        self,
        days: int = 7,
        pair_name: Optional[str] = None
    ) -> List[HedgeAlert]:
        """Get alerts from recent days"""
        from datetime import timedelta
        cutoff_date = date.today() - timedelta(days=days)

        queryset = HedgeAlertModel.objects.filter(
            alert_date__gte=cutoff_date
        )

        if pair_name:
            queryset = queryset.filter(pair_name=pair_name)

        return [model.to_domain() for model in queryset.order_by('-alert_date')]

    def save_alert(self, alert: HedgeAlert) -> HedgeAlert:
        """Save alert to database"""
        model = HedgeAlertModel.objects.create(
            pair_name=alert.pair_name,
            alert_date=alert.alert_date,
            alert_type=alert.alert_type.value,
            severity=alert.severity,
            message=alert.message,
            current_value=alert.current_value,
            threshold_value=alert.threshold_value,
            action_required=alert.action_required,
            action_priority=alert.action_priority,
            is_resolved=False,
        )

        return model.to_domain()

    def resolve_alert(self, alert_id: int) -> Optional[HedgeAlert]:
        """Mark alert as resolved"""
        try:
            model = HedgeAlertModel.objects.get(id=alert_id)
            model.is_resolved = True
            model.resolved_at = date.today()
            model.save()
            return model.to_domain()
        except HedgeAlertModel.DoesNotExist:
            return None


class HedgePerformanceRepository:
    """Repository for hedge performance metrics"""

    def save_performance(
        self,
        pair_name: str,
        trade_date: date,
        returns: float,
        volatility: float,
        sharpe_ratio: float,
        max_drawdown: float,
        hedge_effectiveness: float
    ) -> None:
        """Save performance metrics"""
        pair_model = HedgePairModel.objects.filter(name=pair_name).first()
        if not pair_model:
            raise ValueError(f"Hedge pair not found: {pair_name}")

        HedgePerformanceModel.objects.update_or_create(
            config=pair_model,
            trade_date=trade_date,
            defaults={
                'daily_return': returns,
                'cumulative_return': returns,  # Would be calculated differently in practice
                'volatility': volatility,
                'sharpe_ratio': sharpe_ratio,
                'max_drawdown': max_drawdown,
                'hedge_effectiveness': hedge_effectiveness,
            }
        )

    def get_performance_history(
        self,
        pair_name: str,
        start_date: date,
        end_date: Optional[date] = None
    ) -> List[dict]:
        """Get performance history for a pair"""
        queryset = HedgePerformanceModel.objects.filter(
            config__name=pair_name,
            trade_date__gte=start_date
        )

        if end_date:
            queryset = queryset.filter(trade_date__lte=end_date)

        return [
            {
                'trade_date': p.trade_date,
                'daily_return': float(p.daily_return),
                'volatility': float(p.volatility),
                'sharpe_ratio': float(p.sharpe_ratio),
                'max_drawdown': float(p.max_drawdown),
                'hedge_effectiveness': float(p.hedge_effectiveness),
            }
            for p in queryset.order_by('trade_date')
        ]
