"""Factor interface orchestration contracts for filters, payloads, and failures."""

from datetime import date
from types import SimpleNamespace

import pytest

from apps.factor.application import interface_services


class _DefinitionRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def list_models_for_view(self, **kwargs: object) -> list[object]:
        self.calls.append(("list", kwargs))
        return ["factor"]

    def get_model_by_id(self, factor_id: int) -> object:
        self.calls.append(("get", factor_id))
        return SimpleNamespace(id=factor_id)

    def create_model(self, data: dict[str, object]) -> object:
        self.calls.append(("create", data))
        return data

    def update_model(self, **kwargs: object) -> object:
        self.calls.append(("update", kwargs))
        return kwargs

    def delete_model(self, factor_id: int) -> bool:
        self.calls.append(("delete", factor_id))
        return True

    def toggle_active(self, factor_id: int) -> object:
        self.calls.append(("toggle", factor_id))
        return SimpleNamespace(id=factor_id, is_active=True)


class _PortfolioRepository:
    def __init__(self) -> None:
        self.config = SimpleNamespace(
            id=7,
            name="quality",
            factor_weights={"roe": 1.0},
        )
        self.deleted = True

    def list_models_for_view(self, **_kwargs: object) -> list[object]:
        return [
            SimpleNamespace(universe="all_a", rebalance_frequency="monthly"),
            SimpleNamespace(universe="csi300", rebalance_frequency="weekly"),
        ]

    def get_model_by_id(self, _config_id: int) -> object | None:
        return self.config

    def create_model(self, data: dict[str, object]) -> object:
        return data

    def update_model(self, **kwargs: object) -> object:
        return kwargs

    def delete_model(self, _config_id: int) -> bool:
        return self.deleted

    def set_active(self, config_id: int, is_active: bool) -> object:
        return SimpleNamespace(id=config_id, is_active=is_active)


class _IntegrationService:
    def get_factor_definitions(self) -> list[dict[str, object]]:
        return [{"code": "roe"}]

    def create_factor_portfolio(
        self,
        config_name: str,
        trade_date_value: date | None,
    ) -> dict[str, object]:
        return {"config": config_name, "trade_date": trade_date_value}

    def explain_stock_score(self, **kwargs: object) -> dict[str, object]:
        return {"stock_code": kwargs["stock_code"], "drivers": ["roe"]}

    def calculate_factor_scores(self, **kwargs: object) -> list[dict[str, object]]:
        return [{"stock_code": kwargs["universe"][0]}]  # type: ignore[index]

    def get_top_stocks(
        self,
        _preferences: dict[str, str],
        top_n: int,
    ) -> list[dict[str, object]]:
        return [{"rank": 1, "top_n": top_n}]

    def get_all_configs(self) -> list[dict[str, object]]:
        return [{"name": "quality"}]


@pytest.fixture
def factor_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[_DefinitionRepository, _PortfolioRepository, _IntegrationService]:
    definitions = _DefinitionRepository()
    portfolios = _PortfolioRepository()
    integration = _IntegrationService()
    monkeypatch.setattr(
        interface_services,
        "get_factor_definition_repository",
        lambda: definitions,
    )
    monkeypatch.setattr(
        interface_services,
        "get_factor_portfolio_config_repository",
        lambda: portfolios,
    )
    monkeypatch.setattr(
        interface_services,
        "get_factor_integration_service",
        lambda **_kwargs: integration,
    )
    return definitions, portfolios, integration


def test_factor_definition_crud_and_optional_boolean_filters(
    factor_dependencies: tuple[_DefinitionRepository, _PortfolioRepository, _IntegrationService],
) -> None:
    definitions, _, _ = factor_dependencies

    assert interface_services.list_factor_definitions(
        filters={"category": "quality", "is_active": "true", "search": "roe"}
    ) == ["factor"]
    assert definitions.calls[-1][1] == {
        "category": "quality",
        "is_active": True,
        "search": "roe",
    }
    assert interface_services.get_factor_definition(factor_id=3).id == 3
    assert interface_services.create_factor_definition(data={"code": "roe"}) == {"code": "roe"}
    assert (
        interface_services.update_factor_definition(
            factor_id=3,
            data={"name": "ROE"},
        )["factor_id"]
        == 3
    )
    assert interface_services.toggle_factor_definition_active(factor_id=3).is_active is True
    assert interface_services.delete_factor_definition(factor_id=3) is True


