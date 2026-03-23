"""
Rotation Module Infrastructure Layer - Repositories

Data access layer for rotation module.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional

from django.db.models import Q
from django.utils import timezone

from apps.rotation.domain.entities import (
    AssetCategory,
    AssetClass,
    MomentumScore,
    RotationConfig,
    RotationPortfolio,
    RotationSignal,
    RotationStrategyType,
)
from apps.rotation.infrastructure.models import (
    AssetClassModel,
    MomentumScoreModel,
    RotationConfigModel,
    RotationPortfolioModel,
    RotationSignalModel,
)


class AssetClassRepository:
    """Repository for AssetClass entities"""

    def get_all(self) -> list[AssetClass]:
        """Get all asset classes, including inactive ones."""
        models = AssetClassModel._default_manager.all()
        return [m.to_domain() for m in models]

    def get_all_active(self) -> list[AssetClass]:
        """Get all active asset classes"""
        models = AssetClassModel._default_manager.filter(is_active=True)
        return [m.to_domain() for m in models]

    def get_by_code(self, code: str) -> AssetClass | None:
        """Get asset class by code"""
        try:
            model = AssetClassModel._default_manager.get(code=code, is_active=True)
            return model.to_domain()
        except AssetClassModel.DoesNotExist:
            return None

    def get_by_codes(self, codes: list[str]) -> list[AssetClass]:
        """Get asset classes by list of codes"""
        models = AssetClassModel._default_manager.filter(
            code__in=codes,
            is_active=True
        )
        return [m.to_domain() for m in models]

    def get_by_category(self, category: str) -> list[AssetClass]:
        """Get asset classes by category"""
        models = AssetClassModel._default_manager.filter(
            category=category,
            is_active=True
        )
        return [m.to_domain() for m in models]


class RotationConfigRepository:
    """Repository for RotationConfig entities"""

    def get_all(self) -> list[RotationConfig]:
        """Get all rotation configurations"""
        models = RotationConfigModel._default_manager.all()
        return [m.to_domain() for m in models]

    def get_active(self) -> list[RotationConfig]:
        """Get active rotation configurations"""
        models = RotationConfigModel._default_manager.filter(is_active=True)
        return [m.to_domain() for m in models]

    def get_by_name(self, name: str) -> RotationConfig | None:
        """Get rotation configuration by name"""
        try:
            model = RotationConfigModel._default_manager.get(name=name)
            return model.to_domain()
        except RotationConfigModel.DoesNotExist:
            return None

    def get_model_by_name(self, name: str) -> RotationConfigModel | None:
        """Get rotation configuration ORM model by name."""
        try:
            return RotationConfigModel._default_manager.get(name=name)
        except RotationConfigModel.DoesNotExist:
            return None

    def get_by_id(self, config_id: int) -> RotationConfig | None:
        """Get rotation configuration by ID"""
        try:
            model = RotationConfigModel._default_manager.get(id=config_id)
            return model.to_domain()
        except RotationConfigModel.DoesNotExist:
            return None

    def save(self, config: RotationConfig) -> RotationConfigModel:
        """Save rotation configuration"""
        # Map domain enum back to string
        strategy_map = {
            RotationStrategyType.REGIME_BASED: 'regime_based',
            RotationStrategyType.MOMENTUM: 'momentum',
            RotationStrategyType.RISK_PARITY: 'risk_parity',
            RotationStrategyType.MEAN_REVERSION: 'mean_reversion',
            RotationStrategyType.CUSTOM: 'custom',
        }

        model, created = RotationConfigModel._default_manager.update_or_create(
            name=config.name,
            defaults={
                'description': config.description,
                'strategy_type': strategy_map.get(config.strategy_type, 'momentum'),
                'asset_universe': config.asset_universe,
                'params': config.params,
                'rebalance_frequency': config.rebalance_frequency,
                'min_weight': config.min_weight,
                'max_weight': config.max_weight,
                'max_turnover': config.max_turnover,
                'lookback_period': config.lookback_period,
                'regime_allocations': config.regime_allocations,
                'top_n': config.top_n,
                'is_active': config.is_active,
            }
        )
        return model


class RotationSignalRepository:
    """Repository for RotationSignal entities"""

    def save(self, signal: RotationSignal, config_id: int) -> RotationSignalModel:
        """Save rotation signal"""
        model, _ = RotationSignalModel._default_manager.update_or_create(
            config_id=config_id,
            signal_date=signal.signal_date,
            defaults={
                'target_allocation': signal.target_allocation,
                'current_regime': signal.current_regime,
                'momentum_ranking': signal.momentum_ranking,
                'expected_volatility': signal.expected_volatility,
                'expected_return': signal.expected_return,
                'action_required': signal.action_required,
                'reason': signal.reason,
            },
        )
        return model

    def get_latest_signal(self, config_id: int) -> RotationSignalModel | None:
        """Get latest signal for configuration"""
        return RotationSignalModel._default_manager.filter(
            config_id=config_id
        ).order_by('-signal_date').first()

    def get_signals_by_date_range(
        self,
        config_id: int,
        start_date: date,
        end_date: date
    ) -> list[RotationSignalModel]:
        """Get signals for a date range"""
        return RotationSignalModel._default_manager.filter(
            config_id=config_id,
            signal_date__gte=start_date,
            signal_date__lte=end_date,
        ).order_by('-signal_date')

    def get_latest_for_all_configs(self) -> list[RotationSignalModel]:
        """Get latest signal for each active configuration"""
        configs = RotationConfigModel._default_manager.filter(is_active=True)
        signals = []

        for config in configs:
            latest = self.get_latest_signal(config.id)
            if latest:
                signals.append(latest)

        return signals


class MomentumScoreRepository:
    """Repository for MomentumScore entities"""

    def save(self, score: MomentumScore) -> MomentumScoreModel:
        """Save momentum score"""
        model, created = MomentumScoreModel._default_manager.update_or_create(
            asset_code=score.asset_code,
            calc_date=score.calc_date,
            defaults={
                'momentum_1m': score.momentum_1m,
                'momentum_3m': score.momentum_3m,
                'momentum_6m': score.momentum_6m,
                'momentum_12m': score.momentum_12m,
                'composite_score': score.composite_score,
                'rank': score.rank,
                'sharpe_1m': score.sharpe_1m,
                'sharpe_3m': score.sharpe_3m,
                'ma_signal': score.ma_signal,
                'trend_strength': score.trend_strength,
            }
        )
        return model

    def get_latest_scores(
        self,
        asset_code: str | None = None,
        limit: int = 50
    ) -> list[MomentumScoreModel]:
        """Get latest momentum scores, optionally filtered by asset code."""
        queryset = MomentumScoreModel._default_manager.filter(
            calc_date__gte=date.today() - timedelta(days=7)
        )
        if asset_code:
            queryset = queryset.filter(asset_code=asset_code)
        return queryset.order_by('-calc_date', '-composite_score')[:limit]

    def get_scores_by_date(self, calc_date: date) -> list[MomentumScoreModel]:
        """Get all momentum scores for a specific date"""
        return MomentumScoreModel._default_manager.filter(
            calc_date=calc_date
        ).order_by('-composite_score')

    def get_asset_score(
        self,
        asset_code: str,
        calc_date: date
    ) -> MomentumScoreModel | None:
        """Get momentum score for specific asset and date"""
        try:
            return MomentumScoreModel._default_manager.get(
                asset_code=asset_code,
                calc_date=calc_date
            )
        except MomentumScoreModel.DoesNotExist:
            return None


class RotationPortfolioRepository:
    """Repository for RotationPortfolio entities"""

    def save(self, portfolio: RotationPortfolio, config_id: int) -> RotationPortfolioModel:
        """Save rotation portfolio state"""
        model, created = RotationPortfolioModel._default_manager.update_or_create(
            config_id=config_id,
            trade_date=portfolio.trade_date,
            defaults={
                'current_allocation': portfolio.current_allocation,
                'daily_return': portfolio.daily_return,
                'cumulative_return': portfolio.cumulative_return,
                'portfolio_volatility': portfolio.portfolio_volatility,
                'max_drawdown': portfolio.max_drawdown,
                'turnover_since_last': portfolio.turnover_since_last,
            }
        )
        return model

    def get_latest_portfolio(self, config_id: int) -> RotationPortfolioModel | None:
        """Get latest portfolio state for configuration"""
        return RotationPortfolioModel._default_manager.filter(
            config_id=config_id
        ).order_by('-trade_date').first()

    def get_portfolio_history(
        self,
        config_id: int,
        start_date: date,
        end_date: date
    ) -> list[RotationPortfolioModel]:
        """Get portfolio history for a date range"""
        return RotationPortfolioModel._default_manager.filter(
            config_id=config_id,
            trade_date__gte=start_date,
            trade_date__lte=end_date,
        ).order_by('-trade_date')

