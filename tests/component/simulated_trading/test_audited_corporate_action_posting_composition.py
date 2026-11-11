"""Actual database checks for account posting with canonical Audit/Outbox."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from apps.account.domain.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrant,
    SimulatedCorporateActionWriteGrantBinding,
)
from apps.audit.application.system_audit_event_outbox import (
    SystemAuditEventOutboxUnavailable,
)
from apps.audit.domain.system_audit_event import AuditScopeRef
from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.audit.infrastructure.system_audit_outbox_repository import (
    DjangoSystemAuditOutboxRepository,
)
from apps.simulated_trading.application.corporate_action_posting import (
    AuditedCorporateActionPostingRepositoryPort,
    CorporateActionPostingBlockedError,
)
from apps.simulated_trading.audited_corporate_action_posting_composition import (
    DjangoAuditedCorporateActionPostingRepository,
    DjangoAuditedCorporateActionPostingRepositoryFactory,
    build_audited_cash_entitlement_use_case,
    build_audited_cash_payment_use_case,
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
_CAPTURED_AT = datetime(2026, 11, 10, 1, 0, tzinfo=UTC)
_QUALIFIED_AT = datetime(2026, 11, 10, 1, 5, tzinfo=UTC)
_POSTED_AT = datetime(2026, 11, 10, 1, 10, tzinfo=UTC)
_CONTROLLED_AUTHORITIES: dict[
    DjangoCorporateActionOwnerGrantGate, list[OwnerGrantedCorporateActionAuthority]
] = {}


@pytest.fixture(autouse=True)
def _controlled_owner_authority(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Supply an explicit test owner grant without weakening production gate construction."""
    _CONTROLLED_AUTHORITIES.clear()

    @contextmanager
    def atomic_authority(
        gate: DjangoCorporateActionOwnerGrantGate,
        request: CorporateActionStageRequest,
        *,
        replay_timestamp_verifier: CorporateActionSourceTimestampReplayVerifier | None = None,
    ) -> Iterator[OwnerGrantedCorporateActionAuthority]:
        del replay_timestamp_verifier
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
        if len(authorities) > 1:
            return authorities.pop(0)
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


