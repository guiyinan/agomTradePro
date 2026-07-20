from unittest.mock import patch

import pytest

from agomtradepro import AgomTradeProClient


def test_get_agent_proposal_endpoint_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    expected = {
        "request_id": "apr_20260710_001",
        "proposal": {"id": 7, "status": "submitted", "risk_level": "medium"},
    }
    with patch.object(client, "_request", return_value=expected) as mock_request:
        result = client.agent_proposal.get_proposal(7)

    assert result == expected
    args, kwargs = mock_request.call_args
    assert args[0] == "GET"
    assert args[1] == "/api/agent-runtime/proposals/7/"
    assert kwargs == {"params": None}


def test_list_beta_gate_configs_endpoint_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    expected = [{"config_id": "balanced-v1", "risk_profile": "balanced"}]
    with patch.object(
        client,
        "_request",
        return_value={"success": True, "count": 1, "results": expected},
    ) as mock_request:
        result = client.beta_gate.list_configs()

    assert result == expected
    args, kwargs = mock_request.call_args
    assert args[0] == "GET"
    assert args[1] == "/api/beta-gate/configs/"
    assert kwargs == {"params": None}


def test_list_all_beta_gate_configs_endpoint_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    expected = [
        {
            "config_id": "balanced-v1",
            "risk_profile": "balanced",
            "is_active": False,
        }
    ]
    with patch.object(
        client,
        "_request",
        return_value={"success": True, "count": 1, "results": expected},
    ) as mock_request:
        result = client.beta_gate.list_configs(active_only=False)

    assert result == expected
    args, kwargs = mock_request.call_args
    assert args[0] == "GET"
    assert args[1] == "/api/beta-gate/configs/"
    assert kwargs == {"params": {"active_only": "false"}}


def test_create_beta_gate_config_endpoint_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    payload = {
        "config_id": "balanced-v2",
        "risk_profile": "balanced",
        "allowed_regimes": ["Recovery", "Deflation"],
        "min_confidence": 0.6,
        "max_policy_level": 1,
        "veto_on_p3": True,
        "max_total_position": 80.0,
        "max_single_position": 15.0,
    }
    expected = {
        "success": True,
        "result": {
            "config_id": "balanced-v2",
            "risk_profile": "balanced",
            "version": 2,
            "is_active": True,
        },
    }
    with patch.object(client, "_request", return_value=expected) as mock_request:
        result = client.beta_gate.create_config(payload)

    assert result == expected
    args, kwargs = mock_request.call_args
    assert args[0] == "POST"
    assert args[1] == "/api/beta-gate/configs/"
    assert kwargs == {"json": payload, "data": None}


def test_compare_beta_gate_configs_endpoint_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    expected = {
        "success": True,
        "config1": {"config_id": "balanced-v1", "version": 1},
        "config2": {"config_id": "balanced-v2", "version": 2},
        "differences": [{"field": "is_active", "config1": False, "config2": True}],
    }
    with patch.object(client, "_request", return_value=expected) as mock_request:
        result = client.beta_gate.version_compare(
            {"version1": "balanced-v1", "version2": "balanced-v2"}
        )

    assert result == expected
    args, kwargs = mock_request.call_args
    assert args[0] == "GET"
    assert args[1] == "/api/beta-gate/version/compare/"
    assert kwargs == {
        "params": {
            "version1": "balanced-v1",
            "version2": "balanced-v2",
        }
    }


def test_beta_gate_batch_evaluation_endpoint_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    payload = {
        "asset_codes": ["000001.SH", "000300.SH"],
        "asset_class": "equity",
        "current_regime": "Recovery",
        "regime_confidence": 0.6,
        "policy_level": 0,
        "risk_profile": "balanced",
    }
    expected = {
        "success": True,
        "config": {
            "config_id": "balanced-v1",
            "risk_profile": "balanced",
            "version": 1,
        },
        "query": payload,
        "results": [{"asset_code": "000001.SH", "passed": True}],
        "summary": {"total": 2, "passed": 2, "blocked": 0},
    }
    with patch.object(client, "_request", return_value=expected) as mock_request:
        result = client.beta_gate.test_gate(payload)

    assert result == expected
    args, kwargs = mock_request.call_args
    assert args[0] == "POST"
    assert args[1] == "/api/beta-gate/test/"
    assert kwargs == {"json": payload, "data": None}


def test_get_filter_health_endpoint_contract():
    from agomtradepro.modules.filter import FilterModuleDeprecationWarning

    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    expected = {
        "status": "healthy",
        "service": "Filter API",
        "filters_available": ["HP", "Kalman"],
    }
    with patch.object(client, "_request", return_value=expected) as mock_request:
        with pytest.warns(FilterModuleDeprecationWarning, match="2026-09-30"):
            result = client.filter.health()

    assert result == expected
    args, kwargs = mock_request.call_args
    assert args[0] == "GET"
    assert args[1] == "/api/filter/health/"
    assert kwargs == {"params": None}
