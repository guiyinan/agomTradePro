from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, fields, replace
from datetime import UTC, datetime, timedelta, timezone
from typing import cast
from uuid import uuid4

import pytest

import apps.audit.domain.price_limit_publication_audit as price_limit_audit_domain
from apps.audit.application.price_limit_publication_audit import (
    PriceLimitPublicationAuditDenied,
    PriceLimitPublicationAuditValidationError,
)
from apps.audit.domain.price_limit_publication_audit import (
    PRICE_LIMIT_PUBLICATION_PUBLISHED_EVENT,
    PRICE_LIMIT_PUBLICATION_ROLLED_BACK_EVENT,
    PriceLimitPublicationAuditContractError,
    PriceLimitPublicationPublishedDetail,
    PriceLimitPublicationRecordEvidence,
    PriceLimitPublicationRollbackDetail,
    PriceLimitPublicationTransitionEvidence,
    price_limit_publication_event_identity,
    validate_price_limit_publication_event,
)
from apps.audit.domain.system_audit_event import (
    AuditActorRef,
    AuditCategory,
    AuditCorrelations,
    AuditOutcome,
    AuditResourceRef,
    AuditScopeRef,
    AuditSeverity,
    AuditWritePolicy,
    SystemAuditEvent,
)
from apps.data_center.domain.control_plane import PublicationRollback
from apps.data_center.domain.formal_price_limit_publication import (
    PriceLimitFormalPublicationRecord,
    PriceLimitPublicationEventKind,
    PriceLimitPublicationTimelineEvent,
)
from core.exceptions import AuthorizationError
from core.integration.price_limit_formal_publication_audit import (
    build_price_limit_publication_audit_detail,
)
from tests.unit.data_center.test_formal_price_limit_publication import (
    _NOW,
    _record,
)


def _rehash_event(event: SystemAuditEvent, **changes: object) -> SystemAuditEvent:
    """Change one canonical event envelope field and recompute its hashes."""

    values = {
        field.name: getattr(event, field.name)
        for field in fields(event)
        if field.name not in {"identity_hash", "content_hash"}
    }
    values.update(changes)
    return SystemAuditEvent.create(**values)


def _set_path(payload: dict[str, object], path: tuple[str, ...], value: object) -> None:
    """Replace one exact nested JSON field in a copied test payload."""

    current = payload
    for key in path[:-1]:
        child = current[key]
        assert isinstance(child, dict)
        current = child
    current[path[-1]] = value


@dataclass
class _Principal:
    actor_type: str = "django_user"
    actor_id: str = "django-user:7"
    permission_codename: str = "publish_price_limit"
    database_alias: str = "default"
    user_id: int = 7
    permission_id: int = 11
    verified_at: datetime = _NOW - timedelta(seconds=1)
    authority_content_hash: str = "sha256:" + "a" * 64
    live: bool = True
    assertions: int = 0

    def assert_live(self) -> None:
        self.assertions += 1
        if not self.live:
            raise AuthorizationError("price-limit publisher lease is expired")


def _first_transition(record: object) -> PriceLimitPublicationTimelineEvent:
    value = cast(PriceLimitFormalPublicationRecord, record)
    return PriceLimitPublicationTimelineEvent(
        kind=PriceLimitPublicationEventKind.FIRST_PUBLISH,
        event_id=value.first_activation_id,
        dataset_key=value.seal.dataset_contract.key.value,
        publication_key=value.seal.publication_key,
        previous_publication_id=None,
        previous_publication_hash=None,
        target_publication_id=value.publication_id,
        target_publication_hash=value.publication_hash,
        transitioned_at=value.first_published_at,
    )


