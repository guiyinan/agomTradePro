"""Native PostgreSQL concurrency contract for cash-entitlement idempotency."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, connections

from apps.account.domain.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrant,
    SimulatedCorporateActionWriteGrantBinding,
)
from apps.audit.domain.system_audit_event import AuditScopeRef
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.simulated_trading.application.corporate_action_posting import (
    CorporateActionPostingBlockedError,
    CorporateActionPostingReceipt,
    PostCorporateActionStageUseCase,
)
from apps.simulated_trading.audited_corporate_action_posting_composition import (
    DjangoAuditedCorporateActionPostingRepositoryFactory,
)
from apps.simulated_trading.corporate_action_owner_grant_gate import (
    DjangoCorporateActionOwnerGrantGate,
    OwnerGrantedCorporateActionAuthority,
)
from apps.simulated_trading.corporate_action_write_scope_composition import (
    CorporateActionSourceTimestampReplayVerifier,
    DjangoSimulatedCorporateActionWriteScopeLocker,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionKind,
    CorporateActionStage,
    CorporateActionStageRequest,
)
from apps.simulated_trading.infrastructure import corporate_action_posting_repository
from apps.simulated_trading.infrastructure.corporate_action_posting_models import (
    CorporateActionPostingModel,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_repository import (
    DjangoCorporateActionPostingRepository,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)

_RECORD_DATE = date(2026, 9, 23)
_EFFECTIVE_DATE = date(2026, 9, 24)
_OBSERVED_AT = datetime(2026, 11, 10, 1, 0, tzinfo=UTC)
_QUALIFIED_AT = datetime(2026, 11, 10, 1, 5, tzinfo=UTC)
_POSTED_AT = datetime(2026, 11, 10, 1, 10, tzinfo=UTC)
_CONTROLLED_AUTHORITIES: dict[
    DjangoCorporateActionOwnerGrantGate, list[OwnerGrantedCorporateActionAuthority]
] = {}


@pytest.fixture(autouse=True)
def _controlled_owner_authority(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Use an explicit test owner grant while native tests exercise financial persistence."""
    _CONTROLLED_AUTHORITIES.clear()

    @contextmanager
    def atomic_authority(
        gate: DjangoCorporateActionOwnerGrantGate,
        request: CorporateActionStageRequest,
        *,
        replay_timestamp_verifier: CorporateActionSourceTimestampReplayVerifier | None = None,
    ) -> Iterator[OwnerGrantedCorporateActionAuthority]:
        del request, replay_timestamp_verifier
        authorities = _CONTROLLED_AUTHORITIES.get(gate)
        if not authorities:
            raise AssertionError("controlled owner grant was not registered")
        yield authorities[0]

    def assert_live(
        gate: DjangoCorporateActionOwnerGrantGate, *, as_of: datetime
    ) -> OwnerGrantedCorporateActionAuthority:
        del as_of
        authorities = _CONTROLLED_AUTHORITIES.get(gate)
        if not authorities:
            raise AssertionError("controlled owner grant was not registered")
        return authorities[0]

    def assert_source_timestamp_current_or_proven(
        gate: DjangoCorporateActionOwnerGrantGate,
        *,
        request: CorporateActionStageRequest,
    ) -> None:
        if gate not in _CONTROLLED_AUTHORITIES or not request.payload_sha256:
            raise AssertionError("source timestamp check requires a controlled owner grant")

    monkeypatch.setattr(DjangoCorporateActionOwnerGrantGate, "atomic_authority", atomic_authority)
    monkeypatch.setattr(DjangoCorporateActionOwnerGrantGate, "assert_live", assert_live)
    monkeypatch.setattr(
        DjangoCorporateActionOwnerGrantGate,
        "assert_source_timestamp_current_or_proven",
        assert_source_timestamp_current_or_proven,
    )
    try:
        yield
    finally:
        _CONTROLLED_AUTHORITIES.clear()


