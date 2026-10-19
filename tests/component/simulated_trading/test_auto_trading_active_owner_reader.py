"""Check that auto-trading owner reads stay inside active simulated accounts."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from apps.simulated_trading.infrastructure.account_repository import (
    DjangoSimulatedAccountRepository,
)
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("scope_exit", ("inactive", "real"))
def test_owner_reader_returns_none_after_account_leaves_active_simulated_scope(
    scope_exit: str,
) -> None:
    """A stale bridge owner read must not authorize a no-longer-scoped account."""

    user_model = get_user_model()
    suffix = uuid4().hex
    owner = user_model.objects.create_user(username=f"active-owner-{suffix}")
    account = SimulatedAccountModel.objects.create(
        user=owner,
        account_name=f"active-simulated-{suffix}",
        account_type="simulated",
        initial_capital=Decimal("10000.00"),
        current_cash=Decimal("10000.00"),
        current_market_value=Decimal("0.00"),
        total_value=Decimal("10000.00"),
        is_active=True,
    )
    repository = DjangoSimulatedAccountRepository()

    assert repository.get_owner_id(account_id=account.pk) == owner.pk

    if scope_exit == "inactive":
        account.is_active = False
        account.save(update_fields=("is_active",))
    else:
        account.account_type = "real"
        account.save(update_fields=("account_type",))

    account.refresh_from_db()
    assert account.is_active is (scope_exit != "inactive")
    assert account.account_type == ("real" if scope_exit == "real" else "simulated")
    assert repository.get_owner_id(account_id=account.pk) is None
