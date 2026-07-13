"""equity runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agomtradepro_mcp.registry.runtime_handlers.common import _call_registered_tool


def _fallback_equity_read_pool_catalog(
    sector: str | None = None,
    min_score: float | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.equity.get_stock_pool(
        sector=sector,
        min_score=min_score,
        limit=limit,
    )


def _fallback_equity_read_valuation_analysis(
    stock_code: str,
    lookback_days: int = 252,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.equity.get_valuation(
        stock_code,
        lookback_days=lookback_days,
    )


def _fallback_equity_read_valuation_repair_list(
    universe: str = "all_active",
    phase: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    result = client.equity.list_valuation_repairs(
        universe=universe,
        phase=phase,
        limit=limit,
    )
    repairs = result.get("results", [])
    return {
        "universe": universe,
        "repairs": repairs,
        "total_count": len(repairs),
        "query": {
            "phase": phase,
            "limit": limit,
        },
    }


def _fallback_equity_read_valuation_freshness() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.equity.get_valuation_data_freshness()


def _fallback_equity_read_valuation_quality_latest() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.equity.get_valuation_data_quality_latest()


def _fallback_equity_compute_valuation_repair_status(
    stock_code: str,
    lookback_days: int = 756,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    result = client.equity.get_valuation_repair_status(
        stock_code=stock_code,
        lookback_days=lookback_days,
    )
    if not isinstance(result, dict):
        raise ValueError("equity.compute.valuation_repair_status returned an invalid payload")
    return dict(result)


def _fallback_equity_compute_valuation_repair_history(
    stock_code: str,
    lookback_days: int = 252,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    result = client.equity.get_valuation_repair_history_payload(
        stock_code=stock_code,
        lookback_days=lookback_days,
    )
    if not isinstance(result, dict) or not isinstance(result.get("points"), list):
        raise ValueError("equity.compute.valuation_repair_history returned an invalid payload")
    return dict(result)


def _fallback_equity_read_valuation_repair_config() -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    result = client.equity.get_valuation_repair_config()
    if not isinstance(result, dict):
        raise ValueError("equity.read.valuation_repair_config returned an invalid payload")
    return {"config": dict(result)}


def _fallback_equity_read_valuation_repair_config_catalog(
    limit: int = 20,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    raw_configs = client.equity.list_valuation_repair_configs(limit=limit)
    if not isinstance(raw_configs, list):
        raise ValueError("equity.read.valuation_repair_config_catalog returned an invalid payload")
    configs = [dict(item) for item in raw_configs if isinstance(item, dict)]
    return {"configs": configs, "total_count": len(configs)}


def _fallback_equity_read_financial_history(
    stock_code: str,
    report_type: str = "annual",
    limit: int = 5,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    financials = client.equity.get_financials(
        stock_code,
        report_type=report_type,
        limit=limit,
    )
    if not isinstance(financials, list):
        raise ValueError("equity.read.financial_history returned an invalid payload")
    return {
        "stock_code": stock_code,
        "report_type": report_type,
        "financials": financials,
        "total_count": len(financials),
    }


def _internal_handler_equity_create_valuation_repair_config(
    change_reason: str,
    min_history_points: int = 120,
    default_lookback_days: int = 756,
    confirm_window: int = 20,
    min_rebound: float = 0.05,
    stall_window: int = 40,
    stall_min_progress: float = 0.02,
    target_percentile: float = 0.50,
    undervalued_threshold: float = 0.20,
    near_target_threshold: float = 0.45,
    overvalued_threshold: float = 0.80,
    pe_weight: float = 0.6,
    pb_weight: float = 0.4,
    confidence_base: float = 0.4,
    confidence_sample_threshold: int = 252,
    confidence_sample_bonus: float = 0.2,
    confidence_blend_bonus: float = 0.15,
    confidence_repair_start_bonus: float = 0.15,
    confidence_not_stalled_bonus: float = 0.1,
    repairing_threshold: float = 0.10,
    eta_max_days: int = 999,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    normalized_change_reason = str(change_reason or "").strip()
    if not normalized_change_reason:
        raise ValueError("change_reason must be a non-empty string")

    config_payload = {
        "min_history_points": min_history_points,
        "default_lookback_days": default_lookback_days,
        "confirm_window": confirm_window,
        "min_rebound": min_rebound,
        "stall_window": stall_window,
        "stall_min_progress": stall_min_progress,
        "target_percentile": target_percentile,
        "undervalued_threshold": undervalued_threshold,
        "near_target_threshold": near_target_threshold,
        "overvalued_threshold": overvalued_threshold,
        "pe_weight": pe_weight,
        "pb_weight": pb_weight,
        "confidence_base": confidence_base,
        "confidence_sample_threshold": confidence_sample_threshold,
        "confidence_sample_bonus": confidence_sample_bonus,
        "confidence_blend_bonus": confidence_blend_bonus,
        "confidence_repair_start_bonus": confidence_repair_start_bonus,
        "confidence_not_stalled_bonus": confidence_not_stalled_bonus,
        "repairing_threshold": repairing_threshold,
        "eta_max_days": eta_max_days,
    }

    if abs(pe_weight + pb_weight - 1.0) > 0.01:
        raise ValueError(f"pe_weight + pb_weight must equal 1.0, got {pe_weight + pb_weight}")

    for field_name in (
        "target_percentile",
        "undervalued_threshold",
        "near_target_threshold",
        "overvalued_threshold",
        "min_rebound",
        "stall_min_progress",
    ):
        value = config_payload[field_name]
        if not 0 <= value <= 1:
            raise ValueError(f"{field_name} must be between 0 and 1")

    if not (
        undervalued_threshold < near_target_threshold < target_percentile < overvalued_threshold
    ):
        raise ValueError(
            "thresholds must satisfy undervalued_threshold < near_target_threshold "
            "< target_percentile < overvalued_threshold"
        )

    client = AgomTradeProClient()
    if preview_only:
        configs = client.equity.list_valuation_repair_configs(limit=100)
        active_config = client.equity.get_valuation_repair_config()
        if not isinstance(active_config, dict):
            raise ValueError("active valuation repair config response must be an object")

        persisted_versions = []
        for item in configs:
            try:
                persisted_versions.append(int(item.get("version")))
            except (TypeError, ValueError):
                continue
        latest_persisted_version = max(persisted_versions, default=0)
        expected_next_version = latest_persisted_version + 1
        field_changes = {
            field_name: {
                "current": active_config.get(field_name),
                "requested": requested_value,
            }
            for field_name, requested_value in config_payload.items()
            if active_config.get(field_name) != requested_value
        }

        return {
            "success": True,
            "preview_only": True,
            "active_config": {
                "id": active_config.get("id"),
                "version": active_config.get("version"),
                "is_active": active_config.get("is_active"),
            },
            "latest_persisted_version": latest_persisted_version,
            "expected_next_version": expected_next_version,
            "requested_config": {
                **config_payload,
                "change_reason": normalized_change_reason,
            },
            "field_changes": field_changes,
            "summary": {
                "current_active_version": active_config.get("version"),
                "latest_persisted_version": latest_persisted_version,
                "expected_next_version": expected_next_version,
                "changed_field_count": len(field_changes),
                "is_active_after_create": False,
            },
            "message": (
                "Preview generated. Confirm to create the next valuation-repair config "
                "version as an inactive draft."
            ),
        }

    return client.equity.create_valuation_repair_config(
        change_reason=normalized_change_reason,
        **config_payload,
    )


def _internal_handler_equity_activate_valuation_repair_config(
    config_id: int,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    if isinstance(config_id, bool) or not isinstance(config_id, int) or config_id <= 0:
        raise ValueError("config_id must be a positive integer")

    client = AgomTradeProClient()
    if preview_only:
        target_config = client.equity.get_valuation_repair_config_by_id(config_id)
        active_config = client.equity.get_valuation_repair_config()
        if not isinstance(active_config, dict):
            raise ValueError("active valuation repair config response must be an object")
        if target_config.get("is_active") or target_config.get("id") == active_config.get("id"):
            raise ValueError(f"valuation repair config {config_id} is already active")

        return {
            "success": True,
            "preview_only": True,
            "target_config": {
                "id": target_config.get("id"),
                "version": target_config.get("version"),
                "is_active": target_config.get("is_active"),
                "change_reason": target_config.get("change_reason"),
                "created_by": target_config.get("created_by"),
            },
            "current_active_config": {
                "id": active_config.get("id"),
                "version": active_config.get("version"),
                "is_active": active_config.get("is_active"),
            },
            "summary": {
                "target_config_id": target_config.get("id"),
                "target_version": target_config.get("version"),
                "current_active_config_id": active_config.get("id"),
                "current_active_version": active_config.get("version"),
                "will_deactivate_current": active_config.get("id") is not None,
                "will_activate_target": True,
                "will_update_effective_from": True,
                "will_clear_runtime_cache": True,
            },
            "message": (
                "Preview generated. Confirm to deactivate the current config, activate the "
                "selected valuation-repair config, update its effective time and clear the "
                "runtime config cache."
            ),
        }

    return client.equity.activate_valuation_repair_config(config_id)


def _fallback_equity_read_score(
    stock_code: str,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    from datetime import date

    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    parsed_date = date.fromisoformat(as_of_date) if as_of_date else None
    return client.equity.get_stock_score(stock_code, parsed_date)


def _fallback_equity_compute_recommendations(
    regime: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    recommendations = client.equity.get_recommendations(regime=regime, limit=limit)
    return {
        "recommendations": recommendations,
        "total_count": len(recommendations),
    }


def _fallback_equity_compute_analysis(
    stock_code: str,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    from datetime import date

    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    parsed_date = date.fromisoformat(as_of_date) if as_of_date else None
    return client.equity.analyze_stock(stock_code, parsed_date)


def _internal_handler_equity_run_valuation_repair_scan(
    universe: str = "all_active",
    lookback_days: int = 756,
    limit: int | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    arguments = {"universe": universe, "lookback_days": lookback_days, "limit": limit}
    if preview_only:
        return {
            "success": True,
            "preview_only": True,
            "scan_target": arguments,
            "will_persist_repair_snapshots": True,
        }
    return _call_registered_tool("scan_valuation_repairs", arguments)


def _internal_handler_equity_sync_valuation_data(
    days_back: int = 1,
    stock_codes: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    primary_source: str = "akshare",
    fallback_source: str = "tushare",
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    arguments = {
        "days_back": days_back,
        "stock_codes": None if stock_codes is None else list(stock_codes),
        "start_date": start_date,
        "end_date": end_date,
        "primary_source": primary_source,
        "fallback_source": fallback_source,
    }
    if preview_only:
        return {
            "success": True,
            "preview_only": True,
            "sync_target": arguments,
            "stock_count": len(arguments["stock_codes"] or []),
        }
    return _call_registered_tool("sync_valuation_data", arguments)


def _internal_handler_equity_create_valuation_quality_snapshot(
    as_of_date: str | None = None,
    primary_source: str = "akshare",
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    arguments = {"as_of_date": as_of_date, "primary_source": primary_source}
    if preview_only:
        return {
            "success": True,
            "preview_only": True,
            "snapshot_target": arguments,
            "will_persist_quality_gate": True,
        }
    return _call_registered_tool("validate_valuation_data", arguments)


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "equity_read_pool_catalog": _fallback_equity_read_pool_catalog,
    "equity_read_valuation_analysis": _fallback_equity_read_valuation_analysis,
    "equity_read_valuation_repair_list": _fallback_equity_read_valuation_repair_list,
    "equity_read_valuation_freshness": _fallback_equity_read_valuation_freshness,
    "equity_read_valuation_quality_latest": _fallback_equity_read_valuation_quality_latest,
    "equity_compute_valuation_repair_status": _fallback_equity_compute_valuation_repair_status,
    "equity_compute_valuation_repair_history": _fallback_equity_compute_valuation_repair_history,
    "equity_read_valuation_repair_config": _fallback_equity_read_valuation_repair_config,
    "equity_read_valuation_repair_config_catalog": _fallback_equity_read_valuation_repair_config_catalog,
    "equity_read_financial_history": _fallback_equity_read_financial_history,
    "equity_read_score": _fallback_equity_read_score,
    "equity_compute_recommendations": _fallback_equity_compute_recommendations,
    "equity_compute_analysis": _fallback_equity_compute_analysis,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {
    "equity_create_valuation_repair_config": _internal_handler_equity_create_valuation_repair_config,
    "equity_activate_valuation_repair_config": _internal_handler_equity_activate_valuation_repair_config,
    "equity_run_valuation_repair_scan": _internal_handler_equity_run_valuation_repair_scan,
    "equity_sync_valuation_data": _internal_handler_equity_sync_valuation_data,
    "equity_create_valuation_quality_snapshot": _internal_handler_equity_create_valuation_quality_snapshot,
}
