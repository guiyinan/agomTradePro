"""Owner-route integration coverage for the M1 published-close preview."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from importlib import import_module
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import DEFAULT_DB_ALIAS
from django.utils import timezone
from rest_framework.test import APIClient

from apps.data_center.application.public_published_queries import get_published_price_bar_series
from apps.data_center.application.publication_sync import PublishPriceBarBatchUseCase
from apps.data_center.domain.entities import PriceBar
from apps.data_center.domain.enums import PriceAdjustment
from apps.data_center.infrastructure.control_plane_repositories import (
    CanonicalPublicationRepository,
)
from apps.data_center.infrastructure.models import PriceBarModel
from apps.data_center.infrastructure.price_bar_repository import PriceBarRepository
from apps.data_center.infrastructure.publication_policy_repository import (
    PublicationPolicyRepository,
)
from apps.data_center.infrastructure.publication_rollback_models import (
    CanonicalPublicationPointerModel,
    PublicationMemberModel,
)
from apps.simulated_trading.application.rebalance_plan_preview import (
    ReadOnlyRebalancePlanPreviewBuilder,
)
from apps.simulated_trading.infrastructure.models import (
    DailyInspectionReportModel,
    RebalanceProposalModel,
)
from apps.simulated_trading.infrastructure.published_close_price_reader import (
    M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
    PublishedClosePriceReader,
)
from apps.simulated_trading.infrastructure.rebalance_resource_snapshot_repository import (
    DjangoRebalanceResourceSnapshotRepository,
)
from apps.simulated_trading.m1_risk_policy_composition import (
    build_strategy_m1_risk_source_reader,
)
from apps.strategy.application.execution_gateway import get_strategy_execution_gateway
from tests.component.data_center.test_audited_price_sync_transaction import _seed_contracts
from tests.integration.simulated_trading.test_readonly_rebalance_plan_owner_api import (
    ASSET_BUY,
    _assert_no_financial_writes,
    _create_owner_account,
    _financial_snapshot,
    _FixtureClassificationReader,
    _install_preview_ports,
    _publish_m1_policy_for_preview,
)

pytestmark = pytest.mark.django_db

_SESSION = date(2026, 10, 26)
_CLOSE_UTC = datetime(2026, 10, 26, 7, 0, tzinfo=UTC)
_PUBLISHED_AT = _CLOSE_UTC + timedelta(hours=1)
_CUTOFF = _PUBLISHED_AT
_PRICE = 10.0


def _install_session_clock(monkeypatch: pytest.MonkeyPatch, session: date = _SESSION) -> None:
    """Use one explicit test session while retaining the real price publication gate."""

    close_at = datetime.combine(session, datetime.min.time(), tzinfo=UTC) + timedelta(hours=7)

    def latest_completed(now: datetime) -> date | None:
        if now.tzinfo is None or now.utcoffset() is None or now < close_at:
            return None
        return session

    monkeypatch.setattr(timezone, "now", lambda: _CUTOFF)
    monkeypatch.setattr(
        "apps.simulated_trading.infrastructure.published_close_price_reader.latest_completed_cn_market_session",
        latest_completed,
    )
    monkeypatch.setattr(
        "apps.data_center.application.query_services.latest_completed_cn_market_session",
        latest_completed,
    )
    monkeypatch.setattr(
        "apps.data_center.application.query_use_cases.latest_completed_cn_market_session",
        latest_completed,
    )


def _publish_reference_bar(*, asset_code: str = ASSET_BUY, bar_date: date = _SESSION) -> str:
    """Persist and publish one real price-bar member under the fixed M1 lane."""

    _seed_contracts()
    bar = PriceBar(
        asset_code=asset_code,
        bar_date=bar_date,
        open=_PRICE,
        high=_PRICE,
        low=_PRICE,
        close=_PRICE,
        freq="1d",
        adjustment=PriceAdjustment.NONE,
        volume=1000.0,
        amount=10000.0,
        source="fixture:published-close-owner-api",
        fetched_at=_PUBLISHED_AT,
    )
    repository = PriceBarRepository()
    assert repository.bulk_upsert([bar]) == 1
    publisher = PublishPriceBarBatchUseCase(
        fact_repository=repository,
        publication_repository=CanonicalPublicationRepository(),
        policy_repository=PublicationPolicyRepository(),
    )
    publication = publisher.execute(
        [bar],
        provider_name=bar.source,
        publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
        run_id=str(uuid4()),
        published_at=_PUBLISHED_AT,
    )
    assert publication is not None
    # Mirror the established public-query fixture: persisted candidates become
    # readable only after an explicit current-pointer fixture exists.
    CanonicalPublicationPointerModel.objects.create(
        dataset_key="equity.price.bar",
        publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
        publication_id=publication.publication_id,
        publication_hash=publication.publication_hash,
        activation_id=f"fixture:{publication.publication_id}",
    )
    return publication.publication_id


def _install_published_close_builder(
    monkeypatch: pytest.MonkeyPatch,
    *,
    account: object,
    user_id: int,
) -> object:
    """Reuse typed identity/fee/rule fixtures and the real close publication reader."""

    market_reader, identity_reader, fee_reader, quantity_reader = _install_preview_ports(
        monkeypatch,
        account=account,
        user_id=user_id,
        classification_asset_types={ASSET_BUY: "equity"},
    )
    classification_reader = _FixtureClassificationReader(
        identity_reader=identity_reader,
        asset_types={ASSET_BUY: "equity"},
        missing_codes=frozenset(),
    )
    from apps.risk_center.m1_rebalance_risk_policy_composition import (
        build_m1_risk_policy_application,
    )
    from apps.simulated_trading.infrastructure.m1_risk_policy_account_source_reader import (
        DjangoM1RiskPolicyAccountSourceReader,
    )

    builder = ReadOnlyRebalancePlanPreviewBuilder(
        price_reader=market_reader,
        identity_reader=identity_reader,
        classification_reader=classification_reader,
        fee_policy_reader=fee_reader,
        quantity_rule_reader=quantity_reader,
        resource_snapshot_reader=DjangoRebalanceResourceSnapshotRepository(using=DEFAULT_DB_ALIAS),
        position_rule_evaluator=get_strategy_execution_gateway(),
        risk_policy_qualifier=build_m1_risk_policy_application(using=DEFAULT_DB_ALIAS).qualify,
        risk_policy_account_source_reader=DjangoM1RiskPolicyAccountSourceReader(
            using=DEFAULT_DB_ALIAS
        ),
        strategy_risk_source_reader=build_strategy_m1_risk_source_reader(),
        reference_close_reader=PublishedClosePriceReader(),
        reference_price_basis="published_close",
    )

    def factory(*, reference_price_basis: str = "market") -> ReadOnlyRebalancePlanPreviewBuilder:
        assert reference_price_basis == "published_close"
        return builder

    for module_name in (
        "apps.simulated_trading.rebalance_plan_preview_composition",
        "apps.simulated_trading.application.interface_services",
        "apps.simulated_trading.application.daily_inspection_service",
    ):
        module = import_module(module_name)
        if hasattr(module, "build_readonly_rebalance_plan_preview_builder"):
            monkeypatch.setattr(
                module,
                "build_readonly_rebalance_plan_preview_builder",
                factory,
            )
    return market_reader


def _post_published_close_inspection(
    *,
    client: APIClient,
    account_id: int,
    auto_create_proposal: bool = False,
) -> object:
    """Exercise the real owner inspection view with one explicit 10% target."""

    return client.post(
        f"/api/account/accounts/{account_id}/inspections/run/",
        {
            "inspection_date": _SESSION.isoformat(),
            "temporary_target_weights": f"{ASSET_BUY},10",
            "reference_price_basis": "published_close",
            "auto_create_proposal": auto_create_proposal,
        },
        format="json",
    )


def test_owner_published_close_preview_reads_member_and_preserves_financial_ledgers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The full owner route prices one temporary target from its exact published member."""

    _install_session_clock(monkeypatch)
    user, account = _create_owner_account(
        username="m1-published-close-owner",
        positions=(),
        cash=Decimal("100000.00"),
        max_position_pct=100.0,
        max_total_position_pct=100.0,
    )
    assert user.is_staff is False
    _install_published_close_builder(monkeypatch, account=account, user_id=user.pk)
    publication_id = _publish_reference_bar()

    # A same-session row outside the selected publication must not replace its member.
    decoy = PriceBar(
        asset_code=ASSET_BUY,
        bar_date=_SESSION,
        open=99.0,
        high=99.0,
        low=99.0,
        close=99.0,
        freq="1d",
        adjustment=PriceAdjustment.NONE,
        volume=1000.0,
        amount=99000.0,
        source="fixture:unpublished-decoy",
        fetched_at=_CUTOFF,
    )
    assert PriceBarRepository().bulk_upsert([decoy]) == 1
    published = get_published_price_bar_series(
        ASSET_BUY,
        publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
        start=_SESSION,
        end=_SESSION,
        knowledge_cutoff=_CUTOFF,
    )
    assert published.get("must_not_use_for_decision") is False, published
    assert published["publication_id"] == publication_id
    rows = published["rows"]
    assert isinstance(rows, list) and len(rows) == 1
    assert rows[0]["close"] == _PRICE
    member = PublicationMemberModel.objects.get(
        publication_id=publication_id,
        fact_table=PriceBarModel._meta.db_table,
    )
    selected_fact = PriceBarModel.objects.get(pk=member.fact_pk)
    assert selected_fact.source == "fixture:published-close-owner-api"

    before = _financial_snapshot()
    report_count_before = DailyInspectionReportModel.objects.filter(account_id=account.pk).count()
    proposal_count_before = RebalanceProposalModel.objects.filter(account_id=account.pk).count()
    client = APIClient()
    _publish_m1_policy_for_preview(
        monkeypatch,
        client=client,
        owner=user,
        account=account,
        strategy=None,
    )
    market_reader = _install_published_close_builder(
        monkeypatch,
        account=account,
        user_id=user.pk,
    )

    response = _post_published_close_inspection(client=client, account_id=account.pk)

    assert response.status_code == 200, response.content.decode("utf-8", errors="replace")
    assert response["Content-Type"].split(";", maxsplit=1)[0] == "application/json"
    plan = response.json()["reports"][0]["plan"]
    assert plan["plan_kind"] == "rebalance_preview"
    assert plan["read_only"] is True
    assert plan["execution_submitted"] is False
    assert plan["reference_price_basis"] == "published_close"
    assert plan["risk_context"]["strategy_selection_state"] == "confirmed_unconfigured"
    assert plan["risk_context"]["strategy_id"] is None
    row = next(item for item in plan["asset_items"] if item["asset_code"] == ASSET_BUY)
    assert row["status"] == "ready"
    assert row["price_source"] == "fixture:published-close-owner-api"
    assert row["price_freshness"] == "close_fallback"
    assert row["price_is_fallback"] is True
    assert Decimal(row["reference_price"]) == Decimal("10.00")
    assert Decimal(row["target_weight"]) == Decimal("0.10")
    quantity = Decimal(row["suggested_quantity"])
    assert quantity > 0 and quantity % Decimal("100") == 0
    assert Decimal(row["actionable_quantity"]) == quantity
    gross = quantity * Decimal(row["reference_price"])
    assert Decimal(row["suggested_amount"]) == gross
    fee_total = Decimal(row["fee"]["total"])
    assert fee_total > 0
    assert Decimal(plan["estimated_buy_gross"]) == gross
    assert Decimal(plan["estimated_buy_fees"]) == fee_total
    assert Decimal(plan["estimated_buy_total"]) == gross + fee_total
    assert Decimal(plan["cash_before"]) == Decimal("100000.00")
    assert Decimal(plan["projected_cash_after_buys"]) == (
        Decimal(plan["cash_before"]) - Decimal(plan["estimated_buy_total"])
    )
    provenance = row["price_publication"]
    assert provenance["publication_id"] == publication_id
    assert provenance["publication_key"] == M1_REBALANCE_REFERENCE_PUBLICATION_KEY
    assert provenance["bar_date"] == _SESSION.isoformat()
    assert provenance["knowledge_cutoff"] == plan["as_of"]
    assert provenance["freshness_status"] == "fresh"
    assert market_reader.calls == []
    _assert_no_financial_writes(
        before=before,
        account=account,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
    )


