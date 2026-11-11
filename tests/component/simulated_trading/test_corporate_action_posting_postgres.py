"""Native PostgreSQL concurrency contract for cash-entitlement idempotency."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from threading import Barrier

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, connections

from apps.simulated_trading.application.corporate_action_posting import (
    CorporateActionPostingBlockedError,
    CorporateActionPostingReceipt,
    PostCorporateActionStageUseCase,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionKind,
    CorporateActionStage,
    CorporateActionStageRequest,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_models import (
    CorporateActionPostingModel,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_repository import (
    DjangoCorporateActionPostingRepository,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)

_RECORD_DATE = date(2026, 9, 23)
_EFFECTIVE_DATE = date(2026, 9, 24)
_OBSERVED_AT = datetime(2026, 11, 11, 1, 0, tzinfo=UTC)
_QUALIFIED_AT = datetime(2026, 11, 11, 1, 5, tzinfo=UTC)
_POSTED_AT = datetime(2026, 11, 11, 1, 10, tzinfo=UTC)


class _SourceVerifier:
    """Accept the exact deterministic source values created by this test."""

    def verify_source(self, request: CorporateActionStageRequest) -> bool:
        return (
            request.source_namespace == "exchange_official_disclosure"
            and request.security_id == "002727.SZ"
            and request.asset_code == "002727.SZ"
            and request.source_payload_sha256 == "a" * 64
            and request.qualification_sha256 == "b" * 64
        )


class _OwnershipVerifier:
    """Accept only the account- and record-date-bound fixture proof."""

    def verify_ownership(self, request: CorporateActionStageRequest) -> bool:
        return (
            request.security_id == "002727.SZ"
            and request.asset_code == "002727.SZ"
            and request.ownership_snapshot_id
            == f"account-history:{request.account_id}:{_RECORD_DATE.isoformat()}"
            and request.ownership_snapshot_sha256 == "d" * 64
            and request.ownership_snapshot_as_of_date == _RECORD_DATE
            and request.ownership_snapshot_observed_at == _OBSERVED_AT
            and request.eligible_quantity == Decimal("1000.000000")
        )


def _request(account: SimulatedAccountModel) -> CorporateActionStageRequest:
    """Build one deterministic no-tax-rule cash entitlement for the locked account."""

    return CorporateActionStageRequest(
        account_id=account.pk,
        owner_user_id=account.user_id,
        security_id="002727.SZ",
        asset_code="002727.SZ",
        asset_name="Synthetic security",
        source_namespace="exchange_official_disclosure",
        source_record_id="SZSE:synthetic-source",
        source_event_id="SZSE:002727:postgres-entitlement",
        source_revision_id="sha256:postgres-v1",
        source_payload_sha256="a" * 64,
        qualification_sha256="b" * 64,
        qualifier_identity="test-official-source-v1",
        source_observed_at=_OBSERVED_AT,
        qualified_at=_QUALIFIED_AT,
        posted_at=_POSTED_AT,
        action_kind=CorporateActionKind.CASH_DIVIDEND,
        stage=CorporateActionStage.CASH_ENTITLEMENT,
        entry_kind=CorporateActionEntryKind.POSTING,
        record_date=_RECORD_DATE,
        effective_date=_EFFECTIVE_DATE,
        stage_date=_RECORD_DATE,
        cash_amount=Decimal("200.00"),
        tax_treatment="deferred_withholding",
        tax_rule_id=None,
        tax_rule_sha256=None,
        ownership_snapshot_id=f"account-history:{account.pk}:{_RECORD_DATE.isoformat()}",
        ownership_snapshot_sha256="d" * 64,
        ownership_snapshot_as_of_date=_RECORD_DATE,
        ownership_snapshot_observed_at=_OBSERVED_AT,
        eligible_quantity=Decimal("1000.000000"),
        entitlement_calculation_sha256="e" * 64,
    )


@pytest.mark.django_db(transaction=True)
def test_postgres_concurrent_entitlement_replay_writes_one_receivable() -> None:
    """Two connections racing on one entitlement return one insert and one exact replay."""

    if connection.vendor != "postgresql":
        pytest.skip("native PostgreSQL row-lock behavior is required")

    user = get_user_model().objects.create_user(
        username="corporate-action-postgres-test",
        password="unused",
    )
    account = SimulatedAccountModel.objects.create(
        user=user,
        account_name="corporate-action-postgres-test",
        account_type="simulated",
        initial_capital=Decimal("10000.00"),
        current_cash=Decimal("10000.00"),
        current_market_value=Decimal("0.00"),
        total_value=Decimal("10000.00"),
        is_active=True,
    )
    request = _request(account)
    use_case = PostCorporateActionStageUseCase(
        DjangoCorporateActionPostingRepository(
            source_qualifier=_SourceVerifier(),
            ownership_verifier=_OwnershipVerifier(),
            using="default",
        )
    )
    barrier = Barrier(2)

    def post_from_separate_connection() -> tuple[CorporateActionPostingReceipt, ...]:
        """Start both repository calls together and return the exact receipt tuple."""

        connections.close_all()
        barrier.wait(timeout=30)
        try:
            return use_case.execute((request,))
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(post_from_separate_connection)
        second_future = executor.submit(post_from_separate_connection)
        first_receipts = first_future.result(timeout=60)
        second_receipts = second_future.result(timeout=60)

    receipts = (first_receipts[0], second_receipts[0])
    assert len({receipt.entry_id for receipt in receipts}) == 1
    assert sorted(receipt.replayed for receipt in receipts) == [False, True]
    assert CorporateActionPostingModel.objects.filter(account=account).count() == 1
    row = CorporateActionPostingModel.objects.get(account=account)
    assert row.cash_receivable_delta == Decimal("200.00")
    account.refresh_from_db()
    assert account.current_cash == Decimal("10000.00")


@pytest.mark.parametrize(
    ("scope_error", "expected_code"),
    (
        ("cross_account", "CORPORATE_ACTION_HISTORICAL_OWNERSHIP_UNKNOWN"),
        ("owner", "CORPORATE_ACTION_ACCOUNT_SCOPE_INVALID"),
        ("security", "CORPORATE_ACTION_SOURCE_UNQUALIFIED"),
        ("asset", "CORPORATE_ACTION_SOURCE_UNQUALIFIED"),
    ),
)
@pytest.mark.django_db(transaction=True)
def test_postgres_wrong_owner_account_or_security_scope_blocks_without_writes(
    scope_error: str,
    expected_code: str,
) -> None:
    """Persisted ledger scope cannot be crossed by a caller-supplied snapshot identity."""

    if connection.vendor != "postgresql":
        pytest.skip("native PostgreSQL scope contract is required")

    user = get_user_model().objects.create_user(
        username=f"corporate-action-postgres-scope-{scope_error}",
        password="unused",
    )
    account = SimulatedAccountModel.objects.create(
        user=user,
        account_name=f"corporate-action-postgres-scope-{scope_error}",
        account_type="simulated",
        initial_capital=Decimal("10000.00"),
        current_cash=Decimal("10000.00"),
        current_market_value=Decimal("0.00"),
        total_value=Decimal("10000.00"),
        is_active=True,
    )
    other_user = get_user_model().objects.create_user(
        username=f"corporate-action-postgres-other-owner-{scope_error}",
        password="unused",
    )
    other_account = SimulatedAccountModel.objects.create(
        user=user,
        account_name=f"corporate-action-postgres-other-account-{scope_error}",
        account_type="simulated",
        initial_capital=Decimal("5000.00"),
        current_cash=Decimal("5000.00"),
        current_market_value=Decimal("0.00"),
        total_value=Decimal("5000.00"),
        is_active=True,
    )
    request = _request(account)
    if scope_error == "cross_account":
        request = replace(request, account_id=other_account.pk)
    elif scope_error == "owner":
        request = replace(request, owner_user_id=other_user.pk)
    elif scope_error == "security":
        request = replace(request, security_id="301237.SZ")
    else:
        request = replace(request, asset_code="301237.SZ")

    use_case = PostCorporateActionStageUseCase(
        DjangoCorporateActionPostingRepository(
            source_qualifier=_SourceVerifier(),
            ownership_verifier=_OwnershipVerifier(),
            using="default",
        )
    )
    with pytest.raises(CorporateActionPostingBlockedError) as blocked:
        use_case.execute((request,))

    assert blocked.value.code == expected_code
    assert CorporateActionPostingModel.objects.count() == 0
    account.refresh_from_db()
    other_account.refresh_from_db()
    assert account.current_cash == Decimal("10000.00")
    assert other_account.current_cash == Decimal("5000.00")
