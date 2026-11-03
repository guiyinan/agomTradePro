"""Owner/delegated scope and alias contracts for read-only risk resource access."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.simulated_trading.infrastructure.performance_repositories import (
    DjangoObserverGrantRepository,
)
from apps.simulated_trading.infrastructure.portfolio_risk_resource_repository import (
    DjangoPortfolioRiskResourceRepository,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)
from core.integration.account_ledger import get_portfolio_observer_grant_model

pytestmark = pytest.mark.django_db


class _ValidGrant:
    """Small adapter result used to verify explicit database-alias routing."""

    def is_valid(self) -> bool:
        """Report a valid existing observer grant."""

        return True


class _GrantManager:
    """Record alias and authorization lookup arguments without touching a database."""

    def __init__(self) -> None:
        self.alias: str | None = None
        self.filters: dict[str, object] = {}

    def using(self, alias: str) -> _GrantManager:
        """Return this manager after retaining the selected alias."""

        self.alias = alias
        return self

    def get(self, **filters: object) -> _ValidGrant:
        """Return one valid test grant with the exact selected filters."""

        self.filters = filters
        return _ValidGrant()


class _GrantModel:
    """Minimal model facade with a manager compatible with the existing adapter."""

    _default_manager = _GrantManager()
    DoesNotExist = LookupError


def _make_account(owner: Any, *, name: str) -> SimulatedAccountModel:
    """Create a minimal active simulated account owned by one test user."""

    return SimulatedAccountModel._default_manager.create(
        user=owner,
        account_name=name,
        account_type="simulated",
        initial_capital=Decimal("1000"),
        current_cash=Decimal("1000"),
        total_value=Decimal("1000"),
    )


def _resource_reader() -> DjangoPortfolioRiskResourceRepository:
    """Use the existing grant adapter on the same default account database."""

    return DjangoPortfolioRiskResourceRepository(
        observer_grant_repository=DjangoObserverGrantRepository(using="default"),
        using="default",
    )


def test_observer_grant_repository_uses_the_injected_database_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The existing grant port routes reads to the caller-selected alias."""

    import apps.simulated_trading.infrastructure.performance_repositories as repositories

    manager = _GrantModel._default_manager
    monkeypatch.setattr(
        repositories,
        "get_portfolio_observer_grant_model",
        lambda: _GrantModel,
    )

    allowed = DjangoObserverGrantRepository(using="owner_archive").has_valid_grant(
        owner_user_id=17,
        observer_user_id=29,
    )

    assert allowed is True
    assert manager.alias == "owner_archive"
    assert manager.filters == {
        "owner_user_id": 17,
        "observer_user_id": 29,
        "status": "active",
    }


def test_owner_can_read_scope_without_loading_financial_balances() -> None:
    """Scope discovery selects only identity/state fields and performs no writes."""

    user_model = get_user_model()
    owner = user_model._default_manager.create_user(username="risk-scope-owner")
    account = _make_account(owner, name="risk-scope-owner-account")
    with CaptureQueriesContext(connection) as captured:
        scope = _resource_reader().read_account_scope(
            user_id=owner.pk,
            account_id=account.pk,
        )

    assert scope is not None
    assert scope.owner_user_id == owner.pk
    assert scope.can_read is True
    assert scope.can_write is True
    sql = "\n".join(item["sql"].upper() for item in captured.captured_queries)
    assert "CURRENT_CASH" not in sql
    assert "INITIAL_CAPITAL" not in sql
    assert not any(token in sql for token in ("INSERT ", "UPDATE ", "DELETE "))


def test_active_observer_grant_allows_read_only_scope() -> None:
    """An active observer grant grants read access without owner write access."""

    user_model = get_user_model()
    owner = user_model._default_manager.create_user(username="risk-scope-shared-owner")
    observer = user_model._default_manager.create_user(username="risk-scope-observer")
    account = _make_account(owner, name="risk-scope-shared-account")
    grant_model = get_portfolio_observer_grant_model()
    grant_model._default_manager.create(
        owner_user_id=owner,
        observer_user_id=observer,
        status="active",
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )

    scope = _resource_reader().read_account_scope(
        user_id=observer.pk,
        account_id=account.pk,
    )

    assert scope is not None
    assert scope.owner_user_id == owner.pk
    assert scope.can_read is True
    assert scope.can_write is False


def test_foreign_user_and_missing_account_have_the_same_scope_result() -> None:
    """Unauthorized callers cannot distinguish a foreign account from no account."""

    user_model = get_user_model()
    owner = user_model._default_manager.create_user(username="risk-scope-foreign-owner")
    foreign = user_model._default_manager.create_user(username="risk-scope-foreign-reader")
    account = _make_account(owner, name="risk-scope-foreign-account")
    reader = _resource_reader()

    foreign_scope = reader.read_account_scope(user_id=foreign.pk, account_id=account.pk)
    missing_scope = reader.read_account_scope(
        user_id=foreign.pk,
        account_id=account.pk + 100_000,
    )

    assert foreign_scope is None
    assert missing_scope is None
