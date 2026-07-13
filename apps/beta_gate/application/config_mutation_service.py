"""Version-preserving Beta Gate config mutations."""

from __future__ import annotations

from typing import Any

from apps.beta_gate.application.repository_provider import get_beta_gate_config_repository
from apps.beta_gate.domain.entities import RiskProfile, create_gate_config


def replace_gate_config(config_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    """Create a new config version from an existing config and deactivate the old one."""

    repository = get_beta_gate_config_repository()
    current_model = repository.get_by_id(config_id)
    if current_model is None:
        return None
    current = current_model.to_domain()

    regime = {**current.regime_constraint.to_dict(), **updates.get("regime_constraints", {})}
    policy = {**current.policy_constraint.to_dict(), **updates.get("policy_constraints", {})}
    portfolio = {
        **current.portfolio_constraint.to_dict(),
        **updates.get("portfolio_constraints", {}),
    }
    risk_profile = RiskProfile(updates.get("risk_profile", current.risk_profile.value))
    replacement = create_gate_config(
        risk_profile=risk_profile,
        allowed_regimes=regime["allowed_regimes"],
        min_confidence=regime["min_confidence"],
        max_policy_level=policy["max_allowed_level"],
        veto_on_p3=policy["veto_on_p3"],
        max_total_position=portfolio["max_total_position_pct"],
        max_single_position=portfolio["max_single_position_pct"],
    )
    saved = repository.save(replacement)
    repository.deactivate_by_config_id(config_id)
    return {
        "config_id": saved.config_id,
        "replaces_config_id": config_id,
        "risk_profile": saved.risk_profile.lower(),
        "version": saved.version,
        "is_active": saved.is_active,
        "regime_constraints": saved.regime_constraints,
        "policy_constraints": saved.policy_constraints,
        "portfolio_constraints": saved.portfolio_constraints,
        "effective_date": saved.effective_date.isoformat() if saved.effective_date else None,
        "expires_at": saved.expires_at.isoformat() if saved.expires_at else None,
    }


def deactivate_gate_config(config_id: str) -> bool:
    """Deactivate one config without deleting its governance history."""

    return get_beta_gate_config_repository().deactivate_by_config_id(config_id) is not None
