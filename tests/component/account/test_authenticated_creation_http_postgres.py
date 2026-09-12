"""Actual Session/CSRF HTTP creation on the dedicated PostgreSQL database."""

from collections.abc import Iterator
from decimal import Decimal

import pytest
from django.db import connections
from django.test import Client, override_settings
from django.urls import path
from rest_framework.request import Request

from apps.simulated_trading.application.canonical_account_creation_input import (
    CanonicalAccountCreationInput,
)
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
from apps.simulated_trading.interface.views import AccountListAPIView
from core.integration import authenticated_canonical_account_creation as bridge
from core.integration.canonical_account_creation import CanonicalAccountCreationResult
from tests.component.account.creation_chain_postgres_fixture import CREATION_LEDGER_MODELS
from tests.component.account.test_account_actor_authority_raw_source_publisher_http import (
    _csrf_bootstrap,
    _csrf_token,
    _logged_in_client,
    _use_evid06_http_database,
)
from tests.component.account.test_account_actor_authority_raw_source_publisher_postgres import (
    _new_user,
)
from tests.unit.simulated_trading.test_creation_composition import _settings

pytest_plugins = (
    "tests.component.account.test_current_account_ownership_postgres",
    "tests.component.account.creation_chain_postgres_fixture",
)

urlpatterns = [
    path("csrf/", _csrf_bootstrap),
    path("api/account/accounts/", AccountListAPIView.as_view()),
    path("api/simulated-trading/accounts/", AccountListAPIView.as_view()),
]


def _reject_default(execute, sql, params, many, context):
    raise AssertionError("authenticated creation queried the default database")


