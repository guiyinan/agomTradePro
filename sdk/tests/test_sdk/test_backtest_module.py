"""
Unit tests for AgomSAAF SDK Backtest Module
"""

import pytest
from datetime import date
from unittest.mock import patch

from agomsaaf import AgomSAAFClient


class TestBacktestModule:
    """测试 BacktestModule"""

    @pytest.fixture
    def client(self):
        return AgomSAAFClient(
            base_url="http://test.com",
            api_token="test_token",
        )

    def test_run_backtest(self, client):
        """测试运行回测"""
        mock_response = {
            "id": 1,
            "status": "completed",
            "total_return": 0.25,
            "annual_return": 0.12,
            "max_drawdown": -0.15,
            "sharpe_ratio": 1.5,
        }

        with patch.object(client, "_request", return_value=mock_response):
            result = client.backtest.run(
                strategy_name="momentum",
                start_date=date(2023, 1, 1),
                end_date=date(2024, 12, 31),
                initial_capital=1000000.0,
            )

            assert result.id == 1
            assert result.total_return == 0.25
            assert result.annual_return == 0.12

    def test_get_result(self, client):
        """测试获取回测结果"""
        mock_response = {
            "id": 1,
            "status": "completed",
            "total_return": 0.25,
            "annual_return": 0.12,
            "max_drawdown": -0.15,
            "sharpe_ratio": 1.5,
        }

        with patch.object(client, "_request", return_value=mock_response):
            result = client.backtest.get_result(1)

            assert result.id == 1
            assert result.status == "completed"

    def test_list_backtests(self, client):
        """测试获取回测列表"""
        mock_response = {
            "results": [
                {
                    "id": 1,
                    "status": "completed",
                    "total_return": 0.25,
                    "annual_return": 0.12,
                    "max_drawdown": -0.15,
                },
                {
                    "id": 2,
                    "status": "running",
                    "total_return": 0.0,
                    "annual_return": 0.0,
                    "max_drawdown": 0.0,
                },
            ]
        }

        with patch.object(client, "_request", return_value=mock_response):
            results = client.backtest.list_backtests()

            assert len(results) == 2
            assert results[0].id == 1
            assert results[1].status == "running"

    def test_list_alias(self, client):
        """测试 list() 兼容别名"""
        mock_response = {
            "results": [
                {
                    "id": 1,
                    "status": "completed",
                    "total_return": 0.25,
                    "annual_return": 0.12,
                    "max_drawdown": -0.15,
                }
            ]
        }

        with patch.object(client, "_request", return_value=mock_response):
            results = client.backtest.list(limit=10)

            assert len(results) == 1
            assert results[0].id == 1

    def test_get_equity_curve(self, client):
        """测试获取净值曲线"""
        mock_response = {
            "curve": [
                {"date": "2023-01-01", "value": 1000000.0},
                {"date": "2023-01-02", "value": 1005000.0},
                {"date": "2023-01-03", "value": 1010000.0},
            ]
        }

        with patch.object(client, "_request", return_value=mock_response):
            curve = client.backtest.get_equity_curve(1)

            assert len(curve) == 3
            assert curve[0]["value"] == 1000000.0

    def test_delete_result(self, client):
        """测试删除回测结果"""
        with patch.object(client, "_request", return_value={"deleted": True}):
            client.backtest.delete_result(1)
            # Should not raise any exception
            assert True
