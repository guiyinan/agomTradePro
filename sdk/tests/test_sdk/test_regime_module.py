"""
Unit tests for AgomTradePro SDK Regime Module
"""

from datetime import date
from unittest.mock import patch

import pytest

from agomtradepro import AgomTradeProClient


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
        response = {
            "success": True,
            "snapshot": {
                "observed_at": "2024-01-01",
                "dominant_regime": "Recovery",
                "confidence": 0.81,
            },
            "warnings": [],
            "error": None,
            "raw_data": {
                "growth": [
                    {"date": "2023-12-01", "value": 49.8, "code": "CN_PMI"},
                    {"date": "2024-01-01", "value": 50.8, "code": "CN_PMI"},
                ],
                "inflation": [
                    {"date": "2023-12-01", "value": 2.2, "code": "CN_CPI_NATIONAL_YOY"},
                    {"date": "2024-01-01", "value": 2.1, "code": "CN_CPI_NATIONAL_YOY"},
                ],
            },
        }
        with patch.object(client, "_request", return_value=response) as mock_request:
            regime = client.regime.calculate(
                as_of_date=date(2024, 1, 1),
                growth_indicator="PMI",
                inflation_indicator="CPI",
                use_pit=True,
                data_source="akshare",
            )

            assert regime.dominant_regime == "Recovery"
            assert regime.growth_level == "up"
            assert regime.inflation_level == "down"
            assert regime.growth_value == 50.8
            assert regime.inflation_value == 2.1
            mock_request.assert_called_once_with(
                "POST",
                "/api/regime/calculate/",
                data=None,
                json={
                    "as_of_date": "2024-01-01",
                    "use_pit": True,
                    "growth_indicator": "PMI",
                    "inflation_indicator": "CPI",
                    "data_source": "akshare",
                },
            )

    def test_get_current_preserves_missing_observation_and_decision_block(self, client):
        response = {
            "dominant_regime": "Unknown",
            "observed_at": None,
            "must_not_use_for_decision": True,
            "blocked_reason": "regime_data_unavailable",
            "contract": {
                "is_stale": True,
                "must_not_use_for_decision": True,
            },
        }

        with patch.object(client, "_request", return_value=response):
            regime = client.regime.get_current()

        assert regime.observed_at is None
        assert regime.is_stale is True
        assert regime.must_not_use_for_decision is True
        assert regime.blocked_reason == "regime_data_unavailable"

    def test_calculate_snapshot_returns_canonical_envelope(self, client):
        response = {
            "success": True,
            "snapshot": {
                "observed_at": "2024-01-01",
                "dominant_regime": "Recovery",
            },
            "warnings": [],
            "error": None,
        }

        with patch.object(client, "_request", return_value=response) as mock_request:
            assert (
                client.regime.calculate_snapshot(
                    as_of_date=date(2024, 1, 1),
                    use_pit=False,
                    data_source="tushare",
                )
                == response
            )

        mock_request.assert_called_once_with(
            "POST",
            "/api/regime/calculate/",
            data=None,
            json={
                "as_of_date": "2024-01-01",
                "use_pit": False,
                "growth_indicator": "PMI",
                "inflation_indicator": "CPI",
                "data_source": "tushare",
            },
        )

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
            "success": True,
            "total": 4,
            "distribution": [
                {"dominant_regime": "Recovery", "count": 2, "percentage": 50.0},
                {"dominant_regime": "Overheat", "count": 1, "percentage": 25.0},
                {"dominant_regime": "Deflation", "count": 1, "percentage": 25.0},
            ],
        }

        with patch.object(client, "_request", return_value=mock_response) as mock_request:
            distribution = client.regime.get_regime_distribution(
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31),
            )

            assert distribution["Recovery"] == 2
            assert distribution["Overheat"] == 1
            assert distribution["Stagflation"] == 0
            assert distribution["Deflation"] == 1
            assert "Repression" not in distribution
            mock_request.assert_called_once_with(
                "GET",
                "/api/regime/distribution/",
                params={
                    "start_date": "2024-01-01",
                    "end_date": "2024-01-31",
                },
            )

    def test_get_regime_distribution_normalizes_legacy_repression(self, client):
        """Legacy stored labels remain readable through the canonical Deflation key."""
        mock_response = {
            "success": True,
            "total": 1,
            "distribution": [
                {"dominant_regime": "Repression", "count": 1, "percentage": 100.0},
            ],
        }

        with patch.object(client, "_request", return_value=mock_response):
            distribution = client.regime.get_regime_distribution()

        assert distribution["Deflation"] == 1
        assert "Repression" not in distribution

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
