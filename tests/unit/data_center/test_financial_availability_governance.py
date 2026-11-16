"""Pure contract checks for isolated C2 governance value candidates."""

from __future__ import annotations

import hashlib
import json
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4

import pytest

from apps.data_center.application.financial_availability_current import (
    ResolveCurrentFinancialAvailabilityGovernanceQuery,
    resolve_current_financial_availability_governance,
)
from apps.data_center.application.financial_availability_governance import (
    append_and_apply_financial_availability_governance,
    read_financial_availability_governance,
)
from apps.data_center.application.financial_availability_governance_ports import (
    FinancialAvailabilitySessionRequestProof,
    FinancialAvailabilitySourceRead,
    GetFinancialAvailabilityGovernanceQuery,
)
from apps.data_center.domain.financial_availability_governance import (
    ExchangeSessionOpeningRuleProposal,
    FinancialAvailabilityGovernanceRecord,
    FinancialAvailabilityOwnerEventAction,
    FinancialAvailabilityOwnerEventIdentity,
    FinancialAvailabilityRecordKind,
    StatutorySourceCaptureReference,
    _date_evidence_payload,
    resolve_financial_availability_owner_apply,
)
from apps.data_center.domain.financial_next_session_availability import (
    ExchangeSessionOpeningPhase,
)
from apps.data_center.domain.financial_next_session_witness import (
    FinancialDisclosureAvailabilityPolicy,
)
from apps.data_center.domain.statutory_source_documents import (
    StatutorySourceDateEvidence,
    StatutorySourceDatePrecision,
    StatutorySourceDocumentRevision,
)
from apps.data_center.infrastructure.financial_availability_governance_codec import (
    deserialize_financial_availability_owner_event,
    deserialize_financial_availability_record,
    serialize_financial_availability_owner_event,
    serialize_financial_availability_record,
)
from core.exceptions import DataValidationError

BASE = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
BODY = b"official statutory source PDF bytes for candidate tests"


def _source_reference() -> StatutorySourceCaptureReference:
    revision = StatutorySourceDocumentRevision(
        document_id="szse-rules-2026",
        source_version="2026-01",
        canonical_url="https://www.szse.cn/lawrules/official-rules.pdf",
        issuer="SZSE",
        title="Exchange trading rules",
        legal_number="SZSE-RULE-2026",
        publication_date=StatutorySourceDateEvidence(
            precision=StatutorySourceDatePrecision.DATE,
            date_value=date(2026, 1, 1),
        ),
        effective_date=StatutorySourceDateEvidence(
            precision=StatutorySourceDatePrecision.DATE,
            date_value=date(2026, 1, 2),
        ),
        body_sha256=hashlib.sha256(BODY).hexdigest(),
        body_size_bytes=len(BODY),
    )
    capture_id = uuid4()
    return StatutorySourceCaptureReference(
        issuer=revision.issuer,
        document_id=revision.document_id,
        source_version=revision.source_version,
        title=revision.title,
        legal_number=revision.legal_number,
        source_revision_sha256=revision.source_revision_sha256,
        capture_id=capture_id,
        capture_content_type="application/pdf",
        body_reference=f"statutory-source-body:///v1/{capture_id}.body",
        canonical_url=revision.canonical_url,
        body_sha256=revision.body_sha256,
        body_size_bytes=revision.body_size_bytes,
        publication_date=revision.publication_date,
        source_effective_date=revision.effective_date,
        first_seen_at=BASE,
        capture_observed_at=BASE + timedelta(seconds=1),
        revision_recorded_at=BASE + timedelta(seconds=2),
        capture_recorded_at=BASE + timedelta(seconds=3),
    )


def _opening_record() -> FinancialAvailabilityGovernanceRecord:
    source = _source_reference()
    proposal = ExchangeSessionOpeningRuleProposal(
        exchange="SZSE",
        phase=ExchangeSessionOpeningPhase.OPENING_CALL_AUCTION,
        rule_version="2026-v1",
        source_uri=source.canonical_url,
        source_body_sha256=source.body_sha256,
        effective_start=date(2026, 1, 2),
        effective_end=date(2026, 12, 31),
        timezone_name="Asia/Shanghai",
        local_open_time=time(9, 15),
        first_seen_at=source.first_seen_at,
        source_recorded_at=source.revision_recorded_at,
    )
    return FinancialAvailabilityGovernanceRecord(
        record_id="szse-opening-rule",
        record_version=proposal.rule_version,
        exchange="SZSE",
        kind=FinancialAvailabilityRecordKind.OPENING_RULE,
        content=proposal,
        recorded_at=BASE + timedelta(seconds=4),
        source=source,
    )