def test_portfolio_filters_crud_and_public_payloads(
    factor_dependencies: tuple[_DefinitionRepository, _PortfolioRepository, _IntegrationService],
) -> None:
    _, _, _ = factor_dependencies

    filtered = interface_services.list_portfolio_configs(
        filters={
            "is_active": "false",
            "universe": "csi300",
            "rebalance_frequency": "weekly",
        }
    )
    assert len(filtered) == 1
    assert interface_services.get_portfolio_config(config_id=7).name == "quality"
    assert interface_services.create_portfolio_config(data={"name": "new"}) == {"name": "new"}
    assert (
        interface_services.update_portfolio_config(
            config_id=7,
            data={"name": "updated"},
        )["config_id"]
        == 7
    )
    assert (
        interface_services.set_portfolio_config_active(
            config_id=7,
            is_active=False,
        ).is_active
        is False
    )
    assert interface_services.delete_portfolio_config(config_id=7) is True
    assert interface_services.get_active_factor_definition_payloads() == [{"code": "roe"}]
    assert interface_services.get_all_portfolio_config_payloads() == [{"name": "quality"}]


def test_integration_helpers_forward_cache_and_trade_date_contract(
    factor_dependencies: tuple[_DefinitionRepository, _PortfolioRepository, _IntegrationService],
) -> None:
    target = date(2026, 7, 25)

    assert (
        interface_services.create_factor_portfolio(
            config_name="quality",
            trade_date_value=target,
        )["trade_date"]
        == target
    )
    assert (
        interface_services.explain_stock_score(
            stock_code="000001.SZ",
            factor_weights={"roe": 1.0},
            trade_date_value=target,
        )["stock_code"]
        == "000001.SZ"
    )
    assert interface_services.calculate_factor_scores(
        universe=["000001.SZ"],
        factor_weights={"roe": 1.0},
        trade_date_value=target,
        top_n=1,
    ) == [{"stock_code": "000001.SZ"}]
    assert (
        interface_services.get_top_stocks(
            factor_preferences={"quality": "high"},
            top_n=2,
        )[
            0
        ]["top_n"]
        == 2
    )


def test_factor_portfolio_payload_and_empty_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    holding = SimpleNamespace(
        trade_date=date(2026, 7, 25),
        stock_code="000001.SZ",
        stock_name="Ping An",
        weight=0.125,
        factor_score=88.126,
        rank=1,
        sector="Finance",
    )
    holdings: list[object] = [holding]
    monkeypatch.setattr(
        interface_services,
        "get_factor_portfolio_holding_repository",
        lambda: SimpleNamespace(get_latest_holdings=lambda _name: holdings),
    )

    payload = interface_services.get_factor_portfolio(config_name="quality")
    assert payload is not None
    assert payload["holdings"][0]["weight"] == 12.5
    assert payload["holdings"][0]["factor_score"] == 88.13

    holdings.clear()
    assert interface_services.get_factor_portfolio(config_name="quality") is None


def test_delete_with_message_distinguishes_missing_and_repository_failure(
    factor_dependencies: tuple[_DefinitionRepository, _PortfolioRepository, _IntegrationService],
) -> None:
    _, portfolios, _ = factor_dependencies

    portfolios.config = None
    assert interface_services.delete_portfolio_config_with_message(config_id=7)["status"] == 404

    portfolios.config = SimpleNamespace(name="quality")
    portfolios.deleted = False
    assert interface_services.delete_portfolio_config_with_message(config_id=7)["status"] == 404

    portfolios.deleted = True
    result = interface_services.delete_portfolio_config_with_message(config_id=7)
    assert result["status"] == 200
    assert "quality" in result["message"]


