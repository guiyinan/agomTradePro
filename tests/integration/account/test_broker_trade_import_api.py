import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.account.infrastructure.models import (
    AccountProfileModel,
    BrokerTradeImportBatchModel,
    PortfolioModel,
    PortfolioObserverGrantModel,
    TransactionModel,
)
from apps.account.infrastructure.models import PositionModel as LegacyPositionModel
from apps.decision_rhythm.infrastructure.models import DecisionExecutionLinkModel
from apps.simulated_trading.infrastructure.models import (
    LedgerMigrationMapModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.models import (
    PositionModel as UnifiedPositionModel,
)


def _csv_upload(*, external_trade_id: str = "broker-1") -> SimpleUploadedFile:
    content = (
        "traded_at,action,asset_code,shares,price,external_trade_id,notes\n"
        f"2026-05-20T10:00:00+08:00,buy,000001.SZ,100,10.00,{external_trade_id},manual\n"
    )
    return SimpleUploadedFile(
        "broker_trades.csv",
        content.encode("utf-8"),
        content_type="text/csv",
    )


def _create_user(username: str, *, role: str = "owner") -> User:
    user = User.objects.create_user(username=username, password="pass12345")
    AccountProfileModel.objects.update_or_create(
        user=user,
        defaults={
            "display_name": username,
            "rbac_role": role,
        },
    )
    return user


def _post_import(
    client: APIClient,
    path: str,
    *,
    portfolio_id: int,
    external_trade_id: str = "broker-1",
):
    return client.post(
        path,
        {
            "portfolio_id": portfolio_id,
            "broker_name": "demo",
            "file": _csv_upload(external_trade_id=external_trade_id),
        },
        format="multipart",
    )


@pytest.mark.django_db
def test_broker_trade_preview_is_owner_scoped_and_pure_read():
    owner = _create_user("broker_preview_owner")
    portfolio = PortfolioModel.objects.create(user=owner, name="Broker Preview")
    client = APIClient()
    client.force_authenticate(owner)
    before = {
        "batches": BrokerTradeImportBatchModel.objects.count(),
        "transactions": TransactionModel.objects.count(),
        "legacy_positions": LegacyPositionModel.objects.count(),
        "accounts": SimulatedAccountModel.objects.count(),
        "mappings": LedgerMigrationMapModel.objects.count(),
        "positions": UnifiedPositionModel.objects.count(),
        "trades": SimulatedTradeModel.objects.count(),
        "links": DecisionExecutionLinkModel.objects.count(),
    }

    response = _post_import(
        client,
        "/api/account/broker-trades/preview/",
        portfolio_id=portfolio.id,
    )

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert response.data["valid_rows"] == 1
    assert response.data["duplicate_rows"] == 0
    after = {
        "batches": BrokerTradeImportBatchModel.objects.count(),
        "transactions": TransactionModel.objects.count(),
        "legacy_positions": LegacyPositionModel.objects.count(),
        "accounts": SimulatedAccountModel.objects.count(),
        "mappings": LedgerMigrationMapModel.objects.count(),
        "positions": UnifiedPositionModel.objects.count(),
        "trades": SimulatedTradeModel.objects.count(),
        "links": DecisionExecutionLinkModel.objects.count(),
    }
    assert after == before


@pytest.mark.django_db
def test_broker_trade_import_writes_ledgers_batch_and_execution_link():
    owner = _create_user("broker_import_owner")
    portfolio = PortfolioModel.objects.create(user=owner, name="Broker Import")
    client = APIClient()
    client.force_authenticate(owner)

    response = _post_import(
        client,
        "/api/account/broker-trades/import/",
        portfolio_id=portfolio.id,
    )

    assert response.status_code == 201
    assert response["Content-Type"].startswith("application/json")
    assert response.data["imported_rows"] == 1
    assert response.data["skipped_rows"] == 0
    assert (
        BrokerTradeImportBatchModel.objects.filter(
            user=owner,
            portfolio=portfolio,
            status="completed",
        ).count()
        == 1
    )
    transaction = TransactionModel.objects.get(
        portfolio=portfolio,
        external_trade_id="broker-1",
    )
    mapping = LedgerMigrationMapModel.objects.get(
        source_app="account",
        source_table="portfolio",
        source_id=portfolio.id,
    )
    assert (
        SimulatedAccountModel.objects.filter(
            id=mapping.target_id,
            user=owner,
            account_type="real",
        ).count()
        == 1
    )
    assert (
        UnifiedPositionModel.objects.filter(
            account_id=mapping.target_id,
            asset_code="000001.SZ",
            quantity=100,
        ).count()
        == 1
    )
    assert (
        LegacyPositionModel.objects.filter(
            portfolio=portfolio,
            asset_code="000001.SZ",
            shares=100,
            is_closed=False,
        ).count()
        == 1
    )
    assert (
        SimulatedTradeModel.objects.filter(
            account_id=mapping.target_id,
            asset_code="000001.SZ",
            action="buy",
        ).count()
        == 1
    )
    assert (
        DecisionExecutionLinkModel.objects.filter(
            transaction_id=transaction.id,
            match_method="manual_only",
        ).count()
        == 1
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path",
    (
        "/api/account/broker-trades/preview/",
        "/api/account/broker-trades/import/",
    ),
)
def test_broker_trade_import_rejects_cross_user_and_observer(path: str):
    owner = _create_user("broker_scope_owner")
    other = _create_user("broker_scope_other", role="trader")
    observer = _create_user("broker_scope_observer", role="trader")
    portfolio = PortfolioModel.objects.create(user=owner, name="Broker Scope")
    PortfolioObserverGrantModel.objects.create(
        owner_user_id=owner,
        observer_user_id=observer,
        created_by=owner,
    )

    for user, external_trade_id in (
        (other, "cross-user"),
        (observer, "observer"),
    ):
        client = APIClient()
        client.force_authenticate(user)
        response = _post_import(
            client,
            path,
            portfolio_id=portfolio.id,
            external_trade_id=external_trade_id,
        )
        assert response.status_code == 403

    assert BrokerTradeImportBatchModel.objects.count() == 0
    assert TransactionModel.objects.count() == 0