def _policy_record(
    record_id: str = "szse-financial-availability",
) -> FinancialAvailabilityGovernanceRecord:
    policy = FinancialDisclosureAvailabilityPolicy.create(
        policy_id=record_id,
        policy_version="2026-v1",
        exchange="SZSE",
        opening_phase=ExchangeSessionOpeningPhase.CONTINUOUS_AUCTION,
        effective_start=date(2026, 1, 2),
        effective_end=date(2026, 12, 31),
        calendar_response_max_age_seconds=3600,
        first_seen_at=BASE,
        recorded_at=BASE + timedelta(seconds=4),
    )
    return FinancialAvailabilityGovernanceRecord(
        record_id=policy.policy_id,
        record_version=policy.policy_version,
        exchange=policy.exchange,
        kind=FinancialAvailabilityRecordKind.DISCLOSURE_POLICY,
        content=policy,
        recorded_at=policy.recorded_at,
    )


def _apply_event(
    record: FinancialAvailabilityGovernanceRecord,
    *,
    event_id=None,
    occurred_at: datetime | None = None,
    recorded_at: datetime | None = None,
) -> FinancialAvailabilityOwnerEventIdentity:
    occurred = occurred_at or (record.recorded_at + timedelta(seconds=1))
    recorded = recorded_at or (occurred + timedelta(seconds=1))
    return FinancialAvailabilityOwnerEventIdentity.create(
        action=FinancialAvailabilityOwnerEventAction.APPLY,
        event_id=event_id or uuid4(),
        record=record,
        resulting_content_sha256=record.resulting_content_sha256(approved_at=occurred),
        actor_user_id=42,
        permission_id=17,
        permission_verified_at=occurred - timedelta(seconds=1),
        occurred_at=occurred,
        recorded_at=recorded,
        reason="Owner applied the reviewed source-bound configuration",
    )


def _revoke_event(
    record: FinancialAvailabilityGovernanceRecord,
    apply: FinancialAvailabilityOwnerEventIdentity,
) -> FinancialAvailabilityOwnerEventIdentity:
    occurred = apply.occurred_at + timedelta(hours=1)
    return FinancialAvailabilityOwnerEventIdentity.create(
        action=FinancialAvailabilityOwnerEventAction.REVOKE,
        event_id=uuid4(),
        record=record,
        resulting_content_sha256=apply.resulting_content_sha256,
        actor_user_id=42,
        permission_id=17,
        permission_verified_at=occurred - timedelta(seconds=1),
        occurred_at=occurred,
        recorded_at=occurred + timedelta(seconds=1),
        reason="Owner revoked this exact configuration version",
        predecessor_apply_event_id=apply.event_id,
        predecessor_apply_event_sha256=apply.event_sha256,
    )


class _RecordRepository:
    database_alias = "default"

    def __init__(self, record: FinancialAvailabilityGovernanceRecord, now: datetime) -> None:
        self.record = record
        self.current_time = now

    def now(self) -> datetime:
        return self.current_time

    def atomic(self):
        return nullcontext()

    def lock_change_scope(self, **kwargs):
        del kwargs

    def list_for_effective_date(self, **kwargs):
        del kwargs
        return (self.record,)


class _OwnerEvents:
    database_alias = "default"

    def __init__(self, events: tuple[FinancialAvailabilityOwnerEventIdentity, ...]) -> None:
        self.events = events

    def list_complete_history(self, **kwargs):
        record_id = kwargs["record_id"]
        record_version = kwargs["record_version"]
        return tuple(
            event
            for event in self.events
            if event.record_id == record_id and event.record_version == record_version
        )


class _SourceReader:
    database_alias = "default"

    def __init__(self, source_read: FinancialAvailabilitySourceRead) -> None:
        self.source_read = source_read
        self.requested_known_at: datetime | None = None

    def read_exact_capture(self, **kwargs):
        self.requested_known_at = kwargs["known_at"]
        return self.source_read


def test_opening_record_roundtrip_binds_source_native_revision_and_capture() -> None:
    record = _opening_record()

    decoded = deserialize_financial_availability_record(
        serialize_financial_availability_record(record)
    )

    assert decoded == record
    assert decoded.content_sha256 == record.content_sha256
    assert decoded.source is not None
    assert decoded.source.source_revision_sha256 == record.source.source_revision_sha256