def _controlled_owner_gate(owner_user_id: int) -> DjangoCorporateActionOwnerGrantGate:
    """Build an exact default-alias gate with a domain-valid test grant."""
    recorded_at = datetime.now(UTC) - timedelta(seconds=1)
    binding = SimulatedCorporateActionWriteGrantBinding(
        account_namespace="simulated",
        account_id=f"native-test-account-{owner_user_id}",
        owner_user_id=owner_user_id,
        tenant_id="native-test-tenant",
        owner_id=f"native-test-owner-{owner_user_id}",
        account_source_id=f"native-test-source-{owner_user_id}",
        account_source_version="source-v1",
        account_source_content_hash="a" * 64,
        policy_id=f"native-test-policy-{owner_user_id}",
        policy_version="policy-v1",
        policy_content_hash="b" * 64,
    )
    grant = SimulatedCorporateActionWriteGrant(
        grant_id=f"native-controlled-grant-{owner_user_id}",
        grant_version="1",
        binding=binding,
        consent_evidence_id=f"native-test-consent-{owner_user_id}",
        consent_evidence_version="1",
        consent_evidence_hash="c" * 64,
        issuer_evidence_id="controlled-test-issuer",
        issuer_evidence_version="1",
        issuer_evidence_hash="d" * 64,
        consented_at=recorded_at,
        issued_at=recorded_at,
        recorded_at=recorded_at,
        valid_until=recorded_at + timedelta(hours=2),
    )
    gate = DjangoCorporateActionOwnerGrantGate(
        selector=grant.selector,
        scope_locker=DjangoSimulatedCorporateActionWriteScopeLocker(
            database_alias="default", runtime_environment="test"
        ),
        using="default",
        environment="test",
    )
    _CONTROLLED_AUTHORITIES[gate] = [
        OwnerGrantedCorporateActionAuthority(
            user_id=owner_user_id,
            scope=AuditScopeRef(
                tenant_id=binding.tenant_id,
                owner_id=binding.owner_id,
            ),
            grant=grant,
            authority_valid_until=grant.valid_until,
        )
    ]
    return gate


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
        stage_date=_EFFECTIVE_DATE,
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
    owner_grant_gate = _controlled_owner_gate(account.user_id)
    barrier = Barrier(2)

    def post_from_separate_connection() -> tuple[CorporateActionPostingReceipt, ...]:
        """Race independent same-alias Audit UOWs behind one account row lock."""

        connections.close_all()
        barrier.wait(timeout=30)
        try:
            repository = DjangoAuditedCorporateActionPostingRepositoryFactory(
                environment="test", owner_grant_gate=owner_grant_gate
            ).build_posting_repository(
                source_qualifier=_SourceVerifier(),
                ownership_verifier=_OwnershipVerifier(),
                tax_basis_verifier=None,
                using="default",
            )
            return repository.post_revision_with_audit((request,))
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
    assert SystemAuditEventModel.objects.count() == 1
    assert SystemAuditOutboxModel.objects.count() == 1
    row = CorporateActionPostingModel.objects.get(account=account)
    assert row.cash_receivable_delta == Decimal("200.00")
    account.refresh_from_db()
    assert account.current_cash == Decimal("10000.00")


