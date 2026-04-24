"""Interface-facing query helpers for strategy views."""

from apps.strategy.application.repository_provider import (
    build_strategy_executor as _build_strategy_executor,
    get_strategy_interface_repository,
)


def _repo():
    return get_strategy_interface_repository()


def get_strategy_queryset():
    return _repo().get_strategy_queryset()


def get_strategy_queryset_for_owner(owner_profile_id: int):
    return _repo().get_strategy_queryset_for_owner(owner_profile_id)


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


def get_strategy_execution_logs_page(strategy_id: int, offset: int, limit: int):
    return _repo().get_strategy_execution_logs_page(strategy_id, offset, limit)


def get_strategy_position_rule(strategy_id: int):
    return _repo().get_strategy_position_rule(strategy_id)


def get_position_management_rule_queryset():
    return _repo().get_position_management_rule_queryset()


def get_rule_condition_queryset():
    return _repo().get_rule_condition_queryset()


def get_script_config_queryset():
    return _repo().get_script_config_queryset()


def get_ai_strategy_config_queryset():
    return _repo().get_ai_strategy_config_queryset()


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
