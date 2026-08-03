from unittest.mock import call, patch

from agomtradepro import AgomTradeProClient


class TestEquityModuleReadContracts:
    def test_get_stock_pool_uses_canonical_endpoint_and_returns_named_envelope(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")

        with patch.object(
            client,
            "get",
            return_value={
                "success": True,
                "regime": "Recovery",
                "update_time": "2026-07-11",
                "avg_roe": 12.5,
                "avg_pe": 18.0,
                "stocks": [
                    {"code": "000001.SZ", "sector": "银行", "score": 70},
                    {"code": "600000.SH", "sector": "银行", "score": 50},
                    {"code": "600519.SH", "sector": "白酒", "score": 90},
                ],
            },
        ) as mock_get:
            result = client.equity.get_stock_pool(
                sector="银行",
                min_score=60,
                limit=10,
            )

        assert result == {
            "success": True,
            "regime": "Recovery",
            "update_time": "2026-07-11",
            "avg_roe": 12.5,
            "avg_pe": 18.0,
            "stocks": [{"code": "000001.SZ", "sector": "银行", "score": 70}],
            "total_count": 1,
            "query": {
                "sector": "银行",
                "min_score": 60,
                "max_score": None,
                "limit": 10,
            },
        }
        mock_get.assert_called_once_with("/api/equity/pool/", params=None)

    def test_list_stocks_keeps_legacy_array_contract(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")

        with patch.object(
            client.equity,
            "get_stock_pool",
            return_value={
                "success": True,
                "stocks": [{"code": "000001.SZ"}],
            },
        ) as mock_pool:
            result = client.equity.list_stocks(sector="银行", min_score=60, limit=5)

        assert result == [{"code": "000001.SZ"}]
        mock_pool.assert_called_once_with(
            sector="银行",
            min_score=60,
            max_score=None,
            limit=5,
        )

    def test_equity_pool_propagates_publication_gate_parameters(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")

        with patch.object(
            client,
            "get",
            return_value={
                "success": False,
                "status": "blocked",
                "stocks": [],
                "publication_key": "current",
                "must_not_use_for_decision": True,
                "blocked_reason": "publication_observation_stale",
            },
        ) as mock_get:
            result = client.equity.get_stock_pool(
                mode="published",
                publication_key="current",
            )

        assert result["status"] == "blocked"
        assert result["must_not_use_for_decision"] is True
        mock_get.assert_called_once_with(
            "/api/equity/pool/",
            params={"mode": "published", "publication_key": "current"},
        )

    def test_get_valuation_uses_canonical_lookback_contract(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")

        with patch.object(
            client,
            "get",
            return_value={"success": True, "stock_code": "000001.SZ"},
        ) as mock_get:
            result = client.equity.get_valuation("000001.SZ", lookback_days=365)

        assert result["stock_code"] == "000001.SZ"
        mock_get.assert_called_once_with(
            "/api/equity/valuation/000001.SZ/",
            params={"lookback_days": 365},
        )

    def test_equity_module_propagates_publication_gate_parameters(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")

        with patch.object(
            client,
            "get",
            side_effect=[
                {"results": [{"period_type": "annual"}]},
                {"success": True, "stock_code": "000001.SZ"},
            ],
        ) as mock_get:
            financials = client.equity.get_financials(
                "000001.SZ",
                mode="published",
                publication_key="current",
            )
            valuation = client.equity.get_valuation(
                "000001.SZ",
                lookback_days=365,
                mode="published",
                publication_key="current",
            )

        assert financials == [{"period_type": "annual"}]
        assert valuation["stock_code"] == "000001.SZ"
        assert mock_get.call_args_list == [
            call(
                "/api/equity/financials/000001.SZ/",
                params={
                    "report_type": "annual",
                    "limit": 5,
                    "mode": "published",
                    "publication_key": "current",
                },
            ),
            call(
                "/api/equity/valuation/000001.SZ/",
                params={
                    "lookback_days": 365,
                    "mode": "published",
                    "publication_key": "current",
                },
            ),
        ]

    def test_financials_payload_preserves_blocked_publication_metadata(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")

        blocked_payload = {
            "stock_code": "000001.SZ",
            "report_type": "annual",
            "results": [],
            "count": 0,
            "status": "blocked",
            "publication_id": "equity-financials-2026-08-03",
            "must_not_use_for_decision": True,
            "blocked_reason": "publication_observation_stale",
        }
        with patch.object(client, "get", return_value=blocked_payload) as mock_get:
            result = client.equity.get_financials_payload(
                "000001.SZ",
                mode="published",
                publication_key="current",
            )

        assert result["results"] == []
        assert result["status"] == "blocked"
        assert result["must_not_use_for_decision"] is True
        assert result["blocked_reason"] == "publication_observation_stale"
        mock_get.assert_called_once_with(
            "/api/equity/financials/000001.SZ/",
            params={
                "report_type": "annual",
                "limit": 5,
                "mode": "published",
                "publication_key": "current",
            },
        )

    def test_recommendations_payload_preserves_blocked_publication_metadata(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")

        blocked_payload = {
            "success": False,
            "status": "blocked",
            "stock_codes": [],
            "items": [],
            "screening_criteria": {},
            "mode": "published",
            "publication_key": "current",
            "must_not_use_for_decision": True,
            "blocked_reason": "canonical_publication_missing",
        }
        with patch.object(client, "post", return_value=blocked_payload) as mock_post:
            result = client.equity.get_recommendations_payload(
                regime="Recovery",
                limit=10,
                mode="published",
                publication_key="current",
            )

        assert result["status"] == "blocked"
        assert result["must_not_use_for_decision"] is True
        assert result["blocked_reason"] == "canonical_publication_missing"
        mock_post.assert_called_once_with(
            "/api/equity/screen/",
            data=None,
            json={
                "max_count": 10,
                "regime": "Recovery",
                "mode": "published",
                "publication_key": "current",
            },
        )

    def test_score_and_analysis_propagate_publication_parameters(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")

        with (
            patch.object(
                client.equity,
                "get_stock_detail",
                return_value={
                    "success": True,
                    "stock_code": "000001.SZ",
                    "score": 88.0,
                    "status": "fresh",
                    "mode": "published",
                    "publication_key": "current",
                    "must_not_use_for_decision": False,
                },
            ) as mock_detail,
            patch.object(
                client.equity,
                "get_valuation",
                return_value={
                    "success": True,
                    "stock_code": "000001.SZ",
                    "status": "fresh",
                    "mode": "published",
                    "publication_key": "current",
                    "must_not_use_for_decision": False,
                },
            ) as mock_valuation,
        ):
            score = client.equity.get_stock_score(
                "000001.SZ",
                mode="published",
                publication_key="current",
            )
            analysis = client.equity.analyze_stock(
                "000001.SZ",
                mode="published",
                publication_key="current",
            )

        assert score["overall_score"] == 88.0
        assert score["must_not_use_for_decision"] is False
        assert analysis["valuation"]["status"] == "fresh"
        mock_detail.assert_any_call(
            "000001.SZ",
            mode="published",
            publication_key="current",
        )
        mock_valuation.assert_called_once_with(
            "000001.SZ",
            lookback_days=252,
            mode="published",
            publication_key="current",
        )

    def test_list_valuation_repairs_uses_snapshot_list_endpoint(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")

        with patch.object(
            client,
            "get",
            return_value={"success": True, "results": [{"stock_code": "000001.SZ"}]},
        ) as mock_get:
            result = client.equity.list_valuation_repairs(
                universe="all_active",
                phase="repairing",
                limit=20,
            )

        assert result["results"][0]["stock_code"] == "000001.SZ"
        mock_get.assert_called_once_with(
            "/api/equity/valuation-repair-list/",
            params={
                "universe": "all_active",
                "limit": 20,
                "phase": "repairing",
            },
        )

    def test_get_valuation_data_freshness_uses_canonical_endpoint(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")

        with patch.object(
            client,
            "get",
            return_value={"freshness_status": "fresh"},
        ) as mock_get:
            result = client.equity.get_valuation_data_freshness()

        assert result["freshness_status"] == "fresh"
        mock_get.assert_called_once_with(
            "/api/equity/valuation-data/freshness/",
            params=None,
        )

    def test_get_valuation_data_quality_latest_uses_canonical_endpoint(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")

        with patch.object(
            client,
            "get",
            return_value={"primary_source": "akshare"},
        ) as mock_get:
            result = client.equity.get_valuation_data_quality_latest()

        assert result["primary_source"] == "akshare"
        mock_get.assert_called_once_with(
            "/api/equity/valuation-data/quality-latest/",
            params=None,
        )

    def test_get_valuation_repair_status_uses_canonical_endpoint(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")

        with patch.object(
            client,
            "get",
            return_value={"stock_code": "000001.SZ", "phase": "repairing"},
        ) as mock_get:
            result = client.equity.get_valuation_repair_status(
                "000001.SZ",
                lookback_days=756,
            )

        assert result["phase"] == "repairing"
        mock_get.assert_called_once_with(
            "/api/equity/valuation-repair/000001.SZ/",
            params={"lookback_days": 756},
        )

    def test_get_valuation_repair_history_payload_preserves_provenance(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")
        payload = {
            "stock_code": "000001.SZ",
            "points": [{"trade_date": "2026-07-10", "composite_percentile": 0.3}],
            "data_quality_flag": "ok",
            "data_source_provider": "local_db",
            "data_as_of_date": "2026-07-10",
        }

        with patch.object(client, "get", return_value=payload) as mock_get:
            result = client.equity.get_valuation_repair_history_payload(
                "000001.SZ",
                lookback_days=252,
            )

        assert result == payload
        mock_get.assert_called_once_with(
            "/api/equity/valuation-repair/000001.SZ/history/",
            params={"lookback_days": 252},
        )

    def test_get_valuation_repair_config_uses_staff_active_endpoint(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")

        with patch.object(
            client,
            "get",
            return_value={
                "success": True,
                "source": "default",
                "data": {"version": 0, "target_percentile": 0.5},
            },
        ) as mock_get:
            result = client.equity.get_valuation_repair_config()

        assert result["version"] == 0
        mock_get.assert_called_once_with(
            "/api/equity/config/valuation-repair/active/",
            params=None,
        )

    def test_list_valuation_repair_configs_uses_local_limit(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")

        with patch.object(
            client,
            "get",
            return_value=[{"id": 1}, {"id": 2}],
        ) as mock_get:
            result = client.equity.list_valuation_repair_configs(limit=1)

        assert result == [{"id": 1}]
        mock_get.assert_called_once_with(
            "/api/equity/config/valuation-repair/",
            params=None,
        )

    def test_get_valuation_repair_config_by_id_uses_canonical_detail_endpoint(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")

        with patch.object(
            client,
            "get",
            return_value={"id": 7, "version": 3, "is_active": False},
        ) as mock_get:
            result = client.equity.get_valuation_repair_config_by_id(7)

        assert result["version"] == 3
        mock_get.assert_called_once_with(
            "/api/equity/config/valuation-repair/7/",
            params=None,
        )

    def test_activate_valuation_repair_config_uses_canonical_action_endpoint(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")

        with patch.object(
            client,
            "post",
            return_value={
                "success": True,
                "message": "配置 v3 已激活",
                "data": {"id": 7, "version": 3, "is_active": True},
            },
        ) as mock_post:
            result = client.equity.activate_valuation_repair_config(7)

        assert result["data"]["is_active"] is True
        mock_post.assert_called_once_with(
            "/api/equity/config/valuation-repair/7/activate/",
            data=None,
            json=None,
        )

    def test_create_valuation_repair_config_uses_canonical_staff_endpoint(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")

        with patch.object(
            client,
            "post",
            return_value={
                "id": 9,
                "version": 4,
                "is_active": False,
                "change_reason": "Governed threshold update.",
            },
        ) as mock_post:
            result = client.equity.create_valuation_repair_config(
                change_reason="Governed threshold update.",
                target_percentile=0.55,
            )

        assert result["version"] == 4
        assert result["is_active"] is False
        mock_post.assert_called_once_with(
            "/api/equity/config/valuation-repair/",
            data=None,
            json={
                "change_reason": "Governed threshold update.",
                "min_history_points": 120,
                "default_lookback_days": 756,
                "confirm_window": 20,
                "min_rebound": 0.05,
                "stall_window": 40,
                "stall_min_progress": 0.02,
                "target_percentile": 0.55,
                "undervalued_threshold": 0.20,
                "near_target_threshold": 0.45,
                "overvalued_threshold": 0.80,
                "pe_weight": 0.6,
                "pb_weight": 0.4,
                "confidence_base": 0.4,
                "confidence_sample_threshold": 252,
                "confidence_sample_bonus": 0.2,
                "confidence_blend_bonus": 0.15,
                "confidence_repair_start_bonus": 0.15,
                "confidence_not_stalled_bonus": 0.1,
                "repairing_threshold": 0.10,
                "eta_max_days": 999,
            },
        )
