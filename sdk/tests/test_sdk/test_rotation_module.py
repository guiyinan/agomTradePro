from unittest.mock import patch

from agomtradepro import AgomTradeProClient


class TestRotationModuleReadContracts:
    def test_compare_assets_uses_canonical_pure_compute_endpoint(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")

        with patch.object(
            client,
            "post",
            return_value={
                "calc_date": "2026-07-11",
                "lookback_days": 60,
                "assets": {"510300": {"composite_score": 0.12}},
            },
        ) as mock_post:
            result = client.rotation.compare_assets(["510300", "511260"])

        assert result["assets"]["510300"]["composite_score"] == 0.12
        mock_post.assert_called_once_with(
            "/api/rotation/compare/",
            json={
                "asset_codes": ["510300", "511260"],
                "lookback_days": 60,
            },
        )

    def test_get_all_configs_uses_canonical_config_catalog(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")

        with patch.object(
            client,
            "get",
            return_value={
                "count": 1,
                "next": None,
                "previous": None,
                "results": [{"id": 3, "name": "动量轮动策略"}],
            },
        ) as mock_get:
            configs = client.rotation.get_all_configs()

        assert configs == [{"id": 3, "name": "动量轮动策略"}]
        mock_get.assert_called_once_with("/api/rotation/configs/")