def test_policy_roundtrip_preserves_explicit_phase_and_ttl() -> None:
    record = _policy_record()

    decoded = deserialize_financial_availability_record(
        serialize_financial_availability_record(record)
    )

    assert decoded == record
    assert decoded.content == record.content


def test_opening_rule_proposal_has_no_approval_clock_and_apply_derives_final_hash() -> None:
    record = _opening_record()
    first = record.resulting_content_sha256(approved_at=BASE + timedelta(minutes=1))
    second = record.resulting_content_sha256(approved_at=BASE + timedelta(minutes=2))

    assert "approved_at" not in record.content.to_payload()
    assert first != second
    assert record.content_sha256 != first


def test_source_revision_native_fields_must_match_source_revision_hash() -> None:
    source = _source_reference()

    with pytest.raises(ValueError, match="source revision hash"):
        replace(source, title="different official title")


def test_record_hash_binds_exact_capture_selector() -> None:
    record = _opening_record()
    changed_source = replace(record.source, capture_id=uuid4())

    changed_record = replace(record, source=changed_source)
    assert changed_record.content_sha256 != record.content_sha256


def test_owner_event_roundtrip_and_content_tamper_are_detected() -> None:
    event = _apply_event(_opening_record())
    encoded = serialize_financial_availability_owner_event(event)

    assert deserialize_financial_availability_owner_event(encoded) == event
    changed = json.loads(encoded)
    changed["reason"] = "changed after append"
    with pytest.raises(ValueError, match="event hash"):
        deserialize_financial_availability_owner_event(
            json.dumps(changed, separators=(",", ":")).encode()
        )


def test_apply_resolution_is_knowledge_time_bounded_and_revocation_is_append_only() -> None:
    record = _opening_record()
    apply = _apply_event(record)
    revoke = _revoke_event(record, apply)
    server_now = revoke.recorded_at + timedelta(seconds=1)

    assert (
        resolve_financial_availability_owner_apply(
            record, (apply,), known_at=record.recorded_at, server_now=server_now
        )
        is None
    )
    assert (
        resolve_financial_availability_owner_apply(
            record,
            (apply, revoke),
            known_at=apply.recorded_at,
            server_now=server_now,
        )
        == apply
    )
    assert (
        resolve_financial_availability_owner_apply(
            record,
            (apply, revoke),
            known_at=revoke.recorded_at,
            server_now=server_now,
        )
        is None
    )


def test_future_cutoff_and_future_event_clock_fail_closed() -> None:
    record = _opening_record()
    event = _apply_event(record)

    with pytest.raises(ValueError, match="later than database server time"):
        resolve_financial_availability_owner_apply(
            record,
            (event,),
            known_at=event.recorded_at + timedelta(seconds=1),
            server_now=event.recorded_at,
        )
    with pytest.raises(ValueError, match="future knowledge clock"):
        resolve_financial_availability_owner_apply(
            record,
            (event,),
            known_at=record.recorded_at,
            server_now=event.occurred_at - timedelta(seconds=1),
        )


def test_duplicate_apply_event_history_is_ambiguous_and_blocked() -> None:
    record = _opening_record()
    first = _apply_event(record)
    second = _apply_event(
        record,
        occurred_at=first.occurred_at + timedelta(minutes=1),
        recorded_at=first.recorded_at + timedelta(minutes=1),
    )

    with pytest.raises(ValueError, match="one apply"):
        resolve_financial_availability_owner_apply(
            record,
            (first, second),
            known_at=second.recorded_at,
            server_now=second.recorded_at,
        )


def test_event_app_label_and_codename_are_part_of_permission_identity() -> None:
    event = _apply_event(_policy_record())
    encoded = json.loads(serialize_financial_availability_owner_event(event))
    encoded["permission_app_label"] = "another_app"

    with pytest.raises(ValueError, match="dedicated C2 permission"):
        deserialize_financial_availability_owner_event(
            json.dumps(encoded, separators=(",", ":")).encode()
        )


def test_duplicate_json_keys_are_rejected() -> None:
    raw = b'{"schema":"data_center.financial-availability-record.v1","schema":"other"}'

    with pytest.raises(ValueError, match="duplicate JSON object key"):
        deserialize_financial_availability_record(raw)


