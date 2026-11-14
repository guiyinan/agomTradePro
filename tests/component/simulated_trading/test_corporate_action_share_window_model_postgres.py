"""Native financial-proof contracts with explicitly synthetic source/model input ports.

These are PostgreSQL grant/ledger/Audit/Outbox tests. They do not qualify actual
official disclosures, actual taxpayers, or the ordinary-user HTTP/browser journey.
"""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection, transaction
from django.utils import timezone

from apps.account.simulated_corporate_action_write_issuance_composition import (
    revoke_authenticated_simulated_corporate_action_grant,
)
from apps.simulated_trading.audited_corporate_action_posting_composition import (
    DjangoAuditedCorporateActionPostingRepositoryFactory,
)
from apps.simulated_trading.audited_share_corporate_action_posting_composition import (
    build_audited_share_revision_use_case,
)
from apps.simulated_trading.corporate_action_owner_grant_gate import (
    DjangoCorporateActionOwnerGrantGate,
)
from apps.simulated_trading.corporate_action_owner_ledger_composition import (
    read_locked_owner_corporate_action_posting_state,
)
from apps.simulated_trading.corporate_action_window_audit_composition import (
    CorporateActionWindowAuditGate,
)
from apps.simulated_trading.domain.corporate_action_posting import CorporateActionStage
from core.exceptions import AgomTradeProException
from tests.component.account.test_simulated_corporate_action_write_issuance_postgres import (
    owner_world as owner_world,
)
from tests.component.simulated_trading.test_owner_granted_corporate_action_postgres import (
    owner_service as owner_service,
)
from tests.component.simulated_trading.test_owner_granted_share_corporate_action_postgres import (
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
    Capability,
    _clocks,
    _counts,
    _position,
    _share_request,
    _v3_components,
    authenticated_request,
)
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.support.ash07_owner_account_authority import ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS
from tests.support.simulated_tax_model_native_sources import isolated_task_channels
from tests.unit.simulated_trading.test_corporate_action_share_tax_model import _query
from tests.unit.simulated_trading.test_corporate_action_share_tax_proof import _proof
from tests.unit.simulated_trading.test_corporate_action_window_audit_composition import _evidence

pytestmark = [
    pytest.mark.django_db(transaction=True, available_apps=ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS),
    pytest.mark.skipif(
        connection.vendor != "postgresql", reason="Migrated native PostgreSQL required"
    ),
]


@pytest.fixture(autouse=True)
def isolated_channels():
    with isolated_task_channels():
        yield


class _SyntheticWindow:
    """Typed synthetic current-window input; actual official qualification is out of scope."""

    def __init__(self, canonical, deadline):
        self.canonical = canonical
        self.deadline = deadline
        self.calls = 0
        self.available = True

    def read_current(self, request, *, as_of):
        assert self.available, "an exact financial retry reopened current window inputs"
        self.calls += 1
        base = _evidence()
        # This port is expressly synthetic. Its declared finite fixture lease
        # follows the real test grant instead of an arbitrary wall-clock timeout.
        lease = self.deadline - request.qualified_at
        lease_us = (lease.days * 86400 + lease.seconds) * 1000000 + lease.microseconds
        return replace(
            base,
            account_id=request.account_id,
            owner_user_id=request.owner_user_id,
            runtime_environment="development",
            policy_provenance=replace(
                base.policy_provenance,
                runtime_environment="development",
                lease_ttl_microseconds=lease_us,
                maximum_lease_microseconds=lease_us,
            ),
            asset_code=request.asset_code,
            security_id=request.security_id,
            source_record_id=request.source_record_id,
            source_revision_id=request.source_revision_id,
            source_payload_sha256=request.source_payload_sha256,
            source_observed_at=request.source_observed_at,
            window_start_on=request.record_date,
            window_end_on=as_of.date(),
            original_first_observed_at=request.source_observed_at,
            original_listing_verified_at=request.source_observed_at,
            original_proof_recorded_at=request.qualified_at,
            checked_at=as_of,
            expires_at=self.deadline,
        )