def _rollback_transition(
    *,
    previous: object,
    target: object,
    transitioned_at: datetime = _NOW + timedelta(minutes=2),
) -> PriceLimitPublicationTimelineEvent:
    previous_record = cast(PriceLimitFormalPublicationRecord, previous)
    target_record = cast(PriceLimitFormalPublicationRecord, target)
    rollback_id = str(uuid4())
    rollback = PublicationRollback(
        target_publication_id=target_record.publication_id,
        reason="restore prior price limit",
        operator="django-user:7",
        observed_at=transitioned_at,
        previous_publication_id=previous_record.publication_id,
        rollback_id=rollback_id,
    )
    return PriceLimitPublicationTimelineEvent(
        kind=PriceLimitPublicationEventKind.ROLLBACK,
        event_id=rollback_id,
        dataset_key=target_record.seal.dataset_contract.key.value,
        publication_key=target_record.seal.publication_key,
        previous_publication_id=previous_record.publication_id,
        previous_publication_hash=previous_record.publication_hash,
        target_publication_id=target_record.publication_id,
        target_publication_hash=target_record.publication_hash,
        transitioned_at=transitioned_at,
        rollback=rollback,
    )


def test_published_and_rollback_are_distinct_closed_unscoped_event_families() -> None:
    from apps.audit.application.price_limit_publication_audit import (
        build_price_limit_publication_event,
    )

    first = _record(first_activation_id=str(uuid4()))
    first_event = _first_transition(first)
    principal = _Principal()
    detail = build_price_limit_publication_audit_detail(
        first,
        first_event,
        observed_server_at=_NOW,
    )
    published = build_price_limit_publication_event(
        detail,
        principal=principal,
        database_alias="default",
        sequence_no=1,
        predecessor_hash=None,
    )

    validate_price_limit_publication_event(published)
    parsed = PriceLimitPublicationPublishedDetail.from_payload(published.detail)
    assert published.event_type == PRICE_LIMIT_PUBLICATION_PUBLISHED_EVENT
    assert published.scope is None
    assert published.observed_at == _NOW
    assert published.occurred_at == first_event.transitioned_at
    assert parsed.transition.event_id == first_event.event_id
    assert published.event_id != first_event.event_id
    assert parsed.publication.provider_id == first.seal.snapshot_reference.provider_id
    assert parsed.publication.asset_code == first.seal.snapshot_reference.asset_code
    assert (
        parsed.publication.request_scope_sha256
        == first.seal.snapshot_reference.request_scope_sha256
    )
    assert parsed.publication.seal == first.seal.to_payload()
    assert principal.assertions >= 1

    current = _record(
        first_published_at=_NOW + timedelta(minutes=1),
        first_activation_id=str(uuid4()),
    )
    rollback_event = _rollback_transition(previous=current, target=first)
    rollback_detail = build_price_limit_publication_audit_detail(
        first,
        rollback_event,
        observed_server_at=_NOW + timedelta(minutes=2),
    )
    rolled_back = build_price_limit_publication_event(
        rollback_detail,
        principal=_Principal(),
        database_alias="default",
        sequence_no=3,
        predecessor_hash="b" * 64,
    )

    validate_price_limit_publication_event(rolled_back)
    parsed_rollback = PriceLimitPublicationRollbackDetail.from_payload(rolled_back.detail)
    assert rolled_back.event_type == PRICE_LIMIT_PUBLICATION_ROLLED_BACK_EVENT
    assert rolled_back.scope is None
    assert parsed_rollback.transition.event_id == rollback_event.event_id
    assert parsed_rollback.transition.previous_publication_id == current.publication_id
    assert parsed_rollback.transition.target_publication_hash == first.publication_hash
    assert parsed_rollback.transition.rollback["rollback_id"] == rollback_event.event_id


