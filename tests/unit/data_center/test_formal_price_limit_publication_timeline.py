from __future__ import annotations

from dataclasses import fields as dataclass_fields
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TypeVar, cast
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest

from apps.data_center.domain.contracts import (
    DatasetContract,
    DatasetFieldContract,
    DatasetKey,
    PublicationPolicy,
)
from apps.data_center.domain.control_plane import PublicationRollback
from apps.data_center.domain.formal_price_limit_publication import (
    PriceLimitFormalPublicationRecord,
    PriceLimitFormalPublicationSeal,
    PriceLimitPublicationError,
    PriceLimitPublicationEventKind,
    PriceLimitPublicationPointerExpectation,
    PriceLimitPublicationTimelineEvent,
    create_price_limit_formal_publication_seal,
    resolve_price_limit_publication_at,
    validate_price_limit_publication_timeline,
)
from apps.data_center.domain.price_limit_snapshot import (
    PriceLimitRawReference,
    PriceLimitSnapshot,
    PriceLimitSnapshotCandidate,
    make_price_limit_snapshot,
    price_limit_request_scope_hash,
)
from apps.data_center.domain.provider_response import ProviderResponseTransport
from apps.data_center.domain.publication_member_codec import (
    PriceLimitNullableMemberCodecVersion,
)

_NOW = datetime(2026, 10, 29, 2, 0, tzinfo=UTC)
_EFFECTIVE_DATE = date(2026, 10, 28)
_DATASET = DatasetKey("equity.price.limit", "1.0", "1.0")
_CONTRACT_RECORDED_AT = _NOW - timedelta(days=3)
_POLICY_RECORDED_AT = _NOW - timedelta(days=2)
_T = TypeVar("_T")


def _unsafe_replace(instance: _T, **changes: object) -> _T:
    """Build a deliberately corrupted frozen DTO for explicit revalidation tests."""

    corrupted = object.__new__(type(instance))
    for data_field in dataclass_fields(instance):
        replacement = changes.get(data_field.name, getattr(instance, data_field.name))
        object.__setattr__(corrupted, data_field.name, replacement)
    return cast(_T, corrupted)


def _contract(**changes: object) -> DatasetContract:
    fields = (
        DatasetFieldContract(
            name="lower_limit_price",
            value_type="decimal",
            unit="provider_native_price",
            nullable=False,
            zero_allowed=False,
            minimum=0.01,
        ),
        DatasetFieldContract(
            name="upper_limit_price",
            value_type="decimal",
            unit="provider_native_price",
            nullable=False,
            zero_allowed=False,
            minimum=0.01,
        ),
        DatasetFieldContract(
            name="currency",
            value_type="string",
            unit=None,
            nullable=True,
            zero_allowed=False,
        ),
    )
    return DatasetContract(
        key=_DATASET,
        owner="data_center",
        frequency="daily",
        decision_critical=False,
        fields=fields,
        freshness_seconds=None,
        comparable_group=None,
        execution_freshness_seconds=None,
        calendar_response_max_age_seconds=None,
        **changes,
    )


def _policy(**changes: object) -> PublicationPolicy:
    return PublicationPolicy(
        dataset=_DATASET,
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=(
            "source",
            "payload_hash",
            "raw_payload_hash",
            "source_record_id",
            "fetched_at",
            "raw_payload_scope",
            "fact_content_hash",
        ),
        retention_days=3650,
        policy_version="price-limit-policy-v1",
        member_codec_version=PriceLimitNullableMemberCodecVersion.V1,
        **changes,
    )


