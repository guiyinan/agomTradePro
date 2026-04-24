"""Application services for Beta Gate config/query orchestration."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from .repository_provider import (
    get_beta_gate_config_repository,
    get_beta_gate_decision_repository,
)


class BetaGateConfigQueryService:
    """Coordinate Beta Gate config reads and lifecycle operations."""

    def __init__(
        self,
        *,
        config_repository: Any | None = None,
        decision_repository: Any | None = None,
    ) -> None:
        self.config_repository = config_repository or get_beta_gate_config_repository()
        self.decision_repository = decision_repository or get_beta_gate_decision_repository()

    def save_form_data(self, form_data: Any) -> Any:
        """Persist validated form data through the repository."""

        return self.config_repository.save_form_data(form_data)

    def activate_config(self, config_id: str) -> Any | None:
        """Activate one config by config id."""

        return self.config_repository.activate_by_config_id(config_id)

    def rollback_to_version(self, version: int) -> Any | None:
        """Activate the config for a historical version."""

        return self.config_repository.activate_by_version(version)

    def resolve_version_for_config_id(self, config_id: str) -> int | None:
        """Resolve a config id to its numeric version."""

        return self.config_repository.resolve_version_by_config_id(config_id)

    def get_config_for_edit(self, config_id: str) -> Any | None:
        """Return a config object suitable for form initialisation."""

        return self.config_repository.get_by_id(config_id)

    def get_active_config(self) -> Any | None:
        """Return the first active config model for template use."""

        return self.config_repository.get_active_model()

    def get_recent_decisions(self, limit: int = 10) -> list[Any]:
        """Return the latest decision models for template use."""

        return self.decision_repository.get_latest(limit)

    def list_recent_versions(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return recent config versions formatted for the API."""

        return [
            self._config_version_dict(config)
            for config in self.config_repository.list_latest(limit)
        ]

    def compare_versions(
        self,
        version1_id: str,
        version2_id: str,
    ) -> dict[str, Any] | None:
        """Compare two configs addressed by id or version."""

        config1 = self.config_repository.find_by_config_id_or_version(version1_id)
        config2 = self.config_repository.find_by_config_id_or_version(version2_id)
        if not config1 or not config2:
            return None

        config1_dict = self._config_compare_dict(config1)
        config2_dict = self._config_compare_dict(config2)
        return {
            "config1": config1_dict,
            "config2": config2_dict,
            "differences": self._compare_config_dicts(config1_dict, config2_dict),
        }

    def get_version_page_context(self) -> dict[str, Any]:
        """Build template context for config version history."""

        all_configs = self.config_repository.list_latest(None)
        configs_by_profile: dict[str, list[Any]] = {}
        for config in all_configs:
            profile = config.risk_profile
            configs_by_profile.setdefault(profile, []).append(config)
        return {
            "versions": all_configs,
            "all_configs": all_configs,
            "configs_by_profile": configs_by_profile,
            "page_title": "配置版本对比",
            "page_description": "查看和对比 Beta Gate 配置历史版本",
        }

    def get_config_page_context(self) -> dict[str, Any]:
        """Build template context for the Beta Gate config page."""

        active_config = self.get_active_config()
        recent_decisions = self.get_recent_decisions(limit=10)
        context_data = {
            "active_config": None,
            "recent_decisions": recent_decisions,
            "page_title": "Beta 闸门配置",
            "page_description": "基于 Regime 和 Policy 的资产可见性过滤",
        }
        if active_config:
            context_data["active_config"] = self._template_config(active_config)
        return context_data

    def _config_version_dict(self, config: Any) -> dict[str, Any]:
        return {
            "config_id": config.config_id,
            "version": config.version,
            "risk_profile": config.risk_profile,
            "is_active": config.is_active,
            "effective_date": config.effective_date.isoformat()
            if config.effective_date
            else None,
            "expires_at": config.expires_at.isoformat() if config.expires_at else None,
            "created_at": config.created_at.isoformat() if config.created_at else None,
        }

    def _config_compare_dict(self, config: Any) -> dict[str, Any]:
        return {
            "config_id": config.config_id,
            "version": config.version,
            "risk_profile": config.risk_profile,
            "is_active": config.is_active,
            "effective_date": config.effective_date.isoformat()
            if config.effective_date
            else None,
            "expires_at": config.expires_at.isoformat() if config.expires_at else None,
            "regime_constraints": self._parse_constraints(config.regime_constraints),
            "policy_constraints": self._parse_constraints(config.policy_constraints),
            "portfolio_constraints": self._parse_constraints(config.portfolio_constraints),
        }

    def _template_config(self, config: Any) -> SimpleNamespace:
        regime_constraints = self._parse_constraints(config.regime_constraints)
        policy_constraints = self._parse_constraints(config.policy_constraints)
        portfolio_constraints = self._parse_constraints(config.portfolio_constraints)
        return SimpleNamespace(
            config_id=config.config_id,
            risk_profile=config.risk_profile,
            version=config.version,
            is_active=config.is_active,
            effective_date=config.effective_date,
            expires_at=config.expires_at,
            regime_constraint=SimpleNamespace(
                current_regime=regime_constraints.get("current_regime", "未知"),
                confidence=regime_constraints.get("confidence", 0.5),
                allowed_asset_classes=regime_constraints.get("allowed_asset_classes", []),
            ),
            policy_constraint=SimpleNamespace(
                current_level=policy_constraints.get("current_level", 0),
                max_risk_exposure=policy_constraints.get("max_risk_exposure", 100),
                hard_exclusions=policy_constraints.get("hard_exclusions", []),
            ),
            portfolio_constraint=SimpleNamespace(
                max_positions=portfolio_constraints.get("max_positions", 10),
                max_single_position_weight=portfolio_constraints.get(
                    "max_single_position_weight",
                    20,
                ),
                max_concentration_ratio=portfolio_constraints.get(
                    "max_concentration_ratio",
                    60,
                ),
            ),
        )

    def _parse_constraints(self, constraints: Any) -> dict[str, Any]:
        if isinstance(constraints, dict):
            return constraints
        if isinstance(constraints, str):
            try:
                parsed = json.loads(constraints)
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}

    def _compare_config_dicts(
        self,
        config1: dict[str, Any],
        config2: dict[str, Any],
    ) -> list[dict[str, Any]]:
        fields = [
            "risk_profile",
            "is_active",
            "effective_date",
            "expires_at",
            "regime_constraints",
            "policy_constraints",
            "portfolio_constraints",
        ]
        return [
            {"field": field, "config1": config1.get(field), "config2": config2.get(field)}
            for field in fields
            if config1.get(field) != config2.get(field)
        ]


def get_beta_gate_config_query_service() -> BetaGateConfigQueryService:
    """Return the default Beta Gate config query service."""

    return BetaGateConfigQueryService()
