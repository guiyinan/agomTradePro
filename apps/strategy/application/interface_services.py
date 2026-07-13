"""Interface-facing query helpers for strategy views."""

from __future__ import annotations

from datetime import date
from typing import Any

from apps.simulated_trading.application.interface_services import (
    list_account_trade_payloads,
)
from apps.strategy.application.repository_provider import (
    build_strategy_executor as _build_strategy_executor,
)
from apps.strategy.application.repository_provider import (
    build_strategy_portfolio_provider,
    get_strategy_interface_repository,
)


def _repo():
    return get_strategy_interface_repository()


def get_strategy_queryset():
    return _repo().get_strategy_queryset()


def get_strategy_queryset_for_owner(owner_profile_id: int):
    return _repo().get_strategy_queryset_for_owner(owner_profile_id)


def get_strategy_queryset_for_access(
    *,
    owner_profile_id: int | None,
    include_all: bool = False,
):
    """Return the strategy queryset visible to an owner or staff caller."""

    return _repo().get_strategy_queryset_for_access(
        owner_profile_id=owner_profile_id,
        include_all=include_all,
    )


def build_strategy_list_context(owner_profile_id: int) -> dict:
    strategies = list(_repo().list_user_strategies_with_counts(owner_profile_id))
    for strategy in strategies:
        strategy.rule_summary = _repo().list_strategy_rule_summary(strategy.id)
    return {
        "strategies": strategies,
        "stats": _repo().get_user_strategy_stats(owner_profile_id),
    }


def replace_strategy_rule_conditions(strategy_id: int, validated_rules: list[dict]) -> None:
    _repo().replace_rule_conditions(strategy_id, validated_rules)


def get_strategy_script_config(strategy_id: int):
    return _repo().get_strategy_script_config(strategy_id)


def delete_strategy_script_config(strategy_id: int) -> None:
    _repo().delete_strategy_script_config(strategy_id)


def get_strategy_ai_config(strategy_id: int):
    return _repo().get_strategy_ai_config(strategy_id)


def list_active_prompt_templates():
    return _repo().list_active_prompt_templates()


def list_active_chain_configs():
    return _repo().list_active_chain_configs()


def list_active_ai_providers_for_user(user_id: int):
    return _repo().list_active_ai_providers_for_user(user_id)


def get_strategy_execution_logs_page(strategy_id: int, offset: int, limit: int):
    return _repo().get_strategy_execution_logs_page(strategy_id, offset, limit)


def get_strategy_position_rule(strategy_id: int):
    return _repo().get_strategy_position_rule(strategy_id)


def get_position_management_rule_queryset():
    return _repo().get_position_management_rule_queryset()


def get_position_management_rule_queryset_for_access(
    *,
    owner_profile_id: int | None,
    include_all: bool = False,
):
    """Return position rules visible to an owner or staff caller."""

    return _repo().get_position_management_rule_queryset_for_access(
        owner_profile_id=owner_profile_id,
        include_all=include_all,
    )


def get_rule_condition_queryset():
    return _repo().get_rule_condition_queryset()


def get_script_config_queryset():
    return _repo().get_script_config_queryset()


def get_ai_strategy_config_queryset():
    return _repo().get_ai_strategy_config_queryset()


def get_ai_strategy_config_queryset_for_access(
    *,
    owner_profile_id: int | None,
    include_all: bool = False,
):
    """Return AI strategy configs visible to an owner or staff caller."""

    return _repo().get_ai_strategy_config_queryset_for_access(
        owner_profile_id=owner_profile_id,
        include_all=include_all,
    )


def get_assignment_queryset():
    return _repo().get_assignment_queryset()


def list_assignments_by_portfolio(portfolio_id: int):
    return _repo().list_assignments_by_portfolio(portfolio_id)


def list_active_assignments_for_strategy(strategy_id: int):
    return _repo().list_active_assignments_for_strategy(strategy_id)


def bind_strategy_assignment(*, portfolio_id: int, strategy, assigned_by):
    return _repo().bind_strategy(
        portfolio_id=portfolio_id,
        strategy=strategy,
        assigned_by=assigned_by,
    )


def unbind_strategy_assignments(portfolio_id: int) -> None:
    _repo().unbind_portfolio_strategies(portfolio_id)


def set_strategy_active(strategy_id: int, is_active: bool):
    return _repo().set_strategy_active(strategy_id, is_active)


def set_rule_enabled(rule_id: int, is_enabled: bool):
    return _repo().set_rule_enabled(rule_id, is_enabled)


def set_assignment_active(assignment_id: int, is_active: bool):
    return _repo().set_assignment_active(assignment_id, is_active)


def get_execution_log_queryset():
    return _repo().get_execution_log_queryset()


def list_execution_logs_by_strategy(strategy_id: int, limit: int = 100):
    return _repo().list_execution_logs_by_strategy(strategy_id, limit=limit)


