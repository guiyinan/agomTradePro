from unittest.mock import patch

from agomsaaf import AgomSAAFClient


def test_config_center_snapshot_endpoint_contract():
    client = AgomSAAFClient(base_url="http://test.com", api_token="token")
    with patch.object(client, "_request", return_value={"data": {"sections": []}}) as mock_request:
        client.config_center.get_snapshot()
        args, kwargs = mock_request.call_args
        assert args[0] == "GET"
        assert args[1] == "/api/system/config-center/"
        assert kwargs == {"params": None}


def test_config_capabilities_endpoint_contract():
    client = AgomSAAFClient(base_url="http://test.com", api_token="token")
    with patch.object(client, "_request", return_value={"data": []}) as mock_request:
        client.config_center.list_capabilities()
        args, kwargs = mock_request.call_args
        assert args[0] == "GET"
        assert args[1] == "/api/system/config-capabilities/"
        assert kwargs == {"params": None}