def _snapshot(
    *,
    provider_id: int = 7,
    provider_name: str = "tushare",
    asset_code: str = "600000.SH",
    effective_trade_date: date = _EFFECTIVE_DATE,
    lower_limit_price: Decimal = Decimal("9.123400"),
    upper_limit_price: Decimal = Decimal("11.456700"),
    response_completed_at: datetime = _NOW - timedelta(minutes=5),
    recorded_at: datetime = _NOW - timedelta(minutes=4),
    payload_marker: str = "1",
) -> PriceLimitSnapshot:
    payload_hash = "sha256:" + payload_marker * 64
    raw_reference = PriceLimitRawReference(
        payload_id=str(uuid5(NAMESPACE_URL, payload_hash)),
        payload_hash=payload_hash,
        record_digest="sha256:" + "2" * 64,
        body_sha256="3" * 64,
        retained_content_sha256="3" * 64,
        original_body_retained=True,
        retained_content_encoding="exact_original_utf8_json",
        body_size_bytes=128,
        response_completed_at=response_completed_at,
        provider_name=provider_name,
        dataset_key="equity.price.limit",
        transport=ProviderResponseTransport.DIRECT,
        request_scope_sha256=price_limit_request_scope_hash(
            provider_id=provider_id,
            provider_name=provider_name,
            asset_code=asset_code,
            effective_trade_date=effective_trade_date,
        ),
    )
    candidate = PriceLimitSnapshotCandidate(
        asset_code=asset_code,
        effective_trade_date=effective_trade_date,
        provider_id=provider_id,
        provider_name=provider_name,
        lower_limit_price=lower_limit_price,
        upper_limit_price=upper_limit_price,
        raw_reference=raw_reference,
    )
    return make_price_limit_snapshot(
        candidate,
        snapshot_id=str(uuid4()),
        recorded_at=recorded_at,
    )


def _seal(
    snapshot: PriceLimitSnapshot | None = None,
    *,
    contract: DatasetContract | None = None,
    policy: PublicationPolicy | None = None,
    contract_recorded_at: datetime = _CONTRACT_RECORDED_AT,
    policy_recorded_at: datetime = _POLICY_RECORDED_AT,
    fact_content_hash: str = "4" * 64,
) -> PriceLimitFormalPublicationSeal:
    return create_price_limit_formal_publication_seal(
        dataset_contract=contract or _contract(),
        contract_recorded_at=contract_recorded_at,
        policy=policy or _policy(),
        policy_recorded_at=policy_recorded_at,
        snapshot=snapshot or _snapshot(),
        fact_content_hash=fact_content_hash,
    )


def _record(
    seal: PriceLimitFormalPublicationSeal | None = None,
    *,
    publication_id: str | None = None,
    first_published_at: datetime = _NOW,
    first_activation_id: str = "activation-1",
) -> PriceLimitFormalPublicationRecord:
    return PriceLimitFormalPublicationRecord(
        seal=seal or _seal(),
        publication_id=publication_id or str(uuid4()),
        first_published_at=first_published_at,
        first_activation_id=first_activation_id,
    )


def _first_event(record: PriceLimitFormalPublicationRecord) -> PriceLimitPublicationTimelineEvent:
    seal = record.seal
    return PriceLimitPublicationTimelineEvent(
        kind=PriceLimitPublicationEventKind.FIRST_PUBLISH,
        event_id=record.first_activation_id,
        dataset_key=seal.dataset_contract.key.value,
        publication_key=seal.publication_key,
        previous_publication_id=None,
        previous_publication_hash=None,
        target_publication_id=record.publication_id,
        target_publication_hash=seal.publication_hash,
        transitioned_at=record.first_published_at,
    )


def _pointer(
    record: PriceLimitFormalPublicationRecord,
    *,
    activation_id: str | None = None,
    updated_at: datetime | None = None,
) -> PriceLimitPublicationPointerExpectation:
    return PriceLimitPublicationPointerExpectation(
        dataset_key=record.seal.dataset_contract.key.value,
        publication_key=record.seal.publication_key,
        pointer_id=str(uuid4()),
        publication_id=record.publication_id,
        publication_hash=record.seal.publication_hash,
        activation_id=activation_id or record.first_activation_id,
        updated_at=updated_at or record.first_published_at,
    )


def test_first_publish_timeline_validates_exact_current_pointer_identity() -> None:
    record = _record()
    event = _first_event(record)
    pointer = _pointer(record)

    assert (
        validate_price_limit_publication_timeline(
            records=(record,), events=(event,), current_pointer=pointer
        )
        == record
    )

    bad_pointer = replace(pointer, publication_hash="a" * 64)
    with pytest.raises(PriceLimitPublicationError):
        validate_price_limit_publication_timeline(
            records=(record,), events=(event,), current_pointer=bad_pointer
        )