def test_explain_for_config_distinguishes_missing_empty_and_success(
    factor_dependencies: tuple[_DefinitionRepository, _PortfolioRepository, _IntegrationService],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, portfolios, _ = factor_dependencies

    portfolios.config = None
    assert (
        interface_services.explain_stock_for_config(
            stock_code="000001.SZ",
            config_id=7,
        )["status"]
        == 404
    )

    portfolios.config = SimpleNamespace(factor_weights={"roe": 1.0})
    monkeypatch.setattr(interface_services, "explain_stock_score", lambda **_kwargs: None)
    assert (
        interface_services.explain_stock_for_config(
            stock_code="000001.SZ",
            config_id=7,
        )["status"]
        == 500
    )

    monkeypatch.setattr(
        interface_services,
        "explain_stock_score",
        lambda **_kwargs: {"drivers": ["roe"]},
    )
    assert (
        interface_services.explain_stock_for_config(
            stock_code="000001.SZ",
            config_id=7,
        )["success"]
        is True
    )


def test_manage_and_portfolio_contexts_preserve_filters(
    factor_dependencies: tuple[_DefinitionRepository, _PortfolioRepository, _IntegrationService],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factor_response = SimpleNamespace(
        factors=["roe"],
        stats={"total": 1},
        categories=["quality"],
        category_choices=[("quality", "Quality")],
    )
    portfolio_response = SimpleNamespace(
        configs=["quality"],
        stats={"total": 1},
        factor_definitions=["roe"],
        universe_choices=[("all_a", "All A")],
        weight_method_choices=[("equal", "Equal")],
        rebalance_choices=[("monthly", "Monthly")],
    )
    monkeypatch.setattr(
        interface_services,
        "GetFactorDefinitionsForViewUseCase",
        lambda _repository: SimpleNamespace(execute=lambda _request: factor_response),
    )
    monkeypatch.setattr(
        interface_services,
        "GetPortfolioConfigsForViewUseCase",
        lambda *_repositories: SimpleNamespace(execute=lambda _request: portfolio_response),
    )

    manage = interface_services.build_factor_manage_context(
        {"category": "quality", "is_active": "true", "search": "roe"}
    )
    portfolio = interface_services.build_portfolio_list_context(
        {"is_active": "false", "search": "quality"}
    )

    assert manage["filter_category"] == "quality"
    assert manage["filter_is_active"] == "true"
    assert portfolio["filter_is_active"] == "false"
    assert portfolio["configs"] == ["quality"]


@pytest.mark.parametrize("raw_date", ["bad-date", "", None])
def test_calculation_context_normalizes_date_and_config(
    factor_dependencies: tuple[_DefinitionRepository, _PortfolioRepository, _IntegrationService],
    monkeypatch: pytest.MonkeyPatch,
    raw_date: str | None,
) -> None:
    observed: list[object] = []
    response = SimpleNamespace(
        configs=[],
        factors=[],
        factors_by_category={},
        category_choices=[],
        selected_config=None,
        calculated_results=[],
        trade_date=date(2026, 7, 25),
        top_n=12,
        config_id=7,
    )
    monkeypatch.setattr(
        interface_services,
        "GetFactorCalculationDataUseCase",
        lambda *_repositories: SimpleNamespace(
            execute=lambda request: observed.append(request) or response
        ),
    )

    context = interface_services.build_factor_calculation_context(
        {"trade_date": raw_date, "top_n": "12", "config_id": "7"}
    )

    assert context["top_n"] == 12
    assert context["config_id"] == 7
    assert observed[0].config_id == 7


@pytest.mark.parametrize("success", [True, False])
def test_create_portfolio_form_normalizes_numeric_fields_and_result(
    factor_dependencies: tuple[_DefinitionRepository, _PortfolioRepository, _IntegrationService],
    monkeypatch: pytest.MonkeyPatch,
    success: bool,
) -> None:
    observed: list[object] = []
    response = SimpleNamespace(
        success=success,
        config_id=7,
        message="created",
        error="duplicate",
    )
    monkeypatch.setattr(
        interface_services,
        "CreatePortfolioConfigUseCase",
        lambda _repository: SimpleNamespace(
            execute=lambda request: observed.append(request) or response
        ),
    )

    result = interface_services.create_portfolio_config_from_form(
        {
            "name": "  quality  ",
            "description": "  stable  ",
            "factor_weights": '{"roe": 0.6, "value": 0.4}',
            "top_n": "20",
            "min_market_cap": "10.5",
            "max_market_cap": "",
            "max_pe": "15",
            "max_pb": "2.5",
            "max_debt_ratio": "0.4",
        }
    )

    request = observed[0]
    assert request.name == "quality"
    assert request.factor_weights == {"roe": 0.6, "value": 0.4}
    assert request.min_market_cap == 10.5
    assert request.max_market_cap is None
    assert request.max_pe == 15.0
    assert result["success"] is success


def test_portfolio_action_forwards_config_and_action(
    factor_dependencies: tuple[_DefinitionRepository, _PortfolioRepository, _IntegrationService],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[object] = []
    monkeypatch.setattr(
        interface_services,
        "UpdatePortfolioConfigUseCase",
        lambda *_dependencies: SimpleNamespace(
            execute=lambda request: observed.append(request)
            or {"success": True, "action": request.action_type}
        ),
    )

    result = interface_services.handle_portfolio_config_action(
        config_id=7,
        action_type="activate",
    )

    assert result == {"success": True, "action": "activate"}
    assert observed[0].config_id == 7
