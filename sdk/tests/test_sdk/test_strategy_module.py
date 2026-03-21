"""Unit tests for AgomTradePro SDK Strategy Module."""

from unittest.mock import patch

import pytest

from agomtradepro import AgomTradeProClient


class TestStrategyModule:
    """测试 StrategyModule 新增仓位管理接口。"""

    @pytest.fixture
    def client(self):
        return AgomTradeProClient(
            base_url="http://test.com",
            api_token="test_token",
        )

    def test_list_position_rules(self, client):
        mock_response = {"results": [{"id": 1, "name": "ATR Rule"}]}
        with patch.object(client, "_request", return_value=mock_response):
            result = client.strategy.list_position_rules(strategy_id=10, is_active=True, limit=20)
            assert len(result) == 1
            assert result[0]["id"] == 1

    def test_create_position_rule(self, client):
        mock_response = {"id": 1, "name": "RR2 Rule", "strategy": 10}
        with patch.object(client, "_request", return_value=mock_response):
            result = client.strategy.create_position_rule(
                strategy_id=10,
                name="RR2 Rule",
                buy_price_expr="support_price",
                sell_price_expr="resistance_price",
                stop_loss_expr="support_price - atr",
                take_profit_expr="support_price + 2 * atr",
                position_size_expr="(account_equity * 0.01) / abs(support_price - (support_price - atr))",
            )
            assert result["id"] == 1
            assert result["strategy"] == 10

    def test_evaluate_position_rule(self, client):
        mock_response = {
            "should_buy": True,
            "should_sell": False,
            "buy_price": 10.0,
            "sell_price": 12.0,
            "stop_loss_price": 9.0,
            "take_profit_price": 12.0,
            "position_size": 1000.0,
            "risk_reward_ratio": 2.0,
        }
        with patch.object(client, "_request", return_value=mock_response):
            result = client.strategy.evaluate_position_rule(
                rule_id=1,
                context={"current_price": 10.0, "account_equity": 100000.0},
            )
            assert result["should_buy"] is True
            assert result["risk_reward_ratio"] == 2.0

    def test_evaluate_strategy_position_management(self, client):
        mock_response = {"should_buy": False, "should_sell": True}
        with patch.object(client, "_request", return_value=mock_response):
            result = client.strategy.evaluate_strategy_position_management(
                strategy_id=99,
                context={"current_price": 13.0},
            )
            assert result["should_sell"] is True
