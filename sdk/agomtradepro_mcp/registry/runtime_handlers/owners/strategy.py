"""strategy runtime capability handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agomtradepro_mcp.registry.runtime_handlers.common import _call_registered_tool


def _fallback_strategy_read_catalog(
    strategy_type: str | None = None,
    is_active: bool | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    raw_strategies = client.strategy.list_strategies(
        strategy_type=strategy_type,
        is_active=is_active,
        limit=limit,
    )
    if not isinstance(raw_strategies, list):
        raise ValueError("strategy.read.catalog returned an invalid payload")
    strategies = [dict(item) for item in raw_strategies if isinstance(item, dict)]
    return {
        "strategies": strategies,
        "total_count": len(strategies),
    }


def _fallback_strategy_read_detail(strategy_id: int) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    strategy = client.strategy.get_strategy(strategy_id)
    if not isinstance(strategy, dict):
        raise ValueError("strategy.read.detail returned an invalid payload")
    return {"strategy": dict(strategy)}


def _fallback_strategy_read_ai_config_catalog(
    strategy_id: int | None = None,
    approval_mode: str | None = None,
    ai_provider_id: int | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    raw_configs = client.strategy.list_ai_strategy_configs(
        strategy_id=strategy_id,
        approval_mode=approval_mode,
        ai_provider_id=ai_provider_id,
        limit=limit,
    )
    if not isinstance(raw_configs, list):
        raise ValueError("strategy.read.ai_config_catalog returned an invalid payload")
    configs = [dict(item) for item in raw_configs if isinstance(item, dict)]
    return {"configs": configs, "total_count": len(configs)}


def _fallback_strategy_read_ai_config_detail(strategy_id: int) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    result = client.strategy.get_strategy_ai_config(strategy_id)
    if not isinstance(result, dict):
        raise ValueError("strategy.read.ai_config_detail returned an invalid payload")
    exists = result.get("exists") is not False
    return {
        "strategy_id": strategy_id,
        "exists": exists,
        "config": dict(result) if exists else None,
    }


def _fallback_strategy_read_position_rule_catalog(
    strategy_id: int | None = None,
    is_active: bool | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    raw_rules = client.strategy.list_position_rules(
        strategy_id=strategy_id,
        is_active=is_active,
        limit=limit,
    )
    if not isinstance(raw_rules, list):
        raise ValueError("strategy.read.position_rule_catalog returned an invalid payload")
    rules = [dict(item) for item in raw_rules if isinstance(item, dict)]
    return {"rules": rules, "total_count": len(rules)}


def _fallback_strategy_read_position_rule_detail(
    strategy_id: int,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    rule = client.strategy.get_strategy_position_rule(strategy_id)
    if not isinstance(rule, dict):
        raise ValueError("strategy.read.position_rule_detail returned an invalid payload")
    return {"strategy_id": strategy_id, "rule": dict(rule)}


def _fallback_strategy_compute_position_rule(
    rule_id: int,
    context: dict[str, Any],
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    result = client.strategy.evaluate_position_rule(rule_id=rule_id, context=context)
    if not isinstance(result, dict):
        raise ValueError("strategy.compute.position_rule returned an invalid payload")
    return dict(result)


def _fallback_strategy_compute_position_management(
    strategy_id: int,
    context: dict[str, Any],
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    result = client.strategy.evaluate_strategy_position_management(
        strategy_id=strategy_id,
        context=context,
    )
    if not isinstance(result, dict):
        raise ValueError("strategy.compute.position_management returned an invalid payload")
    return dict(result)


def _fallback_strategy_read_performance(
    strategy_id: int,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    from datetime import date

    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    result = client.strategy.get_strategy_performance(
        strategy_id,
        start_date=date.fromisoformat(start_date) if start_date else None,
        end_date=date.fromisoformat(end_date) if end_date else None,
    )
    if not isinstance(result, dict):
        raise ValueError("strategy.read.performance returned an invalid payload")
    return result


def _fallback_strategy_read_signals(
    strategy_id: int,
    status: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    signals = client.strategy.get_strategy_signals(strategy_id, status=status, limit=limit)
    if not isinstance(signals, list):
        raise ValueError("strategy.read.signals returned an invalid payload")
    return {"signals": signals, "total_count": len(signals)}


def _fallback_strategy_read_positions(strategy_id: int) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    positions = client.strategy.get_strategy_positions(strategy_id)
    if not isinstance(positions, list):
        raise ValueError("strategy.read.positions returned an invalid payload")
    return {"positions": positions, "total_count": len(positions)}


def _fallback_execute_strategy(
    strategy_id: int,
    as_of_date: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from datetime import date

    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    parsed_date = date.fromisoformat(as_of_date) if as_of_date else None
    return client.strategy.execute_strategy(strategy_id, parsed_date)


def _fallback_bind_portfolio_strategy(
    portfolio_id: int,
    strategy_id: int,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.strategy.bind_portfolio_strategy(
        portfolio_id=portfolio_id,
        strategy_id=strategy_id,
    )


def _fallback_unbind_portfolio_strategy(
    portfolio_id: int,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.strategy.unbind_portfolio_strategy(portfolio_id=portfolio_id)


def _fallback_create_position_rule(
    strategy_id: int,
    name: str,
    buy_price_expr: str,
    sell_price_expr: str,
    stop_loss_expr: str,
    take_profit_expr: str,
    position_size_expr: str,
    buy_condition_expr: str = "",
    sell_condition_expr: str = "",
    description: str = "",
    price_precision: int = 2,
    variables_schema: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
    is_active: bool = True,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.strategy.create_position_rule(
        strategy_id=strategy_id,
        name=name,
        buy_price_expr=buy_price_expr,
        sell_price_expr=sell_price_expr,
        stop_loss_expr=stop_loss_expr,
        take_profit_expr=take_profit_expr,
        position_size_expr=position_size_expr,
        buy_condition_expr=buy_condition_expr,
        sell_condition_expr=sell_condition_expr,
        description=description,
        price_precision=price_precision,
        variables_schema=variables_schema,
        metadata=metadata,
        is_active=is_active,
    )


def _fallback_update_position_rule(
    rule_id: int,
    updates: dict[str, Any],
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.strategy.update_position_rule(rule_id=rule_id, **updates)


def _fallback_create_strategy(
    name: str,
    strategy_type: str,
    description: str,
    params: dict[str, Any],
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.strategy.create_strategy(name, strategy_type, description, params)


def _fallback_create_ai_strategy_config(
    strategy_id: int,
    prompt_template_id: int | None = None,
    chain_config_id: int | None = None,
    ai_provider_id: int | None = None,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    approval_mode: str = "conditional",
    confidence_threshold: float = 0.8,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.strategy.create_ai_strategy_config(
        strategy_id=strategy_id,
        prompt_template_id=prompt_template_id,
        chain_config_id=chain_config_id,
        ai_provider_id=ai_provider_id,
        temperature=temperature,
        max_tokens=max_tokens,
        approval_mode=approval_mode,
        confidence_threshold=confidence_threshold,
    )


def _fallback_update_ai_strategy_config(
    config_id: int,
    updates: dict[str, Any],
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    return client.strategy.update_ai_strategy_config(config_id=config_id, **updates)


def _internal_handler_strategy_execute_run(
    strategy_id: int,
    as_of_date: str | None = None,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()

    if preview_only:
        strategy = client.strategy.get_strategy(strategy_id)
        params = dict(strategy.get("params") or {})
        return {
            "success": True,
            "preview_only": True,
            "strategy_id": strategy_id,
            "as_of_date": as_of_date,
            "strategy_summary": {
                "name": strategy.get("name"),
                "type": strategy.get("type") or strategy.get("strategy_type"),
                "status": strategy.get("status"),
                "param_count": len(params),
            },
            "message": (
                "Preview generated. Confirm to execute the strategy and produce fresh "
                "strategy outputs."
            ),
        }

    return _call_registered_tool(
        "execute_strategy",
        {
            "strategy_id": strategy_id,
            "as_of_date": as_of_date,
        },
    )


def _internal_handler_strategy_bind_portfolio(
    portfolio_id: int,
    strategy_id: int,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()

    if preview_only:
        strategy = client.strategy.get_strategy(strategy_id)
        portfolio = client.account.get_portfolio(portfolio_id)
        params = dict(strategy.get("params") or {})
        return {
            "success": True,
            "preview_only": True,
            "portfolio_id": portfolio_id,
            "strategy_id": strategy_id,
            "portfolio_summary": {
                "name": getattr(portfolio, "name", None),
                "total_value": getattr(portfolio, "total_value", None),
                "cash": getattr(portfolio, "cash", None),
            },
            "strategy_summary": {
                "name": strategy.get("name"),
                "type": strategy.get("type") or strategy.get("strategy_type"),
                "status": strategy.get("status"),
                "param_count": len(params),
            },
            "message": (
                "Preview generated. Confirm to bind the strategy to the portfolio and "
                "activate the allocation."
            ),
        }

    return _call_registered_tool(
        "bind_portfolio_strategy",
        {
            "portfolio_id": portfolio_id,
            "strategy_id": strategy_id,
        },
    )


def _internal_handler_strategy_unbind_portfolio(
    portfolio_id: int,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()

    if preview_only:
        portfolio = client.account.get_portfolio(portfolio_id)
        return {
            "success": True,
            "preview_only": True,
            "portfolio_id": portfolio_id,
            "portfolio_summary": {
                "name": getattr(portfolio, "name", None),
                "total_value": getattr(portfolio, "total_value", None),
                "cash": getattr(portfolio, "cash", None),
            },
            "target_status": "unbound",
            "message": (
                "Preview generated. Confirm to deactivate the portfolio's active strategy binding."
            ),
        }

    return _call_registered_tool(
        "unbind_portfolio_strategy",
        {
            "portfolio_id": portfolio_id,
        },
    )


def _internal_handler_strategy_create_position_rule(
    strategy_id: int,
    name: str,
    buy_price_expr: str,
    sell_price_expr: str,
    stop_loss_expr: str,
    take_profit_expr: str,
    position_size_expr: str,
    buy_condition_expr: str = "",
    sell_condition_expr: str = "",
    description: str = "",
    price_precision: int = 2,
    variables_schema: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
    is_active: bool = True,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    normalized_variables_schema = list(variables_schema or [])
    normalized_metadata = dict(metadata or {})

    if preview_only:
        strategy = client.strategy.get_strategy(strategy_id)
        return {
            "success": True,
            "preview_only": True,
            "strategy_id": strategy_id,
            "strategy_summary": {
                "name": strategy.get("name"),
                "strategy_type": strategy.get("strategy_type"),
                "is_active": strategy.get("is_active"),
            },
            "position_rule_summary": {
                "name": name,
                "is_active": is_active,
                "price_precision": price_precision,
                "variable_count": len(normalized_variables_schema),
                "metadata_key_count": len(normalized_metadata),
            },
            "message": (
                "Preview generated. Confirm to create the position rule for the selected strategy."
            ),
        }

    return _call_registered_tool(
        "create_position_rule",
        {
            "strategy_id": strategy_id,
            "name": name,
            "buy_price_expr": buy_price_expr,
            "sell_price_expr": sell_price_expr,
            "stop_loss_expr": stop_loss_expr,
            "take_profit_expr": take_profit_expr,
            "position_size_expr": position_size_expr,
            "buy_condition_expr": buy_condition_expr,
            "sell_condition_expr": sell_condition_expr,
            "description": description,
            "price_precision": price_precision,
            "variables_schema": normalized_variables_schema,
            "metadata": normalized_metadata,
            "is_active": is_active,
        },
    )


def _internal_handler_strategy_update_position_rule(
    rule_id: int,
    updates: dict[str, Any],
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    normalized_updates = dict(updates or {})

    if preview_only:
        rule = client.strategy.get_position_rule(rule_id)
        return {
            "success": True,
            "preview_only": True,
            "rule_id": rule_id,
            "position_rule_summary": {
                "strategy": rule.get("strategy"),
                "name": rule.get("name"),
                "is_active": rule.get("is_active"),
                "price_precision": rule.get("price_precision"),
            },
            "update_summary": {
                "field_count": len(normalized_updates),
                "fields": sorted(normalized_updates),
            },
            "message": (
                "Preview generated. Confirm to update the selected strategy position rule."
            ),
        }

    return _call_registered_tool(
        "update_position_rule",
        {
            "rule_id": rule_id,
            "updates": normalized_updates,
        },
    )


def _internal_handler_strategy_create_ai_config(
    strategy_id: int,
    prompt_template_id: int | None = None,
    chain_config_id: int | None = None,
    ai_provider_id: int | None = None,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    approval_mode: str = "conditional",
    confidence_threshold: float = 0.8,
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()

    if preview_only:
        strategy = client.strategy.get_strategy(strategy_id)
        return {
            "success": True,
            "preview_only": True,
            "strategy_id": strategy_id,
            "strategy_summary": {
                "name": strategy.get("name"),
                "strategy_type": strategy.get("strategy_type"),
                "is_active": strategy.get("is_active"),
            },
            "ai_config_summary": {
                "prompt_template_id": prompt_template_id,
                "chain_config_id": chain_config_id,
                "ai_provider_id": ai_provider_id,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "approval_mode": approval_mode,
                "confidence_threshold": confidence_threshold,
            },
            "message": (
                "Preview generated. Confirm to create the AI config for the selected strategy."
            ),
        }

    return _call_registered_tool(
        "create_ai_strategy_config",
        {
            "strategy_id": strategy_id,
            "prompt_template_id": prompt_template_id,
            "chain_config_id": chain_config_id,
            "ai_provider_id": ai_provider_id,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "approval_mode": approval_mode,
            "confidence_threshold": confidence_threshold,
        },
    )


def _internal_handler_strategy_create_strategy(
    name: str,
    strategy_type: str,
    description: str,
    params: dict[str, Any],
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    normalized_params = dict(params or {})

    if preview_only:
        return {
            "success": True,
            "preview_only": True,
            "strategy_summary": {
                "name": name,
                "strategy_type": strategy_type,
                "description_length": len(description),
                "param_count": len(normalized_params),
                "param_keys": sorted(normalized_params),
                "is_active": bool(normalized_params.get("is_active", True)),
            },
            "message": "Preview generated. Confirm to create the strategy.",
        }

    return _call_registered_tool(
        "create_strategy",
        {
            "name": name,
            "strategy_type": strategy_type,
            "description": description,
            "params": normalized_params,
        },
    )


def _internal_handler_strategy_update_ai_config(
    config_id: int,
    updates: dict[str, Any],
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    from agomtradepro import AgomTradeProClient

    client = AgomTradeProClient()
    normalized_updates = dict(updates or {})

    if preview_only:
        config = client.strategy._get(f"ai-configs/{config_id}/")
        return {
            "success": True,
            "preview_only": True,
            "config_id": config_id,
            "ai_config_summary": {
                "strategy": config.get("strategy"),
                "ai_provider": config.get("ai_provider"),
                "approval_mode": config.get("approval_mode"),
                "confidence_threshold": config.get("confidence_threshold"),
            },
            "update_summary": {
                "field_count": len(normalized_updates),
                "fields": sorted(normalized_updates),
            },
            "message": ("Preview generated. Confirm to update the selected AI strategy config."),
        }

    return _call_registered_tool(
        "update_ai_strategy_config",
        {
            "config_id": config_id,
            "updates": normalized_updates,
        },
    )


LEGACY_TOOL_FALLBACKS: dict[str, Callable[..., Any]] = {
    "strategy_read_catalog": _fallback_strategy_read_catalog,
    "strategy_read_detail": _fallback_strategy_read_detail,
    "strategy_read_ai_config_catalog": _fallback_strategy_read_ai_config_catalog,
    "strategy_read_ai_config_detail": _fallback_strategy_read_ai_config_detail,
    "strategy_read_position_rule_catalog": _fallback_strategy_read_position_rule_catalog,
    "strategy_read_position_rule_detail": _fallback_strategy_read_position_rule_detail,
    "strategy_compute_position_rule": _fallback_strategy_compute_position_rule,
    "strategy_compute_position_management": _fallback_strategy_compute_position_management,
    "strategy_read_performance": _fallback_strategy_read_performance,
    "strategy_read_signals": _fallback_strategy_read_signals,
    "strategy_read_positions": _fallback_strategy_read_positions,
    "execute_strategy": _fallback_execute_strategy,
    "bind_portfolio_strategy": _fallback_bind_portfolio_strategy,
    "unbind_portfolio_strategy": _fallback_unbind_portfolio_strategy,
    "create_position_rule": _fallback_create_position_rule,
    "update_position_rule": _fallback_update_position_rule,
    "create_strategy": _fallback_create_strategy,
    "create_ai_strategy_config": _fallback_create_ai_strategy_config,
    "update_ai_strategy_config": _fallback_update_ai_strategy_config,
}

GOVERNED_HANDLERS: dict[str, Callable[..., Any]] = {
    "strategy_execute_run": _internal_handler_strategy_execute_run,
    "strategy_bind_portfolio": _internal_handler_strategy_bind_portfolio,
    "strategy_unbind_portfolio": _internal_handler_strategy_unbind_portfolio,
    "strategy_create_position_rule": _internal_handler_strategy_create_position_rule,
    "strategy_update_position_rule": _internal_handler_strategy_update_position_rule,
    "strategy_create_strategy": _internal_handler_strategy_create_strategy,
    "strategy_create_ai_config": _internal_handler_strategy_create_ai_config,
    "strategy_update_ai_config": _internal_handler_strategy_update_ai_config,
}
