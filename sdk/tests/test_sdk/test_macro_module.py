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
            "results": [
                {
                    "code": "PMI",
                    "name": "采购经理指数",
                    "unit": "指数",
                    "frequency": "monthly",
                    "data_source": "Tushare",
                },
                {
                    "code": "CPI",
                    "name": "消费者物价指数",
                    "unit": "%",
                    "frequency": "monthly",
                    "data_source": "AKShare",
                },
            ]
        }

        with patch.object(client, "_request", return_value=mock_response):
            indicators = client.macro.list_indicators()

            assert len(indicators) == 2
            assert indicators[0].code == "PMI"
            assert indicators[1].code == "CPI"

    def test_get_indicator(self, client):
        """测试获取指标详情"""
        mock_response = {
            "code": "PMI",
            "name": "采购经理指数",
            "unit": "指数",
            "frequency": "monthly",
            "data_source": "Tushare",
        }

        with patch.object(client, "_request", return_value=mock_response):
            indicator = client.macro.get_indicator("PMI")

            assert indicator.code == "PMI"
            assert indicator.name == "采购经理指数"

    def test_get_indicator_data(self, client):
        """测试获取指标数据"""
        mock_response = {
            "results": [
                {
                    "indicator_code": "PMI",
                    "date": "2024-01-31",
                    "value": 50.8,
                    "unit": "指数",
                },
                {
                    "indicator_code": "PMI",
                    "date": "2024-02-29",
                    "value": 51.2,
                    "unit": "指数",
                },
            ]
        }

        with patch.object(client, "_request", return_value=mock_response):
            data = client.macro.get_indicator_data("PMI")

            assert len(data) == 2
            assert data[0].value == 50.8

    def test_get_latest_data(self, client):
        """测试获取最新数据"""
        mock_response = {
            "results": [
                {
                    "indicator_code": "PMI",
                    "date": "2024-02-29",
                    "value": 51.2,
                    "unit": "指数",
                }
            ]
        }

        with patch.object(client, "_request", return_value=mock_response):
            latest = client.macro.get_latest_data("PMI")

            assert latest is not None
            assert latest.value == 51.2

    def test_sync_indicator(self, client):
        """测试同步指标"""
        mock_response = {
            "created": 5,
            "updated": 2,
            "skipped": 0,
        }

        with patch.object(client, "_request", return_value=mock_response):
            result = client.macro.sync_indicator("PMI", force=True)

            assert result["created"] == 5
