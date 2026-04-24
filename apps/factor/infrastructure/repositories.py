"""
Factor Module Infrastructure Layer - Repositories

Data access layer for factor module.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Optional

from django.db.models import Count, Q
from django.utils import timezone

from apps.factor.domain.entities import (
    FactorDefinition,
    FactorPortfolioConfig,
    FactorPortfolioHolding,
    FactorScore,
)
from apps.factor.infrastructure.models import (
    FactorDefinitionModel,
    FactorExposureModel,
    FactorPerformanceModel,
    FactorPortfolioConfigModel,
    FactorPortfolioHoldingModel,
)


class FactorDefinitionRepository:
    """Repository for FactorDefinition entities"""

    def get_all(self) -> list[FactorDefinition]:
        """Get all factor definitions"""
        models = FactorDefinitionModel._default_manager.all()
        return [m.to_domain() for m in models]

    def get_active(self) -> list[FactorDefinition]:
        """Get active factor definitions"""
        models = FactorDefinitionModel._default_manager.filter(is_active=True)
        return [m.to_domain() for m in models]

    def get_by_code(self, code: str) -> FactorDefinition | None:
        """Get factor definition by code"""
        try:
            model = FactorDefinitionModel._default_manager.get(code=code)
            return model.to_domain()
        except FactorDefinitionModel.DoesNotExist:
            return None

    def get_by_category(self, category: str) -> list[FactorDefinition]:
        """Get factors by category"""
        models = FactorDefinitionModel._default_manager.filter(
            category=category,
            is_active=True
        )
        return [m.to_domain() for m in models]

    def get_model_by_id(self, factor_id: int) -> FactorDefinitionModel | None:
        """Return one factor definition ORM row by id."""

        try:
            return FactorDefinitionModel._default_manager.get(id=factor_id)
        except FactorDefinitionModel.DoesNotExist:
            return None

    def create_model(self, data: dict) -> FactorDefinitionModel:
        """Create one factor definition ORM row."""

        return FactorDefinitionModel._default_manager.create(**data)

    def update_model(
        self,
        *,
        factor_id: int,
        data: dict,
    ) -> FactorDefinitionModel | None:
        """Update one factor definition ORM row."""

        model = self.get_model_by_id(factor_id)
        if model is None:
            return None

        for field, value in data.items():
            setattr(model, field, value)

        update_fields = list(data.keys())
        if hasattr(model, "updated_at"):
            update_fields.append("updated_at")
        model.save(update_fields=update_fields)
        return model

    def delete_model(self, factor_id: int) -> bool:
        """Delete one factor definition ORM row."""

        model = self.get_model_by_id(factor_id)
        if model is None:
            return False
        model.delete()
        return True

    def toggle_active(self, factor_id: int) -> FactorDefinitionModel | None:
        """Toggle one factor definition activation state."""

        model = self.get_model_by_id(factor_id)
        if model is None:
            return None

        model.is_active = not model.is_active
        model.save(update_fields=["is_active", "updated_at"])
        return model

    def list_models_for_view(
        self,
        *,
        category: str | None = None,
        is_active: bool | None = None,
        search: str | None = None,
    ) -> list[FactorDefinitionModel]:
        """Return factor definition ORM rows for management views."""

        queryset = FactorDefinitionModel._default_manager.all()
        if category:
            queryset = queryset.filter(category=category)
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active)
        if search:
            queryset = queryset.filter(
                Q(code__icontains=search)
                | Q(name__icontains=search)
                | Q(description__icontains=search)
            )
        return list(queryset.order_by("category", "code"))

    def get_view_stats(self) -> dict:
        """Return factor definition statistics for management views."""

        return {
            "total": FactorDefinitionModel._default_manager.count(),
            "active": FactorDefinitionModel._default_manager.filter(is_active=True).count(),
            "by_category": dict(
                FactorDefinitionModel._default_manager.values("category")
                .annotate(count=Count("id"))
                .values_list("category", "count")
            ),
        }

    def list_category_rows(self) -> list[dict]:
        """Return distinct category rows for management views."""

        return list(FactorDefinitionModel._default_manager.values("category").distinct())

    def get_category_choices(self) -> dict:
        """Return factor category choices."""

        return dict(FactorDefinitionModel._default_manager.model._meta.get_field("category").choices)

    def list_active_models(self) -> list[FactorDefinitionModel]:
        """Return active factor definition ORM rows for views."""

        return list(FactorDefinitionModel._default_manager.filter(is_active=True))


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
    ) -> FactorExposureModel | None:
        """Get latest exposure for stock-factor pair"""
        return FactorExposureModel._default_manager.filter(
            stock_code=stock_code,
            factor_code=factor_code
        ).order_by('-trade_date').first()

    def get_exposures_by_date(
        self,
        trade_date: date,
        factor_code: str
    ) -> list[FactorExposureModel]:
        """Get all exposures for a factor on a date"""
        return FactorExposureModel._default_manager.filter(
            trade_date=trade_date,
            factor_code=factor_code
        ).order_by('-percentile_rank')


class FactorPortfolioConfigRepository:
    """Repository for FactorPortfolioConfig entities"""

    def get_all(self) -> list[FactorPortfolioConfig]:
        """Get all portfolio configurations"""
        models = FactorPortfolioConfigModel._default_manager.all()
        return [m.to_domain() for m in models]

    def get_active(self) -> list[FactorPortfolioConfig]:
        """Get active portfolio configurations"""
        models = FactorPortfolioConfigModel._default_manager.filter(is_active=True)
        return [m.to_domain() for m in models]

    def get_by_name(self, name: str) -> FactorPortfolioConfig | None:
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

    def create_model(self, data: dict) -> FactorPortfolioConfigModel:
        """Create one portfolio config ORM row."""

        return FactorPortfolioConfigModel._default_manager.create(**data)

    def update_model(
        self,
        *,
        config_id: int,
        data: dict,
    ) -> FactorPortfolioConfigModel | None:
        """Update one portfolio config ORM row."""

        config = self.get_model_by_id(config_id)
        if config is None:
            return None

        for field, value in data.items():
            setattr(config, field, value)

        update_fields = list(data.keys())
        if hasattr(config, "updated_at"):
            update_fields.append("updated_at")
        config.save(update_fields=update_fields)
        return config

    def list_models_for_view(
        self,
        *,
        is_active: bool | None = None,
        search: str | None = None,
    ) -> list[FactorPortfolioConfigModel]:
        """Return portfolio config ORM rows for management views."""

        queryset = FactorPortfolioConfigModel._default_manager.all()
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active)
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(description__icontains=search)
            )
        configs = list(queryset.order_by("-is_active", "-created_at"))
        for config in configs:
            latest_holding = config.holdings.order_by("-trade_date").first()
            config.latest_trade_date = latest_holding.trade_date if latest_holding else None
            config.holdings_count = (
                config.holdings.filter(trade_date=latest_holding.trade_date).count()
                if latest_holding
                else 0
            )
        return configs

    def get_view_stats(self) -> dict:
        """Return portfolio config statistics for management views."""

        return {
            "total": FactorPortfolioConfigModel._default_manager.count(),
            "active": FactorPortfolioConfigModel._default_manager.filter(is_active=True).count(),
        }

    def list_active_models(self) -> list[FactorPortfolioConfigModel]:
        """Return active portfolio config ORM rows for views."""

        return list(FactorPortfolioConfigModel._default_manager.filter(is_active=True))

    def get_model_by_id(self, config_id: int) -> FactorPortfolioConfigModel | None:
        """Return a portfolio config ORM row by id."""

        try:
            return FactorPortfolioConfigModel._default_manager.get(id=config_id)
        except FactorPortfolioConfigModel.DoesNotExist:
            return None

    def set_active(self, config_id: int, is_active: bool) -> FactorPortfolioConfigModel | None:
        """Set portfolio config activation state."""

        config = self.get_model_by_id(config_id)
        if config is None:
            return None
        config.is_active = is_active
        config.save()
        return config

    def delete_model(self, config_id: int) -> bool:
        """Delete one portfolio config ORM row."""

        config = self.get_model_by_id(config_id)
        if config is None:
            return False
        config.delete()
        return True

    def get_latest_calculation_results(
        self,
        *,
        config_id: int,
        top_n: int,
    ) -> tuple[FactorPortfolioConfigModel | None, dict | None]:
        """Return selected config and latest holdings payload for calculation view."""

        selected_config = self.get_model_by_id(config_id)
        if selected_config is None:
            return None, None

        latest_holding = FactorPortfolioHoldingModel._default_manager.filter(
            config=selected_config
        ).order_by("-trade_date").first()
        if latest_holding is None:
            return selected_config, None

        total_stocks = FactorPortfolioHoldingModel._default_manager.filter(
            config=selected_config,
            trade_date=latest_holding.trade_date,
        ).count()
        holdings = FactorPortfolioHoldingModel._default_manager.filter(
            config=selected_config,
            trade_date=latest_holding.trade_date,
        ).order_by("rank")[:top_n]
        return selected_config, {
            "trade_date": latest_holding.trade_date,
            "total_stocks": total_stocks,
            "holdings": holdings,
            "config_name": selected_config.name,
            "top_n": top_n,
        }


class FactorPortfolioHoldingRepository:
    """Repository for FactorPortfolioHolding entities"""

    def save_holdings(
        self,
        config_name: str,
        trade_date: date,
        holdings: list[FactorPortfolioHolding]
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

    def get_latest_holdings(self, config_name: str) -> list[FactorPortfolioHoldingModel]:
        """Get latest holdings for a configuration"""
        return FactorPortfolioHoldingModel._default_manager.filter(
            config__name=config_name
        ).order_by('-trade_date', 'rank')[:30]

