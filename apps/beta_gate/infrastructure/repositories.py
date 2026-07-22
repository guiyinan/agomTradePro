"""
Beta Gate Repositories

硬闸门过滤的数据仓储实现。
"""

import logging
from datetime import date, datetime
from typing import Any, Protocol
from uuid import uuid4

from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from apps.beta_gate.domain.entities import (
    GateConfig,
    GateDecision,
    GateStatus,
    RiskProfile,
    VisibilityUniverse,
)

from .models import (
    GateConfigModel,
    GateDecisionModel,
    VisibilityUniverseSnapshotModel,
)

logger = logging.getLogger(__name__)


class GateConfigFormDataProtocol(Protocol):
    """Validated form shape accepted by config persistence."""

    pk: int | None
    config_id: str
    risk_profile: str
    is_active: bool
    effective_date: date
    expires_at: date | None
    regime_constraints: dict[str, Any]
    policy_constraints: dict[str, Any]
    portfolio_constraints: dict[str, Any]


class GateConfigRepository:
    """
    闸门配置仓储
    """

    def get_by_id(self, config_id: str) -> GateConfigModel | None:
        """按 ID 获取配置"""
        try:
            return GateConfigModel._default_manager.get(config_id=config_id)
        except GateConfigModel.DoesNotExist:
            return None

    def get_by_version(self, version: int) -> GateConfigModel | None:
        """按版本获取配置"""
        return GateConfigModel._default_manager.filter(version=version).first()

    def find_by_config_id_or_version(self, identifier: str) -> GateConfigModel | None:
        """按 config_id 或版本号获取配置。"""
        config = self.get_by_id(str(identifier))
        if config:
            return config
        try:
            return self.get_by_version(int(identifier))
        except (TypeError, ValueError):
            return None

    def get_by_risk_profile(
        self,
        risk_profile: RiskProfile | str,
        at_time: date | datetime | None = None,
    ) -> GateConfigModel | None:
        """按风险画像获取最新有效配置"""
        queryset = GateConfigModel._default_manager.active()
        if at_time is not None:
            queryset = queryset.valid_at(at_time)
        raw_profile = getattr(risk_profile, "value", risk_profile)
        profile_candidates = {str(raw_profile), str(raw_profile).upper(), str(raw_profile).lower()}
        return queryset.filter(risk_profile__in=profile_candidates).first()

    def get_all_active(self, at_time: date | datetime | None = None) -> list[GateConfigModel]:
        """获取所有激活配置"""
        queryset = GateConfigModel._default_manager.active()
        if at_time is not None:
            queryset = queryset.valid_at(at_time)
        return list(queryset)

    def save(self, config: GateConfig) -> GateConfigModel:
        """保存配置"""
        model = GateConfigModel.from_domain(config)
        with transaction.atomic():
            max_version = GateConfigModel._default_manager.aggregate(max_v=Max("version")).get(
                "max_v"
            )
            model.version = (max_version or 0) + 1
            if model.is_active:
                lock_filter = Q(is_active=True) & Q(risk_profile=model.risk_profile)
                if model.pk:
                    lock_filter |= Q(pk=model.pk)
                list(
                    GateConfigModel._default_manager.select_for_update()
                    .filter(lock_filter)
                    .values_list("pk", flat=True)
                )
                GateConfigModel._default_manager.active().filter(
                    risk_profile=model.risk_profile
                ).exclude(pk=model.pk).update(is_active=False)
            model.save()
        return model

    def save_form_data(self, form_data: GateConfigFormDataProtocol) -> GateConfigModel:
        """保存由界面表单校验后的配置数据。"""
        form_pk = form_data.pk
        if form_pk is not None:
            model = GateConfigModel._default_manager.get(pk=form_pk)
        else:
            model = GateConfigModel()
            max_version = GateConfigModel._default_manager.aggregate(max_v=Max("version")).get(
                "max_v"
            )
            model.version = (max_version or 0) + 1

        model.config_id = form_data.config_id
        model.risk_profile = form_data.risk_profile
        model.is_active = form_data.is_active
        model.effective_date = form_data.effective_date
        model.expires_at = form_data.expires_at
        model.regime_constraints = form_data.regime_constraints
        model.policy_constraints = form_data.policy_constraints
        model.portfolio_constraints = form_data.portfolio_constraints

        return self._save_with_single_active(model)

    def get_history(
        self,
        risk_profile: RiskProfile | str | None = None,
        limit: int | None = 100,
    ) -> list[GateConfigModel]:
        """获取配置历史"""
        queryset = GateConfigModel._default_manager.all()
        if risk_profile:
            raw_profile = getattr(risk_profile, "value", risk_profile)
            queryset = queryset.filter(risk_profile__in=[raw_profile, str(raw_profile).upper()])
        ordered = queryset.order_by("-version")
        return list(ordered if limit is None else ordered[:limit])

    def list_latest(self, limit: int | None = 100) -> list[GateConfigModel]:
        """获取最新配置版本。"""
        queryset = GateConfigModel._default_manager.all().order_by("-version")
        return list(queryset if limit is None else queryset[:limit])

    def get_active_model(self) -> GateConfigModel | None:
        """获取第一个激活配置模型。"""
        return GateConfigModel._default_manager.active().first()

    def resolve_version_by_config_id(self, config_id: str) -> int | None:
        """按 config_id 解析版本号。"""
        config = self.get_by_id(config_id)
        return config.version if config else None

    def activate_by_config_id(self, config_id: str) -> GateConfigModel | None:
        """激活指定 config_id 的配置。"""
        config = self.get_by_id(config_id)
        if config is None:
            return None
        return self._activate_model(config)

    def activate_by_version(self, version: int) -> GateConfigModel | None:
        """激活指定版本的配置。"""
        config = self.get_by_version(version)
        if config is None:
            return None
        return self._activate_model(config)

    def deactivate_by_config_id(self, config_id: str) -> GateConfigModel | None:
        """Soft-delete a config while retaining its version history."""

        with transaction.atomic():
            config = (
                GateConfigModel._default_manager.select_for_update()
                .filter(config_id=config_id)
                .first()
            )
            if config is None:
                return None
            if config.is_active:
                config.is_active = False
                config.save(update_fields=["is_active", "updated_at"])
            return config

    def _save_with_single_active(self, model: GateConfigModel) -> GateConfigModel:
        with transaction.atomic():
            if model.is_active:
                lock_filter = Q(is_active=True, risk_profile=model.risk_profile)
                if model.pk:
                    lock_filter |= Q(pk=model.pk)
                list(
                    GateConfigModel._default_manager.select_for_update()
                    .filter(lock_filter)
                    .values_list("pk", flat=True)
                )
                GateConfigModel._default_manager.active().filter(
                    risk_profile=model.risk_profile
                ).exclude(pk=model.pk).update(is_active=False)
            model.save()
        return model

    def _activate_model(self, target_config: GateConfigModel) -> GateConfigModel:
        with transaction.atomic():
            list(
                GateConfigModel._default_manager.select_for_update()
                .filter(
                    Q(pk=target_config.pk)
                    | Q(is_active=True, risk_profile=target_config.risk_profile)
                )
                .values_list("pk", flat=True)
            )
            GateConfigModel._default_manager.active().filter(
                risk_profile=target_config.risk_profile
            ).exclude(pk=target_config.pk).update(is_active=False)
            target_config.is_active = True
            target_config.effective_date = timezone.now().date()
            target_config.save(update_fields=["is_active", "effective_date", "updated_at"])
        return target_config