@pytest.mark.parametrize("field", ["permission_codename", "database_alias", "actor_id"])
def test_price_limit_builder_rejects_another_live_publisher(field: str) -> None:
    from apps.audit.application.price_limit_publication_audit import (
        build_price_limit_publication_event,
    )

    record = _record(first_activation_id=str(uuid4()))
    detail = build_price_limit_publication_audit_detail(
        record,
        _first_transition(record),
        observed_server_at=_NOW,
    )
    principal = _Principal()
    setattr(principal, field, "wrong-value")
    with pytest.raises(PriceLimitPublicationAuditDenied):
        build_price_limit_publication_event(
            detail,
            principal=principal,
            database_alias="default",
            sequence_no=1,
            predecessor_hash=None,
        )


def test_domain_rejects_mismatched_request_scope_seal_or_transition() -> None:
    record = _record(first_activation_id=str(uuid4()))
    detail = build_price_limit_publication_audit_detail(
        record,
        _first_transition(record),
        observed_server_at=_NOW,
    )
    payload = detail.to_payload()
    payload["publication"]["request_scope_sha256"] = "0" * 64
    with pytest.raises(PriceLimitPublicationAuditContractError):
        PriceLimitPublicationPublishedDetail.from_payload(payload)

    changed = replace(_first_transition(record), target_publication_hash="0" * 64)
    with pytest.raises(PriceLimitPublicationAuditValidationError):
        build_price_limit_publication_audit_detail(
            record,
            changed,
            observed_server_at=_NOW,
        )


def test_event_identity_is_stable_and_separates_publish_from_rollback() -> None:
    record = _record(first_activation_id=str(uuid4()))
    publish_identity = price_limit_publication_event_identity(
        publication_id=record.publication_id,
        publication_hash=record.publication_hash,
    )
    replay_identity = price_limit_publication_event_identity(
        publication_id=record.publication_id,
        publication_hash=record.publication_hash,
    )
    rollback_identity = price_limit_publication_event_identity(
        rollback_id=str(uuid4()),
    )

    assert publish_identity == replay_identity
    assert publish_identity != rollback_identity


def test_validator_rejects_unregistered_or_rehashed_cross_family_event() -> None:
    from apps.audit.application.price_limit_publication_audit import (
        build_price_limit_publication_event,
    )

    record = _record(first_activation_id=str(uuid4()))
    detail = build_price_limit_publication_audit_detail(
        record,
        _first_transition(record),
        observed_server_at=_NOW,
    )
    event = build_price_limit_publication_event(
        detail,
        principal=_Principal(),
        database_alias="default",
        sequence_no=1,
        predecessor_hash=None,
    )
    bad = SystemAuditEvent.create(
        event_id=event.event_id,
        event_version=event.event_version,
        schema_version=event.schema_version,
        category=event.category,
        event_type="data.publication.published",
        owner=event.owner,
        write_policy=event.write_policy,
        outcome=event.outcome,
        severity=event.severity,
        reason_codes=event.reason_codes,
        occurred_at=event.occurred_at,
        recorded_at=event.recorded_at,
        observed_at=event.observed_at,
        actor=event.actor,
        source_app=event.source_app,
        source_component=event.source_component,
        source_surface=event.source_surface,
        correlations=event.correlations,
        resource=event.resource,
        dataset_key=event.dataset_key,
        provider_key=event.provider_key,
        capability=event.capability,
        publication_id=event.publication_id,
        evidence_refs=event.evidence_refs,
        detail_schema=event.detail_schema,
        detail=event.detail,
        stream_id=event.stream_id,
        sequence_no=event.sequence_no,
        predecessor_hash=event.predecessor_hash,
        idempotency_key=event.idempotency_key,
        scope=None,
    )
    with pytest.raises(PriceLimitPublicationAuditContractError):
        validate_price_limit_publication_event(bad)


