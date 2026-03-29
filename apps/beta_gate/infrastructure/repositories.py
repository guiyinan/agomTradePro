"""
Beta Gate Repositories

硬闸门过滤的数据仓储实现。
"""

import logging
from typing import Any, Dict, List, Optional

from django.db import transaction
from django.db.models import Q

from .models import (
    GateConfigModel,
    GateDecisionModel,
    VisibilityUniverseSnapshotModel,
)

logger = logging.getLogger(__name__)


class GateConfigRepository:
    """
    闸门配置仓储
    """

    def get_by_id(self, config_id: str) -> Any | None:
        """按 ID 获取配置"""
        try:
            return GateConfigModel._default_manager.get(config_id=config_id)
        except GateConfigModel.DoesNotExist:
            return None

    def get_by_risk_profile(self, risk_profile, at_time=None) -> Any | None:
        """按风险画像获取最新有效配置"""
        queryset = GateConfigModel._default_manager.active()
        return queryset.filter(risk_profile=risk_profile.value).first()

    def get_all_active(self, at_time=None) -> list[Any]:
        """获取所有激活配置"""
        return list(GateConfigModel._default_manager.active())

    def save(self, config) -> Any:
        """保存配置"""
        model = GateConfigModel.from_domain(config)
        with transaction.atomic():
            if model.is_active:
                lock_filter = Q(is_active=True) & Q(risk_profile=model.risk_profile)
                if model.pk:
                    lock_filter |= Q(pk=model.pk)
                list(
                    GateConfigModel._default_manager.select_for_update().filter(lock_filter).values_list(
                        "pk", flat=True
                    )
                )
                GateConfigModel._default_manager.active().filter(
                    risk_profile=model.risk_profile
                ).exclude(pk=model.pk).update(is_active=False)
            model.save()
        return model

    def get_history(self, risk_profile=None, limit=100) -> list[Any]:
        """获取配置历史"""
        queryset = GateConfigModel._default_manager.all()
        if risk_profile:
            queryset = queryset.filter(risk_profile=risk_profile.value)
        return list(queryset.order_by("-version")[:limit])


class GateDecisionRepository:
    """
    闸门决策仓储
    """

    def get_by_id(self, decision_id: str) -> Any | None:
        """按 ID 获取决策"""
        try:
            return GateDecisionModel._default_manager.get(decision_id=decision_id)
        except GateDecisionModel.DoesNotExist:
            return None

    def get_by_asset(self, asset_code: str, limit=100) -> list[Any]:
        """按资产获取决策历史"""
        return list(GateDecisionModel._default_manager.by_asset(asset_code).order_by("-evaluated_at")[:limit])

    def get_recent(self, days=30, status=None) -> list[Any]:
        """获取最近的决策"""
        queryset = GateDecisionModel._default_manager.all()
        return list(queryset.order_by("-evaluated_at")[:days])

    def save(self, decision) -> Any:
        """保存决策"""
        model = GateDecisionModel()
        model.decision_id = getattr(decision, "decision_id", None)
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

    def get_by_id(self, snapshot_id: str) -> dict | None:
        """按 ID 获取快照"""
        try:
            model = VisibilityUniverseSnapshotModel._default_manager.get(snapshot_id=snapshot_id)
            return self._to_dict(model)
        except VisibilityUniverseSnapshotModel.DoesNotExist:
            return None

    def get_latest(self, regime: str, policy_level: int) -> dict | None:
        """获取最新快照"""
        model = VisibilityUniverseSnapshotModel._default_manager.filter(
            current_regime=regime,
            policy_level=policy_level
        ).order_by("-as_of").first()
        if model:
            return self._to_dict(model)
        return None

    def save(self, universe) -> str:
        """保存快照"""
        import uuid
        snapshot_id = f"universe_{uuid.uuid4().hex[:12]}"
        model = VisibilityUniverseSnapshotModel(
            snapshot_id=snapshot_id,
            regime_snapshot_id=getattr(universe, "regime_snapshot_id", ""),
            policy_snapshot_id=getattr(universe, "policy_snapshot_id", ""),
            current_regime=universe.current_regime,
            policy_level=universe.policy_level if hasattr(universe, "policy_level") else 0,
            regime_confidence=getattr(universe, "regime_confidence", 0.5),
            risk_profile=universe.risk_profile.value,
            visible_asset_categories=list(getattr(universe, "visible_asset_categories", [])),
            visible_strategies=list(getattr(universe, "visible_strategies", [])),
            hard_exclusions=list(getattr(universe, "hard_exclusions", [])),
            watch_list=list(getattr(universe, "watch_list", [])),
            as_of=getattr(universe, "as_of", universe.created_at),
        )
        model.save()
        return snapshot_id

    def _to_dict(self, model) -> dict:
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