def test_first_publish_requires_no_previous_identity_and_pointer_time_matches_event() -> None:
    record = _record()
    event = _first_event(record)
    pointer = _pointer(record)
    with pytest.raises(PriceLimitPublicationError):
        validate_price_limit_publication_timeline(
            records=(record,),
            events=(replace(event, previous_publication_id="prior"),),
            current_pointer=pointer,
        )
    with pytest.raises(PriceLimitPublicationError):
        validate_price_limit_publication_timeline(
            records=(record,),
            events=(event,),
            current_pointer=replace(pointer, updated_at=pointer.updated_at + timedelta(seconds=1)),
        )
    with pytest.raises(PriceLimitPublicationError):
        validate_price_limit_publication_timeline(
            records=(record,),
            events=(event,),
            current_pointer=replace(pointer, activation_id="another-activation"),
        )


def test_forward_publish_requires_explicit_contiguous_previous_id_and_hash() -> None:
    first = _record(first_published_at=_NOW)
    second = _record(
        _seal(
            _snapshot(
                lower_limit_price=Decimal("9.1200"),
                upper_limit_price=Decimal("11.4500"),
                response_completed_at=_NOW + timedelta(seconds=10),
                recorded_at=_NOW + timedelta(seconds=11),
                payload_marker="6",
            )
        ),
        first_published_at=_NOW + timedelta(seconds=20),
        first_activation_id="activation-2",
    )
    first_event = _first_event(first)
    forward = PriceLimitPublicationTimelineEvent(
        kind=PriceLimitPublicationEventKind.FORWARD_PUBLISH,
        event_id="activation-2",
        dataset_key=second.seal.dataset_contract.key.value,
        publication_key=second.seal.publication_key,
        previous_publication_id=first.publication_id,
        previous_publication_hash=first.seal.publication_hash,
        target_publication_id=second.publication_id,
        target_publication_hash=second.seal.publication_hash,
        transitioned_at=second.first_published_at,
    )
    pointer = _pointer(second)

    assert (
        validate_price_limit_publication_timeline(
            records=(first, second), events=(first_event, forward), current_pointer=pointer
        )
        == second
    )

    with pytest.raises(PriceLimitPublicationError):
        validate_price_limit_publication_timeline(
            records=(first, second),
            events=(first_event, replace(forward, previous_publication_hash="f" * 64)),
            current_pointer=pointer,
        )
    with pytest.raises(PriceLimitPublicationError):
        validate_price_limit_publication_timeline(
            records=(first, second),
            events=(first_event, replace(forward, previous_publication_id=str(uuid4()))),
            current_pointer=pointer,
        )


def test_timeline_rejects_unordered_duplicate_or_wrong_scope_events() -> None:
    first = _record()
    second = _record(
        _seal(_snapshot(payload_marker="6")),
        first_published_at=_NOW + timedelta(seconds=10),
        first_activation_id="activation-2",
    )
    start = _first_event(first)
    next_event = PriceLimitPublicationTimelineEvent(
        kind=PriceLimitPublicationEventKind.FORWARD_PUBLISH,
        event_id="activation-2",
        dataset_key=second.seal.dataset_contract.key.value,
        publication_key=second.seal.publication_key,
        previous_publication_id=first.publication_id,
        previous_publication_hash=first.seal.publication_hash,
        target_publication_id=second.publication_id,
        target_publication_hash=second.seal.publication_hash,
        transitioned_at=second.first_published_at,
    )
    pointer = _pointer(second)

    invalid_timelines = (
        (start, replace(next_event, transitioned_at=start.transitioned_at)),
        (replace(start, event_id=next_event.event_id), next_event),
        (start, replace(next_event, publication_key="price-limit:" + "0" * 64)),
        (start, replace(next_event, target_publication_id=str(uuid4()))),
    )
    for events in invalid_timelines:
        with pytest.raises(PriceLimitPublicationError):
            validate_price_limit_publication_timeline(
                records=(first, second), events=events, current_pointer=pointer
            )


def test_same_publication_cannot_be_forward_published_again_after_supersession() -> None:
    first = _record()
    second = _record(
        _seal(_snapshot(payload_marker="6")),
        first_published_at=_NOW + timedelta(seconds=10),
        first_activation_id="activation-2",
    )
    start = _first_event(first)
    forward = PriceLimitPublicationTimelineEvent(
        kind=PriceLimitPublicationEventKind.FORWARD_PUBLISH,
        event_id="activation-2",
        dataset_key=second.seal.dataset_contract.key.value,
        publication_key=second.seal.publication_key,
        previous_publication_id=first.publication_id,
        previous_publication_hash=first.seal.publication_hash,
        target_publication_id=second.publication_id,
        target_publication_hash=second.seal.publication_hash,
        transitioned_at=second.first_published_at,
    )
    duplicate_forward = replace(
        forward,
        event_id="activation-3",
        previous_publication_id=second.publication_id,
        previous_publication_hash=second.seal.publication_hash,
        transitioned_at=second.first_published_at + timedelta(seconds=10),
    )
    with pytest.raises(PriceLimitPublicationError):
        validate_price_limit_publication_timeline(
            records=(first, second),
            events=(start, forward, duplicate_forward),
            current_pointer=replace(
                _pointer(second),
                activation_id="activation-3",
                updated_at=duplicate_forward.transitioned_at,
            ),
        )