def test_source_reference_rejects_naive_observation_clock() -> None:
    source = _source_reference()

    with pytest.raises(ValueError, match="aware UTC datetime"):
        replace(source, first_seen_at=datetime(2026, 1, 2))


def test_source_bytes_must_be_visible_at_explicit_knowledge_cutoff() -> None:
    source = _source_reference()

    with pytest.raises(ValueError, match="not knowable at the requested cutoff"):
        FinancialAvailabilitySourceRead(
            reference=source,
            body=BODY,
            checked_at=BASE + timedelta(seconds=4),
            known_at=BASE + timedelta(seconds=2),
        )


def test_source_body_must_match_exact_digest_and_size() -> None:
    with pytest.raises(ValueError, match="source bytes differ"):
        FinancialAvailabilitySourceRead(
            reference=_source_reference(),
            body=b"different source bytes",
            checked_at=BASE + timedelta(seconds=4),
            known_at=BASE + timedelta(seconds=4),
        )


def test_application_read_rereads_exact_source_and_returns_applied_rule() -> None:
    record = _opening_record()
    apply = _apply_event(record)
    known_at = apply.recorded_at
    database_server_now = known_at + timedelta(minutes=2)
    transaction_opened_at = BASE + timedelta(seconds=2)
    source_read = FinancialAvailabilitySourceRead(
        reference=record.source,
        body=BODY,
        checked_at=database_server_now,
        known_at=known_at,
    )
    source_reader = _SourceReader(source_read)

    result = read_financial_availability_governance(
        GetFinancialAvailabilityGovernanceQuery(
            kind=FinancialAvailabilityRecordKind.OPENING_RULE,
            exchange="SZSE",
            effective_on=date(2026, 6, 30),
            known_at=known_at,
        ),
        records=_RecordRepository(record, database_server_now),
        owner_events=_OwnerEvents((apply,)),
        source_reader=source_reader,
    )

    assert result.apply_event == apply
    assert result.source_read == source_read
    assert result.resolved_content.rule_sha256 == apply.resulting_content_sha256
    assert record.source.capture_recorded_at > transaction_opened_at
    assert record.source.capture_recorded_at < known_at
    assert source_reader.requested_known_at == known_at
    assert result.known_at == known_at


def test_application_read_blocks_changed_exact_source_reference() -> None:
    record = _opening_record()
    apply = _apply_event(record)
    known_at = apply.recorded_at
    changed_capture = replace(
        record.source,
        capture_id=uuid4(),
        body_reference=f"statutory-source-body:///v1/{uuid4()}.body",
    )
    source_read = FinancialAvailabilitySourceRead(
        reference=changed_capture,
        body=BODY,
        checked_at=known_at,
        known_at=known_at,
    )

    with pytest.raises(DataValidationError, match="exact source revision/capture"):
        read_financial_availability_governance(
            GetFinancialAvailabilityGovernanceQuery(
                kind=FinancialAvailabilityRecordKind.OPENING_RULE,
                exchange="SZSE",
                effective_on=date(2026, 6, 30),
                known_at=known_at,
            ),
            records=_RecordRepository(record, known_at),
            owner_events=_OwnerEvents((apply,)),
            source_reader=_SourceReader(source_read),
        )


def test_application_read_requires_one_active_version() -> None:
    record = _policy_record()
    apply = _apply_event(record)
    second_record = _policy_record("szse-financial-availability-other")

    class _TwoRecordRepository(_RecordRepository):
        def list_for_effective_date(self, **kwargs):
            del kwargs
            return (self.record, second_record)

    second = _apply_event(
        second_record,
        occurred_at=apply.occurred_at + timedelta(minutes=1),
        recorded_at=apply.recorded_at + timedelta(minutes=1),
    )
    known_at = second.recorded_at

    with pytest.raises(DataValidationError, match="Multiple applied"):
        read_financial_availability_governance(
            GetFinancialAvailabilityGovernanceQuery(
                kind=FinancialAvailabilityRecordKind.DISCLOSURE_POLICY,
                exchange="SZSE",
                effective_on=date(2026, 6, 30),
                known_at=known_at,
            ),
            records=_TwoRecordRepository(record, known_at),
            owner_events=_OwnerEvents((apply, second)),
            source_reader=_SourceReader(
                FinancialAvailabilitySourceRead(
                    reference=_source_reference(),
                    body=BODY,
                    checked_at=known_at,
                    known_at=known_at,
                )
            ),
        )


