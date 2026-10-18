import json
from datetime import datetime, timedelta

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

import apps.account.infrastructure.models as legacy_account_models
import apps.simulated_trading.infrastructure.models as unified_trading_models
from apps.account.infrastructure.models import (
    AccountProfileModel,
    BrokerTradeImportBatchModel,
    PortfolioModel,
    PortfolioObserverGrantModel,
    TransactionModel,
)
from apps.decision_rhythm.infrastructure.models import DecisionExecutionLinkModel
from apps.simulated_trading.infrastructure.models import (
    LedgerMigrationMapModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
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
        "legacy_positions": legacy_account_models.PositionModel.objects.count(),
        "accounts": SimulatedAccountModel.objects.count(),
        "mappings": LedgerMigrationMapModel.objects.count(),
        "positions": unified_trading_models.PositionModel.objects.count(),
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
        "legacy_positions": legacy_account_models.PositionModel.objects.count(),
        "accounts": SimulatedAccountModel.objects.count(),
        "mappings": LedgerMigrationMapModel.objects.count(),
        "positions": unified_trading_models.PositionModel.objects.count(),
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
        unified_trading_models.PositionModel.objects.filter(
            account_id=mapping.target_id,
            asset_code="000001.SZ",
            quantity=100,
        ).count()
        == 1
    )
    assert (
        legacy_account_models.PositionModel.objects.filter(
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


@pytest.mark.parametrize(
    ("path", "transport"),
    [
        ("/api/account/broker-trades/import/", "multipart"),
        ("/api/account/tui/broker-trades/import/", "tui-json"),
    ],
    ids=["multipart-broker-import", "tui-json-import"],
)
@pytest.mark.django_db
def test_broker_trade_import_api_preserves_aware_execution_instant(
    path: str,
    transport: str,
    record_property,
):
    owner = _create_user("broker_source_time_owner")
    portfolio = PortfolioModel.objects.create(user=owner, name="Broker Source Time")
    client = APIClient()
    client.force_authenticate(owner)

    source_text = "2020-05-20T10:00:00.123456+08:00"
    source_time = datetime.fromisoformat(source_text)
    content = (
        "traded_at,action,asset_code,shares,price,external_trade_id,notes\n"
        f"{source_text},buy,000001.SZ,100,10.00,source-time-api,manual\n"
    )
    import_started = timezone.now()
    if transport == "tui-json":
        response = client.post(
            path,
            {
                "portfolio_id": portfolio.id,
                "broker_name": "demo",
                "file": content,
            },
            format="json",
        )
    else:
        upload = SimpleUploadedFile(
            "source_time.csv",
            content.encode("utf-8"),
            content_type="text/csv",
        )
        response = client.post(
            path,
            {
                "portfolio_id": portfolio.id,
                "broker_name": "demo",
                "file": upload,
            },
            format="multipart",
        )
    import_finished = timezone.now()

    transaction = TransactionModel._default_manager.filter(
        portfolio=portfolio,
        external_trade_id="source-time-api",
    ).first()
    mapping = LedgerMigrationMapModel._default_manager.filter(
        source_app="account",
        source_table="portfolio",
        source_id=portfolio.id,
    ).first()
    trade = None
    if mapping is not None:
        trade = SimulatedTradeModel._default_manager.filter(
            account_id=mapping.target_id,
            asset_code="000001.SZ",
            action="buy",
        ).first()
    record_property(
        "broker_import_api_time_observations",
        json.dumps(
            {
                "response": {
                    "status_code": response.status_code,
                    "content_type": response.get("Content-Type"),
                    "imported_rows": (
                        response.data.get("imported_rows")
                        if isinstance(response.data, dict)
                        else None
                    ),
                },
                "source_action": "buy",
                "source_traded_at": source_time,
                "import_started": import_started,
                "import_finished": import_finished,
                "transaction": (
                    None
                    if transaction is None
                    else {
                        "action": transaction.action,
                        "traded_at": transaction.traded_at,
                        "created_at": transaction.created_at,
                    }
                ),
                "simulated_trade": (
                    None
                    if trade is None
                    else {
                        "action": trade.action,
                        "execution_time": trade.execution_time,
                        "created_at": trade.created_at,
                    }
                ),
            },
            default=str,
            sort_keys=True,
        ),
    )
    observed_execution_time = trade.execution_time if trade is not None else None
    assert observed_execution_time == source_time, (
        "broker API simulated mirror must retain the imported aware source "
        f"instant; observed {observed_execution_time!r}, expected {source_time!r}"
    )

    # Response, transaction, and created-at checks follow the intended RED.
    assert response.status_code == 201
    assert response["Content-Type"].startswith("application/json")
    assert response.data["imported_rows"] == 1
    assert source_time.utcoffset() == timedelta(hours=8)
    assert source_time.microsecond == 123456
    assert source_time < import_started
    assert transaction is not None
    assert mapping is not None
    assert trade is not None
    assert transaction.traded_at == source_time
    assert transaction.traded_at.microsecond == source_time.microsecond
    assert transaction.created_at > source_time
    assert import_started <= transaction.created_at <= import_finished
    assert trade.execution_time == source_time
    assert trade.execution_time.microsecond == source_time.microsecond
    assert trade.created_at > source_time
    assert import_started <= trade.created_at <= import_finished


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


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("filename", "content", "expected_message"),
    [
        ("trades.exe", b"not a trade file", "仅支持"),
        ("trades.csv", b"x" * (10 * 1024 * 1024 + 1), "10 MiB"),
    ],
    ids=["unsupported-extension", "oversized-file"],
)
def test_broker_trade_import_rejects_unsupported_or_oversized_files(
    filename: str,
    content: bytes,
    expected_message: str,
):
    owner = _create_user(f"invalid_file_{len(content)}")
    portfolio = PortfolioModel.objects.create(user=owner, name="Invalid Import")
    client = APIClient()
    client.force_authenticate(owner)
    upload = SimpleUploadedFile(filename, content)

    response = client.post(
        "/api/account/broker-trades/preview/",
        {
            "portfolio_id": portfolio.id,
            "broker_name": "demo",
            "file": upload,
        },
        format="multipart",
    )

    assert response.status_code == 400
    assert expected_message in str(response.data)