def test_rollback_is_an_explicit_event_and_must_match_original_rollback_fact() -> None:
    first = _record()
    second = _record(
        _seal(_snapshot(payload_marker="6")),
        first_published_at=_NOW + timedelta(seconds=10),
        first_activation_id="activation-2",
    )
    start = _first_event(first)
    forward = PriceLimitPublicationTimelineEvent(
        kind=PriceLimitPublicationEventKind.FORWARD_PUBLISH,
        event_id="activation-2",
        dataset_key=second.seal.dataset_contract.key.value,
        publication_key=second.seal.publication_key,
        previous_publication_id=first.publication_id,
        previous_publication_hash=first.seal.publication_hash,
        target_publication_id=second.publication_id,
        target_publication_hash=second.seal.publication_hash,
        transitioned_at=second.first_published_at,
    )
    rollback_id = str(uuid4())
    rollback_at = _NOW + timedelta(seconds=20)
    rollback = PublicationRollback(
        target_publication_id=first.publication_id,
        previous_publication_id=second.publication_id,
        reason="restore verified price-limit reference",
        operator="operator-1",
        observed_at=rollback_at,
        rollback_id=rollback_id,
    )
    rollback_event = PriceLimitPublicationTimelineEvent(
        kind=PriceLimitPublicationEventKind.ROLLBACK,
        event_id=rollback_id,
        dataset_key=first.seal.dataset_contract.key.value,
        publication_key=first.seal.publication_key,
        previous_publication_id=second.publication_id,
        previous_publication_hash=second.seal.publication_hash,
        target_publication_id=first.publication_id,
        target_publication_hash=first.seal.publication_hash,
        transitioned_at=rollback_at,
        rollback=rollback,
    )
    pointer = _pointer(first, activation_id=rollback_id, updated_at=rollback_at)

    assert (
        validate_price_limit_publication_timeline(
            records=(first, second),
            events=(start, forward, rollback_event),
            current_pointer=pointer,
        )
        == first
    )
    with pytest.raises(PriceLimitPublicationError):
        validate_price_limit_publication_timeline(
            records=(first, second),
            events=(start, forward, replace(rollback_event, rollback=None)),
            current_pointer=pointer,
        )
    with pytest.raises(PriceLimitPublicationError):
        validate_price_limit_publication_timeline(
            records=(first, second),
            events=(start, forward, replace(rollback_event, event_id="not-rollback-id")),
            current_pointer=pointer,
        )


