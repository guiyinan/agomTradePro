"""Contract tests for the pure formal-calendar seal and Application ports."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import cast
from uuid import uuid4

import pytest

import apps.data_center.domain.formal_exchange_calendar_publication as formal_calendar_domain
from apps.data_center.application.calendar_publication_authority import (
    LockedCalendarPublisherPrincipal,
)
from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarFormalPublicationApplicationError,
    CalendarFormalPublicationCommit,
    CalendarFormalPublicationRequest,
    CalendarPublicationAuditPair,
    CalendarPublicationTransition,
    CurrentPublishedExchangeCalendar,
    PublishExchangeCalendarSnapshotUseCase,
    ReadCurrentExchangeCalendarPublicationQuery,
    ReadCurrentExchangeCalendarPublicationUseCase,
)
from apps.data_center.application.publication_utils import calendar_publication_hash
from apps.data_center.domain.calendar_publication_window import CalendarPublicationLifecycle
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from apps.data_center.domain.control_plane import (
    CalendarNullableMemberCodecVersion,
    CalendarPublicationMemberReference,
    PublicationMember,
)
from apps.data_center.domain.exchange_calendar import (
    ExchangeCalendarDay,
    ExchangeCalendarRawReference,
    ExchangeCalendarSnapshot,
    ExchangeCalendarSnapshotCandidate,
    ExchangeCalendarSnapshotReference,
    exchange_calendar_request_scope_hash,
    make_exchange_calendar_snapshot,
)
from apps.data_center.domain.formal_exchange_calendar_publication import (
    CalendarFormalPublicationError,
    CalendarFormalPublicationRecord,
    CalendarFormalPublicationSeal,
    CalendarPublicationPointerExpectation,
    create_calendar_formal_publication_seal,
    decide_calendar_publication_transition,
    exchange_calendar_publication_key,
    validate_current_calendar_publication,
)

NOW = datetime(2026, 10, 16, 4, 0, 10, tzinfo=UTC)
CALENDAR_DATE = date(2026, 10, 16)
DATASET = DatasetKey("tushare.exchange_calendar.raw", "1.0", "1.0")


def _snapshot(
    *,
    first_seen_at: datetime = NOW - timedelta(seconds=10),
    recorded_at: datetime | None = None,
) -> ExchangeCalendarSnapshot:
    """Build one source-bound snapshot while keeping provider clocks unknown."""

    raw_reference = ExchangeCalendarRawReference(
        payload_id=str(uuid4()),
        payload_hash="sha256:" + "1" * 64,
        record_digest="sha256:" + "2" * 64,
        body_sha256="3" * 64,
        retained_content_sha256="3" * 64,
        request_scope_sha256=exchange_calendar_request_scope_hash(
            "SSE", CALENDAR_DATE, CALENDAR_DATE
        ),
        original_body_retained=True,
        response_completed_at=first_seen_at,
        provider_name="tushare",
        dataset_key=DATASET.value,
        transport="direct",
    )
    candidate = ExchangeCalendarSnapshotCandidate(
        exchange="SSE",
        coverage_start=CALENDAR_DATE,
        coverage_end=CALENDAR_DATE,
        days=(
            ExchangeCalendarDay(
                exchange="SSE",
                calendar_date=CALENDAR_DATE,
                is_open=True,
                previous_open_date=date(2026, 10, 15),
            ),
        ),
        provider_name="tushare",
        raw_reference=raw_reference,
        first_seen_at=first_seen_at,
        source_published_at=None,
    )
    return make_exchange_calendar_snapshot(
        candidate,
        snapshot_id=str(uuid4()),
        recorded_at=recorded_at or first_seen_at + timedelta(seconds=1),
    )


def _policy(
    *,
    dataset: DatasetKey = DATASET,
    policy_version: str = "calendar-policy-1",
    required_evidence: tuple[str, ...] = (
        "source",
        "fetched_at",
        "fact_content_hash",
    ),
) -> PublicationPolicy:
    """Build an explicit versioned calendar nullable-member policy."""

    return PublicationPolicy(
        dataset=dataset,
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=required_evidence,
        retention_days=3650,
        policy_version=policy_version,
        member_codec_version=CalendarNullableMemberCodecVersion.V1,
    )


def _member_reference(
    snapshot: ExchangeCalendarSnapshot,
    *,
    dataset: DatasetKey = DATASET,
    **changes: object,
) -> CalendarPublicationMemberReference:
    """Build one exact member whose calendar source times remain unknown."""

    member = PublicationMember(
        member_id="member-1",
        publication_id="publication-placeholder",
        dataset_key=dataset.value,
        natural_key=f"SSE:{snapshot.coverage_start.isoformat()}:{snapshot.coverage_end.isoformat()}",
        source=snapshot.provider_name,
        source_record_id=snapshot.snapshot_id,
        fact_table="data_center_exchange_calendar_snapshot_fact",
        fact_pk=snapshot.snapshot_id,
        observed_at=None,
        raw_payload_hash=snapshot.raw_reference.payload_hash,
        quality_status="accepted",
        revision_number=1,
        available_at=None,
        fetched_at=snapshot.first_seen_at,
        source_published_at=None,
        raw_payload_scope="record_response_body",
        fact_content_hash="a" * 64,
    )
    return CalendarPublicationMemberReference(
        member=replace(member, **changes),
        snapshot_content_hash=snapshot.content_hash,
        snapshot_record_digest=snapshot.record_digest,
        codec_version=CalendarNullableMemberCodecVersion.V1,
    )


def _seal(
    *,
    snapshot: ExchangeCalendarSnapshot | None = None,
    dataset: DatasetKey = DATASET,
    policy: PublicationPolicy | None = None,
    ttl: object = 60,
    contract_recorded_at: datetime = NOW - timedelta(days=2),
    policy_recorded_at: datetime = NOW - timedelta(days=1),
    member_reference: CalendarPublicationMemberReference | None = None,
) -> CalendarFormalPublicationSeal:
    """Construct one explicit formal identity with repository-owned catalog times."""

    selected = snapshot or _snapshot()
    return create_calendar_formal_publication_seal(
        dataset=dataset,
        exchange=selected.exchange,
        calendar_response_max_age_seconds=cast(int, ttl),
        contract_recorded_at=contract_recorded_at,
        policy=policy or _policy(dataset=dataset),
        policy_recorded_at=policy_recorded_at,
        snapshot=selected,
        member_reference=member_reference or _member_reference(selected, dataset=dataset),
    )


def _record(
    *,
    seal: CalendarFormalPublicationSeal | None = None,
    state: CalendarPublicationLifecycle = CalendarPublicationLifecycle.PUBLISHED,
    published_at: datetime | None = None,
    superseded_at: datetime | None = None,
    activation_id: str = "activation-1",
) -> CalendarFormalPublicationRecord:
    """Build one valid formal record from an exact seal."""

    selected = seal or _seal()
    return CalendarFormalPublicationRecord(
        seal=selected,
        publication_id=str(uuid4()),
        activation_id=activation_id,
        lifecycle=state,
        published_at=published_at or selected.snapshot_recorded_at + timedelta(seconds=1),
        superseded_at=superseded_at,
    )


def _pointer(record: CalendarFormalPublicationRecord) -> CalendarPublicationPointerExpectation:
    """Build one current pointer state exactly bound to a formal record."""

    return CalendarPublicationPointerExpectation(
        dataset_key=record.seal.dataset.value,
        publication_key=record.seal.publication_key,
        pointer_id=str(uuid4()),
        publication_id=record.publication_id,
        publication_hash=record.seal.publication_hash,
        activation_id=record.activation_id,
        updated_at=record.published_at,
    )


def test_formal_hash_binds_ttl_contract_policy_and_member_manifest() -> None:
    snapshot = _snapshot()
    base = _seal(snapshot=snapshot)
    changed_ttl = _seal(snapshot=snapshot, ttl=61)
    changed_contract = _seal(
        snapshot=snapshot,
        dataset=DatasetKey(DATASET.value, "2.0", "1.0"),
    )
    changed_policy = _seal(snapshot=snapshot, policy=_policy(policy_version="calendar-policy-2"))

    assert base.publication_key == "exchange-calendar:SSE"
    assert base.member_manifest_hash != base.publication_hash
    assert changed_ttl.member_manifest_hash == base.member_manifest_hash
    assert changed_ttl.publication_hash != base.publication_hash
    assert changed_contract.publication_hash != base.publication_hash
    assert changed_policy.publication_hash != base.publication_hash
    assert base.member_reference.member.observed_at is None
    assert base.member_reference.member.available_at is None
    assert base.member_reference.member.source_published_at is None
    assert base.member_reference.member.fetched_at == snapshot.first_seen_at
    assert base.member_manifest_hash == calendar_publication_hash(
        (base.member_reference,),
        policy=base.policy,
        codec_version=base.codec_version,
    )


@pytest.mark.parametrize("ttl", [True, 0, -1, 1.5, "60", 2**63])
def test_seal_rejects_missing_or_noncanonical_response_ttl(ttl: object) -> None:
    with pytest.raises(CalendarFormalPublicationError) as caught:
        _seal(ttl=ttl)

    assert caught.value.code == "CALENDAR_FORMAL_TTL_INVALID"


def test_seal_rejects_policy_without_explicit_nullable_codec() -> None:
    policy = replace(_policy(), member_codec_version=None)

    with pytest.raises(CalendarFormalPublicationError) as caught:
        _seal(policy=policy)

    assert caught.value.code == "CALENDAR_FORMAL_POLICY_CODEC_INVALID"


def test_seal_rejects_policy_that_requires_unknown_source_time() -> None:
    policy = _policy(required_evidence=("source", "observed_at"))

    with pytest.raises(CalendarFormalPublicationError) as caught:
        _seal(policy=policy)

    assert caught.value.code == "CALENDAR_FORMAL_POLICY_EVIDENCE_INVALID"


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("source_record_id", "different-snapshot", "CALENDAR_FORMAL_MEMBER_SNAPSHOT_MISMATCH"),
        ("fact_pk", "different-snapshot", "CALENDAR_FORMAL_MEMBER_SNAPSHOT_MISMATCH"),
        ("raw_payload_hash", "sha256:" + "9" * 64, "CALENDAR_FORMAL_MEMBER_RAW_PAYLOAD_MISMATCH"),
        ("fetched_at", NOW, "CALENDAR_FORMAL_MEMBER_TIME_MISMATCH"),
        ("natural_key", "SH:2026-10-16:2026-10-16", "CALENDAR_FORMAL_MEMBER_SCOPE_MISMATCH"),
    ],
)
def test_seal_rejects_member_drift_from_exact_snapshot(
    field: str,
    value: object,
    reason: str,
) -> None:
    snapshot = _snapshot()
    reference = _member_reference(snapshot, **{field: value})

    with pytest.raises(CalendarFormalPublicationError) as caught:
        _seal(snapshot=snapshot, member_reference=reference)

    assert caught.value.code == reason


def test_seal_rejects_catalog_knowledge_after_the_requested_publication_cutoff() -> None:
    seal = _seal(contract_recorded_at=NOW + timedelta(seconds=1))

    with pytest.raises(CalendarFormalPublicationError) as caught:
        _record(seal=seal, published_at=NOW)

    assert caught.value.code == "CALENDAR_FORMAL_CONFIGURATION_NOT_KNOWN"


def test_formal_record_uses_original_response_ttl_and_half_open_bounds() -> None:
    snapshot = _snapshot()
    seal = _seal(snapshot=snapshot, ttl=60)
    record = _record(seal=seal)

    assert record.window.valid_from == record.published_at
    assert record.window.valid_until == snapshot.first_seen_at + timedelta(seconds=60)
    assert record.is_effective_at(record.published_at)
    assert record.is_effective_at(record.window.valid_until - timedelta(microseconds=1))
    assert not record.is_effective_at(record.window.valid_until)


def test_formal_record_rejects_ttl_expired_at_publish_and_unsupported_lifecycle() -> None:
    snapshot = _snapshot()
    seal = _seal(snapshot=snapshot, ttl=10)
    published_at = snapshot.first_seen_at + timedelta(seconds=10)

    with pytest.raises(CalendarFormalPublicationError) as expired:
        _record(seal=seal, published_at=published_at)
    assert expired.value.code == "CALENDAR_WINDOW_EXPIRED_AT_PUBLICATION"

    with pytest.raises(CalendarFormalPublicationError) as unsupported:
        _record(
            seal=seal,
            state=CalendarPublicationLifecycle.ROLLED_BACK,
            superseded_at=published_at + timedelta(seconds=3),
        )
    assert unsupported.value.code == "CALENDAR_FORMAL_LIFECYCLE_UNSUPPORTED"


def test_current_read_blocks_superseded_history_and_noncurrent_pointer() -> None:
    old_record = _record(
        state=CalendarPublicationLifecycle.SUPERSEDED,
        superseded_at=NOW + timedelta(seconds=2),
    )
    old_pointer = _pointer(old_record)
    with pytest.raises(CalendarFormalPublicationError) as history:
        validate_current_calendar_publication(old_record, old_pointer, as_of=NOW)
    assert history.value.code == "CALENDAR_CURRENT_READ_HISTORY_UNSUPPORTED"

    record = _record()
    mismatched_pointer = replace(_pointer(record), publication_hash="f" * 64)
    with pytest.raises(CalendarFormalPublicationError) as pointer:
        validate_current_calendar_publication(record, mismatched_pointer, as_of=NOW)
    assert pointer.value.code == "CALENDAR_CURRENT_POINTER_MISMATCH"


def test_current_read_rejects_pointer_epoch_created_after_cutoff() -> None:
    record = _record()
    pointer = replace(_pointer(record), updated_at=NOW + timedelta(seconds=1))

    with pytest.raises(CalendarFormalPublicationError) as caught:
        validate_current_calendar_publication(record, pointer, as_of=NOW)

    assert caught.value.code == "CALENDAR_CURRENT_POINTER_NOT_KNOWN_AT_CUTOFF"


def test_transition_requires_exact_pointer_and_only_exact_current_replay() -> None:
    first_seal = _seal()
    absent = CalendarPublicationPointerExpectation(
        dataset_key=DATASET.value,
        publication_key=exchange_calendar_publication_key("SSE"),
        pointer_id=None,
        publication_id=None,
        publication_hash=None,
        activation_id=None,
        updated_at=None,
    )
    first = decide_calendar_publication_transition(
        proposed_seal=first_seal,
        expected_pointer=absent,
        actual_pointer=absent,
        current_record=None,
        activation_id="activation-1",
    )
    assert first is formal_calendar_domain.CalendarPublicationTransition.FIRST_PUBLISH

    current = _record(seal=first_seal, activation_id="activation-1")
    pointer = _pointer(current)
    replay = decide_calendar_publication_transition(
        proposed_seal=first_seal,
        expected_pointer=pointer,
        actual_pointer=pointer,
        current_record=current,
        activation_id="activation-1",
    )
    assert replay is formal_calendar_domain.CalendarPublicationTransition.EXACT_CURRENT_REPLAY

    with pytest.raises(CalendarFormalPublicationError) as wrong_activation:
        decide_calendar_publication_transition(
            proposed_seal=first_seal,
            expected_pointer=pointer,
            actual_pointer=pointer,
            current_record=current,
            activation_id="activation-2",
        )
    assert wrong_activation.value.code == "CALENDAR_CURRENT_REPLAY_MISMATCH"

    stale = replace(pointer, updated_at=pointer.updated_at + timedelta(microseconds=1))
    with pytest.raises(CalendarFormalPublicationError) as cas:
        decide_calendar_publication_transition(
            proposed_seal=_seal(ttl=61),
            expected_pointer=pointer,
            actual_pointer=stale,
            current_record=current,
            activation_id="activation-2",
        )
    assert cas.value.code == "CALENDAR_POINTER_CAS_MISMATCH"


def test_formal_seal_payload_exposes_the_hash_inputs_and_policy_identity() -> None:
    seal = _seal()

    payload = seal.to_payload()

    assert seal.policy_identity == seal.policy.identity
    assert seal.policy_version == seal.policy.policy_version
    assert payload["publication_key"] == "exchange-calendar:SSE"
    assert payload["policy_identity"] == seal.policy.identity
    snapshot_payload = cast(dict[str, object], payload["snapshot"])
    assert snapshot_payload["record_digest"] == seal.snapshot.record_digest


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("dataset_type", "CALENDAR_FORMAL_DATASET_INVALID"),
        ("policy_type", "CALENDAR_FORMAL_POLICY_INVALID"),
        ("member_type", "CALENDAR_FORMAL_MEMBER_INVALID"),
        ("snapshot_reference_type", "CALENDAR_FORMAL_SNAPSHOT_INVALID"),
        ("snapshot_type", "CALENDAR_FORMAL_SNAPSHOT_INVALID"),
        ("nested_dataset_invalid", "CALENDAR_FORMAL_NESTED_EVIDENCE_INVALID"),
        ("exchange_token", "CALENDAR_FORMAL_EXCHANGE_INVALID"),
        ("publication_key", "CALENDAR_FORMAL_PUBLICATION_KEY_INVALID"),
        ("bool_ttl", "CALENDAR_FORMAL_TTL_INVALID"),
        ("recorded_before_response", "CALENDAR_FORMAL_SNAPSHOT_KNOWLEDGE_INVALID"),
        ("policy_dataset", "CALENDAR_FORMAL_POLICY_DATASET_MISMATCH"),
        ("policy_codec", "CALENDAR_FORMAL_POLICY_CODEC_INVALID"),
        ("manifest_hash", "CALENDAR_FORMAL_MEMBER_MANIFEST_MISMATCH"),
        ("publication_hash", "CALENDAR_FORMAL_PUBLICATION_HASH_MISMATCH"),
        ("snapshot_reference_mismatch", "CALENDAR_FORMAL_MEMBER_SNAPSHOT_MISMATCH"),
        ("snapshot_provider", "CALENDAR_FORMAL_MEMBER_SNAPSHOT_MISMATCH"),
    ],
)
def test_seal_revalidation_fails_closed_after_in_memory_drift(case: str, reason: str) -> None:
    seal = _seal()
    replacements: dict[str, tuple[str, object]] = {
        "dataset_type": ("dataset", object()),
        "policy_type": ("policy", object()),
        "member_type": ("member_reference", object()),
        "snapshot_reference_type": ("snapshot_reference", object()),
        "snapshot_type": ("snapshot", object()),
        "exchange_token": ("exchange", "SSE/SH"),
        "publication_key": ("publication_key", "exchange-calendar:SZSE"),
        "bool_ttl": ("calendar_response_max_age_seconds", True),
        "recorded_before_response": (
            "snapshot_first_seen_at",
            seal.snapshot_recorded_at + timedelta(seconds=1),
        ),
        "policy_dataset": (
            "policy",
            _policy(dataset=DatasetKey(DATASET.value, "2.0", "1.0")),
        ),
        "policy_codec": ("policy", replace(_policy(), member_codec_version=None)),
        "manifest_hash": ("member_manifest_hash", "f" * 64),
        "publication_hash": ("publication_hash", "f" * 64),
        "snapshot_reference_mismatch": ("snapshot_reference", _snapshot().reference()),
        "snapshot_provider": ("snapshot_provider_name", "another-provider"),
    }
    if case == "nested_dataset_invalid":
        malformed_dataset = object.__new__(DatasetKey)
        object.__setattr__(malformed_dataset, "value", "")
        object.__setattr__(malformed_dataset, "contract_version", "1.0")
        object.__setattr__(malformed_dataset, "schema_version", "1.0")
        field, value = "dataset", malformed_dataset
    else:
        field, value = replacements[case]

    object.__setattr__(seal, field, value)
    with pytest.raises(CalendarFormalPublicationError) as caught:
        seal.validate()

    assert caught.value.code == reason


def test_pointer_expectation_and_transition_decision_reject_partial_identities() -> None:
    with pytest.raises(CalendarFormalPublicationError) as pointer_error:
        CalendarPublicationPointerExpectation(
            dataset_key=DATASET.value,
            publication_key=exchange_calendar_publication_key("SSE"),
            pointer_id=str(uuid4()),
            publication_id=None,
            publication_hash=None,
            activation_id=None,
            updated_at=None,
        )
    assert pointer_error.value.code == "CALENDAR_POINTER_IDENTITY_INVALID"

    with pytest.raises(CalendarFormalPublicationError) as decision_type:
        formal_calendar_domain.CalendarPublicationTransitionDecision(
            transition=cast(formal_calendar_domain.CalendarPublicationTransition, object()),
            current_publication_id=None,
            current_publication_hash=None,
        )
    assert decision_type.value.code == "CALENDAR_TRANSITION_INVALID"

    with pytest.raises(CalendarFormalPublicationError) as first_with_winner:
        formal_calendar_domain.CalendarPublicationTransitionDecision(
            transition=formal_calendar_domain.CalendarPublicationTransition.FIRST_PUBLISH,
            current_publication_id=str(uuid4()),
            current_publication_hash="a" * 64,
        )
    assert first_with_winner.value.code == "CALENDAR_TRANSITION_INVALID"

    with pytest.raises(CalendarFormalPublicationError) as malformed_winner:
        formal_calendar_domain.CalendarPublicationTransitionDecision(
            transition=formal_calendar_domain.CalendarPublicationTransition.FORWARD_PUBLISH,
            current_publication_id="not-a-uuid",
            current_publication_hash="a" * 64,
        )
    assert malformed_winner.value.code == "CALENDAR_FORMAL_UUID_INVALID"


def test_record_revalidation_rejects_corrupt_lifecycle_and_unknown_cutoff() -> None:
    record = _record()
    assert record.is_effective_at(NOW)

    with pytest.raises(CalendarFormalPublicationError) as unknown:
        record.is_effective_at(NOW - timedelta(days=2))
    assert unknown.value.code == "CALENDAR_FORMAL_CONFIGURATION_NOT_KNOWN"

    bad_seal_record = _record()
    object.__setattr__(bad_seal_record.seal, "publication_hash", "f" * 64)
    with pytest.raises(CalendarFormalPublicationError) as bad_seal:
        bad_seal_record.validate()
    assert bad_seal.value.code == "CALENDAR_FORMAL_PUBLICATION_HASH_MISMATCH"

    wrong_lifecycle_record = _record()
    object.__setattr__(wrong_lifecycle_record, "lifecycle", "published")
    with pytest.raises(CalendarFormalPublicationError) as wrong_lifecycle:
        wrong_lifecycle_record.validate()
    assert wrong_lifecycle.value.code == "CALENDAR_FORMAL_LIFECYCLE_INVALID"

    published_with_end = _record()
    object.__setattr__(published_with_end, "superseded_at", NOW + timedelta(seconds=1))
    with pytest.raises(CalendarFormalPublicationError) as published_end:
        published_with_end.validate()
    assert published_end.value.code == "CALENDAR_FORMAL_LIFECYCLE_INVALID"

    missing_end = _record()
    object.__setattr__(missing_end, "lifecycle", CalendarPublicationLifecycle.SUPERSEDED)
    with pytest.raises(CalendarFormalPublicationError) as no_end:
        missing_end.validate()
    assert no_end.value.code == "CALENDAR_FORMAL_LIFECYCLE_INVALID"


def test_transition_requires_scope_target_and_allows_forward_publish() -> None:
    current = _record()
    pointer = _pointer(current)
    absent = CalendarPublicationPointerExpectation(
        dataset_key=DATASET.value,
        publication_key=exchange_calendar_publication_key("SSE"),
        pointer_id=None,
        publication_id=None,
        publication_hash=None,
        activation_id=None,
        updated_at=None,
    )
    proposed = _seal(ttl=61)

    with pytest.raises(CalendarFormalPublicationError) as bad_seal:
        decide_calendar_publication_transition(
            proposed_seal=cast(CalendarFormalPublicationSeal, object()),
            expected_pointer=absent,
            actual_pointer=absent,
            current_record=None,
            activation_id="activation-2",
        )
    assert bad_seal.value.code == "CALENDAR_FORMAL_SEAL_INVALID"

    with pytest.raises(CalendarFormalPublicationError) as expected_scope:
        decide_calendar_publication_transition(
            proposed_seal=proposed,
            expected_pointer=replace(absent, dataset_key="another.dataset"),
            actual_pointer=replace(absent, dataset_key="another.dataset"),
            current_record=None,
            activation_id="activation-2",
        )
    assert expected_scope.value.code == "CALENDAR_POINTER_SCOPE_MISMATCH"

    with pytest.raises(CalendarFormalPublicationError) as actual_scope:
        decide_calendar_publication_transition(
            proposed_seal=proposed,
            expected_pointer=absent,
            actual_pointer=replace(absent, publication_key="exchange-calendar:SZSE"),
            current_record=None,
            activation_id="activation-2",
        )
    assert actual_scope.value.code == "CALENDAR_POINTER_SCOPE_MISMATCH"

    with pytest.raises(CalendarFormalPublicationError) as absent_has_winner:
        decide_calendar_publication_transition(
            proposed_seal=proposed,
            expected_pointer=absent,
            actual_pointer=absent,
            current_record=current,
            activation_id="activation-2",
        )
    assert absent_has_winner.value.code == "CALENDAR_POINTER_TARGET_INVALID"

    with pytest.raises(CalendarFormalPublicationError) as missing_winner:
        decide_calendar_publication_transition(
            proposed_seal=proposed,
            expected_pointer=pointer,
            actual_pointer=pointer,
            current_record=None,
            activation_id="activation-2",
        )
    assert missing_winner.value.code == "CALENDAR_POINTER_TARGET_INVALID"

    superseded = _record(
        state=CalendarPublicationLifecycle.SUPERSEDED,
        superseded_at=NOW + timedelta(seconds=2),
    )
    superseded_pointer = _pointer(superseded)
    with pytest.raises(CalendarFormalPublicationError) as wrong_target:
        decide_calendar_publication_transition(
            proposed_seal=proposed,
            expected_pointer=superseded_pointer,
            actual_pointer=superseded_pointer,
            current_record=superseded,
            activation_id="activation-2",
        )
    assert wrong_target.value.code == "CALENDAR_POINTER_TARGET_INVALID"

    forward = decide_calendar_publication_transition(
        proposed_seal=proposed,
        expected_pointer=pointer,
        actual_pointer=pointer,
        current_record=current,
        activation_id="activation-2",
    )
    assert forward is formal_calendar_domain.CalendarPublicationTransition.FORWARD_PUBLISH


@pytest.mark.parametrize(
    ("exchange", "coverage_start", "coverage_end", "reason"),
    [
        ("SSE/SH", date(2026, 1, 1), date(2026, 1, 2), "CALENDAR_FORMAL_EXCHANGE_INVALID"),
        ("SSE", "2026-01-01", date(2026, 1, 2), "CALENDAR_FORMAL_COVERAGE_INVALID"),
        ("SSE", date(2026, 1, 2), date(2026, 1, 1), "CALENDAR_FORMAL_COVERAGE_INVALID"),
    ],
)
def test_calendar_natural_keys_reject_ambiguous_exchange_and_coverage(
    exchange: str,
    coverage_start: object,
    coverage_end: object,
    reason: str,
) -> None:
    with pytest.raises(CalendarFormalPublicationError) as caught:
        formal_calendar_domain.calendar_snapshot_natural_key(exchange, coverage_start, coverage_end)
    assert caught.value.code == reason


def test_formal_seal_creation_rejects_unpersisted_or_wrong_exchange_snapshot() -> None:
    candidate = _snapshot()
    with pytest.raises(CalendarFormalPublicationError) as unpersisted:
        create_calendar_formal_publication_seal(
            dataset=DATASET,
            exchange="SSE",
            calendar_response_max_age_seconds=60,
            contract_recorded_at=NOW - timedelta(days=2),
            policy=_policy(),
            policy_recorded_at=NOW - timedelta(days=1),
            snapshot=cast(ExchangeCalendarSnapshot, object()),
            member_reference=_member_reference(candidate),
        )
    assert unpersisted.value.code == "CALENDAR_FORMAL_SNAPSHOT_INVALID"

    snapshot = _snapshot()
    with pytest.raises(CalendarFormalPublicationError) as wrong_exchange:
        create_calendar_formal_publication_seal(
            dataset=DATASET,
            exchange="SZSE",
            calendar_response_max_age_seconds=60,
            contract_recorded_at=NOW - timedelta(days=2),
            policy=_policy(),
            policy_recorded_at=NOW - timedelta(days=1),
            snapshot=snapshot,
            member_reference=_member_reference(snapshot),
        )
    assert wrong_exchange.value.code == "CALENDAR_FORMAL_MEMBER_SNAPSHOT_MISMATCH"

    malformed = _snapshot()
    reference = _member_reference(malformed)
    object.__setattr__(malformed, "candidate", object())
    with pytest.raises(CalendarFormalPublicationError) as malformed_snapshot:
        create_calendar_formal_publication_seal(
            dataset=DATASET,
            exchange="SSE",
            calendar_response_max_age_seconds=60,
            contract_recorded_at=NOW - timedelta(days=2),
            policy=_policy(),
            policy_recorded_at=NOW - timedelta(days=1),
            snapshot=malformed,
            member_reference=reference,
        )
    assert malformed_snapshot.value.code == "CALENDAR_FORMAL_INPUT_INVALID"


def test_content_hash_helper_rejects_untyped_or_mismatched_hash_inputs() -> None:
    seal = _seal()

    def calculate(
        *,
        dataset: DatasetKey = seal.dataset,
        member_reference: CalendarPublicationMemberReference = seal.member_reference,
        snapshot_reference: ExchangeCalendarSnapshotReference = seal.snapshot_reference,
        snapshot: ExchangeCalendarSnapshot = seal.snapshot,
    ) -> str:
        return formal_calendar_domain._publication_content_hash_from_values(
            dataset=dataset,
            exchange=seal.exchange,
            publication_key=seal.publication_key,
            calendar_response_max_age_seconds=seal.calendar_response_max_age_seconds,
            contract_recorded_at=seal.contract_recorded_at,
            policy=seal.policy,
            policy_recorded_at=seal.policy_recorded_at,
            member_reference=member_reference,
            snapshot=snapshot,
            snapshot_reference=snapshot_reference,
            snapshot_provider_name=seal.snapshot_provider_name,
            snapshot_first_seen_at=seal.snapshot_first_seen_at,
            snapshot_recorded_at=seal.snapshot_recorded_at,
            member_manifest_hash=seal.member_manifest_hash,
        )

    invalid_cases = (
        ("dataset", object(), "CALENDAR_FORMAL_INPUT_INVALID"),
        ("member_reference", object(), "CALENDAR_FORMAL_MEMBER_INVALID"),
        ("snapshot_reference", object(), "CALENDAR_FORMAL_SNAPSHOT_INVALID"),
        ("snapshot", object(), "CALENDAR_FORMAL_SNAPSHOT_INVALID"),
        ("snapshot_reference", _snapshot().reference(), "CALENDAR_FORMAL_SNAPSHOT_INVALID"),
    )
    for field_name, value, reason in invalid_cases:
        with pytest.raises(CalendarFormalPublicationError) as caught:
            if field_name == "dataset":
                calculate(dataset=cast(DatasetKey, value))
            elif field_name == "member_reference":
                calculate(member_reference=cast(CalendarPublicationMemberReference, value))
            elif field_name == "snapshot_reference":
                calculate(snapshot_reference=cast(ExchangeCalendarSnapshotReference, value))
            else:
                calculate(snapshot=cast(ExchangeCalendarSnapshot, value))
        assert caught.value.code == reason


def test_manifest_hash_helper_rejects_wrong_typed_inputs() -> None:
    seal = _seal()

    with pytest.raises(CalendarFormalPublicationError) as member:
        formal_calendar_domain._calendar_member_manifest_hash(
            cast(CalendarPublicationMemberReference, object()), seal.policy
        )
    assert member.value.code == "CALENDAR_FORMAL_MEMBER_INVALID"

    with pytest.raises(CalendarFormalPublicationError) as policy:
        formal_calendar_domain._calendar_member_manifest_hash(
            seal.member_reference,
            cast(PublicationPolicy, object()),
        )
    assert policy.value.code == "CALENDAR_FORMAL_POLICY_INVALID"


def test_current_read_rejects_unpublished_future_and_expired_evidence() -> None:
    record = _record()
    pointer = _pointer(record)

    with pytest.raises(CalendarFormalPublicationError) as wrong_record:
        validate_current_calendar_publication(
            cast(CalendarFormalPublicationRecord, object()), pointer, as_of=NOW
        )
    assert wrong_record.value.code == "CALENDAR_FORMAL_RECORD_INVALID"

    before_configuration = replace(
        pointer,
        updated_at=NOW - timedelta(days=3),
    )
    with pytest.raises(CalendarFormalPublicationError) as unknown:
        validate_current_calendar_publication(
            record,
            before_configuration,
            as_of=NOW - timedelta(days=2, seconds=1),
        )
    assert unknown.value.code == "CALENDAR_FORMAL_CONFIGURATION_NOT_KNOWN"

    future_record = _record(published_at=NOW + timedelta(seconds=1))
    old_pointer_epoch = replace(_pointer(future_record), updated_at=NOW - timedelta(days=1))
    with pytest.raises(CalendarFormalPublicationError) as not_yet_published:
        validate_current_calendar_publication(
            future_record,
            old_pointer_epoch,
            as_of=NOW,
        )
    assert not_yet_published.value.code == "CALENDAR_PUBLICATION_NOT_EFFECTIVE_AT_CUTOFF"

    expiry = record.seal.snapshot_first_seen_at + timedelta(
        seconds=record.seal.calendar_response_max_age_seconds
    )
    with pytest.raises(CalendarFormalPublicationError) as expired:
        validate_current_calendar_publication(
            record,
            pointer,
            as_of=expiry,
        )
    assert expired.value.code == "CALENDAR_FORMAL_TTL_EXPIRED"


def test_low_level_calendar_publication_identifiers_are_strict() -> None:
    with pytest.raises(CalendarFormalPublicationError) as invalid_key:
        exchange_calendar_publication_key("SSE/SH")
    assert invalid_key.value.code == "CALENDAR_FORMAL_EXCHANGE_INVALID"

    with pytest.raises(CalendarFormalPublicationError) as bad_text:
        formal_calendar_domain._require_text(" ", "source", 100)
    assert bad_text.value.code == "CALENDAR_FORMAL_TEXT_INVALID"

    with pytest.raises(CalendarFormalPublicationError) as bad_token:
        formal_calendar_domain._require_token("bad token", "activation", 300)
    assert bad_token.value.code == "CALENDAR_FORMAL_TOKEN_INVALID"

    for value in (object(), "not-a-uuid", "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"):
        with pytest.raises(CalendarFormalPublicationError) as bad_uuid:
            formal_calendar_domain._require_uuid(value, "publication_id")
        assert bad_uuid.value.code == "CALENDAR_FORMAL_UUID_INVALID"

    with pytest.raises(CalendarFormalPublicationError) as bad_hash:
        formal_calendar_domain._require_sha256("A" * 64, "publication_hash")
    assert bad_hash.value.code == "CALENDAR_FORMAL_HASH_INVALID"

    with pytest.raises(CalendarFormalPublicationError) as bad_time:
        formal_calendar_domain._require_utc(datetime(2026, 10, 16), "as_of")
    assert bad_time.value.code == "CALENDAR_FORMAL_TIME_INVALID"


class _Principal:
    """Small locked-principal test double implementing the public authority port."""

    actor_type = "django_user"
    permission_codename = "publish_exchange_calendar"
    database_alias = "default"
    permission_id = 7

    def __init__(self, *, user_id: int = 1, verified_at: datetime | None = None) -> None:
        self.user_id = user_id
        self.actor_id = f"django-user:{user_id}"
        self.verified_at = verified_at or NOW - timedelta(seconds=2)

    def assert_live(self) -> None:
        """Represent a still-held session and permission lock lease."""


def _commit(request: CalendarFormalPublicationRequest) -> CalendarFormalPublicationCommit:
    """Build one publisher-port result with an exact Audit pair and post-Audit check."""

    record = _record(
        seal=request.proposed_seal,
        activation_id=request.activation_id,
        published_at=NOW,
    )
    pointer = _pointer(record)
    audit = CalendarPublicationAuditPair(
        database_alias="default",
        dataset_key=record.seal.dataset.value,
        exchange=record.seal.exchange,
        publication_id=record.publication_id,
        publication_hash=record.seal.publication_hash,
        event_id="calendar:published:" + "c" * 64,
        event_content_hash="b" * 64,
        actor_user_id=1,
        outbox_id=uuid4(),
        idempotency_key="calendar:published:" + "c" * 64,
        recorded_at=record.published_at,
    )
    return CalendarFormalPublicationCommit(
        record=record,
        pointer=pointer,
        transition=CalendarPublicationTransition.FIRST_PUBLISH,
        audit_pair=audit,
        post_audit_checked_at=NOW + timedelta(seconds=1),
    )


class _Writer:
    """Capture a publish call and return its prepared exact commit receipt."""

    def __init__(self, result: CalendarFormalPublicationCommit) -> None:
        self.result = result
        self.request: CalendarFormalPublicationRequest | None = None
        self.principal: LockedCalendarPublisherPrincipal | None = None

    def publish(
        self,
        request: CalendarFormalPublicationRequest,
        *,
        principal: LockedCalendarPublisherPrincipal,
    ) -> CalendarFormalPublicationCommit:
        """Return the fake repository's verified transaction receipt."""

        self.request = request
        self.principal = principal
        return self.result


