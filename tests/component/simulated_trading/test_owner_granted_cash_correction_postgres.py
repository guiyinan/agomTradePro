"""Native owner-grant cash correction and complete replay contracts."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.utils import timezone

from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability as Capability,
)
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.simulated_trading import corporate_action_owner_grant_gate as grant_gate
from apps.simulated_trading.application.corporate_action_posting import (
    CorporateActionPostingBlockedError,
)
from apps.simulated_trading.audited_corporate_action_posting_composition import _event_id
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionStage,
    CorporateActionStageRequest,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_models import (
    CorporateActionPostingModel,
)
from core.exceptions import BusinessLogicError
from tests.component.simulated_trading.test_owner_granted_corporate_action_capabilities_postgres import (
    _v2_cash_repository as v2_cash_repository,
)
from tests.component.simulated_trading.test_owner_granted_corporate_action_capabilities_postgres import (
    owner_service as owner_service,
)
from tests.component.simulated_trading.test_owner_granted_corporate_action_capabilities_postgres import (
    owner_world as owner_world,
)
from tests.component.simulated_trading.test_owner_granted_corporate_action_capabilities_postgres import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.support.ash07_owner_account_authority import (
    ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS,
)

pytestmark = [
    pytest.mark.django_db(
        transaction=True,
        available_apps=ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS,
    ),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="Native PostgreSQL owner-grant cash correction contract; SQLite must skip.",
    ),
]

_CORRECTED_RECORD_ID = "SZSE:synthetic-correction-record-v2"
_CORRECTED_REVISION_ID = "sha256:postgres-correction-v2"
_CORRECTED_CASH = Decimal("250.00")
_PAYMENT_DATE = date(2026, 9, 25)


@pytest.fixture(autouse=True)
def record_real_audit_lease(monkeypatch):
    """Retain the real operational lease clocks and reason when a native step fails."""
    original = grant_gate.get_system_audit_authority_lease
    observations = []

    def read_observed(**kwargs):
        lease = original(**kwargs)
        observations.append(
            {
                "checked_at": timezone.now().isoformat(),
                "mode": lease.mode,
                "outbox_enabled": lease.outbox_enabled,
                "valid_until": lease.valid_until.isoformat() if lease.valid_until else None,
                "reason_code": lease.reason_code,
            }
        )
        return lease

    monkeypatch.setattr(grant_gate, "get_system_audit_authority_lease", read_observed)
    yield
    print(f"Actual operational Audit lease observations: {observations}", flush=True)


def _correction_requests(
    original: CorporateActionStageRequest,
    *,
    reversal_of_entry_id: int,
) -> tuple[CorporateActionStageRequest, CorporateActionStageRequest]:
    """Build a test-only source-qualified reversal and successor for one entitlement."""

    source_observed_at = original.source_observed_at + timedelta(minutes=20)
    qualified_at = original.qualified_at + timedelta(minutes=20)
    posted_at = original.posted_at + timedelta(minutes=20)
    common = {
        "source_record_id": _CORRECTED_RECORD_ID,
        "source_revision_id": _CORRECTED_REVISION_ID,
        "source_payload_sha256": original.source_payload_sha256,
        "qualification_sha256": original.qualification_sha256,
        "source_observed_at": source_observed_at,
        "qualified_at": qualified_at,
        "posted_at": posted_at,
        "supersedes_revision_id": original.source_revision_id,
    }
    reversal = replace(
        original,
        **common,
        entry_kind=CorporateActionEntryKind.REVERSAL,
        cash_amount=None,
        tax_treatment=None,
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
        reversal_of_entry_id=reversal_of_entry_id,
    )
    successor = replace(
        original,
        **common,
        entry_kind=CorporateActionEntryKind.SUCCESSOR,
        cash_amount=_CORRECTED_CASH,
    )
    # Reverse-only payload fields must remain absent; this also locks the exact
    # account, event, action dates, and predecessor before the batch is posted.
    reversal.__post_init__()
    successor.__post_init__()
    return successor, reversal


def _payment_after_correction(
    corrected_entitlement: CorporateActionStageRequest,
) -> CorporateActionStageRequest:
    """Build the later ordinary payment POSTING on the corrected source revision."""

    payment = replace(
        corrected_entitlement,
        entry_kind=CorporateActionEntryKind.POSTING,
        stage=CorporateActionStage.CASH_PAYMENT,
        stage_date=_PAYMENT_DATE,
        payment_date=_PAYMENT_DATE,
        supersedes_revision_id=None,
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
        source_observed_at=corrected_entitlement.source_observed_at + timedelta(minutes=1),
        qualified_at=corrected_entitlement.qualified_at + timedelta(minutes=1),
        posted_at=corrected_entitlement.posted_at + timedelta(minutes=1),
    )
    payment.__post_init__()
    return payment


def _counts(service) -> tuple[int, int, int]:
    """Count the actual event ledger, Audit, and Outbox rows in this test UOW."""

    return (
        CorporateActionPostingModel.objects.filter(account=service.world.row).count(),
        SystemAuditEventModel.objects.count(),
        SystemAuditOutboxModel.objects.count(),
    )


def test_native_owner_cash_correction_replays_complete_batch_after_payment(owner_service):
    """A later payment makes the row timestamp stale; only the full exact audited batch replays."""

    service = owner_service
    grant, repository = v2_cash_repository(
        service,
        capabilities=(Capability.CASH_STAGE_WRITE,),
        valid_for=timedelta(minutes=8),
    )
    initial = repository.post_revision_with_audit((service.stage,))[0]
    assert not initial.replayed
    correction = _correction_requests(service.stage, reversal_of_entry_id=initial.entry_id)
    correction_receipts = repository.post_revision_with_audit(correction)
    assert all(not receipt.replayed for receipt in correction_receipts)
    assert tuple(receipt.stage_key for receipt in correction_receipts) == tuple(
        request.stage_key for request in correction
    )

    after_correction = _counts(service)
    with pytest.raises(CorporateActionPostingBlockedError):
        repository.post_revision_with_audit((correction[1],))
    assert _counts(service) == after_correction

    corrected_entitlement = next(
        request
        for request in correction
        if request.entry_kind is CorporateActionEntryKind.SUCCESSOR
    )
    payment = _payment_after_correction(corrected_entitlement)
    paid = repository.post_revision_with_audit((payment,))[0]
    assert not paid.replayed
    service.world.row.refresh_from_db()
    assert service.world.row.updated_at != service.world.source.row_updated_at

    # Confirm the exact correction Audit/Outbox pairs exist before exercising
    # the stale-row timestamp proof path on its full original request tuple.
    with repository._coordinator.atomic():
        for request in correction:
            winner = repository._coordinator.get_winner(
                event_id=_event_id(request),
                event_version="1",
                as_of=timezone.now(),
            )
            assert winner is not None
            outbox = repository._coordinator.get_exact_outbox_winner_targeted(winner)
            assert outbox is not None and outbox.event == winner
            grant_refs = [ref for ref in winner.evidence_refs if ref.owner == "account"]
            assert len(grant_refs) == 1
            assert grant_refs[0].artifact_id == grant.grant_id
            assert grant_refs[0].artifact_version == grant.grant_version
            assert grant_refs[0].content_hash == grant.content_hash

    before_replay = _counts(service)
    replayed = repository.post_revision_with_audit(correction)
    assert len(replayed) == 2 and all(receipt.replayed for receipt in replayed)
    assert tuple(receipt.entry_id for receipt in replayed) == tuple(
        receipt.entry_id for receipt in correction_receipts
    )
    assert _counts(service) == before_replay
    service.world.row.refresh_from_db()
    assert service.world.row.current_cash == Decimal("10250.00")


def test_native_owner_cash_correction_second_audit_failure_rolls_back_batch(
    owner_service,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure after the second Audit/Outbox append rolls back both correction rows."""

    service = owner_service
    _grant, repository = v2_cash_repository(
        service,
        capabilities=(Capability.CASH_STAGE_WRITE,),
        valid_for=timedelta(minutes=8),
    )
    initial = repository.post_revision_with_audit((service.stage,))[0]
    correction = _correction_requests(service.stage, reversal_of_entry_id=initial.entry_id)
    baseline_counts = _counts(service)
    service.world.row.refresh_from_db()
    baseline_cash = service.world.row.current_cash
    baseline_receivable = sum(
        CorporateActionPostingModel.objects.filter(account=service.world.row).values_list(
            "cash_receivable_delta", flat=True
        ),
        Decimal("0.00"),
    )

    coordinator = repository._coordinator
    original_append = type(coordinator).append_and_enqueue
    append_count = 0

    def append_second_then_fail(self, *args, **kwargs):
        nonlocal append_count
        result = original_append(self, *args, **kwargs)
        if self is coordinator:
            append_count += 1
            if append_count == 2:
                raise BusinessLogicError("injected second correction Audit/Outbox failure")
        return result

    monkeypatch.setattr(type(coordinator), "append_and_enqueue", append_second_then_fail)
    with pytest.raises(BusinessLogicError, match="second correction"):
        repository.post_revision_with_audit(correction)

    assert append_count == 2
    assert _counts(service) == baseline_counts
    service.world.row.refresh_from_db()
    assert service.world.row.current_cash == baseline_cash
    retained_receivable = sum(
        CorporateActionPostingModel.objects.filter(account=service.world.row).values_list(
            "cash_receivable_delta", flat=True
        ),
        Decimal("0.00"),
    )
    assert retained_receivable == baseline_receivable
