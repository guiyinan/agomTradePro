"""Original journal and header corruption cannot be repaired by financial readback."""

import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from apps.audit.application.system_audit_event_outbox import ExactSystemAuditOutboxWinner
from apps.simulated_trading.infrastructure import (
    corporate_action_tax_assessment_repository as assessment_repository,
)
from apps.simulated_trading.infrastructure import (
    corporate_action_tax_liability_readback as readback,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_models import (
    CorporateActionTaxAssessmentHeaderModel as Header,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_repository import (
    canonical_json,
    material_sha256,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_audit import (
    build_tax_liability_audit_event,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_codec import (
    encode_liability_state,
    encode_liability_transition,
    tax_liability_scope_sha256,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_evidence import _decimal
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_models import (
    CorporateActionTaxLiabilityOperationModel as Operation,
)
from core.exceptions import BusinessLogicError
from tests.unit.simulated_trading.test_corporate_action_tax_liability import _taxable_assessment
from tests.unit.simulated_trading.test_corporate_action_tax_liability_evidence import _material


def _header_and_allocations():
    assessment = _taxable_assessment()
    action, history, policy = assessment.action, assessment.history, assessment.policy
    semantic = json.loads(assessment.semantic_payload_json)
    calculation = semantic["calculation"]
    calculation_json = canonical_json(calculation)
    header = Header(
        pk=1,
        account_id=assessment.account_id,
        owner_user_id=assessment.owner_user_id,
        assessment_revision_id=assessment.assessment_revision_id,
        supersedes_assessment_revision_id=assessment.supersedes_assessment_revision_id,
        asset_code=assessment.asset_code,
        security_id=assessment.security_id,
        corporate_action_id=action.corporate_action_id,
        source_namespace=action.source_namespace,
        source_record_id=action.source_record_id,
        source_event_id=action.source_event_id,
        action_source_revision_id=action.source_revision_id,
        action_source_revision_sha256=action.source_revision_sha256,
        action_source_payload_sha256=action.source_payload_sha256,
        settlement_source_revision_id=history.source_revision_id,
        settlement_source_revision_sha256=history.source_revision_sha256,
        record_date=history.record_date,
        settlement_date=assessment.target_settlement_date,
        settlement_date_rule_id=history.settlement_date_rule_id,
        settlement_date_rule_sha256=history.settlement_date_rule_sha256,
        settlement_calendar_id=history.settlement_calendar_id,
        settlement_calendar_sha256=history.settlement_calendar_sha256,
        policy_id=policy.policy_id,
        policy_version=policy.version,
        policy_source_identity=policy.source_identity,
        policy_source_sha256=policy.source_sha256,
        policy_sha256=policy.policy_sha256,
        statutory_revision_set_sha256=assessment.statutory_source_bundle.source_revision_set_sha256,
        disposition_id=assessment.calculation.disposition_id,
        idempotency_key=assessment.calculation.idempotency_key,
        semantic_payload_json=assessment.semantic_payload_json,
        semantic_sha256=assessment.semantic_sha256,
        observation_manifest_json=assessment.observation_manifest_json,
        observation_manifest_sha256=assessment.observation_manifest_sha256,
        calculation_payload_json=calculation_json,
        calculation_sha256=material_sha256(calculation_json),
        gross_dividend_amount_text=calculation["gross_dividend_amount"],
        taxable_dividend_amount_text=calculation["taxable_dividend_amount"],
        withholding_amount_text=calculation["withholding_amount"],
        recorded_at=_material().recorded_at,
    )
    allocations = [
        SimpleNamespace(
            ordinal=ordinal,
            lot_id=item["lot_id"],
            allocation_payload_json=canonical_json(item),
            allocation_sha256=material_sha256(canonical_json(item)),
            recorded_at=header.recorded_at,
        )
        for ordinal, item in enumerate(calculation["allocations"], 1)
    ]
    return header, allocations


def _retained_repository(monkeypatch):
    header, allocations = _header_and_allocations()
    manager = Mock()
    manager.using.return_value.filter.return_value.order_by.return_value = allocations
    monkeypatch.setattr(
        assessment_repository, "Allocation", SimpleNamespace(_default_manager=manager)
    )
    return (
        assessment_repository.DjangoCorporateActionTaxAssessmentRepository(using="default"),
        header,
        allocations,
    )


def test_historical_header_matches_full_original_semantics_and_ordered_allocations(monkeypatch):
    repository, header, _ = _retained_repository(monkeypatch)
    assert repository.verify_retained_integrity(header) == json.loads(header.semantic_payload_json)


@pytest.mark.parametrize(
    "field,value",
    [
        ("policy_sha256", "0" * 64),
        ("disposition_id", "other"),
        ("source_event_id", "other"),
        ("withholding_amount_text", "999"),
    ],
)
def test_historical_header_columns_cannot_be_rebound(monkeypatch, field, value):
    repository, header, _ = _retained_repository(monkeypatch)
    setattr(header, field, value)
    with pytest.raises(BusinessLogicError):
        repository.verify_retained_integrity(header)


def test_missing_original_fifo_allocation_is_rejected(monkeypatch):
    repository, header, allocations = _retained_repository(monkeypatch)
    allocations.clear()
    with pytest.raises(BusinessLogicError, match="allocations"):
        repository.verify_retained_integrity(header)


def _readback(monkeypatch):
    material = _material()
    state, transition = material.transition.state_after, material.transition
    header, _ = _header_and_allocations()
    event = build_tax_liability_audit_event(material, predecessor_hash=None)
    outbox = ExactSystemAuditOutboxWinner(
        uuid4(), event, event.event_id, event.idempotency_key, event.content_hash
    )
    row = Operation(
        pk=1,
        account_id=state.scope.account_id,
        owner_user_id=state.scope.owner_user_id,
        assessment_id=1,
        operation_id=material.identity.operation_id,
        operation_request_sha256=material.identity.request_sha256,
        scope_sha256=tax_liability_scope_sha256(state.scope),
        sequence=1,
        canonical_account_namespace="account",
        canonical_account_id=material.identity.canonical_account_id,
        currency="CNY",
        state_payload_json=encode_liability_state(state),
        state_sha256=state.state_sha256,
        transition_payload_json=encode_liability_transition(transition),
        transition_sha256=transition.transition_sha256,
        operation_payload_json=material.payload_json,
        operation_sha256=material.content_sha256,
        assessed_amount_text=_decimal(state.assessed_amount),
        net_collected_amount_text=_decimal(state.net_collected_amount),
        outstanding_amount_text=_decimal(state.outstanding_amount),
        tax_due_delta_text=_decimal(transition.tax_due_delta),
        collected_delta_text=_decimal(transition.collected_delta),
        outstanding_delta_text=_decimal(transition.outstanding_delta),
        cash_delta_text=_decimal(transition.cash_delta),
        audit_event_id=event.event_id,
        audit_event_version=event.event_version,
        audit_event_sha256=event.content_hash,
        outbox_record_id=str(outbox.outbox_id),
        outbox_payload_sha256=outbox.payload_hash,
        recorded_at=material.recorded_at,
    )
    manager = Mock()
    manager.using.return_value.select_for_update.return_value.get.return_value = header
    monkeypatch.setattr(readback, "Header", SimpleNamespace(_default_manager=manager))
    audit = Mock(database_alias="default")
    audit.get_winner_targeted.return_value = event
    audit.get_exact_outbox_winner_targeted.return_value = outbox
    verifier = readback.DjangoTaxLiabilityReadback(
        using="default", audit=audit, assessment_audit=Mock()
    )
    monkeypatch.setattr(verifier, "verify_assessment", Mock())
    return verifier, row, material, audit


def test_financial_readback_returns_original_exact_journal_and_outbox_refs(monkeypatch):
    verifier, row, material, audit = _readback(monkeypatch)
    verified = verifier._verify_row(row, prior=None, as_of=material.recorded_at)
    assert verified.material == material
    assert verified.receipt.outbox_record.reference_id == row.outbox_record_id
    assert verified.receipt.cash_snapshot_reference == material.cash_snapshot.evidence
    audit.append_and_enqueue_targeted.assert_not_called()


@pytest.mark.parametrize("missing", ["audit", "outbox"])
def test_missing_original_financial_evidence_blocks_without_repair(monkeypatch, missing):
    verifier, row, material, audit = _readback(monkeypatch)
    if missing == "audit":
        audit.get_winner_targeted.return_value = None
    else:
        audit.get_exact_outbox_winner_targeted.return_value = None
    with pytest.raises(BusinessLogicError, match="repair is forbidden"):
        verifier._verify_row(row, prior=None, as_of=material.recorded_at)
    audit.append_and_enqueue_targeted.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("operation_request_sha256", "0" * 64),
        ("cash_delta_text", "-999"),
        ("assessment_id", 2),
        ("outbox_record_id", "different"),
    ],
)
def test_original_financial_columns_cannot_be_rebound(monkeypatch, field, value):
    verifier, row, material, _ = _readback(monkeypatch)
    setattr(row, field, value)
    with pytest.raises(BusinessLogicError):
        verifier._verify_row(row, prior=None, as_of=material.recorded_at)
