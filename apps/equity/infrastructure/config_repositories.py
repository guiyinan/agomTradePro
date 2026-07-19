"""Configuration repositories for the equity module.

Owns scoring-weight, valuation-repair-config, and bootstrap-config persistence
helpers. The compatibility facade in `repositories.py` remains the stable
import surface; do not import it here.
"""

from typing import Any

from django.utils import timezone

from apps.fund.infrastructure.models import FundTypePreferenceConfigModel
from apps.sector.infrastructure.models import SectorPreferenceConfigModel

from .models import StockScreeningRuleConfigModel


class ScoringWeightConfigRepository:
    """股票评分权重配置仓储"""

    def get_active_config(self):
        """
        获取当前启用的评分权重配置

        Returns:
            ScoringWeightConfig 实体，如果没有启用配置则返回默认配置
        """
        from .models import ScoringWeightConfigModel

        try:
            model = ScoringWeightConfigModel._default_manager.filter(is_active=True).first()

            if model:
                return model.to_domain_entity()

            # 没有启用配置时返回默认配置
            return self._get_default_config()

        except Exception:
            # 发生错误时返回默认配置
            return self._get_default_config()

    def get_config_by_name(self, name: str):
        """
        根据名称获取评分权重配置

        Args:
            name: 配置名称

        Returns:
            ScoringWeightConfig 实体，不存在则返回 None
        """
        from .models import ScoringWeightConfigModel

        try:
            model = ScoringWeightConfigModel._default_manager.filter(name=name).first()

            if model:
                return model.to_domain_entity()

            return None

        except Exception:
            return None

    def get_all_configs(self):
        """
        获取所有评分权重配置

        Returns:
            ScoringWeightConfig 实体列表
        """
        from .models import ScoringWeightConfigModel

        try:
            models = ScoringWeightConfigModel._default_manager.all().order_by(
                "-is_active", "-created_at"
            )
            return [m.to_domain_entity() for m in models]
        except Exception:
            return []

    def save_config(self, config_entity):
        """
        保存评分权重配置

        Args:
            config_entity: ScoringWeightConfig 实体
        """
        from .models import ScoringWeightConfigModel

        ScoringWeightConfigModel._default_manager.update_or_create(
            name=config_entity.name,
            defaults={
                "description": config_entity.description,
                "is_active": config_entity.is_active,
                "growth_weight": config_entity.growth_weight,
                "profitability_weight": config_entity.profitability_weight,
                "valuation_weight": config_entity.valuation_weight,
                "revenue_growth_weight": config_entity.revenue_growth_weight,
                "profit_growth_weight": config_entity.profit_growth_weight,
            },
        )

    def deactivate_other_active_configs(self, exclude_pk: int | None) -> None:
        """Ensure only one scoring-weight config remains active."""

        from .models import ScoringWeightConfigModel

        queryset = ScoringWeightConfigModel._default_manager.filter(is_active=True)
        if exclude_pk is not None:
            queryset = queryset.exclude(pk=exclude_pk)
        queryset.update(is_active=False)

    def _get_default_config(self):
        """
        获取默认评分权重配置

        当数据库中没有配置或配置加载失败时使用此默认值。
        """
        from apps.equity.domain.entities import ScoringWeightConfig

        return ScoringWeightConfig(
            name="默认配置",
            description="系统默认评分权重配置（当数据库配置不可用时使用）",
            is_active=True,
            growth_weight=0.4,
            profitability_weight=0.4,
            valuation_weight=0.2,
            revenue_growth_weight=0.5,
            profit_growth_weight=0.5,
        )


class ValuationRepairConfigRepository:
    """估值修复配置仓储。"""

    def get_queryset(self):
        """Return the config queryset ordered for admin/API use."""

        from .models import ValuationRepairConfigModel

        return ValuationRepairConfigModel._default_manager.all().order_by(
            "-is_active",
            "-version",
            "-created_at",
        )

    def get_active_model(self):
        """Return the active config model if present."""

        return self.get_queryset().filter(is_active=True).first()

    def get_active_domain_config(self):
        """Return the active config as a domain config object if present."""
        model = self.get_active_model()
        return model.to_domain_config() if model else None

    def get_active_version(self) -> int:
        """Return the active config version, or 0 if missing."""
        model = self.get_active_model()
        return int(getattr(model, "version", 0) or 0)

    def list_models(self) -> list:
        """Return all config models for interface/application consumers."""

        return list(self.get_queryset())

    def get_by_id(self, config_id: int):
        """Return one config model by primary key, if present."""

        return self.get_queryset().filter(pk=config_id).first()

    def create(self, *, data: dict, created_by: str):
        """Create one config model."""

        from .models import ValuationRepairConfigModel

        model = ValuationRepairConfigModel(
            **data,
            created_by=created_by,
        )
        model.save()
        return model

    def update(self, *, config_id: int, data: dict):
        """Update one config model and return the refreshed instance."""

        model = self.get_by_id(config_id)
        if model is None:
            return None

        for field_name, value in data.items():
            setattr(model, field_name, value)
        model.save()
        return model

    def activate(self, *, config_id: int):
        """Activate one config model and return the refreshed instance."""

        model = self.get_by_id(config_id)
        if model is None:
            return None

        model.is_active = True
        model.effective_from = timezone.now()
        model.save()
        return model

    def delete(self, *, config_id: int) -> bool:
        """Delete one config model if present."""

        model = self.get_by_id(config_id)
        if model is None:
            return False

        model.delete()
        return True


class EquityBootstrapConfigRepository:
    """Persistence helpers for equity bootstrap configuration commands."""

    def upsert_stock_screening_rule(self, rule_data: dict[str, Any]) -> None:
        """Create or update one stock screening rule row."""

        StockScreeningRuleConfigModel._default_manager.update_or_create(
            regime=rule_data["regime"],
            rule_name=rule_data["rule_name"],
            defaults=rule_data,
        )

    def upsert_sector_preference(self, preference: dict[str, Any]) -> None:
        """Create or update one sector preference row."""

        SectorPreferenceConfigModel._default_manager.update_or_create(
            regime=preference["regime"],
            sector_name=preference["sector_name"],
            defaults=preference,
        )

    def upsert_fund_type_preference(self, preference: dict[str, Any]) -> None:
        """Create or update one fund-type preference row."""

        FundTypePreferenceConfigModel._default_manager.update_or_create(
            regime=preference["regime"],
            fund_type=preference["fund_type"],
            style=preference["style"],
            defaults=preference,
        )


__all__ = [
    "EquityBootstrapConfigRepository",
    "ScoringWeightConfigRepository",
    "ValuationRepairConfigRepository",
]
