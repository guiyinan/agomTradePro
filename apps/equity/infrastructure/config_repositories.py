"""Configuration repositories for the equity module.

Owns scoring-weight, valuation-repair-config, and bootstrap-config persistence
helpers. The compatibility facade in `repositories.py` remains the stable
import surface; do not import it here.
"""

import logging
from typing import Any

from django.db import transaction
from django.db.models import QuerySet
from django.db.utils import OperationalError, ProgrammingError
from django.utils import timezone

from apps.equity.domain.entities import ScoringWeightConfig
from apps.equity.domain.entities_valuation_repair import ValuationRepairConfig
from apps.fund.infrastructure.models import FundTypePreferenceConfigModel
from apps.sector.infrastructure.models import SectorPreferenceConfigModel
from core.exceptions import MissingConfigError

from .models import (
    ScoringWeightConfigModel,
    StockScreeningRuleConfigModel,
    ValuationRepairConfigModel,
)

logger = logging.getLogger(__name__)


class ScoringWeightConfigRepository:
    """股票评分权重配置仓储"""

    def get_active_config(self) -> ScoringWeightConfig:
        """
        获取当前启用的评分权重配置

        Returns:
            当前唯一启用的 ScoringWeightConfig 实体。

        Raises:
            MissingConfigError: 数据库中没有启用的评分权重配置。
        """
        try:
            model = ScoringWeightConfigModel._default_manager.get(is_active=True)
        except ScoringWeightConfigModel.DoesNotExist as exc:
            raise MissingConfigError("未配置启用的股票评分权重，无法执行股票筛选") from exc
        return model.to_domain_entity()

    def get_config_by_name(self, name: str) -> ScoringWeightConfig | None:
        """
        根据名称获取评分权重配置

        Args:
            name: 配置名称

        Returns:
            ScoringWeightConfig 实体，不存在则返回 None
        """
        try:
            model = ScoringWeightConfigModel._default_manager.get(name=name)
        except ScoringWeightConfigModel.DoesNotExist:
            return None
        return model.to_domain_entity()

    def get_all_configs(self) -> list[ScoringWeightConfig]:
        """
        获取所有评分权重配置

        Returns:
            ScoringWeightConfig 实体列表
        """
        models = ScoringWeightConfigModel._default_manager.all().order_by(
            "-is_active", "-created_at"
        )
        return [model.to_domain_entity() for model in models]

    def save_config(self, config_entity: ScoringWeightConfig) -> None:
        """
        保存评分权重配置

        Args:
            config_entity: ScoringWeightConfig 实体
        """
        with transaction.atomic():
            if config_entity.is_active:
                ScoringWeightConfigModel._default_manager.select_for_update().filter(
                    is_active=True
                ).exclude(name=config_entity.name).update(is_active=False)
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


class ValuationRepairConfigRepository:
    """估值修复配置仓储。"""

    def get_queryset(self) -> QuerySet[ValuationRepairConfigModel]:
        """Return the config queryset ordered for admin/API use."""

        return ValuationRepairConfigModel._default_manager.all().order_by(
            "-is_active",
            "-version",
            "-created_at",
        )

    def get_active_model(self) -> ValuationRepairConfigModel | None:
        """Return the active config model if present."""

        return self.get_queryset().filter(is_active=True).first()

    def get_active_model_if_available(self) -> ValuationRepairConfigModel | None:
        """Return the active model, or None while its table is unavailable."""

        try:
            return self.get_active_model()
        except (OperationalError, ProgrammingError) as exc:
            logger.warning(
                "Valuation repair config model is unavailable: %s",
                type(exc).__name__,
            )
            return None

    def get_active_domain_config(self) -> ValuationRepairConfig | None:
        """Return the active config as a domain config object if present."""
        model = self.get_active_model()
        return model.to_domain_config() if model else None

    def get_active_domain_config_if_available(self) -> ValuationRepairConfig | None:
        """Return the active Domain config without leaking schema exceptions upward."""

        model = self.get_active_model_if_available()
        return model.to_domain_config() if model else None

    def get_active_version(self) -> int:
        """Return the active config version, or 0 if missing."""
        model = self.get_active_model()
        return int(getattr(model, "version", 0) or 0)

    def get_active_version_if_available(self) -> int:
        """Return the active version, or zero while its table is unavailable."""

        model = self.get_active_model_if_available()
        return int(getattr(model, "version", 0) or 0)

    def list_models(self) -> list[ValuationRepairConfigModel]:
        """Return all config models for interface/application consumers."""

        return list(self.get_queryset())

    def get_by_id(self, config_id: int) -> ValuationRepairConfigModel | None:
        """Return one config model by primary key, if present."""

        return self.get_queryset().filter(pk=config_id).first()

    def create(
        self,
        *,
        data: dict[str, Any],
        created_by: str,
    ) -> ValuationRepairConfigModel:
        """Create one config model."""

        model = ValuationRepairConfigModel(
            **data,
            created_by=created_by,
        )
        model.save()
        return model

    def update(
        self,
        *,
        config_id: int,
        data: dict[str, Any],
    ) -> ValuationRepairConfigModel | None:
        """Update one config model and return the refreshed instance."""

        model = self.get_by_id(config_id)
        if model is None:
            return None

        for field_name, value in data.items():
            setattr(model, field_name, value)
        model.save()
        return model

    def activate(self, *, config_id: int) -> ValuationRepairConfigModel | None:
        """Activate one config model and return the refreshed instance."""

        with transaction.atomic():
            models = self.get_queryset().select_for_update()
            model = models.filter(pk=config_id).first()
            if model is None:
                return None

            models.filter(is_active=True).exclude(pk=config_id).update(is_active=False)
            model.is_active = True
            model.effective_from = timezone.now()
            model.save(update_fields=["is_active", "effective_from", "updated_at"])
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