@pytest.mark.parametrize(
    "changes",
    (
        {"canonical_url": "http://example.invalid/source.pdf"},
        {"capture_id": "not-a-uuid"},
        {"body_sha256": "not-a-digest"},
        {"body_size_bytes": True},
        {"publication_date": object()},
        {"first_seen_at": BASE + timedelta(seconds=10)},
        {"revision_recorded_at": BASE + timedelta(seconds=10)},
    ),
)
def test_source_reference_rejects_untrusted_shapes_and_clock_order(changes) -> None:
    with pytest.raises(ValueError):
        replace(_source_reference(), **changes).__post_init__()


def test_native_source_date_codec_preserves_date_instant_and_unknown_precision() -> None:
    instant = StatutorySourceDateEvidence(
        precision=StatutorySourceDatePrecision.INSTANT,
        instant_value=BASE,
    )
    unknown = StatutorySourceDateEvidence(precision=StatutorySourceDatePrecision.UNKNOWN)

    assert _date_evidence_payload(instant) == {
        "precision": "instant",
        "date_value": None,
        "instant_value": BASE.isoformat(timespec="microseconds"),
    }
    assert _date_evidence_payload(unknown) == {
        "precision": "unknown",
        "date_value": None,
        "instant_value": None,
    }


@pytest.mark.parametrize(
    "changes",
    (
        {"exchange": ""},
        {"phase": "continuous"},
        {"rule_version": ""},
        {"source_uri": "http://example.invalid/rules.pdf"},
        {"effective_end": date(2025, 12, 31)},
        {"timezone_name": "Mars/Phobos"},
        {"local_open_time": time(9, 15, tzinfo=UTC)},
        {"first_seen_at": BASE + timedelta(days=2)},
    ),
)
def test_opening_rule_proposal_rejects_missing_or_invalid_source_policy_fields(changes) -> None:
    proposal = _opening_record().content

    with pytest.raises(ValueError):
        replace(proposal, **changes).__post_init__()


def test_applied_opening_rule_requires_actual_persist_and_approval_order() -> None:
    proposal = _opening_record().content

    with pytest.raises(ValueError, match="row predates its source"):
        proposal.materialize_applied_rule(
            recorded_at=BASE + timedelta(seconds=1),
            approved_at=BASE + timedelta(seconds=5),
        )
    with pytest.raises(ValueError, match="before its configuration row"):
        proposal.materialize_applied_rule(
            recorded_at=BASE + timedelta(seconds=4),
            approved_at=BASE + timedelta(seconds=3),
        )


def test_governance_record_requires_exact_kind_content_and_source_bindings() -> None:
    opening = _opening_record()
    policy = _policy_record()

    with pytest.raises(ValueError, match="exact financial availability record kind"):
        replace(opening, kind="opening_rule").__post_init__()
    with pytest.raises(ValueError, match="unapplied rule proposal"):
        replace(opening, content=policy.content).__post_init__()
    with pytest.raises(ValueError, match="exact retained source capture"):
        replace(opening, source=None).__post_init__()
    with pytest.raises(ValueError, match="exact source/record clocks"):
        replace(opening, exchange="SSE").__post_init__()
    with pytest.raises(ValueError, match="exact typed policy"):
        replace(policy, content=opening.content).__post_init__()
    with pytest.raises(ValueError, match="unrelated source capture"):
        replace(policy, source=opening.source).__post_init__()
    with pytest.raises(ValueError, match="record identity/knowledge clock"):
        replace(policy, record_id="other-policy").__post_init__()


@pytest.mark.parametrize(
    "changes",
    (
        {"action": "apply"},
        {"event_id": "not-a-uuid"},
        {"actor_user_id": True},
        {"permission_id": False},
        {"permission_codename": "publish_exchange_calendar"},
        {"reason": ""},
        {"occurred_at": BASE},
        {"predecessor_apply_event_id": uuid4()},
    ),
)
def test_owner_apply_event_rejects_invalid_actor_permission_and_clock(changes) -> None:
    event = _apply_event(_opening_record())

    with pytest.raises(ValueError):
        replace(event, **changes).__post_init__()


def test_owner_revoke_requires_exact_predecessor_and_actor_id_is_canonical() -> None:
    record = _opening_record()
    apply = _apply_event(record)
    revoke = _revoke_event(record, apply)

    with pytest.raises(ValueError, match="exact apply event"):
        replace(revoke, predecessor_apply_event_id=None).__post_init__()
    assert apply.actor_id == f"django-user:{apply.actor_user_id}"