class _Reader:
    """Return one prepared exact-current publication read result."""

    def __init__(self, result: CurrentPublishedExchangeCalendar | None) -> None:
        self.result = result
        self.query: ReadCurrentExchangeCalendarPublicationQuery | None = None

    def read_current(
        self,
        query: ReadCurrentExchangeCalendarPublicationQuery,
    ) -> CurrentPublishedExchangeCalendar | None:
        """Capture the exact-current query and return its prepared result."""

        self.query = query
        return self.result


def test_publish_use_case_requires_authorized_exact_commit_and_preserves_gates() -> None:
    snapshot = _snapshot()
    seal = _seal(snapshot=snapshot)
    pointer = CalendarPublicationPointerExpectation(
        dataset_key=seal.dataset.value,
        publication_key=seal.publication_key,
        pointer_id=None,
        publication_id=None,
        publication_hash=None,
        activation_id=None,
        updated_at=None,
    )
    request = CalendarFormalPublicationRequest(
        proposed_seal=seal,
        expected_pointer=pointer,
        activation_id="activation-1",
    )
    result = _commit(request)
    writer = _Writer(result)
    principal = _Principal()

    published = PublishExchangeCalendarSnapshotUseCase(writer).execute(
        request,
        principal=principal,
    )

    assert published is result
    assert writer.request is request
    assert writer.principal is principal
    assert published.record.published_at >= principal.verified_at
    assert published.audit_pair.recorded_at == published.record.published_at
    assert published.must_not_execute is True