def _test_owner_grant(owner_user_id: int, *, grant_id: str) -> SimulatedCorporateActionWriteGrant:
    """Build one deterministic domain-valid grant for an explicitly controlled test gate."""
    recorded_at = datetime.now(UTC) - timedelta(seconds=1)
    binding = SimulatedCorporateActionWriteGrantBinding(
        account_namespace="simulated",
        account_id=f"test-account-{owner_user_id}",
        owner_user_id=owner_user_id,
        tenant_id="test-tenant",
        owner_id=f"test-owner-{owner_user_id}",
        account_source_id=f"test-source-{owner_user_id}",
        account_source_version="source-v1",
        account_source_content_hash="a" * 64,
        policy_id=f"test-policy-{owner_user_id}",
        policy_version="policy-v1",
        policy_content_hash="b" * 64,
    )
    return SimulatedCorporateActionWriteGrant(
        grant_id=grant_id,
        grant_version="1",
        binding=binding,
        consent_evidence_id=f"test-consent-{owner_user_id}",
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


def _owner_authority(
    grant: SimulatedCorporateActionWriteGrant,
) -> OwnerGrantedCorporateActionAuthority:
    """Bind one test grant to the exact tenant and owner Audit scope."""
    return OwnerGrantedCorporateActionAuthority(
        user_id=grant.binding.owner_user_id,
        scope=AuditScopeRef(tenant_id=grant.binding.tenant_id, owner_id=grant.binding.owner_id),
        grant=grant,
        authority_valid_until=grant.valid_until,
    )


def _controlled_owner_gate(owner_user_id: int) -> DjangoCorporateActionOwnerGrantGate:
    """Construct a real owner-gate object with test-only controlled authority methods."""
    grant = _test_owner_grant(
        owner_user_id, grant_id=f"controlled-corporate-action-grant-{owner_user_id}"
    )
    gate = DjangoCorporateActionOwnerGrantGate(
        selector=grant.selector,
        scope_locker=DjangoSimulatedCorporateActionWriteScopeLocker(
            database_alias="default", runtime_environment="test"
        ),
        using="default",
        environment="test",
    )
    _CONTROLLED_AUTHORITIES[gate] = [_owner_authority(grant)]
    return gate


class _SourceVerifier:
    """Accept the exact synthetic public-source fixture for local DB checks."""

    def verify_source(self, request: CorporateActionStageRequest) -> bool:
        return request.source_namespace == "exchange_official_disclosure"


class _OwnershipVerifier:
    """Accept the exact account and record-date snapshot fixture."""

    def verify_ownership(self, request: CorporateActionStageRequest) -> bool:
        return (
            request.ownership_snapshot_id
            == f"account-history:{request.account_id}:{_RECORD_DATE.isoformat()}"
            and request.ownership_snapshot_as_of_date == _RECORD_DATE
            and request.eligible_quantity == Decimal("10.000000")
        )


class _TaxVerifier:
    """Deliberately permissive tax port that production composition must reject."""

    def verify_tax_basis(self, request: CorporateActionStageRequest) -> bool:
        return True


def _account() -> SimulatedAccountModel:
    """Create one active simulated account in the disposable test database."""

    user = get_user_model().objects.create_user(
        username="audited-corporate-action-test", password="unused"
    )
    return SimulatedAccountModel.objects.create(
        user=user,
        account_name="audited-corporate-action-test",
        account_type="simulated",
        initial_capital=Decimal("100.00"),
        current_cash=Decimal("0.00"),
        current_market_value=Decimal("100.00"),
        total_value=Decimal("100.00"),
        is_active=True,
    )


def _request(account: SimulatedAccountModel) -> CorporateActionStageRequest:
    """Build a qualified cash entitlement with explicit historical ownership."""

    return CorporateActionStageRequest(
        account_id=account.pk,
        owner_user_id=account.user_id,
        security_id="002727.SZ",
        asset_code="002727.SZ",
        asset_name="Synthetic security",
        source_namespace="exchange_official_disclosure",
        source_record_id="SZSE:synthetic-disclosure-pdf",
        source_event_id="SZSE:002727:audited-dividend",
        source_revision_id="sha256:" + "a" * 64,
        source_payload_sha256="a" * 64,
        qualification_sha256="b" * 64,
        qualifier_identity="synthetic-qualifier-v1",
        source_observed_at=_CAPTURED_AT,
        qualified_at=_QUALIFIED_AT,
        posted_at=_POSTED_AT,
        action_kind=CorporateActionKind.CASH_DIVIDEND,
        stage=CorporateActionStage.CASH_ENTITLEMENT,
        entry_kind=CorporateActionEntryKind.POSTING,
        record_date=_RECORD_DATE,
        effective_date=_EFFECTIVE_DATE,
        stage_date=_EFFECTIVE_DATE,
        cash_amount=Decimal("2.00"),
        tax_treatment="deferred_withholding",
        ownership_snapshot_id=(f"account-history:{account.pk}:{_RECORD_DATE.isoformat()}"),
        ownership_snapshot_sha256="d" * 64,
        ownership_snapshot_as_of_date=_RECORD_DATE,
        ownership_snapshot_observed_at=_CAPTURED_AT,
        eligible_quantity=Decimal("10.000000"),
        entitlement_calculation_sha256="e" * 64,
    )


def _payment_request(account: SimulatedAccountModel) -> CorporateActionStageRequest:
    """Build a cash payment that reuses this exact source event without owner-proof claims."""

    return replace(
        _request(account),
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


def _audited_repository(owner_user_id: int) -> AuditedCorporateActionPostingRepositoryPort:
    """Bind synthetic evidence verifiers to the actual same-alias repositories."""

    return DjangoAuditedCorporateActionPostingRepositoryFactory(
        environment="test", owner_grant_gate=_controlled_owner_gate(owner_user_id)
    ).build_posting_repository(
        source_qualifier=_SourceVerifier(),
        ownership_verifier=_OwnershipVerifier(),
        tax_basis_verifier=None,
        using="default",
    )


@pytest.mark.django_db
def test_entitlement_and_exact_replay_keep_one_ledger_audit_outbox_pair() -> None:
    """A duplicate request reuses its exact ledger and Audit/Outbox winners."""

    account = _account()
    request = _request(account)
    repository = _audited_repository(account.user_id)

    first = repository.post_revision_with_audit((request,))[0]
    replay = repository.post_revision_with_audit((request,))[0]

    assert not first.replayed
    assert replay.replayed and replay.entry_id == first.entry_id
    assert CorporateActionPostingModel.objects.filter(account=account).count() == 1
    assert SystemAuditEventModel.objects.count() == 1
    assert SystemAuditOutboxModel.objects.count() == 1


@pytest.mark.django_db
def test_cash_payment_and_exact_replay_keep_one_ledger_audit_outbox_pair() -> None:
    """The payment append and its replay share one exact ledger and Audit/Outbox identity."""

    account = _account()
    entitlement = _request(account)
    payment = _payment_request(account)
    repository = _audited_repository(account.user_id)
    repository.post_revision_with_audit((entitlement,))

    first = repository.post_revision_with_audit((payment,))[0]
    replay = repository.post_revision_with_audit((payment,))[0]

    assert not first.replayed
    assert replay.replayed and replay.entry_id == first.entry_id
    account.refresh_from_db()
    assert account.current_cash == Decimal("2.00")
    rows = CorporateActionPostingModel.objects.filter(account=account).order_by("account_revision")
    assert rows.count() == 2
    assert tuple(row.stage for row in rows) == ("cash_entitlement", "cash_payment")
    assert sum((row.cash_receivable_delta for row in rows), Decimal("0.00")) == Decimal("0.00")
    assert SystemAuditEventModel.objects.count() == 2
    assert SystemAuditOutboxModel.objects.count() == 2


@pytest.mark.django_db
def test_audit_append_failure_rolls_back_cash_payment_and_evidence() -> None:
    """A failed Audit append cannot leave the payment cash transfer or ledger row committed."""

    account = _account()
    repository = _audited_repository(account.user_id)
    repository.post_revision_with_audit((_request(account),))

    with patch.object(
        DjangoSystemAuditEventOutboxCoordinator,
        "append_and_enqueue",
        side_effect=SystemAuditEventOutboxUnavailable("payment Audit failure"),
    ):
        with pytest.raises(SystemAuditEventOutboxUnavailable):
            repository.post_revision_with_audit((_payment_request(account),))

    account.refresh_from_db()
    assert account.current_cash == Decimal("0.00")
    assert CorporateActionPostingModel.objects.filter(account=account).count() == 1
    assert SystemAuditEventModel.objects.count() == 1
    assert SystemAuditOutboxModel.objects.count() == 1


@pytest.mark.django_db
def test_outbox_failure_rolls_back_cash_payment_and_audit() -> None:
    """A failed payment Outbox enqueue restores the pre-payment ledger and Audit state."""

    account = _account()
    repository = _audited_repository(account.user_id)
    repository.post_revision_with_audit((_request(account),))

    with patch.object(
        DjangoSystemAuditOutboxRepository,
        "enqueue",
        side_effect=SystemAuditEventOutboxUnavailable("payment Outbox failure"),
    ):
        with pytest.raises(SystemAuditEventOutboxUnavailable):
            repository.post_revision_with_audit((_payment_request(account),))

    account.refresh_from_db()
    assert account.current_cash == Decimal("0.00")
    assert CorporateActionPostingModel.objects.filter(account=account).count() == 1
    assert SystemAuditEventModel.objects.count() == 1
    assert SystemAuditOutboxModel.objects.count() == 1


@pytest.mark.django_db
def test_wrong_owner_blocks_cash_payment_before_additional_writes() -> None:
    """A payment cannot move cash when its claimed owner differs from the locked account."""

    account = _account()
    repository = _audited_repository(account.user_id)
    repository.post_revision_with_audit((_request(account),))
    payment = replace(_payment_request(account), owner_user_id=account.user_id + 1)

    with pytest.raises(CorporateActionPostingBlockedError):
        repository.post_revision_with_audit((payment,))

    account.refresh_from_db()
    assert account.current_cash == Decimal("0.00")
    assert CorporateActionPostingModel.objects.filter(account=account).count() == 1
    assert SystemAuditEventModel.objects.count() == 1
    assert SystemAuditOutboxModel.objects.count() == 1


@pytest.mark.django_db
def test_distinct_source_events_keep_distinct_audit_identities_and_one_stream() -> None:
    """The same account and stage must not collapse two different source events."""

    account = _account()
    first_request = _request(account)
    second_request = replace(first_request, source_event_id="SZSE:002727:audited-dividend-second")
    repository = _audited_repository(account.user_id)

    repository.post_revision_with_audit((first_request,))
    repository.post_revision_with_audit((second_request,))

    assert CorporateActionPostingModel.objects.filter(account=account).count() == 2
    assert SystemAuditEventModel.objects.count() == 2
    assert SystemAuditOutboxModel.objects.count() == 2


@pytest.mark.django_db
def test_audit_append_failure_rolls_back_cash_entitlement() -> None:
    """The account and ledger stay unchanged if required Audit append fails."""

    account = _account()
    request = _request(account)
    repository = _audited_repository(account.user_id)

    with patch.object(
        DjangoSystemAuditEventOutboxCoordinator,
        "append_and_enqueue",
        side_effect=SystemAuditEventOutboxUnavailable("test failure"),
    ):
        with pytest.raises(SystemAuditEventOutboxUnavailable):
            repository.post_revision_with_audit((request,))

    account.refresh_from_db()
    assert account.current_cash == Decimal("0.00")
    assert CorporateActionPostingModel.objects.filter(account=account).count() == 0
    assert SystemAuditEventModel.objects.count() == 0
    assert SystemAuditOutboxModel.objects.count() == 0


@pytest.mark.django_db
def test_outbox_enqueue_failure_rolls_back_ledger_and_audit() -> None:
    """An Outbox failure after Audit insert leaves no durable partial write."""

    account = _account()
    request = _request(account)
    repository = _audited_repository(account.user_id)

    with patch.object(
        DjangoSystemAuditOutboxRepository,
        "enqueue",
        side_effect=SystemAuditEventOutboxUnavailable("test outbox failure"),
    ):
        with pytest.raises(SystemAuditEventOutboxUnavailable):
            repository.post_revision_with_audit((request,))

    assert CorporateActionPostingModel.objects.filter(account=account).count() == 0
    assert SystemAuditEventModel.objects.count() == 0
    assert SystemAuditOutboxModel.objects.count() == 0


@pytest.mark.django_db
def test_wrong_owner_blocks_before_ledger_and_audit_write() -> None:
    """The account row lock rejects owner substitution before any event append."""

    account = _account()
    request = replace(_request(account), owner_user_id=account.user_id + 1)
    repository = _audited_repository(account.user_id)

    with pytest.raises(CorporateActionPostingBlockedError):
        repository.post_revision_with_audit((request,))

    assert CorporateActionPostingModel.objects.filter(account=account).count() == 0
    assert SystemAuditEventModel.objects.count() == 0
    assert SystemAuditOutboxModel.objects.count() == 0


@pytest.mark.django_db
def test_provider_authority_for_other_owner_rolls_back_posting() -> None:
    """A valid account row cannot be audited under another provider owner scope."""

    account = _account()
    request = _request(account)
    repository = _audited_repository(account.user_id + 1)
    with pytest.raises(CorporateActionPostingBlockedError) as captured:
        repository.post_revision_with_audit((request,))

    assert captured.value.code == "CORPORATE_ACTION_AUDIT_AUTHORITY_SCOPE_INVALID"
    assert CorporateActionPostingModel.objects.filter(account=account).count() == 0
    assert SystemAuditEventModel.objects.count() == 0
    assert SystemAuditOutboxModel.objects.count() == 0


@pytest.mark.django_db
def test_authority_change_before_commit_rolls_back_all_three_writes() -> None:
    """A changed issued scope after append invalidates the whole outer transaction."""

    account = _account()
    request = _request(account)
    gate = _controlled_owner_gate(account.user_id)
    initial = _CONTROLLED_AUTHORITIES[gate][0]
    changed = _owner_authority(
        _test_owner_grant(account.user_id, grant_id="controlled-owner-grant-changed")
    )
    _CONTROLLED_AUTHORITIES[gate] = [initial, changed]
    # Rebuild with the gate whose controlled current authority changes at the final check.
    repository = DjangoAuditedCorporateActionPostingRepositoryFactory(
        environment="test", owner_grant_gate=gate
    ).build_posting_repository(
        source_qualifier=_SourceVerifier(),
        ownership_verifier=_OwnershipVerifier(),
        tax_basis_verifier=None,
        using="default",
    )
    with pytest.raises(CorporateActionPostingBlockedError) as captured:
        repository.post_revision_with_audit((request,))

    assert captured.value.code == "CORPORATE_ACTION_AUDIT_AUTHORITY_SCOPE_INVALID"
    assert CorporateActionPostingModel.objects.filter(account=account).count() == 0
    assert SystemAuditEventModel.objects.count() == 0
    assert SystemAuditOutboxModel.objects.count() == 0


def test_mismatched_alias_blocks_before_database_access() -> None:
    """An Audit coordinator cannot bind a different ledger database alias."""

    with pytest.raises(CorporateActionPostingBlockedError) as captured:
        DjangoAuditedCorporateActionPostingRepository(
            posting=DjangoCorporateActionPostingRepository(using="default"),
            coordinator=DjangoSystemAuditEventOutboxCoordinator(using="other"),
            owner_grant_gate=_controlled_owner_gate(1),
            using="default",
        )

    assert captured.value.code == "CORPORATE_ACTION_AUDIT_OUTBOX_UNAVAILABLE"


def test_production_builder_rejects_alias_without_account_valuation_support() -> None:
    """Cash posting cannot use an alias that its account NAV reader cannot see."""

    with pytest.raises(CorporateActionPostingBlockedError) as captured:
        build_audited_cash_entitlement_use_case(
            body_store_root=Path("."),
            runtime_environment="test",
            owner_grant_gate=_controlled_owner_gate(1),
            using="other",
        )

    assert captured.value.code == "CORPORATE_ACTION_AUDIT_OUTBOX_UNAVAILABLE"

    with pytest.raises(CorporateActionPostingBlockedError) as payment_captured:
        build_audited_cash_payment_use_case(
            body_store_root=Path("."),
            runtime_environment="test",
            owner_grant_gate=_controlled_owner_gate(1),
            using="other",
        )

    assert payment_captured.value.code == "CORPORATE_ACTION_AUDIT_OUTBOX_UNAVAILABLE"


def test_tax_verifier_injection_blocks_before_database_access() -> None:
    """The cash-only factory cannot unlock deferred withholding by injection."""

    with pytest.raises(CorporateActionPostingBlockedError) as captured:
        DjangoAuditedCorporateActionPostingRepositoryFactory(
            environment="test", owner_grant_gate=_controlled_owner_gate(1)
        ).build_posting_repository(
            source_qualifier=_SourceVerifier(),
            ownership_verifier=_OwnershipVerifier(),
            tax_basis_verifier=_TaxVerifier(),
            using="default",
        )

    assert captured.value.code == "CORPORATE_ACTION_AUDIT_OUTBOX_UNAVAILABLE"


def test_all_cash_compositions_reject_missing_owner_grant_before_database_access() -> None:
    """No audited factory, repository or builder can fall back to a staff reader."""
    missing_gate = cast(DjangoCorporateActionOwnerGrantGate, None)
    with pytest.raises(CorporateActionPostingBlockedError) as captured:
        DjangoAuditedCorporateActionPostingRepositoryFactory(
            environment="test",
            owner_grant_gate=missing_gate,
        )
    assert captured.value.code == "CORPORATE_ACTION_WRITE_AUTHORITY_UNAVAILABLE"

    with pytest.raises(CorporateActionPostingBlockedError) as repository_error:
        DjangoAuditedCorporateActionPostingRepository(
            posting=DjangoCorporateActionPostingRepository(using="default"),
            coordinator=DjangoSystemAuditEventOutboxCoordinator(using="default"),
            owner_grant_gate=missing_gate,
            using="default",
        )
    assert repository_error.value.code == "CORPORATE_ACTION_AUDIT_OUTBOX_UNAVAILABLE"

    for builder in (build_audited_cash_entitlement_use_case, build_audited_cash_payment_use_case):
        with pytest.raises(CorporateActionPostingBlockedError) as builder_error:
            builder(
                body_store_root=Path("."),
                runtime_environment="test",
                owner_grant_gate=missing_gate,
            )
        assert builder_error.value.code == "CORPORATE_ACTION_WRITE_AUTHORITY_UNAVAILABLE"


def test_direct_audited_repository_rejects_tax_stage_before_ledger_access() -> None:
    """Even a directly constructed adapter cannot release deferred tax posting."""

    account = SimulatedAccountModel(pk=1, user_id=1)
    tax_request = replace(
        _request(account),
        stage=CorporateActionStage.TAX_WITHHOLDING,
        stage_date=date(2026, 10, 20),
        cash_amount=Decimal("0.40"),
        tax_rule_id="synthetic-rule",
        tax_rule_sha256="c" * 64,
        tax_basis_record_id="synthetic-basis",
        tax_basis_sha256="f" * 64,
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
    )
    repository = DjangoAuditedCorporateActionPostingRepository(
        posting=DjangoCorporateActionPostingRepository(
            source_qualifier=_SourceVerifier(),
            ownership_verifier=_OwnershipVerifier(),
            tax_basis_verifier=_TaxVerifier(),
            using="default",
        ),
        coordinator=DjangoSystemAuditEventOutboxCoordinator(using="default"),
        owner_grant_gate=_controlled_owner_gate(1),
        using="default",
    )

    with patch.object(
        DjangoCorporateActionPostingRepository,
        "post_revision",
        side_effect=AssertionError("ledger must not be reached"),
    ):
        with pytest.raises(CorporateActionPostingBlockedError) as captured:
            repository.post_revision_with_audit((tax_request,))

    assert captured.value.code == "CORPORATE_ACTION_STAGE_UNSUPPORTED"


def test_direct_audited_repository_rejects_multi_stage_payment_batch_before_ledger_access() -> None:
    """A payment-enabled adapter still accepts exactly one ordinary stage per call."""

    account = SimulatedAccountModel(pk=1, user_id=1)
    repository = DjangoAuditedCorporateActionPostingRepository(
        posting=DjangoCorporateActionPostingRepository(
            source_qualifier=_SourceVerifier(),
            ownership_verifier=_OwnershipVerifier(),
            using="default",
        ),
        coordinator=DjangoSystemAuditEventOutboxCoordinator(using="default"),
        owner_grant_gate=_controlled_owner_gate(1),
        using="default",
    )

    with patch.object(
        DjangoCorporateActionPostingRepository,
        "post_revision",
        side_effect=AssertionError("ledger must not be reached"),
    ):
        with pytest.raises(CorporateActionPostingBlockedError) as captured:
            repository.post_revision_with_audit((_request(account), _payment_request(account)))

    assert captured.value.code == "CORPORATE_ACTION_STAGE_UNSUPPORTED"


@pytest.mark.django_db
def test_existing_ledger_without_outbox_blocks_replay() -> None:
    """A replay cannot silently create missing canonical delivery evidence."""

    account = _account()
    request = _request(account)
    repository = _audited_repository(account.user_id)
    repository.post_revision_with_audit((request,))

    with patch.object(
        DjangoSystemAuditEventOutboxCoordinator,
        "get_exact_outbox_winner_targeted",
        return_value=None,
    ):
        with pytest.raises(CorporateActionPostingBlockedError) as captured:
            repository.post_revision_with_audit((request,))

    assert captured.value.code == "CORPORATE_ACTION_AUDIT_REPLAY_INVALID"
    assert CorporateActionPostingModel.objects.filter(account=account).count() == 1
    assert SystemAuditEventModel.objects.count() == 1
    assert SystemAuditOutboxModel.objects.count() == 1