def test_owner_apply_resolver_rejects_corrupt_and_mismatched_histories() -> None:
    record = _opening_record()
    apply = _apply_event(record)
    server_now = apply.recorded_at + timedelta(minutes=2)

    with pytest.raises(ValueError, match="future-dated"):
        resolve_financial_availability_owner_apply(
            record,
            (apply,),
            known_at=record.recorded_at - timedelta(seconds=1),
            server_now=record.recorded_at - timedelta(seconds=1),
        )
    with pytest.raises(ValueError, match="immutable tuple"):
        resolve_financial_availability_owner_apply(
            record,
            [apply],
            known_at=apply.recorded_at,
            server_now=server_now,
        )
    assert (
        resolve_financial_availability_owner_apply(
            record,
            (),
            known_at=apply.recorded_at,
            server_now=server_now,
        )
        is None
    )
    with pytest.raises(ValueError, match="untyped item"):
        resolve_financial_availability_owner_apply(
            record,
            (object(),),
            known_at=apply.recorded_at,
            server_now=server_now,
        )
    with pytest.raises(ValueError, match="duplicate event ID"):
        resolve_financial_availability_owner_apply(
            record,
            (apply, apply),
            known_at=apply.recorded_at,
            server_now=server_now,
        )
    with pytest.raises(ValueError, match="differs from the exact configuration"):
        resolve_financial_availability_owner_apply(
            _policy_record(),
            (apply,),
            known_at=apply.recorded_at,
            server_now=server_now,
        )


def test_owner_apply_resolver_recomputes_result_and_exact_revoke_link() -> None:
    record = _opening_record()
    apply = _apply_event(record)
    wrong_result = FinancialAvailabilityOwnerEventIdentity.create(
        action=FinancialAvailabilityOwnerEventAction.APPLY,
        event_id=uuid4(),
        record=record,
        resulting_content_sha256="0" * 64,
        actor_user_id=apply.actor_user_id,
        permission_id=apply.permission_id,
        permission_verified_at=apply.permission_verified_at,
        occurred_at=apply.occurred_at + timedelta(seconds=2),
        recorded_at=apply.recorded_at + timedelta(seconds=2),
        reason="incorrect result hash test",
    )
    with pytest.raises(ValueError, match="result hash"):
        resolve_financial_availability_owner_apply(
            record,
            (wrong_result,),
            known_at=wrong_result.recorded_at,
            server_now=wrong_result.recorded_at,
        )

    wrong_revoke = FinancialAvailabilityOwnerEventIdentity.create(
        action=FinancialAvailabilityOwnerEventAction.REVOKE,
        event_id=uuid4(),
        record=record,
        resulting_content_sha256=apply.resulting_content_sha256,
        actor_user_id=apply.actor_user_id,
        permission_id=apply.permission_id,
        permission_verified_at=apply.permission_verified_at,
        occurred_at=apply.occurred_at + timedelta(minutes=1),
        recorded_at=apply.recorded_at + timedelta(minutes=1),
        reason="wrong predecessor test",
        predecessor_apply_event_id=uuid4(),
        predecessor_apply_event_sha256="a" * 64,
    )
    with pytest.raises(ValueError, match="exact apply event"):
        resolve_financial_availability_owner_apply(
            record,
            (apply, wrong_revoke),
            known_at=wrong_revoke.recorded_at,
            server_now=wrong_revoke.recorded_at,
        )


def test_apply_command_preserves_explicit_source_cutoff_through_owner_port() -> None:
    record = _opening_record()
    event = _apply_event(record)
    known_at = BASE + timedelta(seconds=3)
    proof = FinancialAvailabilitySessionRequestProof(
        user_id=42,
        session_key="session-key-redacted",
        request_authenticated_at=BASE,
        request_user_database_alias="default",
        database_alias="default",
    )

    class _WriteRecords(_RecordRepository):
        def append_record(self, pending):
            self.appended_record = pending
            return pending

    class _WriteOwnerEvents(_OwnerEvents):
        def append_apply_event(self, **kwargs):
            self.requested_known_at = kwargs["known_at"]
            self.appended_record = kwargs["record"]
            return event

    class _WriteAuthorizer:
        database_alias = "default"

        def lock_authorized_principal(self, request_proof):
            assert request_proof == proof
            return nullcontext(object())

    records = _WriteRecords(record, BASE + timedelta(minutes=2))
    owner_events = _WriteOwnerEvents((event,))
    persisted, applied = append_and_apply_financial_availability_governance(
        record,
        proof=proof,
        reason="synthetic orchestration assertion",
        source_known_at=known_at,
        records=records,
        owner_events=owner_events,
        authorizer=_WriteAuthorizer(),
    )

    assert persisted is record
    assert applied is event
    assert records.appended_record is record
    assert owner_events.appended_record is record
    assert owner_events.requested_known_at == known_at