def test_publish_use_case_rejects_commit_with_mismatched_audit_or_early_time() -> None:
    snapshot = _snapshot()
    seal = _seal(snapshot=snapshot)
    request = CalendarFormalPublicationRequest(
        proposed_seal=seal,
        expected_pointer=CalendarPublicationPointerExpectation(
            dataset_key=seal.dataset.value,
            publication_key=seal.publication_key,
            pointer_id=None,
            publication_id=None,
            publication_hash=None,
            activation_id=None,
            updated_at=None,
        ),
        activation_id="activation-1",
    )
    result = _commit(request)
    wrong_audit = replace(result.audit_pair, publication_hash="f" * 64)

    with pytest.raises(CalendarFormalPublicationApplicationError) as audit:
        PublishExchangeCalendarSnapshotUseCase(
            _Writer(replace(result, audit_pair=wrong_audit))
        ).execute(request, principal=_Principal())
    assert audit.value.code == "CALENDAR_PUBLICATION_AUDIT_BINDING_INVALID"

    early_record = replace(result.record, published_at=NOW - timedelta(seconds=5))
    early_result = replace(
        result,
        record=early_record,
        pointer=replace(result.pointer, updated_at=early_record.published_at),
        audit_pair=replace(result.audit_pair, recorded_at=early_record.published_at),
    )
    with pytest.raises(CalendarFormalPublicationApplicationError) as time_error:
        PublishExchangeCalendarSnapshotUseCase(_Writer(early_result)).execute(
            request,
            principal=_Principal(),
        )
    assert time_error.value.code == "CALENDAR_PUBLICATION_AUTHORITY_TIME_INVALID"


