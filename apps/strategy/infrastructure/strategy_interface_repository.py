"""
Django ORM Repository Implementations for Strategy System

Infrastructure层:
- 实现Domain层定义的Protocol接口
- 负责数据持久化和检索
- 提供ORM对象到Domain实体的转换
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.db.models import Count, Q, QuerySet

from apps.ai_provider.infrastructure.models import AIProviderConfig
from apps.prompt.infrastructure.models import ChainConfigORM, PromptTemplateORM
from apps.strategy.infrastructure.models import (
    AIStrategyConfigModel,
    PortfolioStrategyAssignmentModel,
    PositionManagementRuleModel,
    RuleConditionModel,
    ScriptConfigModel,
    StrategyExecutionLogModel,
    StrategyModel,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class StrategyInterfaceRepository:
    """Strategy interface 层只读/轻写入仓储。"""

    def get_strategy_queryset(self) -> QuerySet[StrategyModel]:
        queryset: QuerySet[StrategyModel] = StrategyModel._default_manager.select_related(
            "created_by"
        ).all()
        return queryset

    def get_strategy_queryset_for_owner(
        self,
        owner_profile_id: int,
    ) -> QuerySet[StrategyModel]:
        return self.get_strategy_queryset().filter(created_by_id=owner_profile_id)

    def get_strategy_queryset_for_access(
        self,
        *,
        owner_profile_id: int | None,
        include_all: bool = False,
    ) -> QuerySet[StrategyModel]:
        """Return strategies visible to one authenticated owner or staff caller."""

        queryset = self.get_strategy_queryset()
        if include_all:
            return queryset
        if owner_profile_id is None:
            return queryset.none()
        return queryset.filter(created_by_id=owner_profile_id)

    def list_user_strategies_with_counts(
        self,
        owner_profile_id: int,
    ) -> QuerySet[StrategyModel]:
        queryset: QuerySet[StrategyModel] = (
            self.get_strategy_queryset_for_owner(owner_profile_id)
            .annotate(
                rule_count=Count("rules", distinct=True),
                execution_count=Count("execution_logs", distinct=True),
                portfolio_count=Count("portfolio_assignments", distinct=True),
            )
            .order_by("-created_at")
        )
        return queryset

    def get_user_strategy_stats(self, owner_profile_id: int) -> dict[str, Any]:
        queryset = StrategyModel._default_manager.filter(created_by_id=owner_profile_id)
        return {
            "total": queryset.count(),
            "active": queryset.filter(is_active=True).count(),
            "inactive": queryset.filter(is_active=False).count(),
            "by_type": {
                "rule_based": queryset.filter(strategy_type="rule_based").count(),
                "script_based": queryset.filter(strategy_type="script_based").count(),
                "hybrid": queryset.filter(strategy_type="hybrid").count(),
                "ai_driven": queryset.filter(strategy_type="ai_driven").count(),
            },
        }

    def list_strategy_rule_summary(
        self,
        strategy_id: int,
        limit: int = 3,
    ) -> list[RuleConditionModel]:
        rows: list[RuleConditionModel] = list(
            RuleConditionModel._default_manager.filter(
                strategy_id=strategy_id,
                is_enabled=True,
            ).order_by("-priority", "-created_at")[:limit]
        )
        return rows

    def replace_rule_conditions(
        self,
        strategy_id: int,
        validated_rules: list[dict[str, Any]],
    ) -> None:
        with transaction.atomic():
            RuleConditionModel._default_manager.filter(strategy_id=strategy_id).delete()
            for validated_rule in validated_rules:
                RuleConditionModel._default_manager.create(**validated_rule)

    def get_strategy_script_config(
        self,
        strategy_id: int,
    ) -> ScriptConfigModel | None:
        config: ScriptConfigModel | None = ScriptConfigModel._default_manager.filter(
            strategy_id=strategy_id
        ).first()
        return config

    def delete_strategy_script_config(self, strategy_id: int) -> None:
        ScriptConfigModel._default_manager.filter(strategy_id=strategy_id).delete()

    def get_strategy_ai_config(
        self,
        strategy_id: int,
    ) -> AIStrategyConfigModel | None:
        config: AIStrategyConfigModel | None = AIStrategyConfigModel._default_manager.filter(
            strategy_id=strategy_id
        ).first()
        return config

    def list_active_prompt_templates(self) -> list[PromptTemplateORM]:
        templates: list[PromptTemplateORM] = list(
            PromptTemplateORM._default_manager.filter(is_active=True).order_by("category", "name")
        )
        return templates

    def list_active_chain_configs(self) -> list[ChainConfigORM]:
        configs: list[ChainConfigORM] = list(
            ChainConfigORM._default_manager.filter(is_active=True).order_by("category", "name")
        )
        return configs

    def list_active_ai_providers_for_user(
        self,
        user_id: int,
    ) -> list[AIProviderConfig]:
        providers: list[AIProviderConfig] = list(
            AIProviderConfig._default_manager.filter(
                Q(scope="system") | Q(scope="user", owner_user_id=user_id),
                is_active=True,
            ).order_by("priority", "name")
        )
        return providers

    def get_strategy_execution_logs_page(
        self,
        strategy_id: int,
        offset: int,
        limit: int,
    ) -> tuple[QuerySet[StrategyExecutionLogModel], int]:
        queryset: QuerySet[StrategyExecutionLogModel] = (
            StrategyExecutionLogModel._default_manager.filter(strategy_id=strategy_id)
            .select_related("strategy", "portfolio")
            .order_by("-execution_time")
        )
        return queryset[offset : offset + limit], int(queryset.count())

    def get_strategy_position_rule(
        self,
        strategy_id: int,
    ) -> PositionManagementRuleModel | None:
        rule: PositionManagementRuleModel | None = (
            PositionManagementRuleModel._default_manager.select_related("strategy")
            .filter(strategy_id=strategy_id)
            .first()
        )
        return rule

    def get_position_management_rule_queryset(
        self,
    ) -> QuerySet[PositionManagementRuleModel]:
        queryset: QuerySet[PositionManagementRuleModel] = (
            PositionManagementRuleModel._default_manager.select_related("strategy").all()
        )
        return queryset

    def get_position_management_rule_queryset_for_access(
        self,
        *,
        owner_profile_id: int | None,
        include_all: bool = False,
    ) -> QuerySet[PositionManagementRuleModel]:
        """Return position rules visible to one owner or staff caller."""

        queryset = self.get_position_management_rule_queryset()
        if include_all:
            return queryset
        if owner_profile_id is None:
            return queryset.none()
        return queryset.filter(strategy__created_by_id=owner_profile_id)

    def get_rule_condition_queryset(self) -> QuerySet[RuleConditionModel]:
        queryset: QuerySet[RuleConditionModel] = RuleConditionModel._default_manager.select_related(
            "strategy"
        ).all()
        return queryset

    def get_rule_condition_queryset_for_access(
        self,
        *,
        owner_profile_id: int | None,
        include_all: bool = False,
    ) -> QuerySet[RuleConditionModel]:
        """Return rule conditions visible to one owner or staff caller."""

        queryset = self.get_rule_condition_queryset()
        if include_all:
            return queryset
        if owner_profile_id is None:
            return queryset.none()
        return queryset.filter(strategy__created_by_id=owner_profile_id)

    def get_script_config_queryset(self) -> QuerySet[ScriptConfigModel]:
        queryset: QuerySet[ScriptConfigModel] = ScriptConfigModel._default_manager.select_related(
            "strategy"
        ).order_by(
            "strategy_id",
            "id",
        )
        return queryset

    def get_script_config_queryset_for_access(
        self,
        *,
        owner_profile_id: int | None,
        include_all: bool = False,
    ) -> QuerySet[ScriptConfigModel]:
        """Return script configurations visible to one owner or staff caller."""

        queryset = self.get_script_config_queryset()
        if include_all:
            return queryset
        if owner_profile_id is None:
            return queryset.none()
        return queryset.filter(strategy__created_by_id=owner_profile_id)

    def get_ai_strategy_config_queryset(self) -> QuerySet[AIStrategyConfigModel]:
        queryset: QuerySet[AIStrategyConfigModel] = (
            AIStrategyConfigModel._default_manager.select_related(
                "strategy",
                "prompt_template",
                "chain_config",
                "ai_provider",
            ).order_by("strategy_id", "id")
        )
        return queryset

    def get_ai_strategy_config_queryset_for_access(
        self,
        *,
        owner_profile_id: int | None,
        include_all: bool = False,
    ) -> QuerySet[AIStrategyConfigModel]:
        """Return AI strategy configs visible to one owner or staff caller."""

        queryset = self.get_ai_strategy_config_queryset()
        if include_all:
            return queryset
        if owner_profile_id is None:
            return queryset.none()
        return queryset.filter(strategy__created_by_id=owner_profile_id)

    def strategy_is_accessible(
        self,
        *,
        strategy_id: int,
        owner_profile_id: int | None,
        include_all: bool = False,
    ) -> bool:
        """Return whether one caller may configure the selected strategy."""

        return (
            self.get_strategy_queryset_for_access(
                owner_profile_id=owner_profile_id,
                include_all=include_all,
            )
            .filter(pk=strategy_id)
            .exists()
        )

    def strategy_is_active(self, strategy_id: int) -> bool:
        """Return whether the strategy exists and is enabled for execution."""

        return StrategyModel._default_manager.filter(
            pk=strategy_id,
            is_active=True,
        ).exists()

    def get_assignment_queryset(
        self,
    ) -> QuerySet[PortfolioStrategyAssignmentModel]:
        queryset: QuerySet[PortfolioStrategyAssignmentModel] = (
            PortfolioStrategyAssignmentModel._default_manager.select_related(
                "portfolio",
                "strategy",
                "assigned_by",
            ).all()
        )
        return queryset

    def get_assignment_queryset_for_access(
        self,
        *,
        owner_profile_id: int | None,
        include_all: bool = False,
    ) -> QuerySet[PortfolioStrategyAssignmentModel]:
        """Return assignments owned through both strategy and portfolio."""

        queryset = self.get_assignment_queryset()
        if include_all:
            return queryset
        if owner_profile_id is None:
            return queryset.none()
        return queryset.filter(
            strategy__created_by_id=owner_profile_id,
            portfolio__user__account_profile__id=owner_profile_id,
        )

    def list_assignments_by_portfolio(
        self,
        portfolio_id: int,
    ) -> QuerySet[PortfolioStrategyAssignmentModel]:
        return self.get_assignment_queryset().filter(portfolio_id=portfolio_id)

    def list_assignments_by_portfolio_for_access(
        self,
        *,
        portfolio_id: int,
        owner_profile_id: int | None,
        include_all: bool = False,
    ) -> QuerySet[PortfolioStrategyAssignmentModel]:
        """Return visible assignments for one portfolio."""

        return self.get_assignment_queryset_for_access(
            owner_profile_id=owner_profile_id,
            include_all=include_all,
        ).filter(portfolio_id=portfolio_id)

    def list_active_assignments_for_strategy(
        self,
        strategy_id: int,
    ) -> list[PortfolioStrategyAssignmentModel]:
        assignments: list[PortfolioStrategyAssignmentModel] = list(
            self.get_assignment_queryset().filter(
                strategy_id=strategy_id,
                is_active=True,
            )
        )
        return assignments

    def bind_strategy(
        self,
        *,
        portfolio_id: int,
        strategy: StrategyModel,
        assigned_by: Any,
    ) -> PortfolioStrategyAssignmentModel:
        with transaction.atomic():
            assignments: QuerySet[
                PortfolioStrategyAssignmentModel
            ] = PortfolioStrategyAssignmentModel._default_manager.select_for_update().filter(
                portfolio_id=portfolio_id
            )
            assignments.filter(is_active=True).exclude(strategy=strategy).update(is_active=False)
            assignment_result: tuple[PortfolioStrategyAssignmentModel, bool] = (
                assignments.get_or_create(
                    portfolio_id=portfolio_id,
                    strategy=strategy,
                    defaults={
                        "assigned_by": assigned_by,
                        "is_active": True,
                    },
                )
            )
            assignment, created = assignment_result
            if not created and (
                not assignment.is_active or assignment.assigned_by_id != assigned_by.id
            ):
                assignment.is_active = True
                assignment.assigned_by = assigned_by
                assignment.save(update_fields=["is_active", "assigned_by", "updated_at"])
            return assignment

    def unbind_portfolio_strategies(self, portfolio_id: int) -> None:
        with transaction.atomic():
            PortfolioStrategyAssignmentModel._default_manager.select_for_update().filter(
                portfolio_id=portfolio_id,
                is_active=True,
            ).update(is_active=False)

    def set_strategy_active(
        self,
        strategy_id: int,
        is_active: bool,
    ) -> StrategyModel | None:
        strategy = StrategyModel._default_manager.filter(id=strategy_id).first()
        if strategy is None:
            return None
        strategy.is_active = is_active
        strategy.save(update_fields=["is_active", "updated_at"])
        return strategy

    def set_rule_enabled(
        self,
        rule_id: int,
        is_enabled: bool,
    ) -> RuleConditionModel | None:
        rule = RuleConditionModel._default_manager.filter(id=rule_id).first()
        if rule is None:
            return None
        rule.is_enabled = is_enabled
        rule.save(update_fields=["is_enabled", "updated_at"])
        return rule

    def set_assignment_active(
        self,
        assignment_id: int,
        is_active: bool,
    ) -> PortfolioStrategyAssignmentModel | None:
        assignment = PortfolioStrategyAssignmentModel._default_manager.filter(
            id=assignment_id
        ).first()
        if assignment is None:
            return None
        assignment.is_active = is_active
        assignment.save(update_fields=["is_active", "updated_at"])
        return assignment

    def get_execution_log_queryset(
        self,
    ) -> QuerySet[StrategyExecutionLogModel]:
        queryset: QuerySet[StrategyExecutionLogModel] = (
            StrategyExecutionLogModel._default_manager.select_related(
                "strategy",
                "portfolio",
            ).all()
        )
        return queryset

    def get_execution_log_queryset_for_access(
        self,
        *,
        owner_profile_id: int | None,
        include_all: bool = False,
    ) -> QuerySet[StrategyExecutionLogModel]:
        """Return logs only when both strategy and portfolio belong to the caller."""

        queryset = self.get_execution_log_queryset()
        if include_all:
            return queryset
        if owner_profile_id is None:
            return queryset.none()
        return queryset.filter(
            strategy__created_by_id=owner_profile_id,
            portfolio__user__account_profile__id=owner_profile_id,
        )

    def list_execution_logs_by_strategy(
        self,
        strategy_id: int,
        limit: int = 100,
    ) -> list[StrategyExecutionLogModel]:
        logs: list[StrategyExecutionLogModel] = list(
            self.get_execution_log_queryset().filter(strategy_id=strategy_id)[:limit]
        )
        return logs

    def list_execution_logs_by_strategy_for_access(
        self,
        *,
        strategy_id: int,
        owner_profile_id: int | None,
        include_all: bool = False,
        limit: int = 100,
    ) -> list[StrategyExecutionLogModel]:
        """Return owner-scoped logs for one strategy."""

        return list(
            self.get_execution_log_queryset_for_access(
                owner_profile_id=owner_profile_id,
                include_all=include_all,
            ).filter(strategy_id=strategy_id)[:limit]
        )

    def list_execution_logs_by_portfolio(
        self,
        portfolio_id: int,
        limit: int = 100,
    ) -> list[StrategyExecutionLogModel]:
        logs: list[StrategyExecutionLogModel] = list(
            self.get_execution_log_queryset().filter(portfolio_id=portfolio_id)[:limit]
        )
        return logs

    def list_execution_logs_by_portfolio_for_access(
        self,
        *,
        portfolio_id: int,
        owner_profile_id: int | None,
        include_all: bool = False,
        limit: int = 100,
    ) -> list[StrategyExecutionLogModel]:
        """Return owner-scoped logs for one portfolio."""

        return list(
            self.get_execution_log_queryset_for_access(
                owner_profile_id=owner_profile_id,
                include_all=include_all,
            ).filter(portfolio_id=portfolio_id)[:limit]
        )


__all__ = ["StrategyInterfaceRepository"]
