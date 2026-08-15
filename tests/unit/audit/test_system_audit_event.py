from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from apps.audit.domain.system_audit_event import (
    AuditActorRef,
    AuditCategory,
    AuditCorrelations,
    AuditEvidenceRef,
    AuditOutcome,
    AuditResourceRef,
    AuditScopeRef,
    AuditSeverity,
    AuditWritePolicy,
    SystemAuditEvent,
)
from apps.audit.infrastructure.system_audit_event_codec import decode, encode

NOW = datetime(2026, 8, 14, 12, 0, 0, 123456, tzinfo=timezone.utc)
EVIDENCE_HASH = "a" * 64


def make_event(
    *,
    sequence_no: int = 1,
    predecessor_hash: str | None = None,
    event_id: str = "evt-1",
    idempotency_key: str = "fetch:run-1",
    scope: AuditScopeRef | None = AuditScopeRef("tenant:primary", "owner:research"),
) -> SystemAuditEvent:
    return SystemAuditEvent.create(
        event_id=event_id,
        event_version="1",
        schema_version="system-audit-event.v1",
        category=AuditCategory.DATA_RELIABILITY,
        event_type="data.fetch.completed",
        owner="data_center",
        write_policy=AuditWritePolicy.TRANSACTIONAL_OUTBOX,
        outcome=AuditOutcome.SUCCESS,
        severity=AuditSeverity.INFO,
        reason_codes=("fetch_completed",),
        occurred_at=NOW,
        recorded_at=NOW,
        observed_at=NOW,
        actor=AuditActorRef("service", "collector-1", "collector"),
        source_app="data_center",
        source_component="fetch",
        source_surface="celery",
        correlations=AuditCorrelations(
            run_id="run-1",
            ingested_run_id="ingested-1",
            dataset_key="macro.pmi",
            provider_key="provider-a",
            capability="macro.fetch",
        ),
        resource=AuditResourceRef("raw_audit", "raw-1", "1"),
        dataset_key="macro.pmi",
        provider_key="provider-a",
        capability="macro.fetch",
        publication_id=None,
        evidence_refs=(AuditEvidenceRef("data_center", "raw_audit", "raw-1", "1", EVIDENCE_HASH),),
        detail_schema="data.fetch.completed.v1",
        detail={"rows": 2, "source_status": "valid", "nested": {"ok": True}},
        stream_id="dataset:macro.pmi",
        sequence_no=sequence_no,
        predecessor_hash=predecessor_hash,
        idempotency_key=idempotency_key,
        scope=scope,
    )


def test_canonical_roundtrip_and_hashes() -> None:
    event = make_event()
    payload = encode(event)
    restored = decode(payload)
    assert restored == event
    assert encode(restored) == payload
    assert len(event.identity_hash) == 64
    assert len(event.content_hash) == 64


def test_successor_requires_predecessor_and_hash_changes() -> None:
    with pytest.raises(ValueError, match="predecessor"):
        make_event(sequence_no=2)
    successor = make_event(sequence_no=2, predecessor_hash=make_event().content_hash)
    assert successor.content_hash != make_event().content_hash


def test_sensitive_detail_and_noncanonical_reason_are_rejected() -> None:
    with pytest.raises(ValueError, match="sensitive"):
        replace(make_event(), detail={"api_token": "redacted"})
    with pytest.raises(ValueError, match="reason_codes"):
        replace(make_event(), reason_codes=("Bad Code",))


def test_naive_clock_and_bool_sequence_are_rejected() -> None:
    with pytest.raises(ValueError, match="aware"):
        replace(make_event(), occurred_at=datetime.now())
    payload = dict(encode(make_event()))
    payload["sequence_no"] = True
    with pytest.raises(ValueError, match="integer"):
        decode(payload)


def test_codec_rejects_unknown_keys_and_hash_tamper() -> None:
    payload = dict(encode(make_event()))
    payload["unknown"] = "x"
    with pytest.raises(ValueError, match="unknown"):
        decode(payload)
    tampered = dict(encode(make_event()))
    tampered["detail"] = {"rows": 3, "source_status": "valid", "nested": {"ok": True}}
    with pytest.raises(ValueError, match="hash"):
        decode(tampered)


def test_scope_is_canonical_and_legacy_unscoped_payload_remains_explicit() -> None:
    scoped = make_event()
    legacy = make_event(scope=None)

    assert decode(encode(scoped)).scope == AuditScopeRef("tenant:primary", "owner:research")
    assert decode(encode(legacy)).scope is None

    tampered = dict(encode(scoped))
    tampered["scope"] = {"tenant_id": "tenant:other", "owner_id": "owner:research"}
    with pytest.raises(ValueError, match="hash"):
        decode(tampered)


@pytest.mark.parametrize("value", ["", "tenant with space", " tenant:primary", "x" * 193])
def test_scope_tokens_reject_noncanonical_values(value: str) -> None:
    with pytest.raises(ValueError, match="bounded canonical token"):
        AuditScopeRef(value, "owner:research")