def test_exact_current_replay_preserves_old_audit_time_and_requires_original_actor() -> None:
    seal = _seal()
    old_published_at = NOW - timedelta(seconds=5)
    record = _record(
        seal=seal,
        published_at=old_published_at,
        activation_id="activation-1",
    )
    pointer = _pointer(record)
    request = CalendarFormalPublicationRequest(
        proposed_seal=seal,
        expected_pointer=pointer,
        activation_id=record.activation_id,
    )
    audit = CalendarPublicationAuditPair(
        database_alias="default",
        dataset_key=seal.dataset.value,
        exchange=seal.exchange,
        publication_id=record.publication_id,
        publication_hash=seal.publication_hash,
        event_id="calendar:published:" + "d" * 64,
        event_content_hash="e" * 64,
        actor_user_id=1,
        outbox_id=uuid4(),
        idempotency_key="calendar:published:" + "d" * 64,
        recorded_at=old_published_at,
    )
    replay = CalendarFormalPublicationCommit(
        record=record,
        pointer=pointer,
        transition=CalendarPublicationTransition.EXACT_CURRENT_REPLAY,
        audit_pair=audit,
        post_audit_checked_at=NOW,
    )

    result = PublishExchangeCalendarSnapshotUseCase(_Writer(replay)).execute(
        request,
        principal=_Principal(),
    )

    assert result.record.published_at == old_published_at
    assert result.audit_pair.recorded_at == old_published_at
    assert result.audit_pair.event_content_hash == "e" * 64

    with pytest.raises(CalendarFormalPublicationApplicationError) as actor:
        PublishExchangeCalendarSnapshotUseCase(_Writer(replay)).execute(
            request,
            principal=_Principal(user_id=2),
        )
    assert actor.value.code == "CALENDAR_PUBLICATION_AUDIT_ACTOR_MISMATCH"