def test_exact_target_hold_keeps_published_close_provenance_without_ledger_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A no-op row retains the close publication that established its valuation."""

    _install_session_clock(monkeypatch)
    user, account = _create_owner_account(
        username="m1-published-close-exact-hold",
        positions=((ASSET_BUY, "Fixture holding at published close", True),),
        cash=Decimal("90000.00"),
        position_quantity=Decimal("1000.000000"),
        position_price=Decimal("10.0000"),
        max_position_pct=100.0,
        max_total_position_pct=100.0,
    )
    assert user.is_staff is False
    _install_published_close_builder(monkeypatch, account=account, user_id=user.pk)
    publication_id = _publish_reference_bar()
    before = _financial_snapshot()
    report_count_before = DailyInspectionReportModel.objects.filter(account_id=account.pk).count()
    proposal_count_before = RebalanceProposalModel.objects.filter(account_id=account.pk).count()
    client = APIClient()
    _publish_m1_policy_for_preview(
        monkeypatch,
        client=client,
        owner=user,
        account=account,
        strategy=None,
    )
    market_reader = _install_published_close_builder(
        monkeypatch,
        account=account,
        user_id=user.pk,
    )

    response = _post_published_close_inspection(client=client, account_id=account.pk)

    assert response.status_code == 200, response.content.decode("utf-8", errors="replace")
    plan = response.json()["reports"][0]["plan"]
    assert plan["reference_price_basis"] == "published_close"
    assert Decimal(plan["cash_before"]) == Decimal("90000.00")
    row = next(item for item in plan["asset_items"] if item["asset_code"] == ASSET_BUY)
    assert row["action"] == "hold"
    assert row["status"] == "no_rebalance_required"
    assert Decimal(row["reference_price"]) == Decimal("10.00")
    assert Decimal(row["suggested_quantity"]) == Decimal("0.000000")
    assert row["fee"] is None
    provenance = row["price_publication"]
    assert provenance is not None
    assert provenance["publication_id"] == publication_id
    assert provenance["publication_key"] == M1_REBALANCE_REFERENCE_PUBLICATION_KEY
    assert datetime.fromisoformat(provenance["source_observed_at"]) == _CLOSE_UTC
    assert provenance["knowledge_cutoff"] == plan["as_of"]
    assert provenance["freshness_status"] == "fresh"
    assert market_reader.calls == []
    _assert_no_financial_writes(
        before=before,
        account=account,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
    )


@pytest.mark.parametrize("lane_state", ("missing", "expired"))
def test_missing_or_expired_published_close_never_falls_back_to_market(
    monkeypatch: pytest.MonkeyPatch,
    lane_state: str,
) -> None:
    """An unavailable or stale fixed lane remains blocked without using market quotes."""

    _install_session_clock(monkeypatch)
    user, account = _create_owner_account(
        username=f"m1-published-close-{lane_state}",
        positions=(),
        cash=Decimal("100000.00"),
        max_position_pct=100.0,
        max_total_position_pct=100.0,
    )
    if lane_state == "expired":
        _publish_reference_bar(bar_date=date(2026, 10, 1))
    market_reader = _install_published_close_builder(
        monkeypatch,
        account=account,
        user_id=user.pk,
    )
    client = APIClient()
    _publish_m1_policy_for_preview(
        monkeypatch,
        client=client,
        owner=user,
        account=account,
        strategy=None,
    )
    before = _financial_snapshot()
    report_count_before = DailyInspectionReportModel.objects.filter(account_id=account.pk).count()
    proposal_count_before = RebalanceProposalModel.objects.filter(account_id=account.pk).count()

    response = _post_published_close_inspection(client=client, account_id=account.pk)

    assert response.status_code == 200, response.content.decode("utf-8", errors="replace")
    plan = response.json()["reports"][0]["plan"]
    assert plan["reference_price_basis"] == "published_close"
    row = next(item for item in plan["asset_items"] if item["asset_code"] == ASSET_BUY)
    assert row["status"] == "blocked"
    assert row["reference_price"] is None
    assert row["suggested_quantity"] is None
    assert row["price_publication"] is None
    assert market_reader.calls == []
    _assert_no_financial_writes(
        before=before,
        account=account,
        report_count_before=report_count_before,
        proposal_count_before=proposal_count_before,
    )


def test_non_owner_cannot_request_published_close_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real API rejects a different ordinary user before inspection persistence."""

    owner, account = _create_owner_account(
        username="m1-published-close-non-owner-target",
        positions=(),
    )
    attacker = get_user_model().objects.create_user(
        username=f"m1-published-close-non-owner-{uuid4().hex[:8]}",
        password="unused",
    )
    assert owner.is_staff is False and attacker.is_staff is False
    _install_published_close_builder(monkeypatch, account=account, user_id=owner.pk)
    before = _financial_snapshot()
    report_count_before = DailyInspectionReportModel.objects.filter(account_id=account.pk).count()
    proposal_count_before = RebalanceProposalModel.objects.filter(account_id=account.pk).count()
    client = APIClient()
    client.force_authenticate(user=attacker)

    response = _post_published_close_inspection(client=client, account_id=account.pk)

    assert response.status_code == 403
    assert _financial_snapshot() == before
    assert DailyInspectionReportModel.objects.filter(account_id=account.pk).count() == (
        report_count_before
    )
    assert RebalanceProposalModel.objects.filter(account_id=account.pk).count() == (
        proposal_count_before
    )


def test_published_close_rejects_auto_proposal_before_inspection_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The explicit daily-close basis cannot enter proposal creation."""

    _install_session_clock(monkeypatch)
    owner, account = _create_owner_account(
        username="m1-published-close-auto-proposal",
        positions=(),
    )
    client = APIClient()
    client.force_authenticate(user=owner)
    before = _financial_snapshot()
    report_count_before = DailyInspectionReportModel.objects.filter(account_id=account.pk).count()
    proposal_count_before = RebalanceProposalModel.objects.filter(account_id=account.pk).count()

    response = _post_published_close_inspection(
        client=client,
        account_id=account.pk,
        auto_create_proposal=True,
    )

    assert response.status_code == 400
    assert "只支持只读预览" in response.json()["error"]
    assert _financial_snapshot() == before
    assert DailyInspectionReportModel.objects.filter(account_id=account.pk).count() == (
        report_count_before
    )
    assert RebalanceProposalModel.objects.filter(account_id=account.pk).count() == (
        proposal_count_before
    )
