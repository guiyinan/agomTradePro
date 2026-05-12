"""Application-facing orchestration helpers for factor interface views."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from apps.factor.application.repository_provider import (
    get_factor_definition_repository,
    get_factor_integration_service,
    get_factor_portfolio_config_repository,
)
from apps.factor.application.use_cases import (
    CalculateScoresRequest,
    CalculateScoresUseCase,
    CreatePortfolioConfigRequest,
    CreatePortfolioConfigUseCase,
    FactorCalculateViewRequest,
    FactorListViewRequest,
    GetFactorCalculationDataUseCase,
    GetFactorDefinitionsForViewUseCase,
    GetPortfolioConfigsForViewUseCase,
    PortfolioConfigActionRequest,
    PortfolioListViewRequest,
    UpdatePortfolioConfigUseCase,
)


def _parse_optional_bool(value: str | None) -> bool | None:
    """Parse a query-string boolean value."""

    if value is None or value == "":
        return None
    return value.lower() == "true"


def _parse_trade_date(value: str | None) -> date:
    """Parse a trade-date string and fall back to today."""

    if not value:
        return date.today()
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return date.today()


def list_factor_definitions(*, filters: Mapping[str, Any] | None = None) -> list[Any]:
    """Return factor definitions for API listing."""

    filters = filters or {}
    return get_factor_definition_repository().list_models_for_view(
        category=filters.get("category") or None,
        is_active=_parse_optional_bool(filters.get("is_active")),
        search=filters.get("search") or None,
    )


def get_factor_definition(*, factor_id: int) -> Any | None:
    """Return one factor definition model by id."""

    return get_factor_definition_repository().get_model_by_id(factor_id)


def create_factor_definition(*, data: Mapping[str, Any]) -> Any:
    """Create one factor definition model."""

    return get_factor_definition_repository().create_model(dict(data))


def update_factor_definition(*, factor_id: int, data: Mapping[str, Any]) -> Any | None:
    """Update one factor definition model."""

    return get_factor_definition_repository().update_model(
        factor_id=factor_id,
        data=dict(data),
    )


def delete_factor_definition(*, factor_id: int) -> bool:
    """Delete one factor definition model."""

    return get_factor_definition_repository().delete_model(factor_id)


def toggle_factor_definition_active(*, factor_id: int) -> Any | None:
    """Toggle one factor definition model activation state."""

    return get_factor_definition_repository().toggle_active(factor_id)


def get_active_factor_definition_payloads() -> list[dict]:
    """Return the payload used by the all-active endpoint."""

    return get_factor_integration_service().get_factor_definitions()


def list_portfolio_configs(*, filters: Mapping[str, Any] | None = None) -> list[Any]:
    """Return portfolio configurations for API listing."""

    filters = filters or {}
    configs = get_factor_portfolio_config_repository().list_models_for_view(
        is_active=_parse_optional_bool(filters.get("is_active")),
        search=filters.get("search") or None,
    )
    universe = filters.get("universe") or None
    rebalance_frequency = filters.get("rebalance_frequency") or None

    if universe:
        configs = [config for config in configs if config.universe == universe]
    if rebalance_frequency:
        configs = [
            config
            for config in configs
            if config.rebalance_frequency == rebalance_frequency
        ]
    return configs


def get_portfolio_config(*, config_id: int) -> Any | None:
    """Return one portfolio configuration model by id."""

    return get_factor_portfolio_config_repository().get_model_by_id(config_id)


def create_portfolio_config(*, data: Mapping[str, Any]) -> Any:
    """Create one portfolio configuration model from API data."""

    return get_factor_portfolio_config_repository().create_model(dict(data))


def update_portfolio_config(*, config_id: int, data: Mapping[str, Any]) -> Any | None:
    """Update one portfolio configuration model."""

    return get_factor_portfolio_config_repository().update_model(
        config_id=config_id,
        data=dict(data),
    )


def delete_portfolio_config(*, config_id: int) -> bool:
    """Delete one portfolio configuration model."""

    return get_factor_portfolio_config_repository().delete_model(config_id)


def set_portfolio_config_active(*, config_id: int, is_active: bool) -> Any | None:
    """Set one portfolio configuration active or inactive."""

    return get_factor_portfolio_config_repository().set_active(config_id, is_active)


def create_factor_portfolio(*, config_name: str, trade_date_value=None) -> dict | None:
    """Generate a portfolio for one configuration."""

    return get_factor_integration_service().create_factor_portfolio(
        config_name,
        trade_date_value,
    )


def explain_stock_score(
    *,
    stock_code: str,
    factor_weights: dict[str, float],
    trade_date_value=None,
) -> dict | None:
    """Return stock factor score explanation."""

    return get_factor_integration_service().explain_stock_score(
        stock_code=stock_code,
        factor_weights=factor_weights,
        trade_date=trade_date_value,
    )


def calculate_factor_scores(
    *,
    universe: list[str],
    factor_weights: dict[str, float],
    trade_date_value=None,
    top_n: int = 50,
) -> list[dict]:
    """Return factor scores for an explicit universe."""

    return get_factor_integration_service().calculate_factor_scores(
        universe=universe,
        factor_weights=factor_weights,
        trade_date=trade_date_value,
        top_n=top_n,
    )


def get_top_stocks(*, factor_preferences: dict[str, str], top_n: int = 30) -> list[dict]:
    """Return top stocks from factor preferences."""

    return get_factor_integration_service().get_top_stocks(factor_preferences, top_n)


def get_all_portfolio_config_payloads() -> list[dict]:
    """Return the payload used by the all-configs endpoint."""

    return get_factor_integration_service().get_all_configs()


def build_factor_manage_context(query_params: Mapping[str, Any]) -> dict[str, Any]:
    """Build the factor manage HTML context."""

    category_filter = query_params.get("category", "")
    is_active_str = query_params.get("is_active", "")
    search = query_params.get("search", "")

    use_case = GetFactorDefinitionsForViewUseCase(get_factor_definition_repository())
    response = use_case.execute(
        FactorListViewRequest(
            category=category_filter or None,
            is_active=_parse_optional_bool(is_active_str),
            search=search or None,
        )
    )

    return {
        "factors": response.factors,
        "stats": response.stats,
        "categories": response.categories,
        "category_choices": response.category_choices,
        "filter_category": category_filter,
        "filter_is_active": is_active_str,
        "filter_search": search,
    }


def build_portfolio_list_context(query_params: Mapping[str, Any]) -> dict[str, Any]:
    """Build the portfolio configuration HTML context."""

    is_active_str = query_params.get("is_active", "")
    search = query_params.get("search", "")

    use_case = GetPortfolioConfigsForViewUseCase(
        get_factor_definition_repository(),
        get_factor_portfolio_config_repository(),
    )
    response = use_case.execute(
        PortfolioListViewRequest(
            is_active=_parse_optional_bool(is_active_str),
            search=search or None,
        )
    )

    return {
        "configs": response.configs,
        "stats": response.stats,
        "factor_definitions": response.factor_definitions,
        "universe_choices": response.universe_choices,
        "weight_method_choices": response.weight_method_choices,
        "rebalance_choices": response.rebalance_choices,
        "filter_is_active": is_active_str,
        "filter_search": search,
    }


def build_factor_calculation_context(query_params: Mapping[str, Any]) -> dict[str, Any]:
    """Build the factor calculation HTML context."""

    trade_date_value = _parse_trade_date(query_params.get("trade_date"))
    top_n = int(query_params.get("top_n", 30))
    config_id = query_params.get("config_id")
    config_id_int = int(config_id) if config_id else None

    use_case = GetFactorCalculationDataUseCase(
        get_factor_portfolio_config_repository(),
        get_factor_definition_repository(),
    )
    response = use_case.execute(
        FactorCalculateViewRequest(
            trade_date=trade_date_value,
            top_n=top_n,
            config_id=config_id_int,
        )
    )

    return {
        "configs": response.configs,
        "factors": response.factors,
        "factors_by_category": response.factors_by_category,
        "category_choices": response.category_choices,
        "selected_config": response.selected_config,
        "calculated_results": response.calculated_results,
        "trade_date": response.trade_date,
        "top_n": response.top_n,
        "config_id": response.config_id,
    }


def create_portfolio_config_from_form(post_data: Mapping[str, Any]) -> dict[str, Any]:
    """Create one portfolio configuration from template form data."""

    factor_weights_json = post_data.get("factor_weights", "{}")
    factor_weights = json.loads(factor_weights_json) if factor_weights_json else {}

    use_case = CreatePortfolioConfigUseCase(get_factor_portfolio_config_repository())
    response = use_case.execute(
        CreatePortfolioConfigRequest(
            name=post_data.get("name", "").strip(),
            description=post_data.get("description", "").strip(),
            universe=post_data.get("universe", "all_a"),
            top_n=int(post_data.get("top_n", 30)),
            rebalance_frequency=post_data.get("rebalance_frequency", "monthly"),
            weight_method=post_data.get("weight_method", "equal_weight"),
            factor_weights=factor_weights,
            min_market_cap=float(post_data["min_market_cap"])
            if post_data.get("min_market_cap")
            else None,
            max_market_cap=float(post_data["max_market_cap"])
            if post_data.get("max_market_cap")
            else None,
            max_pe=float(post_data["max_pe"]) if post_data.get("max_pe") else None,
            max_pb=float(post_data["max_pb"]) if post_data.get("max_pb") else None,
            max_debt_ratio=float(post_data["max_debt_ratio"])
            if post_data.get("max_debt_ratio")
            else None,
        )
    )

    if response.success:
        return {
            "success": True,
            "config_id": response.config_id,
            "message": response.message,
        }
    return {
        "success": False,
        "error": response.error,
    }


def handle_portfolio_config_action(*, config_id: int, action_type: str) -> dict[str, Any]:
    """Perform activate, deactivate, or generate for one config."""

    use_case = UpdatePortfolioConfigUseCase(
        get_factor_portfolio_config_repository(),
        get_factor_integration_service(),
    )
    return use_case.execute(
        PortfolioConfigActionRequest(
            config_id=config_id,
            action_type=action_type,
        )
    )


def delete_portfolio_config_with_message(*, config_id: int) -> dict[str, Any]:
    """Delete one config and preserve the existing user-facing message."""

    config = get_factor_portfolio_config_repository().get_model_by_id(config_id)
    if config is None:
        return {"success": False, "error": "配置不存在", "status": 404}

    config_name = config.name
    deleted = get_factor_portfolio_config_repository().delete_model(config_id)
    if not deleted:
        return {"success": False, "error": "配置不存在", "status": 404}
    return {
        "success": True,
        "message": f'组合配置 "{config_name}" 已删除',
        "status": 200,
    }


def calculate_scores_for_config(*, post_data: Mapping[str, Any]) -> dict[str, Any]:
    """Calculate scores for one stored portfolio configuration."""

    use_case = CalculateScoresUseCase(
        get_factor_integration_service(),
        portfolio_repo=get_factor_portfolio_config_repository(),
    )
    response = use_case.execute(
        CalculateScoresRequest(
            config_id=int(post_data["config_id"]),
            top_n=int(post_data.get("top_n", 30)),
            trade_date=_parse_trade_date(post_data.get("trade_date")),
        )
    )

    if response.success:
        return {
            "success": True,
            "total_scores": response.total_scores,
            "scores": response.scores,
            "message": response.message,
            "status": 200,
        }
    return {
        "success": False,
        "error": response.error,
        "status": 500,
    }


def explain_stock_for_config(*, stock_code: str, config_id: int) -> dict[str, Any]:
    """Explain one stock using a stored portfolio config."""

    config = get_factor_portfolio_config_repository().get_model_by_id(config_id)
    if config is None:
        return {"success": False, "error": "配置不存在", "status": 404}

    explanation = explain_stock_score(
        stock_code=stock_code,
        factor_weights=config.factor_weights or {},
    )
    if explanation:
        return {
            "success": True,
            "explanation": explanation,
            "status": 200,
        }
    return {"success": False, "error": "无法获取因子解释", "status": 500}
