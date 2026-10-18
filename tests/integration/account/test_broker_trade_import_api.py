import json
from datetime import date, datetime, timedelta
from decimal import Decimal

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
from apps.account.infrastructure.repositories import PortfolioApiRepository
from apps.decision_rhythm.infrastructure.models import DecisionExecutionLinkModel
from apps.simulated_trading.infrastructure.models import (
    LedgerMigrationMapModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)


def _csv_content(*, external_trade_id: str = "broker-1") -> str:
    return (
        "traded_at,action,asset_code,shares,price,external_trade_id,notes\n"
        f"2026-05-20T10:00:00+08:00,buy,000001.SZ,100,10.00,{external_trade_id},manual\n"
    )


@pytest.fixture
def classified_broker_asset() -> None:
    """Supply explicit classification required by a new actual position projection."""
    legacy_account_models.AssetMetadataModel.objects.create(
        asset_code="000001.SZ",
        name="Local classified broker asset",
        asset_class="equity",
        region="CN",
        cross_border="domestic",
    )


def _post_csv(
    client: APIClient,
    path: str,
    *,
    portfolio_id: int,
    content: str,
    transport: str,
    fields: dict[str, str] | None = None,
):
    data = {
        "portfolio_id": portfolio_id,
        "broker_name": "demo",
        **(fields or {}),
    }
    if transport == "tui-json":
        data["file"] = content
        return client.post(path, data, format="json")
    upload = SimpleUploadedFile(
        "broker_trades.csv",
        content.encode("utf-8"),
        content_type="text/csv",
    )
    data["file"] = upload
    return client.post(path, data, format="multipart")


def _preview_then_excluded_import(
    client: APIClient,
    import_path: str,
    *,
    portfolio_id: int,
    content: str,
    transport: str,
):
    preview_path = (
        "/api/account/tui/broker-trades/preview/"
        if transport == "tui-json"
        else "/api/account/broker-trades/preview/"
    )
    preview = _post_csv(
        client,
        preview_path,
        portfolio_id=portfolio_id,
        content=content,
        transport=transport,
    )
    assert preview.status_code == 200
    preview_data = preview.data
    if transport == "tui-json":
        continuation = preview_data.get("continuation")
        assert isinstance(continuation, dict)
        preview_context = continuation.get("input")
    else:
        preview_context = preview_data
    assert isinstance(preview_context, dict)
    fact_fingerprint = preview_context.get("expected_fact_set_fingerprint")
    balance_fingerprint = preview_context.get("expected_balance_fingerprint")
    assert isinstance(fact_fingerprint, str) and fact_fingerprint
    assert isinstance(balance_fingerprint, str) and balance_fingerprint
    return _post_csv(
        client,
        import_path,
        portfolio_id=portfolio_id,
        content=content,
        transport=transport,
        fields={
            "baseline_decision": "excluded",
            "expected_fact_set_fingerprint": fact_fingerprint,
            "expected_balance_fingerprint": balance_fingerprint,
        },
    )


def _preview_context(
    client: APIClient,
    *,
    portfolio_id: int,
    content: str,
    transport: str,
) -> dict[str, str]:
    """Return both private CAS tokens from the selected API preview surface."""

    preview_path = (
        "/api/account/tui/broker-trades/preview/"
        if transport == "tui-json"
        else "/api/account/broker-trades/preview/"
    )
    response = _post_csv(
        client,
        preview_path,
        portfolio_id=portfolio_id,
        content=content,
        transport=transport,
    )
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    if transport == "tui-json":
        continuation = response.data.get("continuation")
        assert isinstance(continuation, dict)
        context = continuation.get("input")
    else:
        context = response.data
    assert isinstance(context, dict)
    fact_fingerprint = context.get("expected_fact_set_fingerprint")
    balance_fingerprint = context.get("expected_balance_fingerprint")
    assert isinstance(fact_fingerprint, str) and fact_fingerprint
    assert isinstance(balance_fingerprint, str) and balance_fingerprint
    return {
        "expected_fact_set_fingerprint": fact_fingerprint,
        "expected_balance_fingerprint": balance_fingerprint,
    }


