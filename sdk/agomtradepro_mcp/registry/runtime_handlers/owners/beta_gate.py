"""beta_gate runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _fallback_list_beta_gate_configs() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    configs = client.beta_gate.list_configs()
    return {
        "configs": configs,
        "total_count": len(configs),
    }


def _fallback_compare_beta_gate_configs(
    version1: str,
    version2: str,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    normalized_version1 = str(version1).strip()
    normalized_version2 = str(version2).strip()
    if not normalized_version1 or not normalized_version2:
        raise ValueError("version1 and version2 are required")
    if len(normalized_version1) > 64 or len(normalized_version2) > 64:
        raise ValueError("version identifiers must be at most 64 characters")

    client = AgomTradeProClient()
    result = client.beta_gate.version_compare(
        {
            "version1": normalized_version1,
            "version2": normalized_version2,
        }
    )
    if not isinstance(result, dict):
        raise ValueError("Beta Gate config comparison returned an invalid response")
    config1 = result.get("config1")
    config2 = result.get("config2")
    differences = result.get("differences")
    if not isinstance(config1, dict) or not isinstance(config2, dict):
        raise ValueError("Beta Gate config comparison is missing config details")
    if not isinstance(differences, list):
        raise ValueError("Beta Gate config comparison returned invalid differences")
    return {
        "config1": config1,
        "config2": config2,
        "differences": differences,
    }


def _fallback_beta_gate_compute_batch_evaluation(
    asset_codes: list[str],
    asset_class: str,
    current_regime: str,
    regime_confidence: float,
    policy_level: int,
    risk_profile: str = "balanced",
) -> dict[str, Any]:
    import math

    from agomtradepro import AgomTradeProClient

    if not isinstance(asset_codes, list) or not asset_codes:
        raise ValueError("asset_codes must contain at least one asset code")
    if len(asset_codes) > 100:
        raise ValueError("asset_codes must contain at most 100 items")
    normalized_codes = [str(code).strip() for code in asset_codes]
    if any(not code or len(code) > 32 for code in normalized_codes):
        raise ValueError("asset_codes entries must be 1 to 32 characters")
    if len(normalized_codes) != len(set(normalized_codes)):
        raise ValueError("asset_codes must not contain duplicates")

    normalized_asset_class = str(asset_class).strip()
    if not normalized_asset_class or len(normalized_asset_class) > 64:
        raise ValueError("asset_class must be 1 to 64 characters")

    normalized_regime = str(current_regime).strip()
    if normalized_regime not in {
        "Recovery",
        "Overheat",
        "Deflation",
        "Stagflation",
    }:
        raise ValueError("current_regime is not supported")

    normalized_confidence = float(regime_confidence)
    if not math.isfinite(normalized_confidence) or not 0.0 <= normalized_confidence <= 1.0:
        raise ValueError("regime_confidence must be a finite number between 0 and 1")

    normalized_policy_level = int(policy_level)
    if not 0 <= normalized_policy_level <= 3:
        raise ValueError("policy_level must be between 0 and 3")

    normalized_profile = str(risk_profile).strip().lower()
    if normalized_profile not in {"conservative", "balanced", "aggressive"}:
        raise ValueError("risk_profile must be conservative, balanced, or aggressive")

    payload = {
        "asset_codes": normalized_codes,
        "asset_class": normalized_asset_class,
        "current_regime": normalized_regime,
        "regime_confidence": normalized_confidence,
        "policy_level": normalized_policy_level,
        "risk_profile": normalized_profile,
    }
    client = AgomTradeProClient()
    result = client.beta_gate.test_gate(payload)
    if not isinstance(result, dict):
        raise ValueError("Beta Gate batch evaluation returned an invalid response")
    config = result.get("config")
    query = result.get("query")
    results = result.get("results")
    summary = result.get("summary")
    if not isinstance(config, dict) or not isinstance(query, dict):
        raise ValueError("Beta Gate batch evaluation is missing config or query metadata")
    if not isinstance(results, list) or not isinstance(summary, dict):
        raise ValueError("Beta Gate batch evaluation returned invalid results or summary")
    return {
        "config": config,
        "query": query,
        "results": results,
        "summary": summary,
    }


def _internal_handler_beta_gate_create_config(
    risk_profile: str,
    config_id: str | None = None,
    allowed_regimes: list[str] | None = None,
    min_confidence: float = 0.3,
    max_policy_level: int = 2,
    veto_on_p3: bool = True,
    max_total_position: float = 95.0,
    max_single_position: float = 20.0,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    import math

    from agomtradepro import AgomTradeProClient

    normalized_profile = str(risk_profile).strip().lower()
    if normalized_profile not in {"conservative", "balanced", "aggressive"}:
        raise ValueError("risk_profile must be conservative, balanced, or aggressive")

    normalized_config_id = str(config_id).strip() if config_id is not None else ""
    if config_id is not None and not normalized_config_id:
        raise ValueError("config_id must not be blank")
    if len(normalized_config_id) > 64:
        raise ValueError("config_id must be at most 64 characters")

    allowed_values = {"Recovery", "Overheat", "Deflation", "Stagflation"}
    normalized_regimes = (
        list(allowed_regimes)
        if allowed_regimes is not None
        else ["Recovery", "Overheat", "Deflation", "Stagflation"]
    )
    if not normalized_regimes:
        raise ValueError("allowed_regimes must contain at least one regime")
    invalid_regimes = sorted(set(normalized_regimes) - allowed_values)
    if invalid_regimes:
        raise ValueError(f"unsupported allowed_regimes: {', '.join(invalid_regimes)}")

    normalized_confidence = float(min_confidence)
    normalized_policy_level = int(max_policy_level)
    normalized_total_position = float(max_total_position)
    normalized_single_position = float(max_single_position)
    numeric_values = (
        normalized_confidence,
        normalized_total_position,
        normalized_single_position,
    )
    if not all(math.isfinite(value) for value in numeric_values):
        raise ValueError("numeric config values must be finite")
    if not 0.0 <= normalized_confidence <= 1.0:
        raise ValueError("min_confidence must be between 0 and 1")
    if not 0 <= normalized_policy_level <= 3:
        raise ValueError("max_policy_level must be between 0 and 3")
    if not 0.0 <= normalized_total_position <= 100.0:
        raise ValueError("max_total_position must be between 0 and 100")
    if not 0.0 <= normalized_single_position <= 100.0:
        raise ValueError("max_single_position must be between 0 and 100")
    if normalized_single_position > normalized_total_position:
        raise ValueError("max_single_position must not exceed max_total_position")

    payload = {
        "risk_profile": normalized_profile,
        "allowed_regimes": normalized_regimes,
        "min_confidence": normalized_confidence,
        "max_policy_level": normalized_policy_level,
        "veto_on_p3": bool(veto_on_p3),
        "max_total_position": normalized_total_position,
        "max_single_position": normalized_single_position,
    }
    if normalized_config_id:
        payload["config_id"] = normalized_config_id

    client = AgomTradeProClient()
    if preview_only:
        configs = client.beta_gate.list_configs(active_only=False)
        duplicate = next(
            (
                item
                for item in configs
                if normalized_config_id and str(item.get("config_id") or "") == normalized_config_id
            ),
            None,
        )
        if duplicate is not None:
            raise ValueError(f"config_id already exists: {normalized_config_id}")
        active_for_profile = next(
            (
                item
                for item in configs
                if bool(item.get("is_active"))
                and str(item.get("risk_profile") or "").strip().lower() == normalized_profile
            ),
            None,
        )
        latest_version = max(
            (
                int(item.get("version", 0))
                for item in configs
                if str(item.get("version", "")).isdigit()
            ),
            default=0,
        )
        return {
            "success": True,
            "preview_only": True,
            "summary": {
                "config_id": normalized_config_id or None,
                "config_id_source": "caller" if normalized_config_id else "server_generated",
                "risk_profile": normalized_profile,
                "expected_version": latest_version + 1,
                "replaced_active_config": active_for_profile,
                "will_create_config": True,
                "will_activate_new_config": True,
                "will_deactivate_same_profile_active_config": (active_for_profile is not None),
                "will_change_existing_decisions": False,
                "will_execute_trade": False,
                "target_constraints": {
                    "allowed_regimes": normalized_regimes,
                    "min_confidence": normalized_confidence,
                    "max_policy_level": normalized_policy_level,
                    "veto_on_p3": bool(veto_on_p3),
                    "max_total_position": normalized_total_position,
                    "max_single_position": normalized_single_position,
                },
            },
            "message": (
                "Preview generated. Confirm to create and activate the Beta Gate config. "
                "The currently active config for the same risk profile will be deactivated."
            ),
        }

    result = client.beta_gate.create_config(payload)
    if not isinstance(result, dict):
        raise ValueError("Beta Gate create returned an invalid response")
    return result


def _internal_handler_beta_gate_rollback_config(
    config_id: str,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    normalized_config_id = str(config_id).strip()
    if not normalized_config_id:
        raise ValueError("config_id is required")
    if len(normalized_config_id) > 64:
        raise ValueError("config_id must be at most 64 characters")

    client = AgomTradeProClient()
    if preview_only:
        target_response = client.beta_gate.get_config(normalized_config_id)
        if not isinstance(target_response, dict):
            raise ValueError("Beta Gate config detail returned an invalid response")
        target = target_response.get("result", target_response)
        if not isinstance(target, dict) or not target.get("config_id"):
            raise ValueError("Beta Gate config detail is missing the target config")
        if bool(target.get("is_active")):
            raise ValueError(f"config {normalized_config_id} is already active")
        if bool(target.get("is_expired")):
            raise ValueError(f"config {normalized_config_id} is expired")

        risk_profile = str(target.get("risk_profile") or "").strip().lower()
        if risk_profile not in {"conservative", "balanced", "aggressive"}:
            raise ValueError("target config has an invalid risk_profile")
        active_configs = client.beta_gate.list_configs()
        current_active = next(
            (
                item
                for item in active_configs
                if str(item.get("risk_profile") or "").strip().lower() == risk_profile
                and bool(item.get("is_active"))
            ),
            None,
        )
        return {
            "success": True,
            "preview_only": True,
            "target_config": target,
            "current_active_config": current_active,
            "summary": {
                "target_config_id": normalized_config_id,
                "target_version": target.get("version"),
                "risk_profile": risk_profile,
                "current_active_config_id": (
                    current_active.get("config_id") if current_active else None
                ),
                "current_active_version": (
                    current_active.get("version") if current_active else None
                ),
                "will_deactivate_current": current_active is not None,
                "will_activate_target": True,
                "will_create_new_version": False,
                "will_update_effective_date": True,
                "will_change_existing_decisions": False,
                "will_execute_trade": False,
            },
            "message": (
                "Preview generated. Confirm to activate the selected persisted Beta Gate "
                "config and deactivate the current config for the same risk profile."
            ),
        }

    result = client.beta_gate.rollback_config(normalized_config_id)
    if not isinstance(result, dict):
        raise ValueError("Beta Gate rollback returned an invalid response")
    return result


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "list_beta_gate_configs": _fallback_list_beta_gate_configs,
    "compare_beta_gate_configs": _fallback_compare_beta_gate_configs,
    "beta_gate_compute_batch_evaluation": _fallback_beta_gate_compute_batch_evaluation,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {
    "beta_gate_create_config": _internal_handler_beta_gate_create_config,
    "beta_gate_rollback_config": _internal_handler_beta_gate_rollback_config,
}
