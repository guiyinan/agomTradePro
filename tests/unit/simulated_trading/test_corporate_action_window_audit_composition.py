"""Retained window evidence is audit material, never renewed write authority."""

from dataclasses import replace
from datetime import timedelta
from typing import cast

import pytest

from apps.audit.domain.system_audit_event import AuditScopeRef
from apps.simulated_trading import audited_corporate_action_posting_composition as audited
from apps.simulated_trading import corporate_action_window_audit_composition as composition
from apps.simulated_trading.application.corporate_action_current_official_window import (
    CorporateActionCurrentOfficialWindowEvidence,
    CorporateActionCurrentOfficialWindowReader,
    CorporateActionCurrentOfficialWindowReason,
)
from apps.simulated_trading.application.corporate_action_posting import (
    CorporateActionPostingBlockedError,
    CorporateActionPostingReceipt,
)
from tests.unit.account.test_simulated_corporate_action_write_grant import _binding, _grant
from tests.unit.simulated_trading.test_corporate_action_current_official_window import (
    _NOW,
    _Clock,
    _reader,
    _request,
)


def _evidence():
    """Run the actual reader over explicitly synthetic public-port facts."""
    reader, _, _ = _reader(clock=_Clock((_NOW, _NOW, _NOW, _NOW)))
    evidence = reader.read_current(_request(), as_of=_NOW)
    assert evidence.window_ready
    return evidence


def test_blocked_window_stops_before_independent_share_model_io(monkeypatch):
    from types import SimpleNamespace

    from tests.unit.simulated_trading.test_corporate_action_share_tax_proof import (
        _request as share_request,
    )

    unavailable = CorporateActionCurrentOfficialWindowEvidence(
        window_ready=False,
        reason_code=CorporateActionCurrentOfficialWindowReason.REQUEST_INVALID,
        freshness_status="unknown",
        reliability_status="unverified",
    )
    gate = composition.CorporateActionWindowAuditGate(
        SimpleNamespace(read_current=lambda *args, **kwargs: unavailable),
        share_tax_reader=SimpleNamespace(
            read_current=lambda *args, **kwargs: pytest.fail(
                "blocked window must not read share model"
            )
        ),
    )
    with pytest.raises(CorporateActionPostingBlockedError, match=unavailable.reason_code.value):
        gate.read_entry_evidence(share_request())


def test_window_retains_complete_share_model_at_original_audit_clock():
    """Full original clauses, runtime selection and instrument refs survive financial readback."""
    from tests.unit.simulated_trading.test_corporate_action_share_tax_model import _query
    from tests.unit.simulated_trading.test_corporate_action_share_tax_proof import (
        _proof,
    )
    from tests.unit.simulated_trading.test_corporate_action_share_tax_proof import (
        _request as share_request,
    )

    original = _evidence()
    base = _request()
    request = replace(
        share_request(),
        account_id=base.account_id,
        owner_user_id=base.owner_user_id,
        source_record_id=base.source_record_id,
        source_event_id=base.source_event_id,
        source_revision_id=base.source_revision_id,
        source_payload_sha256=base.source_payload_sha256,
        source_observed_at=base.source_observed_at,
        qualified_at=base.qualified_at,
        posted_at=base.posted_at,
    )
    query = replace(
        _query(),
        owner_user_id=request.owner_user_id,
        source_record_id=request.source_record_id,
        source_event_id=request.source_event_id,
        source_revision_id=request.source_revision_id,
        source_payload_sha256=request.source_payload_sha256,
        source_observed_at=request.source_observed_at,
    )
    model = replace(
        _proof().model,
        query_semantic_sha256=query.semantic_sha256,
        known_at=_NOW,
        valid_from=_NOW - timedelta(days=1),
        valid_until=_NOW + timedelta(minutes=1),
        checked_at=_NOW,
    )
    proof = replace(
        _proof(),
        query=query,
        model=model,
        environment=original.runtime_environment,
        instrument_response_completed_at=_NOW - timedelta(days=1),
        checked_at=_NOW,
        valid_until=_NOW + timedelta(minutes=1),
    )
    evidence = replace(
        original, share_tax_proof=proof, expires_at=min(original.expires_at, proof.valid_until)
    )
    payload = composition.corporate_action_window_audit_payload(evidence, request, recorded_at=_NOW)
    restored = composition.restore_corporate_action_window_audit_evidence(
        payload, request, recorded_at=_NOW
    )
    assert restored.share_tax_proof == proof
    assert restored.share_tax_proof.model.source_terms == model.source_terms
    # The original clock validates historical material; no current service is consulted.
    assert restored.share_tax_proof.checked_at == _NOW


