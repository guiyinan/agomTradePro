"""Validated price-limit publication event-chain resolution."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .formal_price_limit_publication import (
        PriceLimitFormalPublicationRecord,
        PriceLimitPublicationPointerExpectation,
        PriceLimitPublicationTimelineEvent,
    )


def _record_index(
    records: tuple[PriceLimitFormalPublicationRecord, ...],
) -> dict[str, PriceLimitFormalPublicationRecord]:
    """Validate exact records and reject duplicate publication identities."""

    from .formal_price_limit_publication import PriceLimitFormalPublicationRecord, _fail

    if type(records) is not tuple:
        raise _fail(
            "PRICE_LIMIT_PUBLICATION_TIMELINE_INVALID", "records must be an immutable tuple"
        )
    by_id: dict[str, PriceLimitFormalPublicationRecord] = {}
    by_hash: set[str] = set()
    scope: tuple[str, str] | None = None
    for record in records:
        if type(record) is not PriceLimitFormalPublicationRecord:
            raise _fail("PRICE_LIMIT_PUBLICATION_RECORD_INVALID", "timeline record must be typed")
        record.validate()
        record_scope = (record.seal.dataset_contract.key.value, record.seal.publication_key)
        if scope is None:
            scope = record_scope
        elif record_scope != scope:
            raise _fail(
                "PRICE_LIMIT_PUBLICATION_SCOPE_MISMATCH", "records span multiple pointer scopes"
            )
        if record.publication_id in by_id or record.publication_hash in by_hash:
            raise _fail(
                "PRICE_LIMIT_PUBLICATION_RECORD_DUPLICATE", "publication identity is duplicated"
            )
        by_id[record.publication_id] = record
        by_hash.add(record.publication_hash)
    return by_id


def validate_price_limit_publication_timeline(
    *,
    records: tuple[PriceLimitFormalPublicationRecord, ...],
    events: tuple[PriceLimitPublicationTimelineEvent, ...],
    current_pointer: PriceLimitPublicationPointerExpectation,
) -> PriceLimitFormalPublicationRecord | None:
    """Verify a complete scope-local event chain and its current pointer endpoint."""

    from .formal_price_limit_publication import (
        PriceLimitPublicationEventKind,
        PriceLimitPublicationPointerExpectation,
        PriceLimitPublicationTimelineEvent,
        _fail,
    )

    if type(current_pointer) is not PriceLimitPublicationPointerExpectation:
        raise _fail("PRICE_LIMIT_PUBLICATION_POINTER_INVALID", "current pointer must be typed")
    current_pointer.validate()
    by_id = _record_index(records)
    if type(events) is not tuple:
        raise _fail("PRICE_LIMIT_PUBLICATION_TIMELINE_INVALID", "events must be an immutable tuple")
    if not events:
        if by_id or not current_pointer.is_absent:
            raise _fail(
                "PRICE_LIMIT_PUBLICATION_TIMELINE_GAP", "records or pointer exist without events"
            )
        return None
    if current_pointer.is_absent:
        raise _fail(
            "PRICE_LIMIT_PUBLICATION_POINTER_INVALID", "event history needs a current pointer"
        )

    expected_scope: tuple[str, str] | None = None
    seen_event_ids: set[str] = set()
    seen_times: set[datetime] = set()
    first_publication_ids: set[str] = set()
    winner: PriceLimitFormalPublicationRecord | None = None
    previous_event_time: datetime | None = None
    for index, event in enumerate(events):
        if type(event) is not PriceLimitPublicationTimelineEvent:
            raise _fail("PRICE_LIMIT_PUBLICATION_EVENT_INVALID", "timeline event must be typed")
        event.validate()
        event_scope = (event.dataset_key, event.publication_key)
        if expected_scope is None:
            expected_scope = event_scope
        elif event_scope != expected_scope:
            raise _fail(
                "PRICE_LIMIT_PUBLICATION_SCOPE_MISMATCH", "events span multiple pointer scopes"
            )
        if event.event_id in seen_event_ids or event.transitioned_at in seen_times:
            raise _fail(
                "PRICE_LIMIT_PUBLICATION_EVENT_DUPLICATE", "event identity or time is duplicated"
            )
        if previous_event_time is not None and event.transitioned_at <= previous_event_time:
            raise _fail(
                "PRICE_LIMIT_PUBLICATION_EVENT_ORDER_INVALID", "events are not strictly increasing"
            )
        target = by_id.get(event.target_publication_id)
        if target is None:
            raise _fail(
                "PRICE_LIMIT_PUBLICATION_EVENT_TARGET_UNKNOWN", "event target record is missing"
            )
        if (target.seal.dataset_contract.key.value, target.seal.publication_key) != event_scope:
            raise _fail("PRICE_LIMIT_PUBLICATION_SCOPE_MISMATCH", "event target has another scope")
        if target.publication_hash != event.target_publication_hash:
            raise _fail(
                "PRICE_LIMIT_PUBLICATION_EVENT_TARGET_MISMATCH", "event target hash differs"
            )
        if winner is None:
            if index != 0 or event.kind is not PriceLimitPublicationEventKind.FIRST_PUBLISH:
                raise _fail(
                    "PRICE_LIMIT_PUBLICATION_TIMELINE_GAP", "history must begin with first publish"
                )
            if event.previous_publication_id is not None:
                raise _fail(
                    "PRICE_LIMIT_PUBLICATION_EVENT_PREVIOUS_INVALID",
                    "first publish has a predecessor",
                )
            if (
                target.first_published_at != event.transitioned_at
                or target.first_activation_id != event.event_id
            ):
                raise _fail(
                    "PRICE_LIMIT_PUBLICATION_EVENT_TARGET_MISMATCH",
                    "first publish differs from record",
                )
            winner = target
            first_publication_ids.add(target.publication_id)
        else:
            if event.kind is PriceLimitPublicationEventKind.FIRST_PUBLISH:
                raise _fail(
                    "PRICE_LIMIT_PUBLICATION_TIMELINE_GAP", "first publish may appear only once"
                )
            if (
                event.previous_publication_id != winner.publication_id
                or event.previous_publication_hash != winner.publication_hash
            ):
                raise _fail(
                    "PRICE_LIMIT_PUBLICATION_EVENT_PREVIOUS_MISMATCH",
                    "event predecessor is not winner",
                )
            if target.publication_id == winner.publication_id:
                raise _fail(
                    "PRICE_LIMIT_PUBLICATION_EVENT_NOOP", "transition cannot point to itself"
                )
            if event.kind is PriceLimitPublicationEventKind.FORWARD_PUBLISH:
                if target.publication_id in first_publication_ids:
                    raise _fail(
                        "PRICE_LIMIT_PUBLICATION_FORWARD_REUSE_INVALID",
                        "a previously published identity can return only through rollback",
                    )
                if (
                    target.first_published_at != event.transitioned_at
                    or target.first_activation_id != event.event_id
                ):
                    raise _fail(
                        "PRICE_LIMIT_PUBLICATION_EVENT_TARGET_MISMATCH",
                        "forward publication differs from its first activation record",
                    )
                first_publication_ids.add(target.publication_id)
            elif event.kind is PriceLimitPublicationEventKind.ROLLBACK:
                if target.publication_id not in first_publication_ids:
                    raise _fail(
                        "PRICE_LIMIT_PUBLICATION_ROLLBACK_TARGET_UNKNOWN",
                        "rollback target was never formally published",
                    )
            else:
                raise _fail("PRICE_LIMIT_PUBLICATION_EVENT_INVALID", "unsupported transition kind")
            winner = target
        seen_event_ids.add(event.event_id)
        seen_times.add(event.transitioned_at)
        previous_event_time = event.transitioned_at

    if first_publication_ids != set(by_id):
        raise _fail(
            "PRICE_LIMIT_PUBLICATION_TIMELINE_GAP", "published record lacks its first event"
        )
    if winner is None:
        raise _fail("PRICE_LIMIT_PUBLICATION_TIMELINE_GAP", "history has no winner")
    if expected_scope != (current_pointer.dataset_key, current_pointer.publication_key):
        raise _fail(
            "PRICE_LIMIT_PUBLICATION_SCOPE_MISMATCH", "current pointer scope differs from history"
        )
    last_event = events[-1]
    if (
        winner.publication_id != current_pointer.publication_id
        or winner.publication_hash != current_pointer.publication_hash
        or current_pointer.activation_id != last_event.event_id
        or current_pointer.updated_at != last_event.transitioned_at
    ):
        raise _fail(
            "PRICE_LIMIT_PUBLICATION_POINTER_MISMATCH",
            "pointer does not match verified history end",
        )
    return winner


def resolve_price_limit_publication_at(
    *,
    records: tuple[PriceLimitFormalPublicationRecord, ...],
    events: tuple[PriceLimitPublicationTimelineEvent, ...],
    current_pointer: PriceLimitPublicationPointerExpectation,
    as_of: datetime,
    server_now: datetime,
) -> PriceLimitFormalPublicationRecord | None:
    """Resolve the verified current winner at a cutoff without sorting fallbacks."""

    from .formal_price_limit_publication import _fail, _require_utc

    _require_utc(as_of, "as_of")
    _require_utc(server_now, "server_now")
    if as_of > server_now:
        raise _fail(
            "PRICE_LIMIT_PUBLICATION_CUTOFF_FUTURE", "as_of cannot be later than server_now"
        )
    validate_price_limit_publication_timeline(
        records=records,
        events=events,
        current_pointer=current_pointer,
    )
    pointer_updated_at = current_pointer.updated_at
    if pointer_updated_at is not None and pointer_updated_at > server_now:
        raise _fail(
            "PRICE_LIMIT_PUBLICATION_POINTER_FUTURE", "current pointer is later than server_now"
        )
    by_id = _record_index(records)
    winner_at: PriceLimitFormalPublicationRecord | None = None
    for event in events:
        if event.transitioned_at > as_of:
            break
        winner_at = by_id[event.target_publication_id]
    if winner_at is None:
        return None
    return winner_at
