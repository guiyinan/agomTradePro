"""Native PostgreSQL V3 owner contracts for synthetic audited share actions.

The source and historical-ownership verifiers in this module accept only explicit
test facts. They exercise real Account grants, the posting models, and the required
Audit/Outbox transaction; they do not establish official-source qualification.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.db import connection
from django.utils import timezone

from apps.account import simulated_corporate_action_policy_scope_composition as policies
from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability as Capability,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
)
from apps.account.infrastructure.identity_models import AccountProfileModel
from apps.account.simulated_corporate_action_write_issuance_composition import (
    issue_authenticated_simulated_corporate_action_grant,
    revoke_authenticated_simulated_corporate_action_grant,
)
from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.simulated_trading.application.corporate_action_posting import (
    CorporateActionPostingBlockedError,
)
from apps.simulated_trading.audited_corporate_action_posting_composition import (
    DjangoAuditedCorporateActionPostingRepositoryFactory,
)
from apps.simulated_trading.audited_share_corporate_action_posting_composition import (
    build_audited_rights_no_effect_use_case,
    build_audited_share_revision_use_case,
)
from apps.simulated_trading.corporate_action_owner_grant_gate import (
    DjangoCorporateActionOwnerGrantGate,
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
from apps.simulated_trading.infrastructure.simulated_account_trade_models import PositionModel
from core.exceptions import AuthorizationError, BusinessLogicError
from tests.component.account.test_simulated_corporate_action_consent_capabilities_http import (
    TERMS_V3_SHA256,
    _publish_known_v3_policy,
)
from tests.component.account.test_simulated_corporate_action_write_issuance_postgres import (
    _request as authenticated_request,
)
from tests.component.account.test_simulated_corporate_action_write_issuance_postgres import (
    owner_world as owner_world,
)
from tests.component.simulated_trading.test_owner_granted_corporate_action_postgres import (
    owner_service as owner_service,
)
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.support.ash07_owner_account_authority import (
    ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS,
)
from tests.support.simulated_tax_model_native_sources import isolated_task_channels

pytestmark = [
    pytest.mark.django_db(
        transaction=True,
        available_apps=ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS,
    ),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="Native PostgreSQL V3 owner grant contract; SQLite must skip explicitly.",
    ),
]

_RECORD_DATE = date(2026, 9, 23)
_EFFECTIVE_DATE = date(2026, 9, 24)
_SELLABLE_DATE = date(2026, 10, 30)
_ASSET_CODE = "002727.SZ"
_SOURCE_DIGESTS = {
    "ash05-synthetic-share-v1": ("a" * 64, "b" * 64),
    "ash05-synthetic-share-v2": ("c" * 64, "d" * 64),
    "ash05-synthetic-rights-v1": ("e" * 64, "f" * 64),
}


@pytest.fixture(autouse=True)
def _isolated_owner_task_channels():
    """Keep cache and task-channel state inside the component test transaction."""
    with isolated_task_channels():
        yield


class _SyntheticSourceVerifier:
    """Accept only the declared synthetic exchange-shaped fixture facts."""

    def __init__(self) -> None:
        self.valid = True

    def verify_source(self, request: CorporateActionStageRequest) -> bool:
        """Check test-only identities without representing an official source proof."""
        expected = _SOURCE_DIGESTS.get(request.source_revision_id)
        return (
            self.valid
            and expected is not None
            and request.source_namespace == "exchange_official_disclosure"
            and request.source_record_id == f"SZSE:SYNTHETIC:{request.source_event_id}"
            and request.security_id == _ASSET_CODE
            and request.asset_code == _ASSET_CODE
            and request.source_payload_sha256 == expected[0]
            and request.qualification_sha256 == expected[1]
            and request.qualifier_identity == "ash05-synthetic-source-verifier-v1"
        )


class _SyntheticOwnershipVerifier:
    """Accept an explicit fixture snapshot bound to this test account and event."""

    def verify_ownership(self, request: CorporateActionStageRequest) -> bool:
        """Require a matching record-date snapshot and its exact qualification clock."""
        return (
            request.security_id == _ASSET_CODE
            and request.asset_code == _ASSET_CODE
            and request.ownership_snapshot_id
            == f"synthetic-owner:{request.account_id}:{request.source_event_id}"
            and request.ownership_snapshot_sha256 == "9" * 64
            and request.ownership_snapshot_as_of_date == _RECORD_DATE
            and request.ownership_snapshot_observed_at == request.qualified_at
            and request.eligible_quantity == Decimal("10.000000")
        )


def _v3_components(service, *, capabilities: tuple[Capability, ...], label: str):
    """Issue an explicit same-chain V3 grant and compose the real audited builders."""
    version = f"ash05-share-{label}-v3"
    _publish_known_v3_policy(version=version)
    policy = policies.read_current_simulated_action_write_policy(
        canonical_account_id=service.world.source.account_id,
        owner_user_id=service.world.user.pk,
        environment="development",
        as_of=timezone.now(),
        expected_grant_schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
    )
    assert policy.terms_sha256 == TERMS_V3_SHA256
    now = timezone.now()
    selected = tuple(sorted(capabilities, key=lambda capability: capability.value))
    command = replace(
        service.world.command,
        grant_id=service.grant.grant_id,
        grant_version=version,
        expected_binding=replace(
            service.world.command.expected_binding,
            policy_version=policy.policy_version,
            policy_content_hash=policy.content_hash,
        ),
        valid_until=policy.grant_valid_until(
            as_of=now, source_valid_until=service.world.source.valid_until
        ),
        expected_predecessor_content_hash=service.grant.content_hash,
        grant_schema=policy.grant_schema,
        capabilities=selected,
        terms_version=policy.terms_version,
        terms_sha256=policy.terms_sha256,
    )
    grant = issue_authenticated_simulated_corporate_action_grant(
        authenticated_request(service.world.user),
        command=command,
        scope_locker=service.world.locker,
        using="default",
    )
    assert grant.schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA
    assert grant.capabilities == selected
    assert grant.terms_sha256 == TERMS_V3_SHA256
    gate = DjangoCorporateActionOwnerGrantGate(
        selector=grant.selector,
        scope_locker=service.world.locker,
        using="default",
        environment="development",
        expected_grant_schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
    )
    source_verifier = _SyntheticSourceVerifier()
    ownership_verifier = _SyntheticOwnershipVerifier()
    factory = DjangoAuditedCorporateActionPostingRepositoryFactory(
        environment="development", owner_grant_gate=gate
    )
    return SimpleNamespace(
        grant=grant,
        factory=factory,
        source_verifier=source_verifier,
        ownership_verifier=ownership_verifier,
        share=build_audited_share_revision_use_case(
            audited_repository=factory,
            source_qualifier=source_verifier,
            ownership_verifier=ownership_verifier,
            using="default",
        ),
        rights=build_audited_rights_no_effect_use_case(
            audited_repository=factory,
            source_qualifier=source_verifier,
            ownership_verifier=ownership_verifier,
            using="default",
        ),
    )


def _clocks() -> tuple[datetime, datetime, datetime]:
    """Return ordered, timezone-aware synthetic source and posting clocks."""
    qualified_at = timezone.now() - timedelta(seconds=2)
    return qualified_at - timedelta(seconds=1), qualified_at, qualified_at + timedelta(seconds=1)


def _stage_date(stage: CorporateActionStage) -> date:
    """Return explicit fixture stage dates with a reached sellable date."""
    if stage is CorporateActionStage.SHARE_ENTITLEMENT:
        return _EFFECTIVE_DATE
    if stage is CorporateActionStage.SHARE_DELIVERY:
        return date(2026, 10, 20)
    return _SELLABLE_DATE


def _share_request(
    service,
    *,
    stage: CorporateActionStage,
    clocks: tuple[datetime, datetime, datetime],
    revision_id: str = "ash05-synthetic-share-v1",
    entry_kind: CorporateActionEntryKind = CorporateActionEntryKind.POSTING,
    supersedes_revision_id: str | None = None,
    reversal_of_entry_id: int | None = None,
    share_amount: Decimal = Decimal("10.000000"),
) -> CorporateActionStageRequest:
    """Build an exact source-shaped fixture request; facts remain synthetic."""
    observed_at, qualified_at, posted_at = clocks
    source_payload_sha256, qualification_sha256 = _SOURCE_DIGESTS[revision_id]
    is_reversal = entry_kind is CorporateActionEntryKind.REVERSAL
    has_entitlement_snapshot = stage is CorporateActionStage.SHARE_ENTITLEMENT and not is_reversal
    has_sellable_date = (
        stage
        in {
            CorporateActionStage.SHARE_DELIVERY,
            CorporateActionStage.SHARE_SELLABLE_RELEASE,
        }
        and not is_reversal
    )
    return CorporateActionStageRequest(
        account_id=service.world.row.pk,
        owner_user_id=service.world.user.pk,
        security_id=_ASSET_CODE,
        asset_code=_ASSET_CODE,
        asset_name="Synthetic share issuer",
        source_namespace="exchange_official_disclosure",
        source_record_id="SZSE:SYNTHETIC:ash05-synthetic-share-event",
        source_event_id="ash05-synthetic-share-event",
        source_revision_id=revision_id,
        source_payload_sha256=source_payload_sha256,
        qualification_sha256=qualification_sha256,
        qualifier_identity="ash05-synthetic-source-verifier-v1",
        source_observed_at=observed_at,
        qualified_at=qualified_at,
        posted_at=posted_at,
        action_kind=CorporateActionKind.SHARE_DISTRIBUTION,
        stage=stage,
        entry_kind=entry_kind,
        record_date=_RECORD_DATE,
        effective_date=_EFFECTIVE_DATE,
        stage_date=_stage_date(stage),
        share_amount=None if is_reversal else share_amount,
        sellable_date=_SELLABLE_DATE if has_sellable_date else None,
        tax_treatment=None if is_reversal else "not_applicable",
        ownership_snapshot_id=(
            f"synthetic-owner:{service.world.row.pk}:ash05-synthetic-share-event"
            if has_entitlement_snapshot
            else None
        ),
        ownership_snapshot_sha256="9" * 64 if has_entitlement_snapshot else None,
        ownership_snapshot_as_of_date=_RECORD_DATE if has_entitlement_snapshot else None,
        ownership_snapshot_observed_at=qualified_at if has_entitlement_snapshot else None,
        eligible_quantity=Decimal("10.000000") if has_entitlement_snapshot else None,
        entitlement_calculation_sha256="8" * 64 if has_entitlement_snapshot else None,
        odd_lot_policy=None if is_reversal else "whole_shares",
        supersedes_revision_id=supersedes_revision_id,
        reversal_of_entry_id=reversal_of_entry_id,
    )


def _rights_request(service, *, clocks: tuple[datetime, datetime, datetime]):
    """Build one explicit synthetic no-exercise rights election with no exercise terms."""
    observed_at, qualified_at, posted_at = clocks
    source_payload_sha256, qualification_sha256 = _SOURCE_DIGESTS["ash05-synthetic-rights-v1"]
    return CorporateActionStageRequest(
        account_id=service.world.row.pk,
        owner_user_id=service.world.user.pk,
        security_id=_ASSET_CODE,
        asset_code=_ASSET_CODE,
        asset_name="Synthetic rights issuer",
        source_namespace="exchange_official_disclosure",
        source_record_id="SZSE:SYNTHETIC:ash05-synthetic-rights-event",
        source_event_id="ash05-synthetic-rights-event",
        source_revision_id="ash05-synthetic-rights-v1",
        source_payload_sha256=source_payload_sha256,
        qualification_sha256=qualification_sha256,
        qualifier_identity="ash05-synthetic-source-verifier-v1",
        source_observed_at=observed_at,
        qualified_at=qualified_at,
        posted_at=posted_at,
        action_kind=CorporateActionKind.RIGHTS_ISSUE,
        stage=CorporateActionStage.RIGHTS_NOT_EXERCISED,
        entry_kind=CorporateActionEntryKind.NO_EFFECT,
        record_date=_RECORD_DATE,
        effective_date=_EFFECTIVE_DATE,
        stage_date=date(2026, 10, 1),
        ownership_snapshot_id=(
            f"synthetic-owner:{service.world.row.pk}:ash05-synthetic-rights-event"
        ),
        ownership_snapshot_sha256="9" * 64,
        ownership_snapshot_as_of_date=_RECORD_DATE,
        ownership_snapshot_observed_at=qualified_at,
        eligible_quantity=Decimal("10.000000"),
        entitlement_calculation_sha256="8" * 64,
        rights_terms_sha256="7" * 64,
        rights_election="not_exercised",
    )


def _position(service) -> PositionModel:
    """Create the account's pre-existing cost-basis row required for share delivery."""
    return PositionModel.objects.create(
        account=service.world.row,
        asset_code=_ASSET_CODE,
        asset_name="Synthetic share issuer",
        asset_type="equity",
        quantity=Decimal("20.000000"),
        available_quantity=Decimal("20.000000"),
        available_quantity_known=True,
        avg_cost=Decimal("10.0000"),
        total_cost=Decimal("200.00"),
        cost_basis_known=True,
        current_price=Decimal("10.0000"),
        market_value=Decimal("200.00"),
        valuation_known=True,
        unrealized_pnl=Decimal("0.00"),
        unrealized_pnl_pct=0.0,
        first_buy_date=date(2026, 1, 5),
        first_buy_date_known=True,
        entry_reason="synthetic owner component fixture",
    )


