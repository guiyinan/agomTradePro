"""Focused in-memory contracts for immutable assessment retry evidence."""

from copy import copy
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from apps.audit.application.system_audit_event_outbox import ExactSystemAuditOutboxWinner
from apps.audit.domain.system_audit_event import AuditScopeRef, AuditWritePolicy
from apps.simulated_trading import (
    audited_corporate_action_tax_assessment_composition as composition,
)
from apps.simulated_trading.application.corporate_action_tax_assessment import (
    TaxAssessmentExactReplayEvidence,
)
from apps.simulated_trading.application.corporate_action_tax_window_proof import (
    CorporateActionTaxWindowProof,
)
from apps.simulated_trading.domain.corporate_action_tax_assessment import (
    CorporateActionTaxAssessment,
)
from apps.simulated_trading.infrastructure import (
    corporate_action_tax_assessment_repository as repository_module,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_repository import (
    StoredTaxAssessment,
)
from core.exceptions import BusinessLogicError
from tests.unit.simulated_trading.test_audited_corporate_action_tax_assessment_composition import (
    _header,
)
from tests.unit.simulated_trading.test_corporate_action_current_official_window import (
    _request,
)
from tests.unit.simulated_trading.test_corporate_action_tax_assessment import _assessment
from tests.unit.simulated_trading.test_corporate_action_tax_assessment_application import (
    _lease,
)
from tests.unit.simulated_trading.test_corporate_action_window_audit_composition import (
    _evidence,
)


def _szse_assessment() -> CorporateActionTaxAssessment:
    """Build a synthetic SZSE assessment aligned with the official-window contract."""
    base = _assessment()
    asset_code = "000001.SZ"
    history = base.history
    ownership = replace(
        history.record_date_ownership_proof,
        asset_code=asset_code,
        security_id=asset_code,
    )
    days = tuple(
        replace(row, asset_code=asset_code, security_id=asset_code)
        for row in history.settlement_days
    )
    history = replace(
        history,
        asset_code=asset_code,
        security_id=asset_code,
        record_date_ownership_proof=ownership,
        settlement_days=days,
    )
    action = replace(
        base.action,
        asset_code=asset_code,
        security_id=asset_code,
        source_namespace="exchange_official_disclosure",
        source_record_id="synthetic-szse-record-1",
        source_event_id="synthetic-szse-event-1",
        source_revision_id="synthetic-szse-revision-1",
        source_revision_sha256="c" * 64,
        source_payload_sha256="d" * 64,
        effective_date=date(2026, 11, 2),
    )
    return _assessment(action=action, history=history)


def _window_proof(
    assessment: CorporateActionTaxAssessment,
    *,
    canonical_account_id: str,
    environment: str = "test",
    checked_at: datetime | None = None,
) -> CorporateActionTaxWindowProof:
    """Build complete synthetic window evidence bound to one exact assessment."""
    action = assessment.action
    evidence_checked_at = (
        datetime(2026, 11, 13, 4, 0, 1, tzinfo=UTC) if checked_at is None else checked_at
    )
    request = replace(
        _request(),
        account_id=assessment.account_id,
        owner_user_id=assessment.owner_user_id,
        asset_code=action.asset_code,
        security_id=action.security_id,
        source_namespace=action.source_namespace,
        source_record_id=action.source_record_id,
        source_event_id=action.source_event_id,
        source_revision_id=action.source_revision_id,
        source_payload_sha256=action.source_payload_sha256,
        source_observed_at=evidence_checked_at - timedelta(seconds=10),
        qualified_at=evidence_checked_at - timedelta(seconds=2),
        posted_at=evidence_checked_at - timedelta(seconds=1),
        record_date=action.record_date,
        ownership_snapshot_as_of_date=action.record_date,
        ownership_snapshot_observed_at=evidence_checked_at - timedelta(seconds=20),
        effective_date=action.effective_date,
    )
    original = _evidence()
    provenance = replace(
        original.policy_provenance,
        runtime_environment=environment,
        known_at=evidence_checked_at - timedelta(days=2),
        effective_at=evidence_checked_at - timedelta(days=1),
    )
    window = replace(
        original,
        account_id=assessment.account_id,
        owner_user_id=assessment.owner_user_id,
        asset_code=action.asset_code,
        security_id=action.security_id,
        source_record_id=action.source_record_id,
        source_revision_id=action.source_revision_id,
        source_payload_sha256=action.source_payload_sha256,
        source_observed_at=request.source_observed_at,
        original_first_observed_at=evidence_checked_at - timedelta(seconds=9),
        original_listing_verified_at=evidence_checked_at - timedelta(seconds=8),
        original_proof_recorded_at=evidence_checked_at - timedelta(seconds=7),
        checked_at=evidence_checked_at,
        expires_at=evidence_checked_at + timedelta(seconds=60),
        runtime_environment=environment,
        selected_event_sha256=action.source_revision_sha256,
        policy_provenance=provenance,
    )
    return CorporateActionTaxWindowProof(
        assessment.semantic_sha256,
        canonical_account_id,
        request,
        window,
    )


def _candidate(
    *, include_window_proof: bool = True
) -> tuple[CorporateActionTaxAssessment, object, object]:
    """Build one exact in-memory retained assessment and its paired Audit winner."""
    assessment = _szse_assessment() if include_window_proof else _assessment()
    header = _header()
    proof = None
    if include_window_proof:
        proof = _window_proof(assessment, canonical_account_id="canonical-simulated-account")
        action = assessment.action
        header.assessment_revision_id = assessment.assessment_revision_id
        header.corporate_action_id = action.corporate_action_id
        header.record_date = assessment.history.record_date
        header.settlement_date = assessment.target_settlement_date
        header.disposition_id = assessment.calculation.disposition_id
        header.idempotency_key = assessment.calculation.idempotency_key
        header.asset_code = action.asset_code
        header.security_id = action.security_id
        header.source_namespace = action.source_namespace
        header.source_record_id = action.source_record_id
        header.source_event_id = action.source_event_id
        header.action_source_revision_id = action.source_revision_id
        header.action_source_revision_sha256 = action.source_revision_sha256
        header.action_source_payload_sha256 = action.source_payload_sha256
        header.semantic_sha256 = assessment.semantic_sha256
        header.observation_manifest_json = assessment.observation_manifest_json
        header.observation_manifest_sha256 = assessment.observation_manifest_sha256
        header.recorded_at = proof.evidence.checked_at + timedelta(seconds=1)
    event = composition._build_event(
        header,
        sequence_no=1,
        predecessor_hash=None,
        official_window_proof=proof,
    )
    outbox = ExactSystemAuditOutboxWinner(
        uuid4(), event, event.event_id, event.idempotency_key, event.content_hash
    )
    return assessment, header, outbox


def _unit(
    monkeypatch: pytest.MonkeyPatch,
    *,
    candidate: StoredTaxAssessment | None,
    winner: object,
    audit_head: object,
    outbox: object,
) -> tuple[composition.DjangoTaxAssessmentAtomicUnitOfWork, Mock]:
    """Build an active caller-owned UOW with only in-memory repository/Audit ports."""
    assessment, header, _ = _candidate()
    del assessment
    audit = Mock(database_alias="default")
    audit.get_winner_targeted.return_value = winner
    audit.get_current_head_targeted.return_value = audit_head
    audit.get_exact_outbox_winner_targeted.return_value = outbox
    unit = composition.DjangoTaxAssessmentAtomicUnitOfWork(
        using="default",
        scope_verifier=Mock(database_alias="default"),
        audit=audit,
        clock=Mock(),
    )
    unit._active = True
    unit._repository = Mock()
    unit._repository.find_exact_semantic_head.return_value = candidate
    unit._repository.read_locked_assessment_lineage.return_value = (
        () if candidate is None else (candidate.header,)
    )
    monkeypatch.setattr(
        composition,
        "connections",
        {"default": SimpleNamespace(in_atomic_block=True)},
    )
    return unit, audit


def test_exact_replay_returns_only_the_verified_retained_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assessment, header, outbox = _candidate()
    event = outbox.event
    scope = AuditScopeRef(header.audit_tenant_id, header.audit_owner_id)
    unit, audit = _unit(
        monkeypatch,
        candidate=StoredTaxAssessment(header, True),
        winner=event,
        audit_head=event,
        outbox=outbox,
    )

    evidence = unit.find_exact_replay(
        assessment,
        actor_user_id=assessment.owner_user_id,
        audit_scope=scope,
        as_of=header.recorded_at + timedelta(seconds=1),
    )

    assert isinstance(evidence, TaxAssessmentExactReplayEvidence)
    assert evidence.assessment_revision_id == header.assessment_revision_id
    assert evidence.semantic_sha256 == assessment.semantic_sha256
    assert evidence.audit_content_sha256 == event.content_hash
    assert evidence.outbox_payload_sha256 == outbox.payload_hash
    audit.lock_streams.assert_called_once()


def test_legacy_exact_pair_without_window_proof_keeps_its_original_bytes_and_does_not_shortcut(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assessment, header, outbox = _candidate(include_window_proof=False)
    event = outbox.event
    unit, audit = _unit(
        monkeypatch,
        candidate=StoredTaxAssessment(header, True),
        winner=event,
        audit_head=event,
        outbox=outbox,
    )

    evidence = unit.find_exact_replay(
        assessment,
        actor_user_id=assessment.owner_user_id,
        audit_scope=AuditScopeRef(header.audit_tenant_id, header.audit_owner_id),
        as_of=header.recorded_at + timedelta(seconds=1),
    )

    assert evidence is None
    assert "current_official_window" not in event.detail
    assert audit.get_current_head_targeted.call_count == 1
    assert audit.get_exact_outbox_winner_targeted.call_count == 1


@pytest.mark.parametrize(
    ("winner", "audit_head", "outbox"),
    [(None, None, None), (object(), object(), None)],
)
def test_exact_head_with_missing_or_different_audit_pair_blocks(
    monkeypatch: pytest.MonkeyPatch,
    winner: object,
    audit_head: object,
    outbox: object,
) -> None:
    assessment, header, _ = _candidate()
    unit, audit = _unit(
        monkeypatch,
        candidate=StoredTaxAssessment(header, True),
        winner=winner,
        audit_head=audit_head,
        outbox=outbox,
    )

    with pytest.raises(BusinessLogicError):
        unit.find_exact_replay(
            assessment,
            actor_user_id=assessment.owner_user_id,
            audit_scope=AuditScopeRef(header.audit_tenant_id, header.audit_owner_id),
            as_of=header.recorded_at + timedelta(seconds=1),
        )

    audit.append_and_enqueue_targeted.assert_not_called()


def test_absent_or_changed_semantic_head_does_not_claim_a_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assessment, header, outbox = _candidate()
    event = outbox.event
    unit, audit = _unit(monkeypatch, candidate=None, winner=event, audit_head=event, outbox=outbox)

    result = unit.find_exact_replay(
        assessment,
        actor_user_id=assessment.owner_user_id,
        audit_scope=AuditScopeRef(header.audit_tenant_id, header.audit_owner_id),
        as_of=header.recorded_at + timedelta(seconds=1),
    )

    assert result is None
    audit.lock_streams.assert_not_called()


@pytest.mark.parametrize("missing_original", [False, True])
def test_changed_request_verifies_original_audit_before_fresh_qualification(
    monkeypatch: pytest.MonkeyPatch, missing_original: bool
) -> None:
    """A changed source revision cannot conceal a broken previously accepted Audit chain."""
    original, header, outbox = _candidate()
    changed = _assessment(
        action=replace(
            original.action,
            source_revision_id="synthetic-successor-source",
            source_revision_sha256="e" * 64,
            source_payload_sha256="f" * 64,
        ),
        history=original.history,
        revision_id="synthetic-new-assessment",
    )
    assert changed.semantic_sha256 != header.semantic_sha256
    assert changed.calculation.idempotency_key == header.idempotency_key
    unit, audit = _unit(
        monkeypatch,
        candidate=StoredTaxAssessment(header, True),
        winner=None if missing_original else outbox.event,
        audit_head=outbox.event,
        outbox=outbox,
    )

    def read():
        return unit.find_exact_replay(
            changed,
            actor_user_id=changed.owner_user_id,
            audit_scope=AuditScopeRef(header.audit_tenant_id, header.audit_owner_id),
            as_of=header.recorded_at + timedelta(seconds=1),
        )

    if missing_original:
        with pytest.raises(BusinessLogicError):
            read()
    else:
        assert read() is None
        audit.get_exact_outbox_winner_targeted.assert_called_once()
    unit._repository.verify_stored.assert_not_called()
    audit.get_winner_targeted.assert_called_once()
    audit.append_and_enqueue_targeted.assert_not_called()


@pytest.mark.parametrize("damage", ["none", "missing_predecessor", "sequence", "predecessor_hash"])
def test_exact_retry_requires_every_original_audit_link(
    monkeypatch: pytest.MonkeyPatch, damage: str
) -> None:
    """A valid last winner cannot hide missing or disconnected earlier Audit evidence."""
    assessment, first, first_outbox = _candidate()
    last = copy(first)
    last.pk = first.pk + 1
    last.assessment_revision_id = "synthetic-successor-revision"
    last.recorded_at += timedelta(seconds=1)
    last.supersedes_id = first.pk
    last.supersedes_assessment_revision_id = first.assessment_revision_id
    proof = composition.read_retained_tax_assessment_window_proof(first, first_outbox.event)
    last_event = composition._build_event(
        last,
        sequence_no=3 if damage == "sequence" else 2,
        predecessor_hash=(
            "f" * 64 if damage == "predecessor_hash" else first_outbox.event.content_hash
        ),
        official_window_proof=proof,
    )
    last_outbox = ExactSystemAuditOutboxWinner(
        uuid4(),
        last_event,
        last_event.event_id,
        last_event.idempotency_key,
        last_event.content_hash,
    )
    unit, audit = _unit(
        monkeypatch,
        candidate=StoredTaxAssessment(last, True),
        winner=last_event,
        audit_head=last_event,
        outbox=last_outbox,
    )
    unit._repository.read_locked_assessment_lineage.return_value = (first, last)
    audit.get_winner_targeted.side_effect = lambda *, event_id, **kwargs: (
        (None if damage == "missing_predecessor" else first_outbox.event)
        if event_id == composition._event_id(first)
        else last_event
    )
    audit.get_exact_outbox_winner_targeted.side_effect = lambda event: (
        first_outbox if event == first_outbox.event else last_outbox
    )

    def read():
        return unit.find_exact_replay(
            assessment,
            actor_user_id=assessment.owner_user_id,
            audit_scope=AuditScopeRef(last.audit_tenant_id, last.audit_owner_id),
            as_of=last.recorded_at + timedelta(seconds=1),
        )

    if damage == "none":
        evidence = read()
        assert evidence is not None
        assert evidence.audit_event_id == last_event.event_id
        assert audit.get_winner_targeted.call_count == 2
    else:
        with pytest.raises(BusinessLogicError):
            read()

    audit.append_and_enqueue_targeted.assert_not_called()


def test_changed_semantic_head_must_be_intact_before_it_can_be_a_successor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not route a corrupted prior head into fresh qualification as a change."""
    assessment, header, _ = _candidate()
    header.semantic_sha256 = "f" * 64

    account_row = SimpleNamespace(user_id=assessment.owner_user_id)
    account_manager = Mock()
    account_manager.using.return_value.select_for_update.return_value.filter.return_value.first.return_value = (
        account_row
    )
    header_manager = Mock()
    using_query = header_manager.using.return_value
    using_query.filter.return_value.exclude.return_value.exists.return_value = False
    query = using_query.select_for_update.return_value.filter.return_value
    query.order_by.return_value = (header,)
    monkeypatch.setattr(
        repository_module,
        "SimulatedAccountModel",
        SimpleNamespace(_default_manager=account_manager),
    )
    monkeypatch.setattr(
        repository_module,
        "Header",
        SimpleNamespace(_default_manager=header_manager),
    )
    monkeypatch.setattr(
        repository_module,
        "connections",
        {"default": SimpleNamespace(in_atomic_block=True, vendor="sqlite")},
    )
    repository = repository_module.DjangoCorporateActionTaxAssessmentRepository(using="default")
    verify_head = Mock(side_effect=BusinessLogicError("retained head is corrupt"))
    monkeypatch.setattr(repository, "verify_retained_integrity", verify_head)

    with pytest.raises(BusinessLogicError, match="retained head is corrupt"):
        repository.find_exact_semantic_head(assessment)

    verify_head.assert_called_once_with(header)


def test_expired_original_window_is_historical_only_on_exact_retry_origin() -> None:
    """An expired retained proof can support replay, never a fresh append."""
    assessment = _szse_assessment()
    proof = _window_proof(
        assessment,
        canonical_account_id="canonical-simulated-account",
    )
    window = proof.evidence
    lease = replace(_lease(assessment), valid_until=window.expires_at + timedelta(seconds=1))
    scope = AuditScopeRef("synthetic-tax-tenant", f"user:{assessment.owner_user_id}")
    replay = TaxAssessmentExactReplayEvidence(
        assessment_revision_id=assessment.assessment_revision_id,
        idempotency_key=assessment.calculation.idempotency_key,
        semantic_sha256=assessment.semantic_sha256,
        observation_manifest_sha256=assessment.observation_manifest_sha256,
        recorded_at=window.checked_at + timedelta(seconds=1),
        audit_scope=scope,
        audit_event_id="synthetic-assessment-audit-event",
        audit_content_sha256="a" * 64,
        outbox_id=str(uuid4()),
        outbox_payload_sha256="a" * 64,
        official_window_proof=proof,
    )
    origin = composition.TaxAssessmentAuditOrigin(
        lease,
        scope,
        "b" * 64,
        AuditWritePolicy.TRANSACTIONAL_OUTBOX,
        official_window_proof=proof,
        write_mode="exact_retry_only",
        replay_evidence=replay,
    )

    assert origin.replay_evidence is replay
    with pytest.raises(BusinessLogicError):
        replace(replay, recorded_at=window.expires_at)
    with pytest.raises(BusinessLogicError, match="exact official window"):
        composition.TaxAssessmentAuditOrigin(
            lease,
            scope,
            "b" * 64,
            AuditWritePolicy.TRANSACTIONAL_OUTBOX,
            official_window_proof=proof,
        )