def _create_mapped_position(
    owner: User,
    portfolio: PortfolioModel,
) -> tuple[unified_trading_models.PositionModel, legacy_account_models.PositionModel]:
    """Create an exact mapped local position for broker reconciliation requests."""

    bridge = PortfolioApiRepository()
    account_id = bridge.ensure_real_account(portfolio)
    position = unified_trading_models.PositionModel.objects.create(
        account_id=account_id,
        asset_code="000001.SZ",
        asset_name="Local classified broker asset",
        asset_type="equity",
        quantity=Decimal("100"),
        available_quantity=Decimal("20"),
        available_quantity_known=False,
        avg_cost=Decimal("10"),
        total_cost=Decimal("1000"),
        current_price=Decimal("19"),
        market_value=Decimal("1900"),
        valuation_known=True,
        unrealized_pnl=Decimal("900"),
        unrealized_pnl_pct=90,
        first_buy_date=date(2020, 5, 19),
        first_buy_date_known=False,
        entry_reason="Local economic balance for broker reconciliation tests",
    )
    legacy_position = bridge.upsert_legacy_projection_from_unified(
        unified_position=position,
        portfolio=portfolio,
        asset_class="equity",
        region="CN",
        cross_border="domestic",
        source="manual",
    )
    assert legacy_position is not None
    assert owner.pk == portfolio.user_id
    return position, legacy_position


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
    return _post_csv(
        client,
        path,
        portfolio_id=portfolio_id,
        content=_csv_content(external_trade_id=external_trade_id),
        transport="multipart",
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
    assert {
        "reconciliation_error_code",
        "batch_summary_error_code",
        "balance_unavailable",
    } <= response.data.keys()
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
def test_tui_broker_import_preview_hides_digests_and_internal_row_fields():
    owner = _create_user("broker_tui_preview_owner")
    portfolio = PortfolioModel.objects.create(user=owner, name="Broker TUI Preview")
    client = APIClient()
    client.force_authenticate(owner)

    response = _post_csv(
        client,
        "/api/account/tui/broker-trades/preview/",
        portfolio_id=portfolio.id,
        content=_csv_content(),
        transport="tui-json",
    )

    assert response.status_code == 200
    assert "expected_fact_set_fingerprint" not in response.data
    assert "expected_balance_fingerprint" not in response.data
    continuation = response.data.get("continuation")
    assert isinstance(continuation, dict)
    continuation_input = continuation.get("input")
    assert isinstance(continuation_input, dict)
    assert continuation_input["expected_fact_set_fingerprint"]
    assert continuation_input["expected_balance_fingerprint"]
    rows = response.data["rows"]
    assert isinstance(rows, list) and rows
    assert all("broker_trade_key" not in row for row in rows)
    assert all("raw_payload" not in row for row in rows)
    assert rows[0]["status"] == "预览有效，待确认"
    assert rows[0]["fee_status"] == "佣金未知；印花税未知；过户费未知"


@pytest.mark.django_db
def test_broker_trade_import_writes_ledgers_batch_and_execution_link(classified_broker_asset):
    owner = _create_user("broker_import_owner")
    portfolio = PortfolioModel.objects.create(user=owner, name="Broker Import")
    client = APIClient()
    client.force_authenticate(owner)

    response = _preview_then_excluded_import(
        client,
        "/api/account/broker-trades/import/",
        portfolio_id=portfolio.id,
        content=_csv_content(),
        transport="multipart",
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
    ids=["multipart", "tui-json"],
)
@pytest.mark.django_db
def test_pending_broker_trade_import_saves_facts_without_preview_context(
    path: str,
    transport: str,
):
    owner = _create_user(f"broker_pending_without_preview_{transport}")
    portfolio = PortfolioModel.objects.create(user=owner, name="Broker Pending")
    client = APIClient()
    client.force_authenticate(owner)

    response = _post_csv(
        client,
        path,
        portfolio_id=portfolio.id,
        content=_csv_content(external_trade_id="pending-without-preview"),
        transport=transport,
        fields={"baseline_decision": "pending"},
    )

    assert response.status_code == 201
    assert response["Content-Type"].startswith("application/json")
    assert response.data["facts_saved_count"] == 1
    assert response.data["pending_fact_count"] == 1
    assert response.data["projected_fact_count"] == 0
    assert TransactionModel.objects.filter(
        portfolio=portfolio,
        external_trade_id="pending-without-preview",
    ).exists()


@pytest.mark.parametrize(
    ("path", "transport", "baseline_decision"),
    [
        ("/api/account/broker-trades/import/", "multipart", "included"),
        ("/api/account/broker-trades/import/", "multipart", "excluded"),
        ("/api/account/tui/broker-trades/import/", "tui-json", "included"),
        ("/api/account/tui/broker-trades/import/", "tui-json", "excluded"),
    ],
    ids=[
        "multipart-included",
        "multipart-excluded",
        "tui-json-included",
        "tui-json-excluded",
    ],
)
@pytest.mark.django_db
def test_included_or_excluded_import_still_requires_preview_context(
    path: str,
    transport: str,
    baseline_decision: str,
):
    owner = _create_user(f"broker_missing_context_{transport}_{baseline_decision}")
    portfolio = PortfolioModel.objects.create(user=owner, name="Broker Missing Context")
    client = APIClient()
    client.force_authenticate(owner)

    response = _post_csv(
        client,
        path,
        portfolio_id=portfolio.id,
        content=_csv_content(external_trade_id="requires-preview-context"),
        transport=transport,
        fields={"baseline_decision": baseline_decision},
    )

    assert response.status_code == 400
    assert not TransactionModel.objects.filter(
        portfolio=portfolio,
        external_trade_id="requires-preview-context",
    ).exists()


@pytest.mark.django_db
def test_broker_trade_import_defaults_to_facts_only_pending_reconciliation():
    owner = _create_user("broker_pending_owner")
    portfolio = PortfolioModel.objects.create(user=owner, name="Broker Pending")
    client = APIClient()
    client.force_authenticate(owner)

    response = _post_import(
        client,
        "/api/account/broker-trades/import/",
        portfolio_id=portfolio.id,
        external_trade_id="pending-fact",
    )

    assert response.status_code == 201
    assert response.data["facts_saved_count"] == 1
    assert response.data["pending_fact_count"] == 1
    assert response.data["projected_fact_count"] == 0
    assert TransactionModel.objects.filter(
        portfolio=portfolio,
        external_trade_id="pending-fact",
    ).exists()
    assert not SimulatedTradeModel.objects.filter(
        asset_code="000001.SZ",
        action="buy",
    ).exists()
    assert not unified_trading_models.PositionModel.objects.filter(
        asset_code="000001.SZ",
        quantity=100,
    ).exists()


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
    classified_broker_asset,
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
    response = _preview_then_excluded_import(
        client,
        path,
        portfolio_id=portfolio.id,
        content=content,
        transport=transport,
    )
    import_finished = timezone.now()

    if transport == "tui-json":
        rows = response.data["rows"]
        summary_row = rows[0]
        assert summary_row["row_number"] == "汇总"
        assert summary_row["display_type"] == "summary"
        assert summary_row["status"] == "导入汇总"
        assert "保存成交事实 1" in summary_row["summary"]
        assert "数量投影 1" in summary_row["summary"]
        assert "asset_code" not in summary_row
        assert response.data["already_in_baseline_count"] == 0
        assert "expected_fact_set_fingerprint" not in response.data
        assert "expected_balance_fingerprint" not in response.data
        assert all("broker_trade_key" not in row for row in rows)
        assert all("raw_payload" not in row for row in rows)
        fact_rows = rows[1:]
        assert all(isinstance(row.get("transaction_id"), int) for row in fact_rows)

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


@pytest.mark.parametrize(
    ("path", "transport"),
    [
        ("/api/account/broker-trades/import/", "multipart"),
        ("/api/account/tui/broker-trades/import/", "tui-json"),
    ],
    ids=["multipart", "tui-json"],
)
@pytest.mark.parametrize(
    ("conflict", "expected_code"),
    [
        ("fact-set", "BROKER_FACT_PREVIEW_CHANGED"),
        ("balance", "BROKER_BALANCE_PREVIEW_CHANGED"),
    ],
    ids=["fact-set-changed", "balance-changed"],
)
@pytest.mark.django_db
def test_broker_trade_cas_conflicts_keep_saved_fact_and_local_quantity(
    path: str,
    transport: str,
    conflict: str,
    expected_code: str,
    classified_broker_asset: None,
) -> None:
    """A stale preview returns JSON 409 while retaining the receipt and local book."""

    owner = _create_user(f"broker_cas_{transport}_{conflict}")
    portfolio = PortfolioModel.objects.create(user=owner, name="Broker CAS conflict")
    client = APIClient()
    client.force_authenticate(owner)
    position, legacy_position = _create_mapped_position(owner, portfolio)
    account_id = position.account_id
    preview_content = _csv_content(external_trade_id="cas-preview-key")
    context = _preview_context(
        client,
        portfolio_id=portfolio.pk,
        content=preview_content,
        transport=transport,
    )

    expected_quantity = Decimal("100")
    if conflict == "fact-set":
        # The submitted file differs economically from the reviewed file.
        content = _csv_content(external_trade_id="cas-confirmed-key")
        external_trade_id = "cas-confirmed-key"
    else:
        content = preview_content
        external_trade_id = "cas-preview-key"
        expected_quantity = Decimal("101")
        changed = unified_trading_models.PositionModel.objects.filter(pk=position.pk).update(
            quantity=expected_quantity,
            total_cost=Decimal("1010"),
            market_value=Decimal("1919"),
            unrealized_pnl=Decimal("909"),
        )
        legacy_changed = legacy_account_models.PositionModel.objects.filter(
            pk=legacy_position.pk
        ).update(shares=101)
        assert changed == 1
        assert legacy_changed == 1

    response = _post_csv(
        client,
        path,
        portfolio_id=portfolio.pk,
        content=content,
        transport=transport,
        fields={"baseline_decision": "excluded", **context},
    )

    assert response.status_code == 409
    assert response["Content-Type"].startswith("application/json")
    assert response.data["reconciliation_conflict_code"] == expected_code
    assert response.data["facts_saved_count"] == 1

    fact = TransactionModel.objects.get(
        portfolio=portfolio,
        external_trade_id=external_trade_id,
    )
    assert fact.broker_reconciliation_state == "projection_blocked"
    assert isinstance(fact.broker_reconciliation_details, dict)
    persisted_reason_code = fact.broker_reconciliation_details.get("last_reason_code")
    assert persisted_reason_code == expected_code
    assert fact.action == "buy"
    assert fact.asset_code == "000001.SZ"
    assert fact.shares == 100
    assert fact.external_trade_id == external_trade_id
    assert fact.broker_trade_key
    assert fact.price == Decimal("10.00")
    assert fact.notional == Decimal("1000.00")
    assert fact.commission == Decimal("0")
    assert fact.commission_known is False
    assert fact.slippage == Decimal("0")
    assert fact.slippage_known is False
    assert fact.stamp_duty == Decimal("0")
    assert fact.stamp_duty_known is False
    assert fact.transfer_fee == Decimal("0")
    assert fact.transfer_fee_known is False
    assert fact.raw_payload
    assert fact.raw_payload["external_trade_id"] == external_trade_id
    assert fact.raw_payload["traded_at"] == "2026-05-20T10:00:00+08:00"
    assert fact.raw_payload["shares"] == "100"
    assert fact.raw_payload["price"] == "10.00"
    assert fact.raw_payload["notes"] == "manual"
    assert "manual" in json.dumps(fact.raw_payload, ensure_ascii=False)
    assert fact.notes == "manual"
    assert timezone.is_aware(fact.traded_at)
    assert fact.traded_at == datetime.fromisoformat("2026-05-20T10:00:00+08:00")
    assert timezone.is_aware(fact.created_at)
    assert fact.created_at > fact.traded_at

    position.refresh_from_db()
    legacy_position.refresh_from_db()
    account = SimulatedAccountModel.objects.get(pk=account_id)
    assert position.quantity == expected_quantity
    assert legacy_position.shares == int(expected_quantity)
    assert account.current_cash == Decimal("0")
    assert SimulatedTradeModel.objects.filter(account_id=account_id).count() == 0

    assert response.data["projected_fact_count"] == 0
    assert response.data["projection_blocked_count"] == 1, (
        "Persisted fact is projection_blocked with reason "
        f"{persisted_reason_code!r}, but response counts are "
        f"pending={response.data.get('pending_fact_count')!r}, "
        f"blocked={response.data.get('projection_blocked_count')!r}."
    )
    assert response.data["pending_fact_count"] == 0

    rows = response.data["rows"]
    fact_rows = [
        row for row in rows if isinstance(row, dict) and row.get("transaction_id") == fact.pk
    ]
    assert len(fact_rows) == 1
    fact_receipt = fact_rows[0]
    if transport == "tui-json":
        # The TUI deliberately translates internal state/codes into display labels.
        assert fact_receipt["reconciliation_status"] == "持仓投影受阻"
        assert fact_receipt["projection_status"] == "持仓投影受阻"
        assert fact_receipt["status_reason"] == "待核对，原因尚未识别"
        assert "reconciliation_state" not in fact_receipt
        assert "reconciliation_reason_code" not in fact_receipt
        summary_row = rows[0]
        assert summary_row["display_type"] == "summary"
        assert "待核对 0" in summary_row["summary"]
        assert "受阻 1" in summary_row["summary"]
    else:
        assert fact_receipt["reconciliation_state"] == fact.broker_reconciliation_state
        assert fact_receipt["reconciliation_reason_code"] == persisted_reason_code


@pytest.mark.parametrize(
    ("path", "transport"),
    [
        ("/api/account/broker-trades/import/", "multipart"),
        ("/api/account/tui/broker-trades/import/", "tui-json"),
    ],
    ids=["multipart", "tui-json"],
)
@pytest.mark.django_db
def test_included_broker_trade_keeps_quantity_and_is_terminally_idempotent(
    path: str,
    transport: str,
    classified_broker_asset: None,
) -> None:
    """An included fill is recorded once and never adds a simulated mirror."""

    owner = _create_user(f"broker_included_{transport}")
    portfolio = PortfolioModel.objects.create(user=owner, name="Broker already included")
    client = APIClient()
    client.force_authenticate(owner)
    position, legacy_position = _create_mapped_position(owner, portfolio)
    account_id = position.account_id
    content = _csv_content(external_trade_id=f"included-{transport}")
    first_context = _preview_context(
        client,
        portfolio_id=portfolio.pk,
        content=content,
        transport=transport,
    )

    first_response = _post_csv(
        client,
        path,
        portfolio_id=portfolio.pk,
        content=content,
        transport=transport,
        fields={"baseline_decision": "included", **first_context},
    )
    assert first_response.status_code == 201
    assert first_response["Content-Type"].startswith("application/json")
    assert first_response.data["facts_saved_count"] == 1
    assert first_response.data["already_in_baseline_count"] == 1
    assert first_response.data["projected_fact_count"] == 0
    assert first_response.data["projection_blocked_count"] == 0

    fact = TransactionModel.objects.get(
        portfolio=portfolio,
        external_trade_id=f"included-{transport}",
    )
    assert fact.broker_reconciliation_state == "already_in_baseline"
    first_import_batch_id = fact.import_batch_id
    assert first_import_batch_id is not None
    position.refresh_from_db()
    legacy_position.refresh_from_db()
    account = SimulatedAccountModel.objects.get(pk=account_id)
    assert position.quantity == Decimal("100")
    assert legacy_position.shares == 100
    assert account.current_cash == Decimal("0")
    assert SimulatedTradeModel.objects.filter(account_id=account_id).count() == 0

    # Refresh the preview after the first fact is stored, then repeat the exact import.
    retry_context = _preview_context(
        client,
        portfolio_id=portfolio.pk,
        content=content,
        transport=transport,
    )
    retry_response = _post_csv(
        client,
        path,
        portfolio_id=portfolio.pk,
        content=content,
        transport=transport,
        fields={"baseline_decision": "included", **retry_context},
    )
    assert retry_response.status_code == 201
    assert retry_response["Content-Type"].startswith("application/json")
    assert retry_response.data["facts_saved_count"] == 0
    assert retry_response.data["duplicate_facts_reused_count"] == 1
    assert retry_response.data["already_in_baseline_count"] == 1
    assert retry_response.data["projected_fact_count"] == 0

    fact.refresh_from_db()
    position.refresh_from_db()
    legacy_position.refresh_from_db()
    assert TransactionModel.objects.filter(portfolio=portfolio).count() == 1
    assert fact.broker_reconciliation_state == "already_in_baseline"
    assert fact.import_batch_id == first_import_batch_id
    assert position.quantity == Decimal("100")
    assert legacy_position.shares == 100
    account = SimulatedAccountModel.objects.get(pk=account_id)
    assert account.current_cash == Decimal("0")
    assert SimulatedTradeModel.objects.filter(account_id=account_id).count() == 0