def _counts(account_id: int) -> tuple[int, int, int]:
    """Count account ledger rows and the globally required Audit/Outbox rows."""
    return (
        CorporateActionPostingModel.objects.filter(account_id=account_id).count(),
        SystemAuditEventModel.objects.count(),
        SystemAuditOutboxModel.objects.count(),
    )


def test_native_v3_share_stages_correct_and_replay_exactly(
    owner_service, record_testsuite_property
):
    """Real non-staff consent covers entitlement, delivery, release and full correction."""
    service = owner_service
    position = _position(service)
    account_cash = service.world.row.current_cash
    legacy_summary = service.world.row.total_value
    components = _v3_components(
        service,
        capabilities=(Capability.SHARE_STAGE_WRITE,),
        label="share-positive",
    )
    record_testsuite_property("share_grant_recorded_at", components.grant.recorded_at.isoformat())
    record_testsuite_property("share_grant_valid_until", components.grant.valid_until.isoformat())
    baseline = _counts(service.world.row.pk)
    clocks = _clocks()
    stages = (
        CorporateActionStage.SHARE_ENTITLEMENT,
        CorporateActionStage.SHARE_DELIVERY,
        CorporateActionStage.SHARE_SELLABLE_RELEASE,
    )
    original_requests = tuple(
        _share_request(service, stage=stage, clocks=clocks) for stage in stages
    )
    original_receipts = {}
    for request in original_requests:
        record_testsuite_property(
            f"share_stage_{request.stage.value}_started_at", timezone.now().isoformat()
        )
        receipt = components.share.execute((request,))[0]
        replay = components.share.execute((request,))[0]
        assert receipt.stage_key == request.stage_key
        assert receipt.entry_id == replay.entry_id
        assert not receipt.replayed and replay.replayed
        original_receipts[request.stage] = receipt
    assert _counts(service.world.row.pk) == tuple(value + 3 for value in baseline)
    position.refresh_from_db()
    assert position.quantity == Decimal("30.000000")
    assert position.available_quantity == Decimal("30.000000")
    assert position.total_cost == Decimal("200.00")
    assert position.market_value == Decimal("200.00")
    assert position.valuation_known is False

    correction_clocks = _clocks()
    correction_revision = "ash05-synthetic-share-v2"
    correction_requests = (
        _share_request(
            service,
            stage=CorporateActionStage.SHARE_SELLABLE_RELEASE,
            clocks=correction_clocks,
            revision_id=correction_revision,
            entry_kind=CorporateActionEntryKind.SUCCESSOR,
            supersedes_revision_id="ash05-synthetic-share-v1",
            share_amount=Decimal("12.000000"),
        ),
        _share_request(
            service,
            stage=CorporateActionStage.SHARE_ENTITLEMENT,
            clocks=correction_clocks,
            revision_id=correction_revision,
            entry_kind=CorporateActionEntryKind.REVERSAL,
            supersedes_revision_id="ash05-synthetic-share-v1",
            reversal_of_entry_id=original_receipts[CorporateActionStage.SHARE_ENTITLEMENT].entry_id,
        ),
        _share_request(
            service,
            stage=CorporateActionStage.SHARE_DELIVERY,
            clocks=correction_clocks,
            revision_id=correction_revision,
            entry_kind=CorporateActionEntryKind.SUCCESSOR,
            supersedes_revision_id="ash05-synthetic-share-v1",
            share_amount=Decimal("12.000000"),
        ),
        _share_request(
            service,
            stage=CorporateActionStage.SHARE_SELLABLE_RELEASE,
            clocks=correction_clocks,
            revision_id=correction_revision,
            entry_kind=CorporateActionEntryKind.REVERSAL,
            supersedes_revision_id="ash05-synthetic-share-v1",
            reversal_of_entry_id=original_receipts[
                CorporateActionStage.SHARE_SELLABLE_RELEASE
            ].entry_id,
        ),
        _share_request(
            service,
            stage=CorporateActionStage.SHARE_ENTITLEMENT,
            clocks=correction_clocks,
            revision_id=correction_revision,
            entry_kind=CorporateActionEntryKind.SUCCESSOR,
            supersedes_revision_id="ash05-synthetic-share-v1",
            share_amount=Decimal("12.000000"),
        ),
        _share_request(
            service,
            stage=CorporateActionStage.SHARE_DELIVERY,
            clocks=correction_clocks,
            revision_id=correction_revision,
            entry_kind=CorporateActionEntryKind.REVERSAL,
            supersedes_revision_id="ash05-synthetic-share-v1",
            reversal_of_entry_id=original_receipts[CorporateActionStage.SHARE_DELIVERY].entry_id,
        ),
    )
    corrected = components.share.execute(correction_requests)
    assert tuple(receipt.stage_key for receipt in corrected) == tuple(
        request.stage_key for request in correction_requests
    )
    assert all(not receipt.replayed for receipt in corrected)
    assert len({receipt.entry_id for receipt in corrected}) == len(correction_requests)
    replayed = components.share.execute(correction_requests)
    assert tuple(receipt.entry_id for receipt in replayed) == tuple(
        receipt.entry_id for receipt in corrected
    )
    assert all(receipt.replayed for receipt in replayed)
    assert _counts(service.world.row.pk) == tuple(value + 9 for value in baseline)
    position.refresh_from_db()
    service.world.row.refresh_from_db()
    assert position.quantity == Decimal("32.000000")
    assert position.available_quantity == Decimal("32.000000")
    assert position.total_cost == Decimal("200.00")
    assert position.market_value == Decimal("200.00")
    assert service.world.row.current_cash == account_cash
    assert service.world.row.total_value == legacy_summary