def test_forward_publication_round_trips_without_reusing_the_business_activation_id() -> None:
    from apps.audit.application.price_limit_publication_audit import (
        build_price_limit_publication_event,
    )

    previous = _record(first_activation_id=str(uuid4()))
    target = _record(
        first_published_at=_NOW + timedelta(minutes=1),
        first_activation_id=str(uuid4()),
    )
    transition = PriceLimitPublicationTimelineEvent(
        kind=PriceLimitPublicationEventKind.FORWARD_PUBLISH,
        event_id=target.first_activation_id,
        dataset_key=target.seal.dataset_contract.key.value,
        publication_key=target.seal.publication_key,
        previous_publication_id=previous.publication_id,
        previous_publication_hash=previous.publication_hash,
        target_publication_id=target.publication_id,
        target_publication_hash=target.publication_hash,
        transitioned_at=target.first_published_at,
    )
    detail = build_price_limit_publication_audit_detail(
        target,
        transition,
        observed_server_at=_NOW + timedelta(minutes=2),
    )
    event = build_price_limit_publication_event(
        detail,
        principal=_Principal(),
        database_alias="default",
        sequence_no=2,
        predecessor_hash="a" * 64,
    )

    validate_price_limit_publication_event(event)
    parsed = PriceLimitPublicationPublishedDetail.from_payload(event.detail)
    assert parsed.transition.kind == "forward_publish"
    assert parsed.transition.previous_publication_id == previous.publication_id
    assert parsed.transition.previous_publication_hash == previous.publication_hash
    assert parsed.transition.event_id == target.first_activation_id
    assert event.event_id != target.first_activation_id
    with pytest.raises(PriceLimitPublicationAuditContractError):
        PriceLimitPublicationRollbackDetail.from_payload(event.detail)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("encoding",), "price-limit-formal-publication.v2"),
        (("coverage_scope",), "implicit_provider_range"),
        (("must_not_use_for_decision",), False),
        (("must_not_execute",), False),
        (("currency",), "CNY"),
        (("source_clocks", "observed_at"), "2026-10-29T02:00:00+00:00"),
        (("dataset_contract", "key", "value"), "other.dataset"),
        (("policy", "dataset", "value"), "other.dataset"),
        (("member_manifest_hash",), "sha256:" + "a" * 64),
        (("snapshot", "raw_reference", "body_sha256"), "sha256:" + "b" * 64),
        (("snapshot", "raw_reference", "payload_hash"), "c" * 64),
        (("snapshot", "raw_reference", "record_digest"), "d" * 64),
        (("snapshot", "raw_reference", "original_body_retained"), False),
        (("snapshot", "raw_reference", "retained_content_encoding"), "normalized_json"),
        (("snapshot", "raw_reference", "time_semantics"), "provider_published_at"),
        (("snapshot", "raw_reference", "dataset_key"), "other.dataset"),
        (("snapshot", "raw_reference", "provider_name"), "other_provider"),
        (("snapshot", "raw_reference", "request_scope_sha256"), "0" * 64),
        (("snapshot", "dataset_key"), "other.dataset"),
        (("snapshot_reference", "snapshot_id"), str(uuid4())),
        (("member_evidence", "dataset_key"), "other.dataset"),
        (("member_evidence", "publication_key"), "other-key"),
        (("member_evidence", "member", "raw_payload_hash"), "0" * 64),
        (("member_evidence", "member", "raw_payload_scope"), "batch_response_body"),
        (("member_evidence", "member", "fact_table"), "data_center_price_bar_fact"),
        (("member_evidence", "member", "fact_pk"), str(uuid4())),
        (("member_evidence", "member", "source_record_id"), str(uuid4())),
        (("member_evidence", "member", "fact_content_hash"), None),
        (("snapshot_reference", "content_hash"), "sha256:" + "e" * 64),
        (("snapshot_reference", "record_digest"), "sha256:" + "f" * 64),
        (("snapshot_reference", "raw_payload_id"), str(uuid4())),
        (("snapshot_reference", "raw_payload_hash"), "sha256:" + "0" * 64),
        (("snapshot_reference", "raw_record_digest"), "sha256:" + "9" * 64),
        (("member_evidence", "member", "fetched_at"), "2026-10-29T02:00:00+00:00"),
        (("snapshot", "response_completed_at"), "2026-10-29T02:00:00+00:00"),
        (("response_completed_at",), "2026-10-29T02:00:00+00:00"),
        (("member_evidence", "member", "fact_content_hash"), "sha256:" + "3" * 64),
    ],
)
def test_published_seal_rejects_source_or_manifest_substitution(
    path: tuple[str, ...], value: object
) -> None:
    record = _record(first_activation_id=str(uuid4()))
    detail = build_price_limit_publication_audit_detail(
        record,
        _first_transition(record),
        observed_server_at=_NOW,
    )
    payload = deepcopy(detail.to_payload())
    _set_path(payload, ("publication", "seal", *path), value)

    with pytest.raises(PriceLimitPublicationAuditContractError):
        PriceLimitPublicationPublishedDetail.from_payload(payload)


