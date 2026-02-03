"""
Beta Gate DRF Views

硬闸门过滤的 API 视图。

简化版本，避免复杂的依赖。
"""

import logging
from rest_framework import viewsets, status
from rest_framework.response import Response

from ..infrastructure.repositories import get_config_repository


logger = logging.getLogger(__name__)


class GateConfigViewSet(viewsets.ViewSet):
    """闸门配置视图集（简化版）"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.config_repository = get_config_repository()

    def list(self, request) -> Response:
        """获取所有激活配置"""
        try:
            configs = self.config_repository.get_all_active()
            results = []
            for config in configs:
                results.append({
                    "config_id": config.config_id,
                    "risk_profile": config.risk_profile.value,
                    "version": config.version,
                    "is_active": config.is_active,
                    "regime_constraints": config.regime_constraint.to_dict(),
                    "policy_constraints": config.policy_constraint.to_dict(),
                    "portfolio_constraints": config.portfolio_constraint.to_dict(),
                    "effective_date": config.effective_date.isoformat() if config.effective_date else None,
                    "expires_at": config.expires_at.isoformat() if config.expires_at else None,
                })
            return Response({
                "success": True,
                "count": len(results),
                "results": results,
            })
        except Exception as e:
            logger.error(f"Failed to list configs: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def retrieve(self, request, pk=None) -> Response:
        """获取指定配置"""
        try:
            config = self.config_repository.get_by_id(pk)
            if config is None:
                return Response(
                    {"success": False, "error": "Config not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )
            return Response({
                "success": True,
                "result": {
                    "config_id": config.config_id,
                    "risk_profile": config.risk_profile.value,
                    "version": config.version,
                    "is_active": config.is_active,
                    "regime_constraints": config.regime_constraint.to_dict(),
                    "policy_constraints": config.policy_constraint.to_dict(),
                    "portfolio_constraints": config.portfolio_constraint.to_dict(),
                },
            })
        except Exception as e:
            logger.error(f"Failed to retrieve config: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class GateDecisionViewSet(viewsets.ViewSet):
    """闸门决策视图集（简化版）"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        from ..infrastructure.repositories import get_decision_repository
        self.decision_repository = get_decision_repository()

    def list(self, request) -> Response:
        """获取决策历史"""
        try:
            days = int(request.query_params.get("days", 30))
            decisions = self.decision_repository.get_recent(days)
            results = []
            for decision in decisions:
                results.append({
                    "decision_id": getattr(decision, "decision_id", ""),
                    "asset_code": decision.asset_code,
                    "asset_class": decision.asset_class,
                    "status": decision.status.value,
                    "current_regime": decision.current_regime,
                    "policy_level": decision.policy_level,
                    "regime_confidence": decision.regime_confidence,
                    "evaluated_at": decision.evaluated_at.isoformat(),
                })
            return Response({
                "success": True,
                "count": len(results),
                "results": results,
            })
        except Exception as e:
            logger.error(f"Failed to list decisions: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def retrieve(self, request, pk=None) -> Response:
        """获取指定决策"""
        try:
            decision = self.decision_repository.get_by_id(pk)
            if decision is None:
                return Response(
                    {"success": False, "error": "Decision not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )
            return Response({
                "success": True,
                "result": {
                    "decision_id": getattr(decision, "decision_id", ""),
                    "asset_code": decision.asset_code,
                    "asset_class": decision.asset_class,
                    "status": decision.status.value,
                    "current_regime": decision.current_regime,
                    "policy_level": decision.policy_level,
                    "regime_confidence": decision.regime_confidence,
                    "evaluated_at": decision.evaluated_at.isoformat(),
                },
            })
        except Exception as e:
            logger.error(f"Failed to retrieve decision: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class VisibilityUniverseViewSet(viewsets.ViewSet):
    """可见性宇宙视图集（简化版）"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        from ..infrastructure.repositories import get_universe_repository
        self.universe_repository = get_universe_repository()

    def list(self, request) -> Response:
        """获取历史快照"""
        try:
            regime = request.query_params.get("regime", None)
            policy_level = request.query_params.get("policy_level", None)
            limit = int(request.query_params.get("limit", 100))

            snapshots = self.universe_repository.get_history(regime, policy_level, limit)
            return Response({
                "success": True,
                "count": len(snapshots),
                "results": snapshots,
            })
        except Exception as e:
            logger.error(f"Failed to list universe snapshots: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def retrieve(self, request, pk=None) -> Response:
        """获取指定快照"""
        try:
            snapshot = self.universe_repository.get_by_id(pk)
            if snapshot is None:
                return Response(
                    {"success": False, "error": "Snapshot not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )
            return Response({
                "success": True,
                "result": snapshot,
            })
        except Exception as e:
            logger.error(f"Failed to retrieve snapshot: {e}", exc_info=True)
            return Response(
                {"success": False, "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
