"""Actual database checks for account posting with canonical Audit/Outbox."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from apps.audit.application.system_audit_authority_renewal_guard import (
    SystemAuditAuthorityLease,
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
    DjangoRuntimeCorporateActionAuditGate,
    build_audited_cash_entitlement_use_case,
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
_REAL_ASSERT_LIVE = DjangoRuntimeCorporateActionAuditGate.assert_live


@dataclass(frozen=True, slots=True)
class _SyntheticAuthority:
    """Model the exact provider-issued scope in local transaction tests."""

    user_id: int
    scope: AuditScopeRef


@pytest.fixture(autouse=True)
def _synthetic_audit_authority() -> Iterator[None]:
    """Avoid live config I/O while exercising the actual ledger/Audit repositories."""

    def live_authority(*, as_of: datetime) -> _SyntheticAuthority:
        assert as_of.tzinfo is not None
        user = get_user_model().objects.get(username="audited-corporate-action-test")
        return _SyntheticAuthority(
            user_id=user.pk,
            scope=AuditScopeRef("test-tenant", f"test-owner-{user.pk}"),
        )

    with patch.object(
        DjangoRuntimeCorporateActionAuditGate, "assert_live", side_effect=live_authority
    ):
        yield


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


def _audited_repository() -> AuditedCorporateActionPostingRepositoryPort:
    """Bind synthetic evidence verifiers to the actual same-alias repositories."""

    return DjangoAuditedCorporateActionPostingRepositoryFactory().build_posting_repository(
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
    repository = _audited_repository()

    first = repository.post_revision_with_audit((request,))[0]
    replay = repository.post_revision_with_audit((request,))[0]

    assert not first.replayed
    assert replay.replayed and replay.entry_id == first.entry_id
    assert CorporateActionPostingModel.objects.filter(account=account).count() == 1
    assert SystemAuditEventModel.objects.count() == 1
    assert SystemAuditOutboxModel.objects.count() == 1


@pytest.mark.django_db
def test_distinct_source_events_keep_distinct_audit_identities_and_one_stream() -> None:
    """The same account and stage must not collapse two different source events."""

    account = _account()
    first_request = _request(account)
    second_request = replace(first_request, source_event_id="SZSE:002727:audited-dividend-second")
    repository = _audited_repository()

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
    repository = _audited_repository()

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
    repository = _audited_repository()

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
    repository = _audited_repository()

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
    repository = _audited_repository()
    other_authority = _SyntheticAuthority(
        user_id=account.user_id + 1,
        scope=AuditScopeRef("other-tenant", "other-owner"),
    )

    with patch.object(
        DjangoRuntimeCorporateActionAuditGate,
        "assert_live",
        return_value=other_authority,
    ):
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
    repository = _audited_repository()
    initial = _SyntheticAuthority(
        user_id=account.user_id,
        scope=AuditScopeRef("test-tenant", f"test-owner-{account.user_id}"),
    )
    changed = _SyntheticAuthority(
        user_id=account.user_id,
        scope=AuditScopeRef("changed-tenant", f"test-owner-{account.user_id}"),
    )

    with patch.object(
        DjangoRuntimeCorporateActionAuditGate,
        "assert_live",
        side_effect=(initial, initial, changed),
    ):
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
            authority_gate=DjangoRuntimeCorporateActionAuditGate(
                environment="test", using="default"
            ),
            using="default",
        )

    assert captured.value.code == "CORPORATE_ACTION_AUDIT_OUTBOX_UNAVAILABLE"


def test_production_builder_rejects_alias_without_account_valuation_support() -> None:
    """Cash posting cannot use an alias that its account NAV reader cannot see."""

    with pytest.raises(CorporateActionPostingBlockedError) as captured:
        build_audited_cash_entitlement_use_case(
            body_store_root=Path("."), runtime_environment="test", using="other"
        )

    assert captured.value.code == "CORPORATE_ACTION_AUDIT_OUTBOX_UNAVAILABLE"


def test_tax_verifier_injection_blocks_before_database_access() -> None:
    """The cash-only factory cannot unlock deferred withholding by injection."""

    with pytest.raises(CorporateActionPostingBlockedError) as captured:
        DjangoAuditedCorporateActionPostingRepositoryFactory().build_posting_repository(
            source_qualifier=_SourceVerifier(),
            ownership_verifier=_OwnershipVerifier(),
            tax_basis_verifier=_TaxVerifier(),
            using="default",
        )

    assert captured.value.code == "CORPORATE_ACTION_AUDIT_OUTBOX_UNAVAILABLE"


def test_runtime_gate_rejects_disabled_audit_before_database_access() -> None:
    """Operator-disabled Audit mode cannot create an audited posting adapter."""

    gate = DjangoRuntimeCorporateActionAuditGate(environment="test", using="default")
    disabled = SystemAuditAuthorityLease(mode="off", outbox_enabled=False, valid_until=None)
    with patch(
        "apps.simulated_trading.audited_corporate_action_posting_composition.get_system_audit_authority_lease",
        return_value=disabled,
    ):
        with pytest.raises(CorporateActionPostingBlockedError) as captured:
            _REAL_ASSERT_LIVE(gate, as_of=_POSTED_AT)

    assert captured.value.code == "CORPORATE_ACTION_AUDIT_AUTHORITY_UNAVAILABLE"


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
        authority_gate=DjangoRuntimeCorporateActionAuditGate(environment="test", using="default"),
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


@pytest.mark.django_db
def test_existing_ledger_without_outbox_blocks_replay() -> None:
    """A replay cannot silently create missing canonical delivery evidence."""

    account = _account()
    request = _request(account)
    repository = _audited_repository()
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