class GateDecisionRepository:
    """
    闸门决策仓储
    """

    def get_by_id(self, decision_id: str) -> GateDecisionModel | None:
        """按 ID 获取决策"""
        try:
            return GateDecisionModel._default_manager.get(decision_id=decision_id)
        except GateDecisionModel.DoesNotExist:
            return None

    def get_by_asset(self, asset_code: str, limit: int = 100) -> list[GateDecisionModel]:
        """按资产获取决策历史"""
        return list(
            GateDecisionModel._default_manager.by_asset(asset_code).order_by("-evaluated_at")[
                :limit
            ]
        )

    def get_recent(
        self, days: int = 30, status: GateStatus | str | None = None
    ) -> list[GateDecisionModel]:
        """获取最近的决策"""
        queryset = GateDecisionModel._default_manager.all()
        if status is not None:
            raw_status = status.value if isinstance(status, GateStatus) else status
            queryset = queryset.filter(status=raw_status)
        return list(queryset.order_by("-evaluated_at")[:days])

    def get_latest(self, limit: int = 10) -> list[GateDecisionModel]:
        """获取最近的决策模型。"""
        return list(GateDecisionModel._default_manager.all().order_by("-evaluated_at")[:limit])

    def save(self, decision: GateDecision) -> GateDecisionModel:
        """保存决策"""
        model = GateDecisionModel()
        model.decision_id = f"decision_{uuid4().hex}"
        model.asset_code = decision.asset_code
        model.asset_class = decision.asset_class
        model.status = decision.status.value
        model.current_regime = decision.current_regime
        model.policy_level = decision.policy_level
        model.regime_confidence = decision.regime_confidence
        model.evaluation_details = {
            "regime_check": getattr(decision, "regime_check", (True, "")),
            "policy_check": getattr(decision, "policy_check", (True, "")),
            "risk_check": getattr(decision, "risk_check", (True, "")),
            "portfolio_check": getattr(decision, "portfolio_check", (True, "")),
            "blocking_reason": getattr(decision, "blocking_reason", ""),
        }
        model.save()
        return model