def test_retained_window_roundtrip_preserves_original_clocks_without_current_refresh() -> None:
    """Historical readback uses the original Audit clock and original lease."""
    evidence = _evidence()
    request = _request()
    payload = composition.corporate_action_window_audit_payload(evidence, request, recorded_at=_NOW)
    assert payload["must_not_use_for_decision"] is True
    assert payload["freshness_at_check"] == "current"
    restored = composition.restore_corporate_action_window_audit_evidence(
        payload, request, recorded_at=_NOW
    )
    assert restored == evidence
    assert restored.expires_at == evidence.expires_at


@pytest.mark.parametrize(
    "failure", ["owner", "body", "checked", "expired", "extra", "boolean", "boolean_number"]
)
def test_window_audit_readback_rejects_identity_clock_and_shape_changes(failure: str) -> None:
    """Publicly recomputable hashes and arbitrary JSON cannot replace exact evidence."""
    request = _request()
    payload = composition.corporate_action_window_audit_payload(
        _evidence(), request, recorded_at=_NOW
    )
    if failure == "owner":
        payload["owner_user_id"] = 999
    elif failure == "body":
        payload["source_payload_sha256"] = "f" * 64
    elif failure == "checked":
        payload["checked_at"] = (_NOW + timedelta(seconds=1)).isoformat()
    elif failure == "extra":
        payload["extra"] = "ignored"
    elif failure == "boolean":
        payload["must_not_use_for_decision"] = False
    elif failure == "boolean_number":
        payload["window_ready"] = 1
    recorded_at = _NOW + timedelta(days=1) if failure == "expired" else _NOW
    with pytest.raises(CorporateActionPostingBlockedError):
        composition.restore_corporate_action_window_audit_evidence(
            payload, request, recorded_at=recorded_at
        )


@pytest.mark.parametrize("change", ["scope", "backwards"])
def test_final_window_gate_rejects_new_window_metadata_after_posting(
    monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    """A refreshed listing scope cannot silently replace the scope attached to Audit."""
    first = _evidence()
    later = (
        replace(first, scope_sha256="f" * 64)
        if change == "scope"
        else replace(first, checked_at=_NOW - timedelta(seconds=1))
    )
    states = iter((first, later))

    class Reader:
        def read_current(self, request, *, as_of):
            return next(states)

    monkeypatch.setattr(composition.timezone, "now", lambda: _NOW)
    gate = composition.CorporateActionWindowAuditGate(
        cast(CorporateActionCurrentOfficialWindowReader, Reader())
    )
    captured = gate.read_entry_evidence(_request())
    with pytest.raises(CorporateActionPostingBlockedError):
        gate.assert_unchanged(_request(), captured)


def test_posting_audit_retains_exact_window_and_replays_it_at_original_clock() -> None:
    """The financial Audit binds the window while original V1 material stays readable."""
    request = _request()
    evidence = _evidence()
    grant = _grant(binding=_binding(owner_user_id=request.owner_user_id))
    scope = AuditScopeRef(tenant_id=grant.binding.tenant_id, owner_id=grant.binding.owner_id)
    receipt = CorporateActionPostingReceipt(41, 1, request.stage_key, request.payload_sha256, False)
    kwargs = {
        "recorded_at": _NOW + timedelta(seconds=1),
        "sequence_no": 1,
        "predecessor_hash": None,
        "scope": scope,
        "owner_grant": grant,
    }
    old = audited._build_event(request, receipt, **kwargs)
    event = audited._build_event(request, receipt, window_evidence=evidence, **kwargs)
    assert "current_official_window" not in old.detail
    assert event.detail[
        "current_official_window"
    ] == composition.corporate_action_window_audit_payload(
        evidence,
        request,
        recorded_at=event.recorded_at,
    )
    assert any(
        ref.artifact_type == "official_corporate_action_window" for ref in event.evidence_refs
    )
    for retained in (old, event):
        assert audited.DjangoAuditedCorporateActionPostingRepository._matches_winner(
            retained,
            request,
            receipt,
            scope,
            owner_grant=grant,
        )