def test_current_read_use_case_returns_only_exact_pointer_current_object() -> None:
    record = _record()
    pointer = _pointer(record)
    result = CurrentPublishedExchangeCalendar(record=record, pointer=pointer, as_of=NOW)
    query = ReadCurrentExchangeCalendarPublicationQuery(
        dataset_key=record.seal.dataset.value,
        exchange=record.seal.exchange,
        as_of=NOW,
    )
    reader = _Reader(result)

    current = ReadCurrentExchangeCalendarPublicationUseCase(reader).execute(query)

    assert current is result
    assert reader.query is query
    assert current.must_not_execute is True


def test_current_read_use_case_blocks_historical_query_and_missing_pointer() -> None:
    record = _record()
    pointer = _pointer(record)
    earlier = ReadCurrentExchangeCalendarPublicationQuery(
        dataset_key=record.seal.dataset.value,
        exchange=record.seal.exchange,
        as_of=record.published_at - timedelta(microseconds=1),
    )
    with pytest.raises(CalendarFormalPublicationApplicationError) as historical:
        CurrentPublishedExchangeCalendar(record=record, pointer=pointer, as_of=earlier.as_of)
    assert historical.value.code == "CALENDAR_CURRENT_POINTER_NOT_KNOWN_AT_CUTOFF"

    with pytest.raises(CalendarFormalPublicationApplicationError) as missing:
        ReadCurrentExchangeCalendarPublicationUseCase(_Reader(None)).execute(
            ReadCurrentExchangeCalendarPublicationQuery(
                dataset_key=DATASET.value,
                exchange="SSE",
                as_of=NOW,
            )
        )
    assert missing.value.code == "CALENDAR_CURRENT_PUBLICATION_MISSING"