class VisibilityUniverseRepository:
    """
    可见性宇宙仓储
    """

    def get_by_id(self, snapshot_id: str) -> dict[str, Any] | None:
        """按 ID 获取快照"""
        try:
            model = VisibilityUniverseSnapshotModel._default_manager.get(snapshot_id=snapshot_id)
            return self._to_dict(model)
        except VisibilityUniverseSnapshotModel.DoesNotExist:
            return None

    def get_latest(self, regime: str, policy_level: int) -> dict[str, Any] | None:
        """获取最新快照"""
        model = (
            VisibilityUniverseSnapshotModel._default_manager.filter(
                current_regime=regime, policy_level=policy_level
            )
            .order_by("-as_of")
            .first()
        )
        if model:
            return self._to_dict(model)
        return None

    def save(self, universe: VisibilityUniverse) -> str:
        """保存快照"""
        snapshot_id = f"universe_{uuid4().hex[:12]}"
        model = VisibilityUniverseSnapshotModel(
            snapshot_id=snapshot_id,
            regime_snapshot_id=getattr(universe, "regime_snapshot_id", ""),
            policy_snapshot_id=getattr(universe, "policy_snapshot_id", ""),
            current_regime=universe.current_regime,
            policy_level=universe.policy_level,
            regime_confidence=universe.regime_confidence,
            risk_profile=universe.risk_profile.value,
            visible_asset_categories=list(universe.visible_asset_categories),
            visible_strategies=list(universe.visible_strategies),
            hard_exclusions=list(universe.hard_exclusions),
            watch_list=list(universe.watch_list),
            as_of=universe.as_of,
        )
        model.save()
        return snapshot_id

    def get_history(
        self,
        regime: str | None = None,
        policy_level: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """获取历史可见性宇宙快照。"""
        queryset = VisibilityUniverseSnapshotModel._default_manager.all()
        if regime:
            queryset = queryset.filter(current_regime=regime)
        if policy_level is not None:
            queryset = queryset.filter(policy_level=policy_level)
        try:
            limit_int = int(limit)
        except (TypeError, ValueError):
            limit_int = 100
        return [self._to_dict(model) for model in queryset.order_by("-as_of")[:limit_int]]

    def _to_dict(self, model: VisibilityUniverseSnapshotModel) -> dict[str, Any]:
        """转换为字典"""
        return {
            "snapshot_id": model.snapshot_id,
            "regime_snapshot_id": model.regime_snapshot_id,
            "policy_snapshot_id": model.policy_snapshot_id,
            "current_regime": model.current_regime,
            "policy_level": model.policy_level,
            "regime_confidence": model.regime_confidence,
            "risk_profile": model.risk_profile,
            "visible_asset_categories": model.visible_asset_categories,
            "visible_strategies": model.visible_strategies,
            "hard_exclusions": model.hard_exclusions,
            "watch_list": model.watch_list,
            "as_of": model.as_of,
            "created_at": model.created_at,
        }


def get_config_repository() -> GateConfigRepository:
    """获取配置仓储实例"""
    return GateConfigRepository()


def get_decision_repository() -> GateDecisionRepository:
    """获取决策仓储实例"""
    return GateDecisionRepository()


def get_universe_repository() -> VisibilityUniverseRepository:
    """获取宇宙仓储实例"""
    return VisibilityUniverseRepository()