class _SyntheticModel:
    """Complete original model material supplied only by this declared synthetic port."""

    def __init__(self, canonical, deadline, *, change=False):
        self.canonical = canonical
        self.deadline = deadline
        self.change = change
        self.calls = 0
        self.available = True

    def read_current(self, request, *, as_of):
        assert self.available, "an exact financial retry reopened current model inputs"
        self.calls += 1
        names = (
            "owner_user_id",
            "security_id",
            "asset_code",
            "source_namespace",
            "source_record_id",
            "source_event_id",
            "source_revision_id",
            "source_payload_sha256",
            "action_kind",
            "stage",
            "entry_kind",
            "record_date",
            "effective_date",
            "stage_date",
            "source_observed_at",
        )
        query = replace(
            _query(),
            physical_account_id=request.account_id,
            canonical_account_id=self.canonical,
            **{name: getattr(request, name) for name in names},
        )
        base = _proof()
        model = replace(
            base.model,
            query_semantic_sha256=query.semantic_sha256,
            known_at=request.source_observed_at,
            valid_from=request.source_observed_at - timedelta(days=1),
            valid_until=self.deadline,
            checked_at=as_of,
            runtime_profile_id=(
                "changed-synthetic-profile"
                if self.change and self.calls > 1
                else "synthetic-native-profile"
            ),
        )
        return replace(
            base,
            query=query,
            model=model,
            environment="development",
            checked_at=as_of,
            valid_until=self.deadline,
            instrument_response_completed_at=request.source_observed_at - timedelta(days=1),
        )


def _components(service, *, change=False):
    original = _v3_components(
        service, capabilities=(Capability.SHARE_STAGE_WRITE,), label="full-window-model"
    )
    deadline = original.grant.valid_until
    source = _SyntheticWindow(service.world.source.account_id, deadline)
    model = _SyntheticModel(service.world.source.account_id, deadline, change=change)
    gate = DjangoCorporateActionOwnerGrantGate(
        selector=original.grant.selector,
        scope_locker=service.world.locker,
        using="default",
        environment="development",
        expected_grant_schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
    )
    factory = DjangoAuditedCorporateActionPostingRepositoryFactory(
        environment="development",
        owner_grant_gate=gate,
        window_gate=CorporateActionWindowAuditGate(source, share_tax_reader=model),
    )
    use_case = build_audited_share_revision_use_case(
        audited_repository=factory,
        source_qualifier=original.source_verifier,
        ownership_verifier=original.ownership_verifier,
        using="default",
    )
    return original, use_case, source, model


def test_native_full_share_model_original_audit_survives_source_loss_and_withdrawal(owner_service):
    service = owner_service
    position = _position(service)
    original, use_case, source, model = _components(service)
    clocks = _clocks()
    requests = tuple(
        _share_request(service, stage=stage, clocks=clocks)
        for stage in (
            CorporateActionStage.SHARE_ENTITLEMENT,
            CorporateActionStage.SHARE_DELIVERY,
            CorporateActionStage.SHARE_SELLABLE_RELEASE,
        )
    )
    before = _counts(service.world.row.pk)
    receipts = []
    for request in requests:
        receipts.append(use_case.execute((request,))[0])
    calls = (source.calls, model.calls)
    source.available = model.available = False
    for request, receipt in zip(requests, receipts, strict=True):
        retry = use_case.execute((request,))[0]
        assert retry.replayed and retry.entry_id == receipt.entry_id
    assert (source.calls, model.calls) == calls
    assert _counts(service.world.row.pk) == tuple(value + 3 for value in before)
    revoke_authenticated_simulated_corporate_action_grant(
        authenticated_request(service.world.user),
        selector=original.grant.selector,
        revocation_id="native-full-model-withdrawal",
        revocation_version="1",
        using="default",
    )
    with pytest.raises(AgomTradeProException):
        use_case.execute((requests[0],))
    service.world.row.refresh_from_db()
    with transaction.atomic():
        state = read_locked_owner_corporate_action_posting_state(
            account=service.world.row,
            canonical_account_id=service.world.source.account_id,
            as_of=timezone.now(),
        )
    assert len(state.audit_receipts) == 3
    assert all(quantity == 0 for _, quantity in state.share_receivables)
    position.refresh_from_db()
    assert position.quantity == position.available_quantity == Decimal("30.000000")


def test_native_changed_share_model_rolls_back_ledger_position_and_audit(owner_service):
    service = owner_service
    position = _position(service)
    _, use_case, _, model = _components(service, change=True)
    request = _share_request(
        service, stage=CorporateActionStage.SHARE_ENTITLEMENT, clocks=_clocks()
    )
    before = _counts(service.world.row.pk)
    cash = service.world.row.current_cash
    with pytest.raises(AgomTradeProException):
        use_case.execute((request,))
    assert model.calls >= 2
    assert _counts(service.world.row.pk) == before
    service.world.row.refresh_from_db()
    position.refresh_from_db()
    assert service.world.row.current_cash == cash
    assert position.quantity == position.available_quantity == Decimal("20.000000")
