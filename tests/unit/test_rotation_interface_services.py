from types import SimpleNamespace

from apps.rotation.application.interface_services import _user_accounts_for_context


def test_user_accounts_for_context_uses_simulated_trading_query_service(monkeypatch):
    expected_accounts = [SimpleNamespace(account_id=1), SimpleNamespace(account_id=2)]
    monkeypatch.setattr(
        "apps.rotation.application.interface_services.list_active_account_models_for_user",
        lambda user_id: expected_accounts if user_id == 7 else [],
    )

    authenticated_user = SimpleNamespace(id=7, is_authenticated=True)
    anonymous_user = SimpleNamespace(id=0, is_authenticated=False)

    assert _user_accounts_for_context(authenticated_user) == expected_accounts
    assert _user_accounts_for_context(anonymous_user) == []