def list_execution_logs_by_portfolio(portfolio_id: int, limit: int = 100):
    return _repo().list_execution_logs_by_portfolio(portfolio_id, limit=limit)


def build_strategy_executor():
    return _build_strategy_executor()


def execute_strategy_for_assignments(
    *,
    strategy_id: int,
    portfolio_id: int | None = None,
    as_of_date: date | None = None,
) -> dict[str, Any]:
    """Execute a strategy for one assigned portfolio or all active assignments."""

    assignments = list_active_assignments_for_strategy(strategy_id)
    if portfolio_id is not None:
        assignments = [item for item in assignments if item.portfolio_id == portfolio_id]
        if not assignments:
            raise ValueError("portfolio is not actively assigned to this strategy")
    if not assignments:
        raise ValueError("strategy has no active portfolio assignments")

    executor = build_strategy_executor()
    results = [
        executor.execute_strategy(strategy_id, assignment.portfolio_id)
        for assignment in assignments
    ]
    failed = [
        {
            "portfolio_id": result.portfolio_id,
            "error": result.error_message,
        }
        for result in results
        if not result.is_success
    ]
    execution_ids = [result.execution_time.isoformat() for result in results]
    signals_count = sum(len(result.signals) for result in results)
    return {
        "success": all(result.is_success for result in results),
        "strategy_id": strategy_id,
        "as_of_date": as_of_date.isoformat() if as_of_date else None,
        "execution_id": execution_ids[0] if len(execution_ids) == 1 else execution_ids,
        "generated_signals": signals_count,
        "signals_count": signals_count,
        "failed_rules": failed,
        "duration_ms": sum(result.execution_duration_ms for result in results),
        "executed_portfolios": len(results),
    }


def list_strategy_signal_payloads(
    *,
    strategy_id: int,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Flatten persisted strategy execution signals into a stable read contract."""

    payloads: list[dict[str, Any]] = []
    for log in list_execution_logs_by_strategy(strategy_id, limit=max(limit, 100)):
        for signal in log.signals_generated or []:
            signal_payload = dict(signal)
            signal_payload.setdefault("status", "generated")
            if status and signal_payload["status"] != status:
                continue
            signal_payload["execution_log_id"] = log.id
            signal_payload["portfolio_id"] = log.portfolio_id
            signal_payload["execution_time"] = log.execution_time.isoformat()
            payloads.append(signal_payload)
            if len(payloads) >= limit:
                return payloads
    return payloads


def get_strategy_performance_payload(
    *,
    strategy_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    """Summarize persisted strategy executions without inventing return metrics."""

    logs = list_execution_logs_by_strategy(strategy_id, limit=5000)
    filtered = [
        log
        for log in logs
        if (start_date is None or log.execution_time.date() >= start_date)
        and (end_date is None or log.execution_time.date() <= end_date)
    ]
    success_count = sum(1 for log in filtered if log.is_success)
    signal_count = sum(len(log.signals_generated or []) for log in filtered)
    durations = [log.execution_duration_ms for log in filtered]
    return {
        "strategy_id": strategy_id,
        "metric_scope": "execution",
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "execution_count": len(filtered),
        "successful_execution_count": success_count,
        "failed_execution_count": len(filtered) - success_count,
        "success_rate": success_count / len(filtered) if filtered else 0.0,
        "signals_generated": signal_count,
        "average_duration_ms": sum(durations) / len(durations) if durations else 0.0,
        "latest_execution_time": (
            filtered[0].execution_time.isoformat() if filtered else None
        ),
    }


def list_strategy_position_payloads(*, strategy_id: int) -> list[dict[str, Any]]:
    """Return positions for all portfolios actively assigned to a strategy."""

    provider = build_strategy_portfolio_provider()
    payloads: list[dict[str, Any]] = []
    for assignment in list_active_assignments_for_strategy(strategy_id):
        for position in provider.get_positions(assignment.portfolio_id):
            payloads.append(
                {
                    **position,
                    "portfolio_id": assignment.portfolio_id,
                    "portfolio_name": assignment.portfolio.account_name,
                }
            )
    return payloads


def list_strategy_trade_payloads(
    *,
    strategy_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return account-ledger trades for portfolios actively assigned to a strategy."""

    payloads: list[dict[str, Any]] = []
    for assignment in list_active_assignments_for_strategy(strategy_id):
        trades = list_account_trade_payloads(
            account_id=assignment.portfolio_id,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )
        for trade in trades:
            payloads.append(
                {
                    **trade,
                    "portfolio_id": assignment.portfolio_id,
                    "portfolio_name": assignment.portfolio.account_name,
                }
            )
    payloads.sort(key=lambda item: item.get("execution_time") or "", reverse=True)
    return payloads[:limit]