@pytest.mark.django_db
def test_postgres_payment_waits_for_szse_date_and_settles_exact_receivable() -> None:
    """The native ledger rejects early and partial payment before one exact transfer."""

    if connection.vendor != "postgresql":
        pytest.skip("native PostgreSQL cash-payment contract is required")

    user = get_user_model().objects.create_user(
        username="corporate-action-postgres-payment",
        password="unused",
    )
    account = SimulatedAccountModel.objects.create(
        user=user,
        account_name="corporate-action-postgres-payment",
        account_type="simulated",
        initial_capital=Decimal("10000.00"),
        current_cash=Decimal("10000.00"),
        current_market_value=Decimal("0.00"),
        total_value=Decimal("10000.00"),
        is_active=True,
    )
    entitlement = _request(account)
    payment = replace(
        entitlement,
        stage=CorporateActionStage.CASH_PAYMENT,
        stage_date=_EFFECTIVE_DATE,
        payment_date=_EFFECTIVE_DATE,
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
    )
    use_case = PostCorporateActionStageUseCase(
        DjangoCorporateActionPostingRepository(
            source_qualifier=_SourceVerifier(),
            ownership_verifier=_OwnershipVerifier(),
            using="default",
        )
    )
    use_case.execute((entitlement,))

    before_szse_payment_date = datetime(2026, 9, 23, 15, 59, 59, tzinfo=UTC)
    with patch.object(
        corporate_action_posting_repository.timezone,
        "now",
        return_value=before_szse_payment_date,
    ):
        with pytest.raises(CorporateActionPostingBlockedError) as early:
            use_case.execute((payment,))
    assert early.value.code == "CORPORATE_ACTION_PAYMENT_DATE_NOT_REACHED"

    with pytest.raises(CorporateActionPostingBlockedError) as partial:
        use_case.execute((replace(payment, cash_amount=Decimal("199.99")),))
    assert partial.value.code == "CORPORATE_ACTION_RECEIVABLE_NOT_FULLY_SETTLED"
    account.refresh_from_db()
    assert account.current_cash == Decimal("10000.00")
    assert CorporateActionPostingModel.objects.filter(account=account).count() == 1

    paid = use_case.execute((payment,))
    assert len(paid) == 1 and paid[0].replayed is False
    account.refresh_from_db()
    assert account.current_cash == Decimal("10200.00")
    assert CorporateActionPostingModel.objects.filter(account=account).count() == 2
    assert use_case.execute((payment,))[0].replayed is True


@pytest.mark.django_db
def test_postgres_audited_cash_payment_commits_and_replays_with_one_audit_pair() -> None:
    """Native PostgreSQL commits one qualified payment and reuses its exact replay."""

    if connection.vendor != "postgresql":
        pytest.skip("native PostgreSQL audited payment contract is required")

    user = get_user_model().objects.create_user(
        username="corporate-action-postgres-audited-payment",
        password="unused",
    )
    account = SimulatedAccountModel.objects.create(
        user=user,
        account_name="corporate-action-postgres-audited-payment",
        account_type="simulated",
        initial_capital=Decimal("10000.00"),
        current_cash=Decimal("10000.00"),
        current_market_value=Decimal("0.00"),
        total_value=Decimal("10000.00"),
        is_active=True,
    )
    entitlement = _request(account)
    payment = replace(
        entitlement,
        stage=CorporateActionStage.CASH_PAYMENT,
        stage_date=_EFFECTIVE_DATE,
        payment_date=_EFFECTIVE_DATE,
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
    )
    owner_grant_gate = _controlled_owner_gate(account.user_id)
    repository = DjangoAuditedCorporateActionPostingRepositoryFactory(
        environment="test", owner_grant_gate=owner_grant_gate
    ).build_posting_repository(
        source_qualifier=_SourceVerifier(),
        ownership_verifier=_OwnershipVerifier(),
        tax_basis_verifier=None,
        using="default",
    )
    repository.post_revision_with_audit((entitlement,))
    paid = repository.post_revision_with_audit((payment,))[0]
    replay = repository.post_revision_with_audit((payment,))[0]

    assert not paid.replayed
    assert replay.replayed and replay.entry_id == paid.entry_id
    account.refresh_from_db()
    assert account.current_cash == Decimal("10200.00")
    rows = CorporateActionPostingModel.objects.filter(account=account).order_by("account_revision")
    assert tuple(row.stage for row in rows) == ("cash_entitlement", "cash_payment")
    assert sum((row.cash_receivable_delta for row in rows), Decimal("0.00")) == Decimal("0.00")
    assert SystemAuditEventModel.objects.count() == 2
    assert SystemAuditOutboxModel.objects.count() == 2


@pytest.mark.parametrize(
    ("scope_error", "expected_code"),
    (
        ("cross_account", "CORPORATE_ACTION_HISTORICAL_OWNERSHIP_UNKNOWN"),
        ("owner", "CORPORATE_ACTION_ACCOUNT_SCOPE_INVALID"),
        ("security", "CORPORATE_ACTION_SOURCE_UNQUALIFIED"),
        ("asset", "CORPORATE_ACTION_SOURCE_UNQUALIFIED"),
    ),
)
@pytest.mark.django_db
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
