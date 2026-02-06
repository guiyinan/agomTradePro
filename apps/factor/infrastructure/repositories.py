"""
Factor Module Infrastructure Layer - Repositories

Data access layer for factor module.
"""

from datetime import date, datetime
from typing import List, Dict, Optional
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from apps.factor.infrastructure.models import (
    FactorDefinitionModel,
    FactorExposureModel,
    FactorPortfolioConfigModel,
    FactorPortfolioHoldingModel,
    FactorPerformanceModel,
)
from apps.factor.domain.entities import (
    FactorDefinition,
    FactorPortfolioConfig,
    FactorScore,
    FactorPortfolioHolding,
)


class FactorDefinitionRepository:
    """Repository for FactorDefinition entities"""

    def get_all(self) -> List[FactorDefinition]:
        """Get all factor definitions"""
        models = FactorDefinitionModel._default_manager.all()
        return [m.to_domain() for m in models]

    def get_active(self) -> List[FactorDefinition]:
        """Get active factor definitions"""
        models = FactorDefinitionModel._default_manager.filter(is_active=True)
        return [m.to_domain() for m in models]

    def get_by_code(self, code: str) -> Optional[FactorDefinition]:
        """Get factor definition by code"""
        try:
            model = FactorDefinitionModel._default_manager.get(code=code)
            return model.to_domain()
        except FactorDefinitionModel.DoesNotExist:
            return None

    def get_by_category(self, category: str) -> List[FactorDefinition]:
        """Get factors by category"""
        models = FactorDefinitionModel._default_manager.filter(
            category=category,
            is_active=True
        )
        return [m.to_domain() for m in models]


class FactorExposureRepository:
    """Repository for FactorExposure entities"""

    def save(self, exposure) -> FactorExposureModel:
        """Save factor exposure"""
        model = FactorExposureModel._default_manager.create(
            stock_code=exposure.stock_code,
            trade_date=exposure.trade_date,
            factor_code=exposure.factor_code,
            factor_value=float(exposure.factor_value),
            percentile_rank=float(exposure.percentile_rank),
            z_score=float(exposure.z_score),
            normalized_score=float(exposure.normalized_score),
        )
        return model

    def get_latest_exposure(
        self,
        stock_code: str,
        factor_code: str
    ) -> Optional[FactorExposureModel]:
        """Get latest exposure for stock-factor pair"""
        return FactorExposureModel._default_manager.filter(
            stock_code=stock_code,
            factor_code=factor_code
        ).order_by('-trade_date').first()

    def get_exposures_by_date(
        self,
        trade_date: date,
        factor_code: str
    ) -> List[FactorExposureModel]:
        """Get all exposures for a factor on a date"""
        return FactorExposureModel._default_manager.filter(
            trade_date=trade_date,
            factor_code=factor_code
        ).order_by('-percentile_rank')


class FactorPortfolioConfigRepository:
    """Repository for FactorPortfolioConfig entities"""

    def get_all(self) -> List[FactorPortfolioConfig]:
        """Get all portfolio configurations"""
        models = FactorPortfolioConfigModel._default_manager.all()
        return [m.to_domain() for m in models]

    def get_active(self) -> List[FactorPortfolioConfig]:
        """Get active portfolio configurations"""
        models = FactorPortfolioConfigModel._default_manager.filter(is_active=True)
        return [m.to_domain() for m in models]

    def get_by_name(self, name: str) -> Optional[FactorPortfolioConfig]:
        """Get portfolio configuration by name"""
        try:
            model = FactorPortfolioConfigModel._default_manager.get(name=name)
            return model.to_domain()
        except FactorPortfolioConfigModel.DoesNotExist:
            return None

    def save(self, config: FactorPortfolioConfig) -> FactorPortfolioConfigModel:
        """Save portfolio configuration"""
        model, created = FactorPortfolioConfigModel._default_manager.update_or_create(
            name=config.name,
            defaults={
                'description': config.description,
                'factor_weights': config.factor_weights,
                'universe': config.universe,
                'min_market_cap': float(config.min_market_cap) if config.min_market_cap else None,
                'max_market_cap': float(config.max_market_cap) if config.max_market_cap else None,
                'max_pe': float(config.max_pe) if config.max_pe else None,
                'min_pe': float(config.min_pe) if config.min_pe else None,
                'max_pb': float(config.max_pb) if config.max_pb else None,
                'max_debt_ratio': config.max_debt_ratio,
                'top_n': config.top_n,
                'rebalance_frequency': config.rebalance_frequency,
                'weight_method': config.weight_method,
                'max_sector_weight': config.max_sector_weight,
                'max_single_stock_weight': config.max_single_stock_weight,
                'is_active': config.is_active,
            }
        )
        return model


class FactorPortfolioHoldingRepository:
    """Repository for FactorPortfolioHolding entities"""

    def save_holdings(
        self,
        config_name: str,
        trade_date: date,
        holdings: List[FactorPortfolioHolding]
    ) -> int:
        """Save portfolio holdings"""
        from apps.factor.infrastructure.models import FactorPortfolioConfigModel

        config = FactorPortfolioConfigModel._default_manager.get(name=config_name)

        # Delete existing holdings for this date
        FactorPortfolioHoldingModel._default_manager.filter(
            config=config,
            trade_date=trade_date
        ).delete()

        # Create new holdings
        holding_models = [
            FactorPortfolioHoldingModel(
                config=config,
                trade_date=trade_date,
                stock_code=h.stock_code,
                stock_name=h.stock_name,
                weight=float(h.weight),
                factor_score=float(h.factor_score),
                rank=h.rank,
                sector=h.sector,
                factor_scores=h.factor_scores,
            )
            for h in holdings
        ]

        FactorPortfolioHoldingModel._default_manager.bulk_create(holding_models)
        return len(holding_models)

    def get_latest_holdings(self, config_name: str) -> List[FactorPortfolioHoldingModel]:
        """Get latest holdings for a configuration"""
        return FactorPortfolioHoldingModel._default_manager.filter(
            config__name=config_name
        ).order_by('-trade_date', 'rank')[:30]