def test_current_read_rejects_superseded_record_even_inside_its_old_window() -> None:
    old = _record(
        state=CalendarPublicationLifecycle.SUPERSEDED,
        superseded_at=NOW + timedelta(seconds=3),
    )
    query = ReadCurrentExchangeCalendarPublicationQuery(
        dataset_key=old.seal.dataset.value,
        exchange=old.seal.exchange,
        as_of=NOW,
    )
    with pytest.raises(CalendarFormalPublicationApplicationError) as caught:
        ReadCurrentExchangeCalendarPublicationUseCase(
            _Reader(CurrentPublishedExchangeCalendar(record=old, pointer=_pointer(old), as_of=NOW))
        ).execute(query)
    assert caught.value.code == "CALENDAR_CURRENT_READ_HISTORY_UNSUPPORTED"


def test_request_rejects_pointer_for_another_exchange_scope() -> None:
    snapshot = _snapshot()
    other_pointer = CalendarPublicationPointerExpectation(
        dataset_key=DATASET.value,
        publication_key=exchange_calendar_publication_key("SZSE"),
        pointer_id=None,
        publication_id=None,
        publication_hash=None,
        activation_id=None,
        updated_at=None,
    )

    with pytest.raises(CalendarFormalPublicationApplicationError) as caught:
        CalendarFormalPublicationRequest(
            proposed_seal=_seal(snapshot=snapshot),
            expected_pointer=other_pointer,
            activation_id="activation-1",
        )
    assert caught.value.code == "CALENDAR_PUBLICATION_REQUEST_SCOPE_INVALID"
