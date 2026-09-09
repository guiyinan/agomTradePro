from unittest.mock import Mock, patch

import pytest

from apps.data_center.infrastructure.tushare_client import create_tushare_pro_client
from core.exceptions import DataFetchError


def client_with_payload(payload):
    session = Mock()
    session.headers = {}
    session.get.return_value.status_code = 200
    session.get.return_value.json.return_value = payload
    with patch(
        "apps.data_center.infrastructure.tushare_client._create_requests_session",
        return_value=session,
    ):
        client = create_tushare_pro_client(
            token="test-secret", http_url="http://example.test/tushare/", request_mode="rest_path"
        )
    return client, session


def test_rest_path_maps_names_and_keeps_key_out_of_query():
    client, session = client_with_payload(
        {"code": 0, "data": {"fields": ["trade_date", "adj_factor"], "items": [["20260908", 8.6]]}}
    )
    result = client.adj_factor(ts_code="600519.SH", fields="trade_date,adj_factor")
    assert result.iloc[0]["adj_factor"] == 8.6
    assert session.headers == {"X-API-Key": "test-secret"}
    session.get.assert_called_once_with(
        "http://example.test/tushare/adj-factor",
        params={"ts_code": "600519.SH", "fields": "trade_date,adj_factor"},
        timeout=30,
        allow_redirects=False,
    )
    assert session.trust_env is False


@pytest.mark.parametrize(
    "payload",
    [
        {"code": 0, "data": {"fields": ["a"], "items": [[1]], "has_more": True}},
        {"code": 0, "data": {"fields": ["a"], "items": [[1, 2]]}},
        {"code": 500, "msg": "private server text"},
    ],
)
def test_rest_path_rejects_incomplete_or_invalid_data(payload):
    client, _ = client_with_payload(payload)
    with pytest.raises(DataFetchError):
        client.daily()


@pytest.mark.parametrize("name", ["../daily", "daily?token=x", "https://other.test"])
def test_rest_path_rejects_path_injection(name):
    client, session = client_with_payload({})
    with pytest.raises(ValueError):
        client.query(name)
    session.get.assert_not_called()
