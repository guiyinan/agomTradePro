import pytest
from django.contrib.auth import get_user_model

from apps.account.infrastructure.models import AccountProfileModel


@pytest.mark.django_db
def test_controlled_fixture_import_can_disable_user_provisioning(monkeypatch) -> None:
    monkeypatch.setenv("AGOMTRADEPRO_DISABLE_USER_PROVISIONING_SIGNALS", "1")

    user = get_user_model().objects.create_user(username="fixture_import_user")

    assert not AccountProfileModel._default_manager.filter(user=user).exists()
