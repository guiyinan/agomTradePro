from unittest.mock import patch

from agomtradepro import AgomTradeProClient


class TestAccountModuleUnifiedAliases:
    def test_list_accounts_uses_unified_account_endpoint(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="token")

        with patch.object(client, "get", return_value={"accounts": [{"account_id": 1, "account_type": "real"}]}) as mock_get:
            rows = client.account.list_accounts(account_type="real", active_only=True, limit=10)

        assert rows == [{"account_id": 1, "account_type": "real"}]
        mock_get.assert_called_once_with(
            "/api/account/accounts/",
            params={"active_only": True, "limit": 10, "account_type": "real"},
        )

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
