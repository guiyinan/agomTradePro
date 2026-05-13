from unittest.mock import patch

from agomtradepro import AgomTradeProClient


def test_config_center_snapshot_endpoint_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    with patch.object(client, "_request", return_value={"data": {"sections": []}}) as mock_request:
        client.config_center.get_snapshot()
        args, kwargs = mock_request.call_args
        assert args[0] == "GET"
        assert args[1] == "/api/system/config-center/"
        assert kwargs == {"params": None}


def test_config_capabilities_endpoint_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    with patch.object(client, "_request", return_value={"data": []}) as mock_request:
        client.config_center.list_capabilities()
        args, kwargs = mock_request.call_args
        assert args[0] == "GET"
        assert args[1] == "/api/system/config-capabilities/"
        assert kwargs == {"params": None}


def test_get_qlib_runtime_endpoint_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    with patch.object(client, "_request", return_value={"data": {"enabled": True}}) as mock_request:
        client.config_center.get_qlib_runtime()
        args, kwargs = mock_request.call_args
        assert args[0] == "GET"
        assert args[1] == "/api/system/config-center/qlib/runtime/"
        assert kwargs == {"params": None}


def test_update_qlib_runtime_endpoint_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    with patch.object(client, "_request", return_value={"data": {"enabled": True}}) as mock_request:
        client.config_center.update_qlib_runtime({"enabled": True})
        args, kwargs = mock_request.call_args
        assert args[0] == "POST"
        assert args[1] == "/api/system/config-center/qlib/runtime/"
        assert kwargs == {"data": None, "json": {"enabled": True}}


def test_list_qlib_training_profiles_endpoint_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    with patch.object(client, "_request", return_value={"data": []}) as mock_request:
        client.config_center.list_qlib_training_profiles()
        args, kwargs = mock_request.call_args
        assert args[0] == "GET"
        assert args[1] == "/api/system/config-center/qlib/training-profiles/"
        assert kwargs == {"params": None}


def test_save_qlib_training_profile_endpoint_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    payload = {"profile_key": "lgb_v1", "name": "LGB V1"}
    with patch.object(client, "_request", return_value={"data": payload}) as mock_request:
        client.config_center.save_qlib_training_profile(payload)
        args, kwargs = mock_request.call_args
        assert args[0] == "POST"
        assert args[1] == "/api/system/config-center/qlib/training-profiles/"
        assert kwargs == {"data": None, "json": payload}


def test_list_qlib_training_runs_endpoint_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    with patch.object(client, "_request", return_value={"data": []}) as mock_request:
        client.config_center.list_qlib_training_runs(limit=10)
        args, kwargs = mock_request.call_args
        assert args[0] == "GET"
        assert args[1] == "/api/system/config-center/qlib/training-runs/"
        assert kwargs == {"params": {"limit": 10}}


def test_get_qlib_training_run_detail_endpoint_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    with patch.object(client, "_request", return_value={"data": {"run_id": "abc"}}) as mock_request:
        client.config_center.get_qlib_training_run_detail("abc")
        args, kwargs = mock_request.call_args
        assert args[0] == "GET"
        assert args[1] == "/api/system/config-center/qlib/training-runs/abc/"
        assert kwargs == {"params": None}


def test_trigger_qlib_training_endpoint_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    payload = {"model_name": "lgb_csi300", "model_type": "LGBModel"}
    with patch.object(client, "_request", return_value={"data": {"run_id": "abc"}}) as mock_request:
        client.config_center.trigger_qlib_training(payload)
        args, kwargs = mock_request.call_args
        assert args[0] == "POST"
        assert args[1] == "/api/system/config-center/qlib/training-runs/trigger/"
        assert kwargs == {"data": None, "json": payload}