def test_historical_resolution_uses_verified_event_chain_not_latest_record_order() -> None:
    first = _record()
    second = _record(
        _seal(_snapshot(payload_marker="6")),
        first_published_at=_NOW + timedelta(seconds=10),
        first_activation_id="activation-2",
    )
    start = _first_event(first)
    forward = PriceLimitPublicationTimelineEvent(
        kind=PriceLimitPublicationEventKind.FORWARD_PUBLISH,
        event_id="activation-2",
        dataset_key=second.seal.dataset_contract.key.value,
        publication_key=second.seal.publication_key,
        previous_publication_id=first.publication_id,
        previous_publication_hash=first.seal.publication_hash,
        target_publication_id=second.publication_id,
        target_publication_hash=second.seal.publication_hash,
        transitioned_at=second.first_published_at,
    )
    rollback_id = str(uuid4())
    rollback_at = _NOW + timedelta(seconds=20)
    rollback = PublicationRollback(
        target_publication_id=first.publication_id,
        previous_publication_id=second.publication_id,
        reason="rollback",
        operator="operator-1",
        observed_at=rollback_at,
        rollback_id=rollback_id,
    )
    rollback_event = PriceLimitPublicationTimelineEvent(
        kind=PriceLimitPublicationEventKind.ROLLBACK,
        event_id=rollback_id,
        dataset_key=first.seal.dataset_contract.key.value,
        publication_key=first.seal.publication_key,
        previous_publication_id=second.publication_id,
        previous_publication_hash=second.seal.publication_hash,
        target_publication_id=first.publication_id,
        target_publication_hash=first.seal.publication_hash,
        transitioned_at=rollback_at,
        rollback=rollback,
    )
    pointer = _pointer(first, activation_id=rollback_id, updated_at=rollback_at)
    server_now = rollback_at + timedelta(seconds=10)

    assert (
        resolve_price_limit_publication_at(
            records=(first, second),
            events=(start, forward, rollback_event),
            current_pointer=pointer,
            as_of=_NOW + timedelta(seconds=5),
            server_now=server_now,
        )
        == first
    )
    assert (
        resolve_price_limit_publication_at(
            records=(first, second),
            events=(start, forward, rollback_event),
            current_pointer=pointer,
            as_of=_NOW + timedelta(seconds=15),
            server_now=server_now,
        )
        == second
    )
    assert (
        resolve_price_limit_publication_at(
            records=(first, second),
            events=(start, forward, rollback_event),
            current_pointer=pointer,
            as_of=_NOW + timedelta(seconds=25),
            server_now=server_now,
        )
        == first
    )
    assert (
        resolve_price_limit_publication_at(
            records=(first, second),
            events=(start, forward, rollback_event),
            current_pointer=pointer,
            as_of=_NOW - timedelta(seconds=1),
            server_now=server_now,
        )
        is None
    )
    with pytest.raises(PriceLimitPublicationError):
        resolve_price_limit_publication_at(
            records=(first, second),
            events=(start, forward, rollback_event),
            current_pointer=pointer,
            as_of=server_now + timedelta(seconds=1),
            server_now=server_now,
        )


def test_timeline_event_guards_reject_partial_scope_identity_and_rollback_drift() -> None:
    record = _record()
    event = _first_event(record)
    invalid_events = (
        {"kind": "first_publish"},
        {"event_id": "bad activation"},
        {"dataset_key": "equity.price.bar"},
        {"publication_key": " "},
        {"target_publication_id": "bad"},
        {"target_publication_hash": "sha256:" + "a" * 64},
        {"transitioned_at": datetime(2026, 10, 29, 2, 0)},
        {"previous_publication_id": str(uuid4())},
        {"previous_publication_hash": "a" * 64},
        {
            "rollback": PublicationRollback(
                target_publication_id=record.publication_id,
                previous_publication_id="",
                reason="rollback",
                operator="operator-1",
                observed_at=_NOW + timedelta(seconds=10),
                rollback_id=str(uuid4()),
            )
        },
    )
    for changes in invalid_events:
        with pytest.raises((PriceLimitPublicationError, ValueError)):
            replace(event, **changes)

    rollback_id = str(uuid4())
    rollback = PublicationRollback(
        target_publication_id=record.publication_id,
        previous_publication_id=str(uuid4()),
        reason="test rollback",
        operator="operator-1",
        observed_at=_NOW + timedelta(seconds=1),
        rollback_id=rollback_id,
    )
    event_with_rollback = replace(
        event,
        kind=PriceLimitPublicationEventKind.ROLLBACK,
        event_id=rollback_id,
        previous_publication_id=rollback.previous_publication_id,
        previous_publication_hash="c" * 64,
        transitioned_at=rollback.observed_at,
        rollback=rollback,
    )
    with pytest.raises(PriceLimitPublicationError):
        replace(event_with_rollback, event_id=str(uuid4()))
    with pytest.raises(PriceLimitPublicationError):
        replace(event_with_rollback, rollback=None)