@pytest.mark.parametrize(
    "changes",
    [
        {"event_version": "2"},
        {"schema_version": "system-audit-event.v2"},
        {"detail_schema": "data.price_limit.publication.published.v2"},
        {"category": AuditCategory.EXECUTION_CONTROL},
        {"owner": "another_app"},
        {"write_policy": AuditWritePolicy.BEST_EFFORT},
        {"outcome": AuditOutcome.BLOCKED},
        {"severity": AuditSeverity.WARNING},
        {"reason_codes": ("other_reason",)},
        {"actor": AuditActorRef("service", "service:1")},
        {"scope": AuditScopeRef("tenant:test", "owner:test")},
        {"source_app": "another_app"},
        {"source_component": "another_component"},
        {"source_surface": "worker"},
        {"dataset_key": "other.dataset"},
        {"provider_key": "999"},
        {"capability": "another.capability"},
        {"publication_id": str(uuid4())},
        {"resource": AuditResourceRef("other_resource", "resource:1", "v1")},
        {"evidence_refs": ()},
        {"stream_id": "other.stream"},
        {"event_id": "different-event-id"},
        {"idempotency_key": "different-idempotency-key"},
        {"recorded_at": _NOW + timedelta(seconds=1)},
        {"observed_at": None},
        {"occurred_at": _NOW - timedelta(seconds=1)},
        {"correlations": AuditCorrelations(request_id="request:unexpected")},
    ],
)
def test_closed_event_rejects_rehashed_envelope_substitution(changes: dict[str, object]) -> None:
    from apps.audit.application.price_limit_publication_audit import (
        build_price_limit_publication_event,
    )

    record = _record(first_activation_id=str(uuid4()))
    detail = build_price_limit_publication_audit_detail(
        record,
        _first_transition(record),
        observed_server_at=_NOW,
    )
    event = build_price_limit_publication_event(
        detail,
        principal=_Principal(),
        database_alias="default",
        sequence_no=1,
        predecessor_hash=None,
    )
    changed_event = _rehash_event(event, **changes)

    with pytest.raises(PriceLimitPublicationAuditContractError):
        validate_price_limit_publication_event(changed_event)


@pytest.mark.parametrize(
    "bad_payload",
    [
        None,
        [],
        {1: "non-text key"},
        {"non_finite": float("nan")},
        {"non_finite": float("inf")},
        {"unsupported": object()},
        {"nested": {"": "empty key"}},
    ],
)
def test_domain_json_boundary_rejects_noncanonical_or_non_json_values(
    bad_payload: object,
) -> None:
    with pytest.raises(PriceLimitPublicationAuditContractError):
        price_limit_audit_domain._json_copy(bad_payload)