def test_native_v3_rights_no_effect_requires_its_own_capability(owner_service):
    """A rights-only grant records no exercise and cannot authorize share delivery."""
    service = owner_service
    position = _position(service)
    original_cash = service.world.row.current_cash
    original_position = (position.quantity, position.available_quantity, position.total_cost)
    components = _v3_components(
        service,
        capabilities=(Capability.RIGHTS_NOT_EXERCISED,),
        label="rights-only",
    )
    rights = _rights_request(service, clocks=_clocks())
    share = _share_request(
        service,
        stage=CorporateActionStage.SHARE_ENTITLEMENT,
        clocks=_clocks(),
    )
    baseline = _counts(service.world.row.pk)
    with pytest.raises(CorporateActionPostingBlockedError):
        components.share.execute((share,))
    assert _counts(service.world.row.pk) == baseline
    first = components.rights.execute((rights,))[0]
    replay = components.rights.execute((rights,))[0]
    assert first.entry_id == replay.entry_id
    assert not first.replayed and replay.replayed
    assert _counts(service.world.row.pk) == tuple(value + 1 for value in baseline)
    assert rights.rights_election == "not_exercised"
    assert rights.rights_terms_sha256 == "7" * 64
    assert rights.share_amount is None and rights.cash_amount is None
    position.refresh_from_db()
    service.world.row.refresh_from_db()
    assert service.world.row.current_cash == original_cash
    assert (
        position.quantity,
        position.available_quantity,
        position.total_cost,
    ) == original_position
    row = CorporateActionPostingModel.objects.get(pk=first.entry_id)
    assert all(
        value == 0
        for value in (
            row.cash_delta,
            row.cash_receivable_delta,
            row.share_delta,
            row.share_receivable_delta,
            row.available_share_delta,
        )
    )


