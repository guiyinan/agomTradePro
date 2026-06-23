import pytest

from apps.account.infrastructure.repositories import AccountInterfaceRepository
from apps.rotation.infrastructure.repositories import RotationInterfaceRepository
from apps.strategy.infrastructure.repositories import StrategyInterfaceRepository


@pytest.mark.django_db
def test_account_interface_querysets_use_stable_ordering(django_user_model):
    repo = AccountInterfaceRepository()
    user = django_user_model.objects.create_user(username="ordering_user", password="pass123")

    assert repo.get_asset_metadata_queryset().query.order_by == ("asset_code", "id")
    assert repo.get_trading_cost_config_queryset(user.id).query.order_by == ("portfolio_id", "id")


@pytest.mark.django_db
def test_strategy_interface_querysets_use_stable_ordering():
    repo = StrategyInterfaceRepository()

    assert repo.get_script_config_queryset().query.order_by == ("strategy_id", "id")
    assert repo.get_ai_strategy_config_queryset().query.order_by == ("strategy_id", "id")


@pytest.mark.django_db
def test_rotation_interface_querysets_use_stable_ordering(django_user_model):
    repo = RotationInterfaceRepository()
    user = django_user_model.objects.create_user(username="rotation_order_user", password="pass123")

    assert repo.portfolio_config_queryset_for_user(user).query.order_by == ("account_id", "id")
