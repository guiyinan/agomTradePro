from datetime import date
from types import SimpleNamespace

import pytest

from apps.rotation.application.interface_services import _user_accounts_for_context
from apps.rotation.infrastructure.repositories import RotationInterfaceRepository


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


@pytest.mark.django_db
def test_rotation_repository_rejects_non_numeric_relation_filters(django_user_model):
    """Invalid URL/query identifiers return empty results instead of ORM errors."""

    user = django_user_model.objects.create_user(username="rotation_filter_user")
    repository = RotationInterfaceRepository()

    assert repository.get_portfolio_config_for_account("not-an-id", user) is None
    assert (
        repository.list_recent_signal_rows(
            config_filter="not-an-id",
            cutoff_date=date.today(),
        )
        == []
    )