def test_timeline_rejects_empty_gaps_bad_records_and_unordered_or_dangling_events() -> None:
    record = _record()
    event = _first_event(record)
    pointer = _pointer(record)
    absent = PriceLimitPublicationPointerExpectation(
        dataset_key="equity.price.limit",
        publication_key=record.seal.publication_key,
        pointer_id=None,
        publication_id=None,
        publication_hash=None,
        activation_id=None,
        updated_at=None,
    )
    assert (
        validate_price_limit_publication_timeline(records=(), events=(), current_pointer=absent)
        is None
    )

    invalid_inputs = (
        ([record], (), absent),
        ((record,), (), absent),
        ((), (), pointer),
        ((record,), (event,), absent),
        ((object(),), (event,), pointer),
        ((record,), [event], pointer),
        ((record,), (object(),), pointer),
        ((record, record), (event,), pointer),
        ((record,), (replace(event, target_publication_id=str(uuid4())),), pointer),
        ((record,), (replace(event, target_publication_hash="a" * 64),), pointer),
        ((record,), (replace(event, publication_key="price-limit:" + "a" * 64),), pointer),
    )
    for records, events, current_pointer in invalid_inputs:
        with pytest.raises(PriceLimitPublicationError):
            validate_price_limit_publication_timeline(
                records=cast(tuple[PriceLimitFormalPublicationRecord, ...], records),
                events=cast(tuple[PriceLimitPublicationTimelineEvent, ...], events),
                current_pointer=current_pointer,
            )
    with pytest.raises(PriceLimitPublicationError):
        validate_price_limit_publication_timeline(
            records=(record, _record(_seal(_snapshot(provider_id=8)))),
            events=(event,),
            current_pointer=pointer,
        )
    with pytest.raises(PriceLimitPublicationError):
        validate_price_limit_publication_timeline(
            records=(record,),
            events=(event,),
            current_pointer=cast(PriceLimitPublicationPointerExpectation, object()),
        )


