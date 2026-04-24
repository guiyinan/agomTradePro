"""
Hedge Module Infrastructure Layer - Repositories

Data access layer for hedge portfolio management.
Provides clean separation between domain logic and data persistence.
"""

from datetime import date
from typing import Dict, List, Optional

from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.hedge.domain.entities import (
    CorrelationMetric,
    HedgeAlert,
    HedgeAlertType,
    HedgeMethod,
    HedgePair,
    HedgePortfolio,
)
from apps.hedge.infrastructure.models import (
    CorrelationHistoryModel,
    HedgeAlertModel,
    HedgePairModel,
    HedgePerformanceModel,
    HedgePortfolioSnapshotModel,
)


def _attach_domain_meta(entity, model, fields: tuple[str, ...]):
    """Attach persistence metadata (e.g. id/timestamps) to frozen domain entities."""
    for field in fields:
        if hasattr(model, field):
            object.__setattr__(entity, field, getattr(model, field))
    return entity


class HedgePairRepository:
    """Repository for HedgePair entities"""

    def get_queryset(self, active_only: bool | None = None) -> QuerySet[HedgePairModel]:
        """Return the ORM queryset for hedge pairs."""
        queryset = HedgePairModel._default_manager.all()
        if active_only is True:
            queryset = queryset.filter(is_active=True)
        elif active_only is False:
            queryset = queryset.filter(is_active=False)
        return queryset

    def get_all(self, active_only: bool = True) -> list[HedgePair]:
        """Get all hedge pairs"""
        queryset = self.get_queryset(active_only=True if active_only else None)

        return [
            _attach_domain_meta(model.to_domain(), model, ("id", "created_at", "updated_at"))
            for model in queryset
        ]

    def get_by_name(self, name: str) -> HedgePair | None:
        """Get hedge pair by name"""
        try:
            model = HedgePairModel._default_manager.get(name=name)
            return _attach_domain_meta(model.to_domain(), model, ("id", "created_at", "updated_at"))
        except HedgePairModel.DoesNotExist:
            return None

    def get_by_id(self, pair_id: int) -> HedgePair | None:
        """Get hedge pair by ID"""
        try:
            model = HedgePairModel._default_manager.get(id=pair_id)
            return _attach_domain_meta(model.to_domain(), model, ("id", "created_at", "updated_at"))
        except HedgePairModel.DoesNotExist:
            return None

    def get_by_assets(self, long_asset: str, hedge_asset: str) -> HedgePair | None:
        """Get hedge pair by asset codes"""
        try:
            model = HedgePairModel._default_manager.get(
                long_asset=long_asset,
                hedge_asset=hedge_asset
            )
            return _attach_domain_meta(model.to_domain(), model, ("id", "created_at", "updated_at"))
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
        return _attach_domain_meta(model.to_domain(), model, ("id", "created_at", "updated_at"))

    def update(self, pair: HedgePair) -> HedgePair | None:
        """Update existing hedge pair"""
        model = HedgePairModel._default_manager.filter(name=pair.name).first()
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
        model.is_active = pair.is_active
        model.save()

        return _attach_domain_meta(model.to_domain(), model, ("id", "created_at", "updated_at"))

    def set_active(self, pair_id: int, is_active: bool) -> HedgePair | None:
        """Set active status for a hedge pair"""
        model = HedgePairModel._default_manager.filter(id=pair_id).first()
        if not model:
            return None

        model.is_active = is_active
        model.save()

        return _attach_domain_meta(model.to_domain(), model, ("id", "created_at", "updated_at"))


