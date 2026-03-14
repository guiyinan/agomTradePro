"""
Unit tests for AgomSAAF SDK Macro Module
"""

import pytest
from datetime import date
from unittest.mock import patch

from agomsaaf import AgomSAAFClient


class TestMacroModule:
    """测试 MacroModule"""

    @pytest.fixture
    def client(self):
        return AgomSAAFClient(
            base_url="http://test.com",
            api_token="test_token",
        )

    def test_list_indicators(self, client):
        """测试获取指标列表"""
        mock_response = {
            "indicators": [
                {
                    "code": "CN_PMI",
                    "name": "采购经理指数",
                },
                {
                    "code": "CN_CPI",
                    "name": "消费者物价指数",
                },
            ]
        }

        with patch.object(client, "_request", return_value=mock_response):
            indicators = client.macro.list_indicators()

            assert len(indicators) == 2
            assert indicators[0].code == "CN_PMI"
            assert indicators[1].code == "CN_CPI"

    def test_get_indicator(self, client):
        """测试获取指标详情"""
        mock_response = {"indicators": [{"code": "CN_PMI", "name": "采购经理指数"}]}

        with patch.object(client, "_request", return_value=mock_response):
            indicator = client.macro.get_indicator("PMI")

            assert indicator.code == "CN_PMI"
            assert indicator.name == "采购经理指数"

    def test_get_indicator_data(self, client):
        """测试获取指标数据"""
        mock_response = [
            {"date": "2024-01-31", "value": 50.8, "unit": "指数"},
            {"date": "2024-02-29", "value": 51.2, "unit": "指数"},
        ]

        with patch.object(client, "_request", return_value=mock_response):
            data = client.macro.get_indicator_data("PMI")

            assert len(data) == 2
            assert data[0].value == 50.8
            assert data[0].indicator_code == "CN_PMI"

    def test_get_latest_data(self, client):
        """测试获取最新数据"""
        mock_response = [{"date": "2024-02-29", "value": 51.2, "unit": "指数"}]

        with patch.object(client, "_request", return_value=mock_response):
            latest = client.macro.get_latest_data("PMI")

            assert latest is not None
            assert latest.value == 51.2

    def test_sync_indicator(self, client):
        """测试同步指标"""
        mock_response = {
            "success": True,
            "synced_count": 5,
        }

        with patch.object(client, "_request", return_value=mock_response):
            result = client.macro.sync_indicator("PMI", force=True)

            assert result["synced_count"] == 5