@pytest.mark.parametrize(
    ("parser", "value"),
    [
        (price_limit_audit_domain._parse_date, None),
        (price_limit_audit_domain._parse_date, "2026-10-28T00:00:00"),
        (price_limit_audit_domain._parse_date, "20261028"),
        (price_limit_audit_domain._parse_utc, None),
        (price_limit_audit_domain._parse_utc, "2026-10-29T02:00:00+00:00"),
        (price_limit_audit_domain._parse_utc, "not-a-timestampZ"),
        (price_limit_audit_domain._parse_utc, "2026-10-29T02:00:00Z"),
        (price_limit_audit_domain._parse_seal_utc, "not-a-timestamp"),
        (price_limit_audit_domain._parse_seal_utc, "2026-10-29T10:00:00+08:00"),
    ],
)
def test_domain_timestamp_and_date_parsers_require_exact_utc_forms(
    parser: Callable[[object, str], object], value: object
) -> None:
    with pytest.raises(PriceLimitPublicationAuditContractError):
        parser(value, "test")


def test_event_identity_and_stream_require_one_closed_price_limit_scope() -> None:
    record = _record(first_activation_id=str(uuid4()))
    with pytest.raises(PriceLimitPublicationAuditContractError):
        price_limit_audit_domain.price_limit_publication_stream_id("other.dataset", "pointer")
    with pytest.raises(PriceLimitPublicationAuditContractError):
        price_limit_audit_domain.price_limit_publication_event_identity()
    with pytest.raises(PriceLimitPublicationAuditContractError):
        price_limit_audit_domain.price_limit_publication_event_identity(
            rollback_id=str(uuid4()),
            publication_id=record.publication_id,
            publication_hash=record.publication_hash,
        )
    with pytest.raises(PriceLimitPublicationAuditContractError):
        price_limit_audit_domain.price_limit_publication_event_identity(
            publication_id="not-a-uuid",
            publication_hash=record.publication_hash,
        )
    with pytest.raises(PriceLimitPublicationAuditContractError):
        price_limit_audit_domain.price_limit_publication_event_identity(
            publication_id=record.publication_id,
            publication_hash="sha256:" + "a" * 64,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider_id", True),
        ("provider_id", 0),
        ("publication_key", "another-key"),
        ("effective_trade_date", "2026-10-28T00:00:00"),
        ("first_published_at", _NOW - timedelta(days=4)),
    ],
)
def test_publication_evidence_revalidates_scope_and_knowledge_time(
    field: str, value: object
) -> None:
    record = _record(first_activation_id=str(uuid4()))
    detail = build_price_limit_publication_audit_detail(
        record,
        _first_transition(record),
        observed_server_at=_NOW,
    )
    payload = deepcopy(detail.to_payload())
    payload["publication"][field] = value

    with pytest.raises(PriceLimitPublicationAuditContractError):
        PriceLimitPublicationRecordEvidence.from_payload(payload["publication"])


