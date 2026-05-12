"""
Unit tests for AgomTradePro SDK Regime Module
"""

from datetime import date
from unittest.mock import Mock, patch

import pytest

from agomtradepro import AgomTradeProClient
from agomtradepro.types import RegimeState, RegimeType


class TestRegimeModule:
    """测试 RegimeModule"""

    @pytest.fixture
    def client(self):
        return AgomTradeProClient(
            base_url="http://test.com",
            api_token="test_token",
        )

    def test_get_current(self, client, mock_regime_response):
        """测试获取当前象限"""
        with patch.object(client, "_request", return_value=mock_regime_response):
            regime = client.regime.get_current()

            assert regime.dominant_regime == "Recovery"
            assert regime.growth_level == "up"
            assert regime.inflation_level == "down"
            assert regime.growth_indicator == "PMI"
            assert regime.inflation_indicator == "CPI"
            assert regime.growth_value == 50.8
            assert regime.inflation_value == 2.1

    def test_calculate_regime(self, client, mock_regime_response):
        """测试计算指定日期象限"""
        with patch.object(client, "_request", return_value=mock_regime_response):
            regime = client.regime.calculate(
                as_of_date=date(2024, 1, 1),
                growth_indicator="PMI",
                inflation_indicator="CPI",
            )

            assert regime.dominant_regime == "Recovery"

    def test_get_regime_history(self, client):
        """测试获取象限历史"""
        mock_response = {
            "results": [
                {
                    "dominant_regime": "Recovery",
                    "observed_at": "2024-01-15",
                    "growth_level": "up",
                    "inflation_level": "down",
                },
                {
                    "dominant_regime": "Overheat",
                    "observed_at": "2024-01-14",
                    "growth_level": "up",
                    "inflation_level": "up",
                },
            ]
        }

        with patch.object(client, "_request", return_value=mock_response):
            history = client.regime.history(
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31),
                limit=100,
            )

            assert len(history) == 2
            assert history[0].dominant_regime == "Recovery"
            assert history[1].dominant_regime == "Overheat"

    def test_get_regime_distribution(self, client):
        """测试获取象限分布统计"""
        mock_response = {
            "results": [
                {"dominant_regime": "Recovery", "observed_at": "2024-01-01"},
                {"dominant_regime": "Recovery", "observed_at": "2024-01-02"},
                {"dominant_regime": "Overheat", "observed_at": "2024-01-03"},
            ]
        }

        with patch.object(client, "_request", return_value=mock_response):
            distribution = client.regime.get_regime_distribution(
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31),
            )

            assert distribution["Recovery"] == 2
            assert distribution["Overheat"] == 1
            assert distribution["Stagflation"] == 0
            assert distribution["Repression"] == 0

    def test_parse_regime_state_with_string_date(self):
        """测试解析包含字符串日期的响应"""
        from agomtradepro.modules.regime import RegimeModule

        data = {
            "dominant_regime": "Recovery",
            "observed_at": "2024-01-15",
            "growth_level": "up",
            "inflation_level": "down",
            "growth_indicator": "PMI",
            "inflation_indicator": "CPI",
        }

        client = AgomTradeProClient(
            base_url="http://test.com",
            api_token="test_token",
        )
        module = RegimeModule(client)
        regime = module._parse_regime_state(data)

        assert regime.observed_at == date(2024, 1, 15)
