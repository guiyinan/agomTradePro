"""
Unit tests for AgomTradePro SDK Signal Module
"""

from datetime import datetime
from unittest.mock import patch

import pytest

from agomtradepro import AgomTradeProClient
from agomtradepro.exceptions import ValidationError


class TestSignalModule:
    """测试 SignalModule"""

    @pytest.fixture
    def client(self):
        return AgomTradeProClient(
            base_url="http://test.com",
            api_token="test_token",
        )

    def test_list_signals(self, client):
        """测试获取信号列表"""
        mock_response = {
            "results": [
                {
                    "id": 1,
                    "asset_code": "000001.SH",
                    "logic_desc": "PMI rising",
                    "status": "approved",
                    "created_at": "2024-01-15T10:30:00Z",
                    "invalidation_logic": "PMI falls below 50",
                    "invalidation_threshold": 49.5,
                },
                {
                    "id": 2,
                    "asset_code": "000002.SZ",
                    "logic_desc": "CPI declining",
                    "status": "pending",
                    "created_at": "2024-01-15T11:00:00Z",
                    "invalidation_logic": None,
                    "invalidation_threshold": None,
                },
            ]
        }

        with patch.object(client, "_request", return_value=mock_response) as mocked:
            signals = client.signal.list(status="approved")

            assert len(signals) == 2
            assert signals[0].asset_code == "000001.SH"
            assert signals[0].status == "approved"
            mocked.assert_called_once_with(
                "GET",
                "/api/signal/",
                params={"limit": 50, "offset": 0, "status": "approved"},
            )

    @pytest.mark.parametrize(
        ("field", "value"),
        [("limit", 0), ("limit", 501), ("offset", -1), ("offset", 1_000_001)],
    )
    def test_list_signals_rejects_invalid_pagination_before_request(
        self,
        client,
        field,
        value,
    ):
        """分页边界在请求发出前失败，并保留稳定业务码。"""

        with patch.object(client, "_request") as mocked:
            with pytest.raises(ValidationError) as raised:
                client.signal.list(**{field: value})

        assert raised.value.code == "invalid_signal_list_query"
        mocked.assert_not_called()

    def test_list_signals_maps_empty_page_to_empty_list(self, client):
        """API 的空数组和空结果 envelope 都映射为空 SDK 列表。"""

        for response in ([], {"results": []}, {"signals": []}, {"data": []}):
            with patch.object(client, "_request", return_value=response):
                assert client.signal.list(limit=5, offset=10) == []

    def test_get_signal(self, client):
        """测试获取单个信号"""
        mock_response = {
            "id": 123,
            "asset_code": "000001.SH",
            "logic_desc": "Test signal",
            "status": "approved",
            "created_at": "2024-01-15T10:30:00Z",
            "invalidation_description": "Test invalidation",
            "invalidation_threshold": 50.0,
            "approved_at": "2024-01-15T11:00:00Z",
        }

        with patch.object(client, "_request", return_value=mock_response) as mocked:
            signal = client.signal.get(123)

            assert signal.id == 123
            assert signal.asset_code == "000001.SH"
            assert signal.status == "approved"
            assert signal.invalidation_logic == "Test invalidation"
            mocked.assert_called_once_with("GET", "/api/signal/123/", params=None)

    def test_create_signal(self, client):
        """测试创建信号"""
        mock_response = {
            "id": 124,
            "asset_code": "000001.SH",
            "logic_desc": "New signal",
            "status": "pending",
            "created_at": "2024-01-15T12:00:00Z",
            "invalidation_logic": "Test",
            "invalidation_threshold": 50.0,
        }

        with patch.object(client, "_request", return_value=mock_response):
            signal = client.signal.create(
                asset_code="000001.SH",
                logic_desc="New signal",
                invalidation_logic="Test",
                invalidation_threshold=50.0,
            )

            assert signal.id == 124
            assert signal.status == "pending"

    def test_approve_signal(self, client):
        """测试审批信号"""
        mock_response = {
            "id": 123,
            "asset_code": "000001.SH",
            "status": "approved",
            "approved_at": "2024-01-15T12:00:00Z",
        }

        with patch.object(client, "_request", return_value=mock_response):
            signal = client.signal.approve(123, approver="admin")

            assert signal.status == "approved"

    def test_parse_signal_with_sparse_payload(self, client):
        """测试兼容后端精简字段返回（有意兼容策略）"""
        mock_response = {
            "id": 125,
            "approved_at": "2024-01-15T12:00:00Z",
        }

        with patch.object(client, "_request", return_value=mock_response):
            signal = client.signal.get(125)

            assert signal.id == 125
            assert signal.asset_code == ""
            assert signal.logic_desc == ""
            assert signal.status == "pending"
            assert signal.created_at is None
            assert signal.approved_at == datetime.fromisoformat("2024-01-15T12:00:00+00:00")

    def test_check_eligibility(self, client):
        """测试检查准入条件"""
        mock_response = {
            "is_eligible": True,
            "regime_match": True,
            "policy_match": True,
            "current_regime": "Recovery",
            "policy_status": "stimulus",
        }

        with patch.object(client, "_request", return_value=mock_response) as mocked:
            result = client.signal.check_eligibility(
                asset_code="000001.SH",
                logic_desc="PMI rising",
            )

            assert result.is_eligible is True
            assert result.regime_match is True
            mocked.assert_called_once_with(
                "POST",
                "/api/signal/check_eligibility/",
                data=None,
                json={
                    "asset_code": "000001.SH",
                    "logic_desc": "PMI rising",
                },
            )
