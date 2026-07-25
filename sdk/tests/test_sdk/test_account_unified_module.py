from inspect import Parameter, signature
from unittest.mock import patch

from agomtradepro import AgomTradeProClient
from agomtradepro.modules.account import AccountModule


class TestAccountModuleUnifiedAliases:
    def test_create_trading_cost_config_requires_minimum_commission(self):
        parameter = signature(AccountModule.create_trading_cost_config).parameters["min_commission"]

        assert parameter.default is Parameter.empty

    def test_create_trading_cost_config_sends_explicit_minimum_commission(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")

        with patch.object(client, "post", return_value={"id": 8}) as mock_post:
            result = client.account.create_trading_cost_config(
                portfolio_id=3,
                min_commission=2.5,
            )

        assert result == {"id": 8}
        assert mock_post.call_args.kwargs["json"]["min_commission"] == 2.5

    def test_list_accounts_uses_unified_account_endpoint(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")

        with patch.object(
            client, "get", return_value={"accounts": [{"account_id": 1, "account_type": "real"}]}
        ) as mock_get:
            rows = client.account.list_accounts(account_type="real", active_only=True, limit=10)

        assert rows == [{"account_id": 1, "account_type": "real"}]
        mock_get.assert_called_once_with(
            "/api/account/accounts/",
            params={"active_only": True, "limit": 10, "account_type": "real"},
        )

    def test_get_account_uses_unified_account_detail_endpoint(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")

        with patch.object(
            client,
            "get",
            return_value={"account": {"account_id": 3, "account_type": "simulated"}},
        ) as mock_get:
            account = client.account.get_account(3)

        assert account == {"account_id": 3, "account_type": "simulated"}
        mock_get.assert_called_once_with("/api/account/accounts/3/")

    def test_get_account_positions_uses_unified_account_positions_endpoint(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")

        with patch.object(
            client,
            "get",
            return_value={
                "positions": [
                    {
                        "account_id": 3,
                        "asset_code": "510300.SH",
                    }
                ]
            },
        ) as mock_get:
            positions = client.account.get_account_positions(3)

        assert positions == [{"account_id": 3, "asset_code": "510300.SH"}]
        mock_get.assert_called_once_with("/api/account/accounts/3/positions/")

    def test_create_account_passes_account_type(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")

        with patch.object(
            client,
            "post",
            return_value={"account": {"account_id": 7, "account_type": "real"}},
        ) as mock_post:
            account = client.account.create_account(
                name="真实账户",
                initial_capital=100000,
                account_type="real",
            )

        assert account["account_type"] == "real"
        mock_post.assert_called_once()
        payload = mock_post.call_args.kwargs["json"]
        assert payload["account_type"] == "real"
        assert mock_post.call_args.args[0] == "/api/account/accounts/"

    def test_get_account_performance_uses_basic_endpoint_without_dates(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")

        with patch.object(
            client,
            "get",
            return_value={"performance": {"total_return": 0.05}},
        ) as mock_get:
            result = client.account.get_account_performance(account_id=3)

        assert result == {"total_return": 0.05}
        mock_get.assert_called_once_with("/api/account/accounts/3/performance/")

    def test_get_account_performance_uses_report_endpoint_when_dates_provided(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")

        with patch.object(client, "get", return_value={"returns": {"twr": 5.0}}) as mock_get:
            result = client.account.get_account_performance(
                account_id=3,
                start_date="2024-01-01",
                end_date="2024-01-31",
            )

        assert result["returns"]["twr"] == 5.0
        mock_get.assert_called_once_with(
            "/api/account/accounts/3/performance-report/",
            params={"start_date": "2024-01-01", "end_date": "2024-01-31"},
        )

    def test_preview_broker_trades_csv_uses_multipart_endpoint(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")
        csv_text = "traded_at,action,asset_code,shares,price\n2026-05-01,buy,600519.SH,100,1500\n"

        with patch.object(client, "post", return_value={"valid_rows": 1}) as mock_post:
            result = client.account.preview_broker_trades_csv(
                portfolio_id=9,
                csv_text=csv_text,
                broker_name="eastmoney",
            )

        assert result["valid_rows"] == 1
        mock_post.assert_called_once()
        assert mock_post.call_args.args[0] == "/api/account/broker-trades/preview/"
        assert mock_post.call_args.kwargs["data"] == {
            "portfolio_id": 9,
            "broker_name": "eastmoney",
        }
        filename, content = mock_post.call_args.kwargs["files"]["file"]
        assert filename == "broker_trades.csv"
        assert content == csv_text.encode("utf-8")

    def test_import_broker_trades_csv_uses_confirm_endpoint(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")

        with patch.object(client, "post", return_value={"created_rows": 1}) as mock_post:
            result = client.account.import_broker_trades_csv(
                portfolio_id=9,
                csv_text="traded_at,action,asset_code,shares,price\n2026-05-01,sell,600519.SH,100,1510\n",
            )

        assert result["created_rows"] == 1
        assert mock_post.call_args.args[0] == "/api/account/broker-trades/import/"

    def test_structured_broker_trades_use_canonical_csv_sdk_methods(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")
        trades = [
            {
                "traded_at": "2026-05-01T10:00:00+08:00",
                "action": "buy",
                "asset_code": "600519.SH",
                "shares": 100,
                "price": 1500,
                "external_trade_id": "trade-1",
            }
        ]

        with (
            patch.object(
                client.account,
                "preview_broker_trades_csv",
                return_value={"valid_rows": 1},
            ) as mock_preview,
            patch.object(
                client.account,
                "import_broker_trades_csv",
                return_value={"imported_rows": 1},
            ) as mock_import,
        ):
            preview = client.account.preview_broker_trades(
                portfolio_id=9,
                trades=trades,
                broker_name="eastmoney",
            )
            imported = client.account.import_broker_trades(
                portfolio_id=9,
                trades=trades,
                broker_name="eastmoney",
            )

        assert preview == {"valid_rows": 1}
        assert imported == {"imported_rows": 1}
        preview_kwargs = mock_preview.call_args.kwargs
        import_kwargs = mock_import.call_args.kwargs
        assert preview_kwargs["portfolio_id"] == 9
        assert preview_kwargs["broker_name"] == "eastmoney"
        assert preview_kwargs["filename"] == "broker_trades.structured.csv"
        assert "trade-1" in preview_kwargs["csv_text"]
        assert import_kwargs == preview_kwargs