def test_timeline_rejects_missing_predecessors_duplicate_times_and_forward_identity_reuse() -> None:
    first = _record()
    second = _record(
        _seal(_snapshot(payload_marker="6")),
        first_published_at=_NOW + timedelta(seconds=10),
        first_activation_id="activation-2",
    )
    first_event = _first_event(first)
    forward = PriceLimitPublicationTimelineEvent(
        kind=PriceLimitPublicationEventKind.FORWARD_PUBLISH,
        event_id="activation-2",
        dataset_key=second.seal.dataset_contract.key.value,
        publication_key=second.seal.publication_key,
        previous_publication_id=first.publication_id,
        previous_publication_hash=first.seal.publication_hash,
        target_publication_id=second.publication_id,
        target_publication_hash=second.seal.publication_hash,
        transitioned_at=second.first_published_at,
    )
    pointer = _pointer(second)
    rejected_timelines: tuple[tuple[PriceLimitPublicationTimelineEvent, ...], ...] = (
        (replace(first_event, kind=PriceLimitPublicationEventKind.FORWARD_PUBLISH),),
        (
            replace(
                first_event,
                previous_publication_id=str(uuid4()),
                previous_publication_hash="a" * 64,
            ),
        ),
        (first_event, replace(forward, kind=PriceLimitPublicationEventKind.FIRST_PUBLISH)),
        (first_event, replace(forward, transitioned_at=first_event.transitioned_at)),
        (
            first_event,
            replace(forward, transitioned_at=first_event.transitioned_at - timedelta(seconds=1)),
        ),
        (first_event, replace(forward, event_id=first_event.event_id)),
        (first_event, replace(forward, previous_publication_id=str(uuid4()))),
        (first_event, replace(forward, previous_publication_hash="f" * 64)),
    )
    for events in rejected_timelines:
        with pytest.raises(PriceLimitPublicationError):
            validate_price_limit_publication_timeline(
                records=(first, second), events=events, current_pointer=pointer
            )

    third = _record(
        _seal(_snapshot(payload_marker="8")),
        first_published_at=_NOW + timedelta(seconds=30),
        first_activation_id="activation-3",
    )
    unpublished_forward = PriceLimitPublicationTimelineEvent(
        kind=PriceLimitPublicationEventKind.FORWARD_PUBLISH,
        event_id="wrong-activation",
        dataset_key=third.seal.dataset_contract.key.value,
        publication_key=third.seal.publication_key,
        previous_publication_id=first.publication_id,
        previous_publication_hash=first.publication_hash,
        target_publication_id=third.publication_id,
        target_publication_hash=third.publication_hash,
        transitioned_at=third.first_published_at + timedelta(seconds=1),
    )
    with pytest.raises(PriceLimitPublicationError):
        validate_price_limit_publication_timeline(
            records=(first, third),
            events=(first_event, unpublished_forward),
            current_pointer=replace(
                pointer,
                publication_id=third.publication_id,
                publication_hash=third.publication_hash,
                activation_id=unpublished_forward.event_id,
                updated_at=unpublished_forward.transitioned_at,
            ),
        )

    repeated_forward = replace(
        forward,
        event_id="activation-3",
        previous_publication_id=second.publication_id,
        previous_publication_hash=second.publication_hash,
        transitioned_at=second.first_published_at + timedelta(seconds=10),
    )
    rollback_id = str(uuid4())
    rollback_time = second.first_published_at + timedelta(seconds=5)
    rollback = PublicationRollback(
        target_publication_id=first.publication_id,
        previous_publication_id=second.publication_id,
        reason="restore prior reference",
        operator="operator-1",
        observed_at=rollback_time,
        rollback_id=rollback_id,
    )
    rollback_event = PriceLimitPublicationTimelineEvent(
        kind=PriceLimitPublicationEventKind.ROLLBACK,
        event_id=rollback_id,
        dataset_key=first.seal.dataset_contract.key.value,
        publication_key=first.seal.publication_key,
        previous_publication_id=second.publication_id,
        previous_publication_hash=second.publication_hash,
        target_publication_id=first.publication_id,
        target_publication_hash=first.publication_hash,
        transitioned_at=rollback_time,
        rollback=rollback,
    )
    with pytest.raises(PriceLimitPublicationError):
        validate_price_limit_publication_timeline(
            records=(first, second),
            events=(first_event, forward, rollback_event, repeated_forward),
            current_pointer=replace(
                pointer,
                publication_id=second.publication_id,
                publication_hash=second.publication_hash,
                activation_id=repeated_forward.event_id,
                updated_at=repeated_forward.transitioned_at,
            ),
        )

    returned_forward = replace(
        repeated_forward,
        previous_publication_id=first.publication_id,
        previous_publication_hash=first.publication_hash,
    )
    with pytest.raises(PriceLimitPublicationError):
        validate_price_limit_publication_timeline(
            records=(first, second),
            events=(first_event, forward, rollback_event, returned_forward),
            current_pointer=replace(
                pointer,
                publication_id=second.publication_id,
                publication_hash=second.publication_hash,
                activation_id=returned_forward.event_id,
                updated_at=returned_forward.transitioned_at,
            ),
        )

    unknown_record = _record(
        _seal(_snapshot(payload_marker="9")),
        first_published_at=second.first_published_at + timedelta(seconds=30),
        first_activation_id="activation-unknown",
    )
    rollback_to_unknown = replace(
        rollback_event,
        event_id="rollback-unknown",
        previous_publication_id=second.publication_id,
        previous_publication_hash=second.publication_hash,
        target_publication_id=unknown_record.publication_id,
        target_publication_hash=unknown_record.publication_hash,
        transitioned_at=second.first_published_at + timedelta(seconds=20),
        rollback=PublicationRollback(
            target_publication_id=unknown_record.publication_id,
            previous_publication_id=second.publication_id,
            reason="unknown target",
            operator="operator-1",
            observed_at=second.first_published_at + timedelta(seconds=20),
            rollback_id="rollback-unknown",
        ),
    )
    with pytest.raises(PriceLimitPublicationError):
        validate_price_limit_publication_timeline(
            records=(first, second, unknown_record),
            events=(first_event, forward, rollback_to_unknown),
            current_pointer=replace(
                pointer,
                publication_id=unknown_record.publication_id,
                publication_hash=unknown_record.publication_hash,
                activation_id=rollback_to_unknown.event_id,
                updated_at=rollback_to_unknown.transitioned_at,
            ),
        )


def test_timeline_requires_pointer_endpoint_and_resolution_checks_future_pointer_clock() -> None:
    record = _record()
    event = _first_event(record)
    pointer = _pointer(record)
    with pytest.raises(PriceLimitPublicationError):
        validate_price_limit_publication_timeline(
            records=(record,),
            events=(event,),
            current_pointer=replace(pointer, publication_id=str(uuid4())),
        )
    with pytest.raises(PriceLimitPublicationError):
        validate_price_limit_publication_timeline(
            records=(record,),
            events=(event,),
            current_pointer=replace(pointer, publication_key="price-limit:" + "0" * 64),
        )

    future_record = _record(first_published_at=_NOW + timedelta(seconds=30))
    future_event = _first_event(future_record)
    future_pointer = _pointer(future_record)
    with pytest.raises(PriceLimitPublicationError):
        resolve_price_limit_publication_at(
            records=(future_record,),
            events=(future_event,),
            current_pointer=future_pointer,
            as_of=_NOW + timedelta(seconds=20),
            server_now=_NOW + timedelta(seconds=20),
        )