@pytest.fixture
def creation_http_alias(
    creation_chain_alias: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[str]:
    """Change only the database and explicit configuration seams, keeping real auth."""

    import apps.simulated_trading.interface.views as views

    def create_on_test_alias(
        *, request: Request, parameters: CanonicalAccountCreationInput
    ) -> CanonicalAccountCreationResult:
        return bridge.create_authenticated_canonical_account(
            request=request,
            parameters=parameters,
            using=creation_chain_alias,
            environment="development",
        )

    monkeypatch.setattr(views, "create_authenticated_canonical_account", create_on_test_alias)
    monkeypatch.setattr(
        bridge, "get_active_account_creation_evidence_settings", lambda _: _settings()
    )
    with (
        _use_evid06_http_database(creation_chain_alias),
        override_settings(ROOT_URLCONF=__name__),
        connections["default"].execute_wrapper(_reject_default),
    ):
        yield creation_chain_alias


def _post(
    client: Client,
    csrf: str,
    *,
    key: str = "http-create-1",
    endpoint: str = "/api/account/accounts/",
    **changes: object,
):
    payload = {
        "account_name": "Growth Lab",
        "account_type": "simulated",
        "initial_capital": "250000.00",
        "max_position_pct": 25.0,
        "stop_loss_pct": 8.0,
        "commission_rate": 0.0002,
        "slippage_rate": 0.0008,
    }
    payload.update(changes)
    return client.post(
        endpoint,
        payload,
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
        HTTP_IDEMPOTENCY_KEY=key,
    )


def test_real_session_creates_and_replays_one_owned_graph(creation_http_alias: str) -> None:
    client, user, csrf = _logged_in_client(creation_http_alias)
    first = _post(client, csrf, endpoint="/api/simulated-trading/accounts/")
    assert first.status_code == 201, first.content
    assert first["Content-Type"].startswith("application/json")
    assert first.json()["replayed"] is False
    assert first.json()["success"] is True
    assert first.json()["account"]["account_name"] == "Growth Lab"
    assert first.json()["account"]["account_type"] == "simulated"
    replay = _post(client, csrf)
    assert replay.status_code == 200, replay.content
    assert replay.json()["replayed"] is True
    account_id = first.json()["account"]["account_id"]
    assert replay.json()["account"]["account_id"] == account_id
    row = SimulatedAccountModel.objects.using(creation_http_alias).get(pk=account_id)
    assert row.user_id == user.pk
    assert row.account_type == "simulated"
    assert row.initial_capital == Decimal("250000.00")
    assert row.max_position_pct == 25.0
    assert row.commission_rate == 0.0002
    assert row.auto_trading_enabled is True
    assert [m.objects.using(creation_http_alias).count() for m in CREATION_LEDGER_MODELS] == [
        1,
        1,
        1,
        1,
        1,
        1,
        0,
        1,
    ]
    assert _post(client, csrf, initial_capital="250001.00").status_code == 409
    assert _post(client, csrf, key="different-key").status_code == 409


def test_real_users_can_create_same_name_without_sharing_identity(creation_http_alias: str) -> None:
    first_client, first_user, csrf = _logged_in_client(creation_http_alias)
    assert _post(first_client, csrf, account_type="real").status_code == 201
    second_user, _ = _new_user(creation_http_alias, username="creation-other-user")
    client = Client(enforce_csrf_checks=True)
    assert client.login(username=second_user.username, password="evid06-test-password")
    second = _post(client, _csrf_token(client), account_type="real")
    assert second.status_code == 201, second.content
    assert second.json()["account"]["auto_trading_enabled"] is False
    assert second.json()["account"]["account_type"] == "real"
    rows = SimulatedAccountModel.objects.using(creation_http_alias).filter(
        account_name="Growth Lab"
    )
    assert set(rows.values_list("user_id", flat=True)) == {first_user.pk, second_user.pk}


def test_http_rejects_anonymous_csrf_and_client_identity_before_writes(
    creation_http_alias: str,
) -> None:
    anonymous = Client(enforce_csrf_checks=True)
    assert _post(anonymous, "").status_code in {401, 403}
    client, _, csrf = _logged_in_client(creation_http_alias)
    assert _post(client, "").status_code == 403
    assert _post(client, csrf, user_id=1).status_code == 400
    assert _post(client, csrf, key="").status_code == 400
    assert SimulatedAccountModel.objects.using(creation_http_alias).count() == 0
    assert all(m.objects.using(creation_http_alias).count() == 0 for m in CREATION_LEDGER_MODELS)


@pytest.mark.parametrize("same_owner", [True, False])
def test_legacy_account_name_conflict_remains_owner_scoped(
    creation_http_alias: str, same_owner: bool
) -> None:
    """Existing unsealed rows retain name isolation without gaining provenance."""
    client, user, csrf = _logged_in_client(creation_http_alias)
    existing_owner = user
    if not same_owner:
        existing_owner, _ = _new_user(creation_http_alias, username="legacy-other-owner")
    existing = SimulatedAccountModel.objects.using(creation_http_alias).create(
        user=existing_owner,
        account_name="Legacy Shared Name",
        account_type="real",
        initial_capital=Decimal("100000.00"),
        current_cash=Decimal("100000.00"),
        total_value=Decimal("100000.00"),
        auto_trading_enabled=False,
    )
    response = _post(
        client,
        csrf,
        account_name=existing.account_name,
        account_type="real",
        initial_capital="150000.00",
    )
    assert response["Content-Type"].startswith("application/json")
    if same_owner:
        assert response.status_code == 409, response.content
        assert SimulatedAccountModel.objects.using(creation_http_alias).count() == 1
        assert all(
            m.objects.using(creation_http_alias).count() == 0 for m in CREATION_LEDGER_MODELS
        )
    else:
        assert response.status_code == 201, response.content
        account = response.json()["account"]
        assert account["account_type"] == "real"
        assert account["auto_trading_enabled"] is False
        created = SimulatedAccountModel.objects.using(creation_http_alias).get(
            pk=account["account_id"]
        )
        assert created.user_id == user.pk
        assert created.pk != existing.pk
        assert created.initial_capital == Decimal("150000.00")
        assert SimulatedAccountModel.objects.using(creation_http_alias).count() == 2