class CorrelationHistoryRepository:
    """Repository for correlation history data"""

    def get_queryset(self) -> QuerySet[CorrelationHistoryModel]:
        """Return the ORM queryset for correlation history."""
        return CorrelationHistoryModel._default_manager.all()

    def get_latest(
        self,
        asset1: str,
        asset2: str,
        window_days: int = 60
    ) -> CorrelationMetric | None:
        """Get latest correlation metric for a pair"""
        model = CorrelationHistoryModel._default_manager.filter(
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
        end_date: date | None = None,
        window_days: int = 60
    ) -> list[CorrelationMetric]:
        """Get correlation history for a date range"""
        queryset = CorrelationHistoryModel._default_manager.filter(
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
        model, created = CorrelationHistoryModel._default_manager.get_or_create(
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
    ) -> list[CorrelationMetric]:
        """Get all recent correlation metrics"""
        from datetime import timedelta
        cutoff_date = date.today() - timedelta(days=days)

        queryset = CorrelationHistoryModel._default_manager.filter(
            calc_date__gte=cutoff_date,
            window_days=window_days
        ).order_by('-calc_date')

        return [model.to_domain() for model in queryset]


class HedgePortfolioRepository:
    """Repository for hedge portfolio snapshots"""

    def get_queryset(self) -> QuerySet[HedgePortfolioSnapshotModel]:
        """Return the ORM queryset for portfolio snapshots."""
        return HedgePortfolioSnapshotModel._default_manager.select_related('pair').all()

    def save_portfolio(self, portfolio: HedgePortfolio) -> HedgePortfolio:
        """Save hedge portfolio state"""
        pair_model = HedgePairModel._default_manager.filter(name=portfolio.pair_name).first()
        if not pair_model:
            raise ValueError(f"Hedge pair not found: {portfolio.pair_name}")

        portfolio_values = {
            'long_weight': portfolio.long_weight,
            'hedge_weight': portfolio.hedge_weight,
            'hedge_ratio': portfolio.hedge_ratio,
            'target_hedge_ratio': portfolio.target_hedge_ratio,
            'current_correlation': portfolio.current_correlation,
            'correlation_20d': portfolio.correlation_20d,
            'correlation_60d': portfolio.correlation_60d,
            'portfolio_beta': portfolio.portfolio_beta,
            'portfolio_volatility': portfolio.portfolio_volatility,
            'hedge_effectiveness': portfolio.hedge_effectiveness,
            'daily_return': portfolio.daily_return,
            'unhedged_return': portfolio.unhedged_return,
            'hedge_return': portfolio.hedge_return,
            'value_at_risk': portfolio.value_at_risk,
            'max_drawdown': portfolio.max_drawdown,
            'rebalance_needed': portfolio.rebalance_needed,
            'rebalance_reason': portfolio.rebalance_reason,
        }

        model, created = HedgePortfolioSnapshotModel._default_manager.get_or_create(
            pair=pair_model,
            trade_date=portfolio.trade_date,
            defaults=portfolio_values,
        )

        if not created:
            for field_name, value in portfolio_values.items():
                setattr(model, field_name, value)
            model.save()

        return portfolio

    def get_latest_portfolio(self, pair_name: str) -> HedgePortfolio | None:
        """Get latest portfolio state for a pair"""
        model = HedgePortfolioSnapshotModel._default_manager.filter(
            pair__name=pair_name
        ).order_by('-trade_date').first()

        if model:
            return model.to_domain()
        return None

    def get_portfolio_history(
        self,
        pair_name: str,
        start_date: date,
        end_date: date | None = None
    ) -> list[HedgePortfolio]:
        """Get portfolio history for a date range"""
        queryset = HedgePortfolioSnapshotModel._default_manager.filter(
            pair__name=pair_name,
            trade_date__gte=start_date
        )

        if end_date:
            queryset = queryset.filter(trade_date__lte=end_date)

        return [model.to_domain() for model in queryset.order_by('trade_date')]

    def get_recent_snapshots(
        self,
        pair_name: str | None = None,
        rebalance_needed: bool | None = None,
        limit: int = 50
    ) -> list[dict]:
        """
        Get recent snapshots with filtering.
        Returns dict representations for view rendering.
        """
        queryset = self.get_queryset()

        if pair_name:
            queryset = queryset.filter(pair__name__icontains=pair_name)
        if rebalance_needed is not None:
            queryset = queryset.filter(rebalance_needed=rebalance_needed)

        snapshots = queryset.order_by('-trade_date', '-created_at')[:limit]

        return [
            {
                'id': s.id,
                'pair_name': s.pair.name if s.pair else 'Unknown',
                'pair_id': s.pair_id,
                'trade_date': s.trade_date,
                'long_weight': round(s.long_weight * 100, 2),
                'hedge_weight': round(s.hedge_weight * 100, 2),
                'hedge_ratio': round(s.hedge_ratio, 3),
                'target_hedge_ratio': round(s.target_hedge_ratio, 3),
                'current_correlation': round(s.current_correlation, 4),
                'correlation_20d': round(s.correlation_20d, 4),
                'correlation_60d': round(s.correlation_60d, 4),
                'portfolio_beta': round(s.portfolio_beta, 3),
                'portfolio_volatility': round(s.portfolio_volatility * 100, 2),
                'hedge_effectiveness': round(s.hedge_effectiveness * 100, 1),
                'daily_return': round(s.daily_return * 100, 3),
                'unhedged_return': round(s.unhedged_return * 100, 3),
                'hedge_return': round(s.hedge_return * 100, 3),
                'value_at_risk': round(s.value_at_risk * 100, 2),
                'max_drawdown': round(s.max_drawdown * 100, 2),
                'rebalance_needed': s.rebalance_needed,
                'rebalance_reason': s.rebalance_reason,
                'created_at': s.created_at,
            }
            for s in snapshots
        ]

    def get_statistics(self) -> dict[str, int]:
        """Get statistics for snapshots"""
        from django.db.models import Count

        total = HedgePortfolioSnapshotModel._default_manager.count()
        rebalance_needed = HedgePortfolioSnapshotModel._default_manager.filter(
            rebalance_needed=True
        ).count()
        unique_pairs = HedgePortfolioSnapshotModel._default_manager.values(
            'pair__name'
        ).distinct().count()

        return {
            'total_snapshots': total,
            'rebalance_needed': rebalance_needed,
            'unique_pairs': unique_pairs,
        }


class HedgeAlertRepository:
    """Repository for hedge alerts"""

    def get_queryset(self, is_resolved: bool | None = None) -> QuerySet[HedgeAlertModel]:
        """Return the ORM queryset for hedge alerts."""
        queryset = HedgeAlertModel._default_manager.all()
        if is_resolved is not None:
            queryset = queryset.filter(is_resolved=is_resolved)
        return queryset

    def get_active_alerts(self, pair_name: str | None = None) -> list[HedgeAlert]:
        """Get all active (unresolved) alerts"""
        queryset = self.get_queryset(is_resolved=False)

        if pair_name:
            queryset = queryset.filter(pair_name=pair_name)

        return [
            _attach_domain_meta(model.to_domain(), model, ("id", "created_at"))
            for model in queryset.order_by('-alert_date')
        ]

    def get_recent_alerts(
        self,
        days: int = 7,
        pair_name: str | None = None
    ) -> list[HedgeAlert]:
        """Get alerts from recent days"""
        from datetime import timedelta
        cutoff_date = date.today() - timedelta(days=days)

        queryset = HedgeAlertModel._default_manager.filter(
            alert_date__gte=cutoff_date
        )

        if pair_name:
            queryset = queryset.filter(pair_name=pair_name)

        return [
            _attach_domain_meta(model.to_domain(), model, ("id", "created_at"))
            for model in queryset.order_by('-alert_date')
        ]

    def save_alert(self, alert: HedgeAlert) -> HedgeAlert:
        """Save alert to database"""
        model = HedgeAlertModel._default_manager.create(
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

        return _attach_domain_meta(model.to_domain(), model, ("id", "created_at"))

    def resolve_alert(self, alert_id: int) -> HedgeAlert | None:
        """Mark alert as resolved"""
        try:
            model = HedgeAlertModel._default_manager.get(id=alert_id)
            model.is_resolved = True
            model.resolved_at = timezone.now()
            model.save()
            return _attach_domain_meta(model.to_domain(), model, ("id", "created_at"))
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
        pair_model = HedgePairModel._default_manager.filter(name=pair_name).first()
        if not pair_model:
            raise ValueError(f"Hedge pair not found: {pair_name}")

        HedgePerformanceModel._default_manager.update_or_create(
            pair=pair_model,
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
        end_date: date | None = None
    ) -> list[dict]:
        """Get performance history for a pair"""
        queryset = HedgePerformanceModel._default_manager.filter(
            pair__name=pair_name,
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
