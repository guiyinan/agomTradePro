"""Parameterized contracts for advertised API module roots."""

from collections.abc import Mapping, Sequence
from typing import Any

import pytest

API_ROOT_CONTRACTS = (
    pytest.param(
        "authenticated_client",
        "/api/ai/",
        {
            "endpoints.providers": "/api/ai/providers/",
            "endpoints.logs": "/api/ai/logs/",
            "endpoints.me_providers": "/api/ai/me/providers/",
            "endpoints.me_quota": "/api/ai/me/quota/current/",
        },
        {},
        id="ai-provider",
    ),
    pytest.param(
        "api_client",
        "/api/alpha/",
        {"module": "alpha"},
        {"endpoints": "/api/alpha/scores/"},
        id="alpha",
    ),
    pytest.param(
        "admin_client",
        "/api/audit/",
        {
            "endpoints.summary": "/api/audit/summary/",
            "endpoints.run_validation": "/api/audit/run-validation/",
        },
        {},
        id="audit",
    ),
    pytest.param(
        "authenticated_client",
        "/api/backtest/",
        {
            "endpoints.backtests": "/api/backtest/backtests/",
            "endpoints.run": "/api/backtest/run/",
        },
        {},
        id="backtest",
    ),
    pytest.param(
        "authenticated_client",
        "/api/beta-gate/",
        {
            "endpoints.configs": "/api/beta-gate/configs/",
            "endpoints.test": "/api/beta-gate/test/",
        },
        {},
        id="beta-gate",
    ),
    pytest.param(
        "client",
        "/api/dashboard/",
        {
            "endpoints.allocation": "/api/dashboard/allocation/",
            "endpoints.positions_data": "/api/dashboard/positions/data/",
            "endpoints.alpha_stocks": "/api/dashboard/alpha/stocks/",
            "endpoints.v1_alpha_decision_chain": ("/api/dashboard/v1/alpha-decision-chain/"),
        },
        {},
        id="dashboard",
    ),
    pytest.param(
        "authenticated_client",
        "/api/decision/",
        {
            "endpoints.workspace_recommendations": ("/api/decision/workspace/recommendations/"),
            "endpoints.execute_preview": "/api/decision/execute/preview/",
        },
        {},
        id="decision",
    ),
    pytest.param(
        "admin_client",
        "/api/events/",
        {
            "endpoints.publish": "/api/events/publish/",
            "endpoints.replay_preview": "/api/events/replay/preview/",
            "endpoints.replay_commit": "/api/events/replay/commit/",
        },
        {},
        id="events",
    ),
    pytest.param(
        "authenticated_client",
        "/api/factor/",
        {
            "endpoints.definitions": "/api/factor/definitions/",
            "endpoints.configs": "/api/factor/configs/",
        },
        {},
        id="factor",
    ),
    pytest.param(
        "authenticated_client",
        "/api/fund/",
        {
            "endpoints.screen": "/api/fund/screen/",
            "endpoints.multidim_screen": "/api/fund/multidim-screen/",
        },
        {},
        id="fund",
    ),
    pytest.param(
        "authenticated_client",
        "/api/prompt/",
        {
            "endpoints.templates": "/api/prompt/templates/",
            "endpoints.chat": "/api/prompt/chat",
        },
        {},
        id="prompt",
    ),
    pytest.param(
        "authenticated_client",
        "/api/regime/",
        {
            "endpoints.current": "/api/regime/current/",
            "endpoints.navigator": "/api/regime/navigator/",
        },
        {},
        id="regime",
    ),
    pytest.param(
        "api_client",
        "/api/rotation/",
        {
            "endpoints.assets": "/api/rotation/assets/",
            "endpoints.actions": "/api/rotation/",
        },
        {},
        id="rotation",
    ),
    pytest.param(
        "authenticated_client",
        "/api/sector/",
        {
            "endpoints.rotation": "/api/sector/rotation/",
            "endpoints.analyze": "/api/sector/analyze/",
        },
        {},
        id="sector",
    ),
    pytest.param(
        "authenticated_client",
        "/api/sentiment/",
        {
            "endpoints.analyze": "/api/sentiment/analyze/",
            "endpoints.health": "/api/sentiment/health/",
        },
        {},
        id="sentiment",
    ),
    pytest.param(
        "authenticated_client",
        "/api/simulated-trading/",
        {"module": "simulated-trading"},
        {"endpoints": "/api/simulated-trading/accounts/"},
        id="simulated-trading",
    ),
    pytest.param(
        "authenticated_client",
        "/api/strategy/",
        {
            "endpoints.strategies": "/api/strategy/strategies/",
            "endpoints.execution_evaluate": "/api/strategy/execution/evaluate/",
        },
        {},
        id="strategy",
    ),
)

API_PERMISSION_CONTRACTS = (
    pytest.param(
        "api_client",
        "/api/ai/providers/",
        {401, 403},
        id="ai-provider-anonymous",
    ),
    pytest.param(
        "authenticated_client",
        "/api/ai/providers/",
        {403},
        id="ai-provider-non-admin",
    ),
    pytest.param(
        "api_client",
        "/api/alpha-triggers/performance/",
        {401, 403},
        id="alpha-trigger-anonymous",
    ),
    pytest.param(
        "api_client",
        "/api/equity/valuation/300308.SZ/",
        {401, 403},
        id="equity-valuation-anonymous",
    ),
    pytest.param(
        "api_client",
        "/api/rotation/configs/",
        {401, 403},
        id="rotation-config-anonymous",
    ),
    pytest.param(
        "api_client",
        "/api/sector/rotation/",
        {401, 403},
        id="sector-rotation-anonymous",
    ),
    pytest.param(
        "api_client",
        "/api/sector/score/801010/",
        {401, 403},
        id="sector-score-anonymous",
    ),
)


def _resolve_path(payload: Mapping[str, Any], dotted_path: str) -> Any:
    """Resolve one dotted path from a JSON object."""

    value: Any = payload
    for segment in dotted_path.split("."):
        value = value[segment]
    return value


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("client_fixture", "endpoint", "expected_values", "expected_members"),
    API_ROOT_CONTRACTS,
)
def test_api_root_contract_matrix(
    request: pytest.FixtureRequest,
    client_fixture: str,
    endpoint: str,
    expected_values: Mapping[str, Any],
    expected_members: Mapping[str, Any],
) -> None:
    """Every advertised module root must retain its JSON discovery contract."""

    client = request.getfixturevalue(client_fixture)
    response = client.get(endpoint)

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    for dotted_path, expected in expected_values.items():
        assert _resolve_path(payload, dotted_path) == expected
    for dotted_path, expected_member in expected_members.items():
        container: Sequence[Any] | Mapping[str, Any] = _resolve_path(payload, dotted_path)
        assert expected_member in container


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("client_fixture", "endpoint", "expected_statuses"),
    API_PERMISSION_CONTRACTS,
)
def test_api_permission_contract_matrix(
    request: pytest.FixtureRequest,
    client_fixture: str,
    endpoint: str,
    expected_statuses: set[int],
) -> None:
    """Protected edge endpoints must reject the wrong caller role as JSON."""

    client = request.getfixturevalue(client_fixture)
    response = client.get(endpoint)

    assert response.status_code in expected_statuses
    assert response["Content-Type"].startswith("application/json")
