from unittest.mock import patch

from agomtradepro import AgomTradeProClient


class TestHedgeModuleReadContracts:
    def test_check_effectiveness_resolves_pair_then_calls_canonical_action(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")

        with (
            patch.object(
                client,
                "get",
                return_value={"results": [{"id": 2, "name": "股债对冲"}]},
            ) as mock_get,
            patch.object(
                client,
                "post",
                return_value={
                    "pair_name": "股债对冲",
                    "effectiveness": 0.82,
                    "rating": "优秀",
                    "recommendation": "维持当前配置",
                },
            ) as mock_post,
        ):
            result = client.hedge.check_effectiveness("股债对冲")

        assert result["effectiveness"] == 0.82
        mock_get.assert_called_once_with("/api/hedge/pairs/")
        mock_post.assert_called_once_with(
            "/api/hedge/pairs/2/check_effectiveness/",
            json={},
        )

    def test_get_correlation_matrix_uses_canonical_pure_calculation_endpoint(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")

        with patch.object(
            client,
            "post",
            return_value={
                "asset_codes": ["510300", "511260"],
                "window_days": 30,
                "matrix": {
                    "510300": {"510300": 1.0, "511260": -0.42},
                    "511260": {"510300": -0.42, "511260": 1.0},
                },
            },
        ) as mock_post:
            result = client.hedge.get_correlation_matrix(
                ["510300", "511260"],
                window_days=30,
            )

        assert result["matrix"]["510300"]["511260"] == -0.42
        mock_post.assert_called_once_with(
            "/api/hedge/actions/get_correlation_matrix/",
            json={
                "asset_codes": ["510300", "511260"],
                "window_days": 30,
            },
        )

    def test_get_all_pairs_uses_canonical_pair_catalog(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")

        with patch.object(
            client,
            "get",
            return_value={"results": [{"id": 2, "name": "股债对冲"}]},
        ) as mock_get:
            pairs = client.hedge.get_all_pairs()

        assert pairs == [{"id": 2, "name": "股债对冲"}]
        mock_get.assert_called_once_with("/api/hedge/pairs/")

    def test_get_pair_info_reads_from_canonical_pair_catalog(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")

        with patch.object(
            client,
            "get",
            return_value={
                "results": [
                    {
                        "id": 2,
                        "name": "股债对冲",
                        "hedge_method": "beta",
                    }
                ]
            },
        ) as mock_get:
            pair = client.hedge.get_pair_info("股债对冲")

        assert pair is not None
        assert pair["hedge_method"] == "beta"
        mock_get.assert_called_once_with("/api/hedge/pairs/")

    def test_get_alerts_uses_active_alert_endpoint(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")

        with patch.object(
            client,
            "get",
            return_value={"results": [{"id": 9, "severity": "warning"}]},
        ) as mock_get:
            alerts = client.hedge.get_alerts()

        assert alerts == [{"id": 9, "severity": "warning"}]
        mock_get.assert_called_once_with("/api/hedge/alerts/active/?days=7")

    def test_get_portfolio_state_uses_latest_snapshot_endpoint(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")

        with patch.object(
            client,
            "get",
            return_value={
                "results": [
                    {
                        "pair_name": "股债对冲",
                        "hedge_effectiveness": 0.72,
                    }
                ]
            },
        ) as mock_get:
            state = client.hedge.get_portfolio_state("股债对冲")

        assert state is not None
        assert state["hedge_effectiveness"] == 0.72
        mock_get.assert_called_once_with("/api/hedge/snapshots/latest/")
