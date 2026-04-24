"""Django read model for beta-gate config summaries."""

from __future__ import annotations

from typing import Any

from .models import GateConfigModel


class DjangoBetaGateConfigSummaryRepository:
    """ORM-backed beta-gate config-summary repository."""

    def get_beta_gate_summary(self) -> dict[str, Any]:
        """Return beta-gate configuration summary."""

        active_config = GateConfigModel._default_manager.active().first()
        total_versions = GateConfigModel._default_manager.count()
        if not active_config:
            return {
                "status": "missing",
                "summary": {
                    "message": "未发现激活的 Beta Gate 配置",
                    "total_versions": total_versions,
                },
            }

        return {
            "status": "configured",
            "summary": {
                "config_id": active_config.config_id,
                "risk_profile": active_config.risk_profile,
                "version": active_config.version,
                "total_versions": total_versions,
                "effective_date": (
                    active_config.effective_date.isoformat() if active_config.effective_date else None
                ),
            },
        }

    def get_active_config_context(self) -> dict[str, Any]:
        """Return active beta-gate context for decision workspace."""

        active_config = GateConfigModel._default_manager.active().first()
        if active_config is None:
            return {
                "allowed_asset_classes": [],
                "config_id": None,
            }

        regime_constraints = (
            active_config.regime_constraints
            if isinstance(active_config.regime_constraints, dict)
            else {}
        )
        return {
            "allowed_asset_classes": regime_constraints.get("allowed_asset_classes", []),
            "config_id": active_config.config_id,
        }