def test_native_v3_revoked_share_grant_blocks_exact_replay(owner_service):
    """An old ledger/Audit winner cannot bypass withdrawal of current share consent."""
    service = owner_service
    components = _v3_components(
        service,
        capabilities=(Capability.SHARE_STAGE_WRITE,),
        label="share-withdrawal",
    )
    request = _share_request(
        service,
        stage=CorporateActionStage.SHARE_ENTITLEMENT,
        clocks=_clocks(),
    )
    first = components.share.execute((request,))[0]
    assert not first.replayed
    revoke_authenticated_simulated_corporate_action_grant(
        authenticated_request(service.world.user),
        selector=components.grant.selector,
        revocation_id="ash05-v3-share-withdrawal",
        revocation_version="1",
        using="default",
    )
    baseline = _counts(service.world.row.pk)
    with pytest.raises((CorporateActionPostingBlockedError, AuthorizationError)):
        components.share.execute((request,))
    assert _counts(service.world.row.pk) == baseline


@pytest.mark.parametrize(
    "failure", ("audit_append", "late_role_revocation", "source_requalification")
)
def test_native_v3_share_delivery_failure_rolls_back_all_participants(
    owner_service, monkeypatch, failure
):
    """Late Audit, authority, or source failure restores ledger, position, Audit and Outbox."""
    service = owner_service
    position = _position(service)
    components = _v3_components(
        service,
        capabilities=(Capability.SHARE_STAGE_WRITE,),
        label=f"rollback-{failure}",
    )
    clocks = _clocks()
    entitlement = _share_request(
        service,
        stage=CorporateActionStage.SHARE_ENTITLEMENT,
        clocks=clocks,
    )
    delivery = _share_request(
        service,
        stage=CorporateActionStage.SHARE_DELIVERY,
        clocks=clocks,
    )
    components.share.execute((entitlement,))
    baseline_counts = _counts(service.world.row.pk)
    baseline_position = (
        position.quantity,
        position.available_quantity,
        position.avg_cost,
        position.total_cost,
        position.market_value,
        position.valuation_known,
    )
    baseline_cash = service.world.row.current_cash
    baseline_summary = service.world.row.total_value
    original_role = AccountProfileModel.objects.get(user_id=service.world.user.pk).rbac_role
    original_append = DjangoSystemAuditEventOutboxCoordinator.append_and_enqueue

    def append_then_invalidate(self, *args, **kwargs):
        result = original_append(self, *args, **kwargs)
        if failure == "audit_append":
            raise BusinessLogicError("injected failure after Audit and Outbox append")
        if failure == "late_role_revocation":
            AccountProfileModel.objects.filter(user_id=service.world.user.pk).update(
                rbac_role="read_only"
            )
        else:
            components.source_verifier.valid = False
        return result

    monkeypatch.setattr(
        DjangoSystemAuditEventOutboxCoordinator,
        "append_and_enqueue",
        append_then_invalidate,
    )
    with pytest.raises(
        (CorporateActionPostingBlockedError, BusinessLogicError, AuthorizationError)
    ):
        components.share.execute((delivery,))

    assert _counts(service.world.row.pk) == baseline_counts
    position.refresh_from_db()
    service.world.row.refresh_from_db()
    assert (
        position.quantity,
        position.available_quantity,
        position.avg_cost,
        position.total_cost,
        position.market_value,
        position.valuation_known,
    ) == baseline_position
    assert service.world.row.current_cash == baseline_cash
    assert service.world.row.total_value == baseline_summary
    assert AccountProfileModel.objects.get(user_id=service.world.user.pk).rbac_role == original_role