def test_detail_dtos_revalidate_types_target_hashes_and_observation_clocks() -> None:
    record = _record(first_activation_id=str(uuid4()))
    published = build_price_limit_publication_audit_detail(
        record,
        _first_transition(record),
        observed_server_at=_NOW,
    )
    with pytest.raises(PriceLimitPublicationAuditContractError):
        replace(published, publication=object())
    with pytest.raises(PriceLimitPublicationAuditContractError):
        replace(published, transition=object())
    with pytest.raises(PriceLimitPublicationAuditContractError):
        replace(published, transition=replace(published.transition, kind="rollback"))
    changed_target = replace(
        published.transition,
        target_publication_hash="f" * 64,
    )
    with pytest.raises(PriceLimitPublicationAuditContractError):
        replace(published, transition=changed_target)
    with pytest.raises(PriceLimitPublicationAuditContractError):
        replace(published, observed_server_at=_NOW - timedelta(seconds=1))

    previous = _record(
        first_published_at=_NOW + timedelta(minutes=1),
        first_activation_id=str(uuid4()),
    )
    rollback_event = _rollback_transition(previous=previous, target=record)
    rolled_back = build_price_limit_publication_audit_detail(
        record,
        rollback_event,
        observed_server_at=_NOW + timedelta(minutes=2),
    )
    assert type(rolled_back) is PriceLimitPublicationRollbackDetail
    with pytest.raises(PriceLimitPublicationAuditContractError):
        replace(rolled_back, publication=object())
    with pytest.raises(PriceLimitPublicationAuditContractError):
        replace(rolled_back, transition=object())
    with pytest.raises(PriceLimitPublicationAuditContractError):
        replace(
            rolled_back,
            transition=replace(rolled_back.transition, target_publication_hash="f" * 64),
        )
    with pytest.raises(PriceLimitPublicationAuditContractError):
        replace(rolled_back, observed_server_at=_NOW + timedelta(minutes=1))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rollback_id", str(uuid4())),
        ("target_publication_id", str(uuid4())),
        ("previous_publication_id", str(uuid4())),
        ("observed_at", "2026-10-29T02:03:00Z"),
        ("reason", "  "),
        ("operator", "human operator"),
    ],
)
def test_rollback_record_must_match_its_exact_pointer_transition(field: str, value: object) -> None:
    previous = _record(
        first_published_at=_NOW + timedelta(minutes=1),
        first_activation_id=str(uuid4()),
    )
    target = _record(first_activation_id=str(uuid4()))
    detail = build_price_limit_publication_audit_detail(
        target,
        _rollback_transition(previous=previous, target=target),
        observed_server_at=_NOW + timedelta(minutes=2),
    )
    payload = detail.transition.to_payload()
    rollback = dict(payload["rollback"])
    rollback[field] = value
    payload["rollback"] = rollback

    with pytest.raises(PriceLimitPublicationAuditContractError):
        PriceLimitPublicationTransitionEvidence.from_payload(payload)


def test_domain_mapping_and_token_boundary_require_canonical_nested_json() -> None:
    assert price_limit_audit_domain._mapping({"note": "ok"}, "test") == {"note": "ok"}
    with pytest.raises(PriceLimitPublicationAuditContractError):
        price_limit_audit_domain._mapping({"extra": "value"}, "test", {"required"})
    with pytest.raises(PriceLimitPublicationAuditContractError):
        price_limit_audit_domain._mapping("not-an-object", "test")
    for token in ("", " has-space", "has space", "x" * 301):
        with pytest.raises(PriceLimitPublicationAuditContractError):
            price_limit_audit_domain._require_token(token, "test")
    with pytest.raises(PriceLimitPublicationAuditContractError):
        price_limit_audit_domain._require_date(datetime(2026, 10, 28, tzinfo=UTC), "test")
    with pytest.raises(PriceLimitPublicationAuditContractError):
        price_limit_audit_domain._require_utc(
            datetime(2026, 10, 29, 10, tzinfo=timezone(timedelta(hours=8))), "test"
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "unknown"},
        {"dataset_key": "other.dataset"},
        {"previous_publication_id": str(uuid4())},
        {"previous_publication_hash": "a" * 64},
        {
            "kind": "forward_publish",
            "previous_publication_id": None,
            "previous_publication_hash": None,
        },
        {
            "kind": "forward_publish",
            "previous_publication_id": _record().publication_id,
            "previous_publication_hash": "a" * 64,
        },
        {"rollback": {}},
    ],
)
def test_timeline_contract_rejects_invalid_predecessor_or_family(
    changes: dict[str, object],
) -> None:
    record = _record(first_activation_id=str(uuid4()))
    detail = build_price_limit_publication_audit_detail(
        record,
        _first_transition(record),
        observed_server_at=_NOW,
    )
    transition = detail.transition
    if changes.get("kind") == "forward_publish" and changes.get("previous_publication_id"):
        changes = {
            **changes,
            "previous_publication_id": record.publication_id,
            "target_publication_id": record.publication_id,
        }
    with pytest.raises(PriceLimitPublicationAuditContractError):
        replace(transition, **changes)
