"""
Unit tests for AgomSAAF SDK Signal Module
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, patch

from agomsaaf import AgomSAAFClient
from agomsaaf.types import SignalStatus


class TestSignalModule:
    """测试 SignalModule"""

    @pytest.fixture
    def client(self):
        return AgomSAAFClient(
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

        with patch.object(client, "_request", return_value=mock_response):
            signals = client.signal.list(status="approved")

            assert len(signals) == 2
            assert signals[0].asset_code == "000001.SH"
            assert signals[0].status == "approved"

    def test_get_signal(self, client):
        """测试获取单个信号"""
        mock_response = {
            "id": 123,
            "asset_code": "000001.SH",
            "logic_desc": "Test signal",
            "status": "approved",
            "created_at": "2024-01-15T10:30:00Z",
            "invalidation_logic": "Test invalidation",
            "invalidation_threshold": 50.0,
            "approved_at": "2024-01-15T11:00:00Z",
        }

        with patch.object(client, "_request", return_value=mock_response):
            signal = client.signal.get(123)

            assert signal.id == 123
            assert signal.asset_code == "000001.SH"
            assert signal.status == "approved"

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

    def test_check_eligibility(self, client):
        """测试检查准入条件"""
        mock_response = {
            "is_eligible": True,
            "regime_match": True,
            "policy_match": True,
            "current_regime": "Recovery",
            "policy_status": "stimulus",
        }

        with patch.object(client, "_request", return_value=mock_response):
            result = client.signal.check_eligibility(
                asset_code="000001.SH",
                logic_desc="PMI rising",
            )

            assert result["is_eligible"] is True
            assert result["regime_match"] is True