def test_current_pair_locks_both_scopes_and_all_events_before_sampling_cutoff() -> None:
    opening = _opening_record()
    policy = _policy_record()
    opening_apply = _apply_event(opening)
    policy_apply = _apply_event(policy)
    locked_at = BASE + timedelta(minutes=5)
    later_checked_at = locked_at + timedelta(seconds=2)
    order: list[str] = []

    class _CurrentRecords:
        database_alias = "default"

        def require_caller_owned_current_uow(self):
            order.append("uow")

        def lock_current_scopes(self, scopes):
            assert scopes == (
                (FinancialAvailabilityRecordKind.OPENING_RULE, "SZSE"),
                (FinancialAvailabilityRecordKind.DISCLOSURE_POLICY, "SZSE"),
            )
            order.append("scope")

        def list_scope_for_current_update(self, *, kind, exchange):
            assert exchange == "SZSE"
            order.append(f"rows:{kind.value}")
            return (opening,) if kind is FinancialAvailabilityRecordKind.OPENING_RULE else (policy,)

        def now(self):
            order.append("clock")
            return locked_at if order.count("clock") == 1 else later_checked_at

    class _CurrentEvents:
        database_alias = "default"

        def list_complete_history_for_update(self, *, record_id, record_version):
            order.append(f"events:{record_id}:{record_version}")
            return (opening_apply,) if record_id == opening.record_id else (policy_apply,)

    source_read = FinancialAvailabilitySourceRead(
        reference=opening.source,
        body=BODY,
        checked_at=locked_at,
        known_at=locked_at,
    )
    source_reader = _SourceReader(source_read)
    result = resolve_current_financial_availability_governance(
        ResolveCurrentFinancialAvailabilityGovernanceQuery(
            exchange="SZSE",
            effective_on=date(2026, 12, 1),
        ),
        records=_CurrentRecords(),
        owner_events=_CurrentEvents(),
        source_reader=source_reader,
    )

    assert result.known_at == locked_at
    assert result.checked_at == later_checked_at
    assert result.opening_rule.apply_event == opening_apply
    assert result.disclosure_policy.apply_event == policy_apply
    assert source_reader.requested_known_at == locked_at
    assert order[:2] == ["uow", "scope"]
    assert order.index("clock") > max(
        index for index, item in enumerate(order) if item.startswith("events:")
    )


def test_current_pair_blocks_absent_scope_and_does_not_invent_phase_or_ttl() -> None:
    policy = _policy_record()
    policy_apply = _apply_event(policy)

    class _CurrentRecords:
        database_alias = "default"

        def require_caller_owned_current_uow(self):
            return None

        def lock_current_scopes(self, scopes):
            assert len(scopes) == 2

        def list_scope_for_current_update(self, *, kind, exchange):
            if kind is FinancialAvailabilityRecordKind.OPENING_RULE:
                return ()
            assert exchange == "SZSE"
            return (policy,)

        def now(self):
            return policy_apply.recorded_at + timedelta(minutes=1)

    class _CurrentEvents:
        database_alias = "default"

        def list_complete_history_for_update(self, **kwargs):
            del kwargs
            return (policy_apply,)

    source_reader = _SourceReader(
        FinancialAvailabilitySourceRead(
            reference=_source_reference(),
            body=BODY,
            checked_at=policy_apply.recorded_at + timedelta(minutes=1),
            known_at=policy_apply.recorded_at + timedelta(minutes=1),
        )
    )
    with pytest.raises(DataValidationError) as error:
        resolve_current_financial_availability_governance(
            ResolveCurrentFinancialAvailabilityGovernanceQuery(
                exchange="SZSE",
                effective_on=date(2026, 12, 1),
            ),
            records=_CurrentRecords(),
            owner_events=_CurrentEvents(),
            source_reader=source_reader,
        )
    assert error.value.code == "FIN_AVAILABILITY_GOVERNANCE_MISSING"
