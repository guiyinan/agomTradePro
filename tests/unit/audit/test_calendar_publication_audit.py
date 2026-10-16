from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import cast
from uuid import uuid4

import pytest

from apps.audit.application.calendar_publication_audit import (
    CALENDAR_AUDIT_READ_PERMISSION,
    AppendCalendarPublicationAuditUseCase,
    CalendarPublicationAuditCorruption,
    CalendarPublicationAuditDenied,
    CalendarPublicationAuditOutboxWriter,
    CalendarPublicationAuditReaderContext,
    CalendarPublicationAuditUnavailable,
    CalendarPublicationAuditValidationError,
    CalendarPublicationBlockedObservation,
    CalendarPublicationPublishedObservation,
    ListCalendarPublicationAuditEventsCommand,
    ListCalendarPublicationAuditEventsUseCase,
    build_calendar_publication_blocked_event,
    build_calendar_publication_published_event,
)
from apps.audit.domain.calendar_publication_audit import (
    CALENDAR_PUBLICATION_BLOCKED_EVENT,
    CALENDAR_PUBLISH_PERMISSION,
    CalendarPublicationAuditContractError,
    CalendarPublicationAuditEvidence,
    CalendarPublicationBlockedDetail,
    CalendarPublicationPublishedDetail,
    calendar_publication_event_identity,
    calendar_publication_event_selector,
    calendar_publication_stream_id,
    validate_calendar_publication_event,
)
from apps.audit.domain.system_audit_event import (
    AuditActorRef,
    AuditCorrelations,
    AuditSeverity,
    SystemAuditEvent,
)
from core.exceptions import AuthorizationError

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
DATASET = "exchange.calendar.days"
EXCHANGE = "SSE"


@dataclass
class FakePublisherPrincipal:
    """Test principal modeling the Data Center's locked live lease."""

    actor_type: str = "django_user"
    actor_id: str = "django-user:7"
    permission_codename: str = "publish_exchange_calendar"
    database_alias: str = "default"
    verified_at: datetime = NOW - timedelta(seconds=1)
    user_id: int = 7
    live: bool = True
    assertions: int = 0

    def assert_live(self) -> None:
        """Count and reject use of an expired or revoked test lease."""

        self.assertions += 1
        if not self.live:
            raise AuthorizationError("test publisher lease expired")


def _evidence() -> CalendarPublicationAuditEvidence:
    """Build an exact synthetic snapshot/raw reference binding."""

    first_seen = NOW - timedelta(hours=2)
    return CalendarPublicationAuditEvidence(
        snapshot_id=str(uuid4()),
        exchange=EXCHANGE,
        coverage_start=date(2026, 10, 16),
        coverage_end=date(2026, 12, 31),
        provider_name="tushare",
        first_seen_at=first_seen,
        snapshot_recorded_at=first_seen + timedelta(seconds=1),
        source_published_at=None,
        fact_content_hash="a" * 64,
        snapshot_content_hash="sha256:" + "b" * 64,
        snapshot_record_digest="sha256:" + "c" * 64,
        raw_payload_id=str(uuid4()),
        raw_payload_hash="sha256:" + "d" * 64,
        raw_record_digest="sha256:" + "e" * 64,
        raw_body_sha256="f" * 64,
        raw_retained_content_sha256="1" * 64,
        raw_request_scope_sha256="2" * 64,
        original_body_retained=True,
        response_completed_at=first_seen,
        raw_provider_name="tushare",
        raw_dataset_key="exchange.calendar.days",
        raw_transport="http-json",
    )


def _published_observation() -> CalendarPublicationPublishedObservation:
    """Build one immutable published outcome for builder tests."""

    return CalendarPublicationPublishedObservation(
        detail=CalendarPublicationPublishedDetail(
            dataset_key=DATASET,
            exchange=EXCHANGE,
            publication_id="publication-001",
            publication_key="effective",
            policy_version="calendar-v1",
            publication_hash="3" * 64,
            snapshot_evidence=_evidence(),
        ),
        recorded_at=NOW,
    )


def _published_event(
    *,
    principal: FakePublisherPrincipal | None = None,
    sequence_no: int = 1,
    predecessor_hash: str | None = None,
) -> SystemAuditEvent:
    """Build one published event under the synthetic locked principal."""

    return build_calendar_publication_published_event(
        _published_observation(),
        principal=principal or FakePublisherPrincipal(),
        database_alias="default",
        sequence_no=sequence_no,
        predecessor_hash=predecessor_hash,
    )


def _event_with_detail(
    event: SystemAuditEvent,
    detail: dict[str, object],
    *,
    event_id: str | None = None,
    detail_schema: str | None = None,
    recorded_at: datetime | None = None,
    occurred_at: datetime | None = None,
    correlations: AuditCorrelations | None = None,
    actor: AuditActorRef | None = None,
    severity: AuditSeverity | None = None,
) -> SystemAuditEvent:
    """Rebuild the envelope hash around one deliberate contract mutation."""

    return SystemAuditEvent.create(
        event_id=event_id if event_id is not None else event.event_id,
        event_version=event.event_version,
        schema_version=event.schema_version,
        category=event.category,
        event_type=event.event_type,
        owner=event.owner,
        write_policy=event.write_policy,
        outcome=event.outcome,
        severity=severity if severity is not None else event.severity,
        reason_codes=event.reason_codes,
        occurred_at=occurred_at if occurred_at is not None else event.occurred_at,
        recorded_at=recorded_at if recorded_at is not None else event.recorded_at,
        observed_at=event.observed_at,
        actor=actor if actor is not None else event.actor,
        source_app=event.source_app,
        source_component=event.source_component,
        source_surface=event.source_surface,
        correlations=correlations if correlations is not None else event.correlations,
        resource=event.resource,
        dataset_key=event.dataset_key,
        provider_key=event.provider_key,
        capability=event.capability,
        publication_id=event.publication_id,
        evidence_refs=event.evidence_refs,
        detail_schema=detail_schema if detail_schema is not None else event.detail_schema,
        detail=detail,
        stream_id=event.stream_id,
        sequence_no=event.sequence_no,
        predecessor_hash=event.predecessor_hash,
        idempotency_key=event.idempotency_key,
        scope=None,
    )


def test_published_builder_binds_fact_row_and_raw_response_without_source_clock_invention() -> None:
    principal = FakePublisherPrincipal()
    event = _published_event(principal=principal)
    validate_calendar_publication_event(event)

    assert principal.assertions >= 1
    assert event.scope is None
    assert event.observed_at is None
    assert event.actor.actor_id == "django-user:7"
    assert event.evidence_refs[0].content_hash == "a" * 64
    detail = CalendarPublicationPublishedDetail.from_payload(event.detail)
    payload = detail.to_payload()
    assert payload["authentication_mode"] == "session"
    assert payload["permission_codename"] == "publish_exchange_calendar"
    evidence = payload["snapshot_evidence"]
    assert isinstance(evidence, dict)
    snapshot = evidence["snapshot"]
    raw = evidence["raw_reference"]
    assert isinstance(snapshot, dict)
    assert isinstance(raw, dict)
    assert snapshot["source_published_at"] is None
    assert snapshot["fact_content_hash"] == "a" * 64
    assert snapshot["content_hash"] == "sha256:" + "b" * 64
    assert snapshot["record_digest"] == "sha256:" + "c" * 64
    assert raw["body_sha256"] == "f" * 64
    assert raw["response_time_semantics"] == "local_response_body_completion"


def test_blocked_builder_keeps_attempt_identity_without_fabricating_candidate_evidence() -> None:
    observation = CalendarPublicationBlockedObservation(
        detail=CalendarPublicationBlockedDetail(
            dataset_key=DATASET,
            exchange=EXCHANGE,
            request_id="request-blocked-1",
            blocked_reason="calendar_source_unavailable",
        ),
        recorded_at=NOW,
    )
    event = build_calendar_publication_blocked_event(
        observation,
        principal=FakePublisherPrincipal(),
        database_alias="default",
        sequence_no=1,
        predecessor_hash=None,
    )

    validate_calendar_publication_event(event)
    assert event.event_type == CALENDAR_PUBLICATION_BLOCKED_EVENT
    assert event.scope is None
    assert event.publication_id is None
    assert event.evidence_refs == ()
    assert event.correlations.evidence_ref == "calendar-publication-attempt:request-blocked-1"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("permission_codename", "change_exchange_calendar", "permission_codename"),
        ("authentication_mode", "token", "authentication_mode"),
    ],
)
def test_published_detail_labels_are_closed_even_when_envelope_hash_is_recomputed(
    field: str,
    value: str,
    message: str,
) -> None:
    event = _published_event()
    detail = dict(event.detail)
    detail[field] = value
    changed = _event_with_detail(event, detail)

    with pytest.raises(CalendarPublicationAuditContractError, match=message):
        validate_calendar_publication_event(changed)


def test_raw_boolean_and_hash_domains_are_type_sensitive() -> None:
    payload = _evidence().to_payload()
    raw_reference = payload["raw_reference"]
    assert isinstance(raw_reference, dict)
    raw_reference["original_body_retained"] = 1
    with pytest.raises(CalendarPublicationAuditContractError, match="boolean"):
        CalendarPublicationAuditEvidence.from_payload(payload)

    evidence = _evidence()
    with pytest.raises(CalendarPublicationAuditContractError, match="fact_content_hash"):
        replace(
            evidence,
            fact_content_hash="sha256:" + "a" * 64,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("coverage_end", date(2026, 10, 15), "coverage is reversed"),
        ("source_published_at", datetime(2026, 10, 16), "source_published_at"),
        ("snapshot_recorded_at", NOW - timedelta(hours=3), "precedes local first_seen_at"),
        ("original_body_retained", 1, "original_body_retained must be bool"),
        ("first_seen_at", NOW - timedelta(hours=3), "first_seen_at must equal"),
        ("provider_name", "another-provider", "providers differ"),
        ("coverage_start", NOW, "coverage_start must be a date"),
        ("snapshot_id", "not-a-uuid", "snapshot_id must be a canonical UUID"),
        ("fact_content_hash", "sha256:" + "a" * 64, "fact_content_hash"),
        ("snapshot_content_hash", "a" * 64, "snapshot_content_hash"),
    ],
)
def test_evidence_rejects_inconsistent_source_binding(
    field: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(CalendarPublicationAuditContractError, match=message):
        replace(_evidence(), **{field: value})


def test_evidence_payload_requires_exact_keys_types_and_canonical_date_time() -> None:
    with pytest.raises(CalendarPublicationAuditContractError, match="must be an object"):
        CalendarPublicationAuditEvidence.from_payload(None)

    payload = _evidence().to_payload()
    payload["unexpected"] = "value"
    with pytest.raises(CalendarPublicationAuditContractError, match="unknown or missing keys"):
        CalendarPublicationAuditEvidence.from_payload(payload)

    payload = _evidence().to_payload()
    payload[1] = "non-string key"
    with pytest.raises(CalendarPublicationAuditContractError, match="must be an object"):
        CalendarPublicationAuditEvidence.from_payload(payload)

    payload = _evidence().to_payload()
    raw = payload["raw_reference"]
    assert isinstance(raw, dict)
    raw["response_time_semantics"] = "upstream_observed_at"
    with pytest.raises(CalendarPublicationAuditContractError, match="semantics"):
        CalendarPublicationAuditEvidence.from_payload(payload)

    payload = _evidence().to_payload()
    snapshot = payload["snapshot"]
    assert isinstance(snapshot, dict)
    snapshot["coverage_start"] = "20261016"
    with pytest.raises(CalendarPublicationAuditContractError, match="not canonical"):
        CalendarPublicationAuditEvidence.from_payload(payload)

    payload = _evidence().to_payload()
    snapshot = payload["snapshot"]
    assert isinstance(snapshot, dict)
    snapshot["coverage_start"] = "2026-99-16"
    with pytest.raises(CalendarPublicationAuditContractError, match="not an ISO date"):
        CalendarPublicationAuditEvidence.from_payload(payload)

    payload = _evidence().to_payload()
    snapshot = payload["snapshot"]
    assert isinstance(snapshot, dict)
    snapshot["recorded_at"] = "2026-99-16T12:00:00.000000Z"
    with pytest.raises(CalendarPublicationAuditContractError, match="is invalid"):
        CalendarPublicationAuditEvidence.from_payload(payload)

    payload = _evidence().to_payload()
    raw = payload["raw_reference"]
    assert isinstance(raw, dict)
    raw["body_sha256"] = 123
    with pytest.raises(CalendarPublicationAuditContractError, match="must be a string"):
        CalendarPublicationAuditEvidence.from_payload(payload)

    payload = _evidence().to_payload()
    raw = payload["raw_reference"]
    assert isinstance(raw, dict)
    raw["original_body_retained"] = 1
    with pytest.raises(CalendarPublicationAuditContractError, match="must be a boolean"):
        CalendarPublicationAuditEvidence.from_payload(payload)


def test_typed_details_reject_wrong_evidence_exchange_and_block_reason() -> None:
    published = CalendarPublicationPublishedDetail(
        dataset_key=DATASET,
        exchange=EXCHANGE,
        publication_id="publication-001",
        publication_key="effective",
        policy_version="calendar-v1",
        publication_hash="3" * 64,
        snapshot_evidence=_evidence(),
    )
    with pytest.raises(CalendarPublicationAuditContractError, match="typed contract"):
        replace(published, snapshot_evidence=cast(CalendarPublicationAuditEvidence, object()))
    with pytest.raises(CalendarPublicationAuditContractError, match="exchanges differ"):
        replace(published, exchange="SZE")
    with pytest.raises(CalendarPublicationAuditContractError, match="RawPayload dataset"):
        replace(published, snapshot_evidence=replace(_evidence(), raw_dataset_key="other.dataset"))

    with pytest.raises(CalendarPublicationAuditContractError, match="not canonical"):
        CalendarPublicationBlockedDetail(
            dataset_key=DATASET,
            exchange=EXCHANGE,
            request_id="request-1",
            blocked_reason="Bad Reason",
        )
    with pytest.raises(CalendarPublicationAuditContractError, match="typed contract"):
        CalendarPublicationBlockedDetail(
            dataset_key=DATASET,
            exchange=EXCHANGE,
            request_id="request-1",
            blocked_reason="calendar_source_unavailable",
            snapshot_evidence=cast(CalendarPublicationAuditEvidence, object()),
        )
    with pytest.raises(CalendarPublicationAuditContractError, match="exchanges differ"):
        CalendarPublicationBlockedDetail(
            dataset_key=DATASET,
            exchange="SZE",
            request_id="request-1",
            blocked_reason="calendar_source_unavailable",
            snapshot_evidence=_evidence(),
        )
    with pytest.raises(CalendarPublicationAuditContractError, match="RawPayload datasets differ"):
        CalendarPublicationBlockedDetail(
            dataset_key=DATASET,
            exchange=EXCHANGE,
            request_id="request-3",
            blocked_reason="calendar_source_unavailable",
            snapshot_evidence=replace(_evidence(), raw_dataset_key="other.dataset"),
        )

    detail = CalendarPublicationBlockedDetail(
        dataset_key=DATASET,
        exchange=EXCHANGE,
        request_id="request-2",
        blocked_reason="calendar_source_unavailable",
    )
    with pytest.raises(CalendarPublicationAuditContractError, match="must be a string"):
        payload = detail.to_payload()
        payload["dataset_key"] = 2
        CalendarPublicationBlockedDetail.from_payload(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("permission_codename", "view_exchange_calendar_publication_audit"),
        ("database_alias", "archive"),
        ("actor_id", "django-user:8"),
    ],
)
def test_builder_rejects_wrong_locked_principal(field: str, value: str) -> None:
    principal = FakePublisherPrincipal()
    setattr(principal, field, value)

    with pytest.raises(CalendarPublicationAuditDenied):
        _published_event(principal=principal)


def test_builder_rechecks_the_live_lease_before_using_actor_fields() -> None:
    principal = FakePublisherPrincipal(live=False)

    with pytest.raises(CalendarPublicationAuditDenied):
        _published_event(principal=principal)

    assert principal.assertions == 1


class FakeCalendarReaderPrincipal:
    """Mutable test lease whose permission can be revoked during a read."""

    def __init__(
        self,
        *,
        live: bool = True,
        user_id: int = 7,
        database_alias: str = "default",
        verified_at: datetime = NOW,
        session_expires_at: datetime = NOW + timedelta(hours=1),
    ) -> None:
        self.actor_type = "django_user"
        self.actor_id = f"django-user:{user_id}"
        self.permission_codename = "view_exchange_calendar_publication_audit"
        self.database_alias = database_alias
        self.authority_content_hash = "sha256:" + "a" * 64
        self.verified_at = verified_at
        self.session_expires_at = session_expires_at
        self.user_id = user_id
        self.live = live
        self.assertions = 0

    def assert_live(self) -> None:
        self.assertions += 1
        if not self.live:
            raise AuthorizationError("reader permission lease is no longer live")


def test_calendar_read_context_cannot_be_self_asserted_or_reused_for_another_selector() -> None:
    context = CalendarPublicationAuditReaderContext(
        authority_source_id="calendar-read-permission",
        authority_source_version="v1",
        authority_content_hash="sha256:" + "a" * 64,
        dataset_key=DATASET,
        exchange=EXCHANGE,
        user_id=7,
        actor_id="django-user:7",
        database_alias="default",
        authority_state="active",
        verified_at=NOW,
        session_expires_at=NOW + timedelta(hours=1),
    )

    with pytest.raises(CalendarPublicationAuditDenied):
        context.assert_live()

    principal = FakeCalendarReaderPrincipal()
    sealed = CalendarPublicationAuditReaderContext._from_authority(
        principal=principal,
        dataset_key=DATASET,
        exchange=EXCHANGE,
    )
    sealed.assert_live()
    assert sealed.verified_at == NOW
    assert sealed.permission_codename == CALENDAR_AUDIT_READ_PERMISSION
    principal.live = False
    with pytest.raises(CalendarPublicationAuditDenied):
        sealed.assert_live()


class FakeCalendarReadAuthorityProvider:
    """Authority port fake that issues only one exact dataset/exchange context."""

    def __init__(
        self,
        context: CalendarPublicationAuditReaderContext | None,
        *,
        principal: FakeCalendarReaderPrincipal | None = None,
        revoke_on_normal_exit: bool = False,
    ) -> None:
        self.context = context
        self.principal = principal
        self.revoke_on_normal_exit = revoke_on_normal_exit
        self.request_proof: object | None = None
        self.active = False
        self.exit_count = 0
        self.active_during_exception = False

    @contextmanager
    def _locked_context(
        self, context: CalendarPublicationAuditReaderContext
    ) -> Iterator[CalendarPublicationAuditReaderContext]:
        self.active = True
        try:
            yield context
        except BaseException:
            self.active_during_exception = self.active
            raise
        else:
            if self.revoke_on_normal_exit and self.principal is not None:
                self.principal.live = False
            context.assert_live()
        finally:
            self.active = False
            self.exit_count += 1

    def lock_reader(
        self,
        *,
        request_proof: object,
        dataset_key: str,
        exchange: str,
        database_alias: str,
    ) -> AbstractContextManager[CalendarPublicationAuditReaderContext] | None:
        self.request_proof = request_proof
        del dataset_key, exchange, database_alias
        if self.context is None:
            return None
        return self._locked_context(self.context)


class FakeCalendarAuditReader:
    """Dedicated selector fake that makes broad generic reads visible in tests."""

    database_alias = "default"

    def __init__(self, events: tuple[SystemAuditEvent, ...] = ()) -> None:
        self.events = events
        self.selector: tuple[str, str, datetime] | None = None

    def list_calendar_publication_events(
        self,
        *,
        dataset_key: str,
        exchange: str,
        as_of: datetime,
    ) -> tuple[SystemAuditEvent, ...]:
        self.selector = (dataset_key, exchange, as_of)
        return self.events


def _reader_context(
    *,
    dataset_key: str = DATASET,
    exchange: str = EXCHANGE,
    alias: str = "default",
    principal: FakeCalendarReaderPrincipal | None = None,
) -> CalendarPublicationAuditReaderContext:
    """Issue one test-only exact reader capability."""

    return CalendarPublicationAuditReaderContext._from_authority(
        principal=principal or FakeCalendarReaderPrincipal(database_alias=alias),
        dataset_key=dataset_key,
        exchange=exchange,
    )


def test_reader_uses_only_dedicated_dataset_exchange_selector() -> None:
    event = _published_event()
    provider = FakeCalendarReadAuthorityProvider(_reader_context())
    repository = FakeCalendarAuditReader((event,))
    proof = object()
    result = ListCalendarPublicationAuditEventsUseCase(
        authority_provider=provider,
        repository=repository,
    ).execute(
        ListCalendarPublicationAuditEventsCommand(
            dataset_key=DATASET,
            exchange=EXCHANGE,
            as_of=NOW,
            request_proof=proof,
        )
    )

    assert result.events == (event,)
    assert repository.selector == (DATASET, EXCHANGE, NOW)
    assert provider.request_proof is proof


def test_reader_live_permission_does_not_need_to_precede_historical_event_cutoff() -> None:
    """A current locked grant authorizes a historical event query."""

    original_event = _published_event()
    event = _event_with_detail(
        original_event,
        dict(original_event.detail),
        recorded_at=NOW - timedelta(hours=1),
        occurred_at=NOW - timedelta(hours=1),
    )
    context = CalendarPublicationAuditReaderContext._from_authority(
        principal=FakeCalendarReaderPrincipal(),
        dataset_key=DATASET,
        exchange=EXCHANGE,
    )
    repository = FakeCalendarAuditReader((event,))
    historical_cutoff = NOW - timedelta(minutes=30)

    result = ListCalendarPublicationAuditEventsUseCase(
        authority_provider=FakeCalendarReadAuthorityProvider(context),
        repository=repository,
    ).execute(
        ListCalendarPublicationAuditEventsCommand(
            dataset_key=DATASET,
            exchange=EXCHANGE,
            as_of=historical_cutoff,
            request_proof=object(),
        )
    )

    assert result.events == (event,)
    assert repository.selector == (DATASET, EXCHANGE, historical_cutoff)


def test_result_validation_runs_inside_locked_reader_context() -> None:
    """A bad result must fail before the authority context manager exits."""

    context = _reader_context()
    provider = FakeCalendarReadAuthorityProvider(context)
    repository = FakeCalendarAuditReader((_published_event(),))
    with pytest.raises(CalendarPublicationAuditCorruption, match="outside the exact selector"):
        ListCalendarPublicationAuditEventsUseCase(
            authority_provider=provider,
            repository=repository,
        ).execute(
            ListCalendarPublicationAuditEventsCommand(
                dataset_key=DATASET,
                exchange=EXCHANGE,
                as_of=NOW - timedelta(seconds=1),
                request_proof=object(),
            )
        )

    assert provider.active_during_exception
    assert provider.exit_count == 1


def test_live_permission_is_rechecked_after_query_and_at_lease_exit() -> None:
    """Revocation during a read cannot produce a successful result."""

    principal = FakeCalendarReaderPrincipal()
    context = _reader_context(principal=principal)
    provider = FakeCalendarReadAuthorityProvider(
        context,
        principal=principal,
        revoke_on_normal_exit=True,
    )
    repository = FakeCalendarAuditReader((_published_event(),))

    with pytest.raises(CalendarPublicationAuditDenied):
        ListCalendarPublicationAuditEventsUseCase(
            authority_provider=provider,
            repository=repository,
        ).execute(
            ListCalendarPublicationAuditEventsCommand(
                dataset_key=DATASET,
                exchange=EXCHANGE,
                as_of=NOW,
                request_proof=object(),
            )
        )

    assert repository.selector == (DATASET, EXCHANGE, NOW)
    assert provider.exit_count == 1
    assert not provider.active


def test_raw_user_id_or_missing_authority_provider_cannot_authorize_read() -> None:
    provider = FakeCalendarReadAuthorityProvider(None)
    repository = FakeCalendarAuditReader()

    with pytest.raises(CalendarPublicationAuditUnavailable):
        ListCalendarPublicationAuditEventsUseCase(
            authority_provider=provider,
            repository=repository,
        ).execute(
            ListCalendarPublicationAuditEventsCommand(
                dataset_key=DATASET,
                exchange=EXCHANGE,
                as_of=NOW,
                request_proof={"user_id": 7},
            )
        )

    assert repository.selector is None


def test_reader_maps_provider_authorization_failure_to_typed_denial() -> None:
    class DenyingProvider:
        def lock_reader(
            self,
            *,
            request_proof: object,
            dataset_key: str,
            exchange: str,
            database_alias: str,
        ) -> AbstractContextManager[CalendarPublicationAuditReaderContext] | None:
            del request_proof, dataset_key, exchange, database_alias
            raise AuthorizationError("permission revoked")

    repository = FakeCalendarAuditReader()
    use_case = ListCalendarPublicationAuditEventsUseCase(
        authority_provider=DenyingProvider(),
        repository=repository,
    )
    with pytest.raises(CalendarPublicationAuditDenied):
        use_case.execute(
            ListCalendarPublicationAuditEventsCommand(
                dataset_key=DATASET,
                exchange=EXCHANGE,
                as_of=NOW,
                request_proof=object(),
            )
        )
    assert repository.selector is None


def test_reader_rejects_permission_for_another_exchange_or_database_alias() -> None:
    for context in (
        _reader_context(exchange="SZE"),
        _reader_context(alias="analytics"),
    ):
        repository = FakeCalendarAuditReader()
        with pytest.raises(CalendarPublicationAuditDenied):
            ListCalendarPublicationAuditEventsUseCase(
                authority_provider=FakeCalendarReadAuthorityProvider(context),
                repository=repository,
            ).execute(
                ListCalendarPublicationAuditEventsCommand(
                    dataset_key=DATASET,
                    exchange=EXCHANGE,
                    as_of=NOW,
                    request_proof=object(),
                )
            )
        assert repository.selector is None


def test_use_case_rejects_broken_predecessor_chain_from_repository() -> None:
    first = _published_event()
    second_observation = CalendarPublicationPublishedObservation(
        detail=CalendarPublicationPublishedDetail(
            dataset_key=DATASET,
            exchange=EXCHANGE,
            publication_id="publication-002",
            publication_key="effective",
            policy_version="calendar-v1",
            publication_hash="4" * 64,
            snapshot_evidence=_evidence(),
        ),
        recorded_at=NOW + timedelta(seconds=1),
    )
    second = build_calendar_publication_published_event(
        second_observation,
        principal=FakePublisherPrincipal(verified_at=NOW),
        database_alias="default",
        sequence_no=2,
        predecessor_hash="9" * 64,
    )
    use_case = ListCalendarPublicationAuditEventsUseCase(
        authority_provider=FakeCalendarReadAuthorityProvider(_reader_context()),
        repository=FakeCalendarAuditReader((first, second)),
    )

    with pytest.raises(CalendarPublicationAuditCorruption, match="predecessor chain"):
        use_case.execute(
            ListCalendarPublicationAuditEventsCommand(
                dataset_key=DATASET,
                exchange=EXCHANGE,
                as_of=NOW + timedelta(minutes=1),
                request_proof=object(),
            )
        )


def test_contract_rejects_an_unregistered_unscoped_event_and_unknown_selector_kind() -> None:
    event = _published_event()
    changed = SystemAuditEvent.create(
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
    with pytest.raises(CalendarPublicationAuditContractError, match="unregistered"):
        validate_calendar_publication_event(changed)
    with pytest.raises(CalendarPublicationAuditContractError, match="kind"):
        calendar_publication_event_identity(
            event_kind="rolled-back",
            dataset_key=DATASET,
            exchange=EXCHANGE,
            request_identity="id-1",
        )
    with pytest.raises(CalendarPublicationAuditContractError, match="kind"):
        calendar_publication_event_identity(
            event_kind=cast(str, []),
            dataset_key=DATASET,
            exchange=EXCHANGE,
            request_identity="id-1",
        )


def test_stream_and_event_identity_are_exact_and_bounded() -> None:
    stream = calendar_publication_stream_id(DATASET, EXCHANGE)
    event_id, idempotency_key = calendar_publication_event_identity(
        event_kind="published",
        dataset_key=DATASET,
        exchange=EXCHANGE,
        request_identity="publication-001",
    )

    assert stream.startswith("data.calendar.publication:")
    assert len(stream.rsplit(":", maxsplit=1)[1]) == 64
    assert event_id == idempotency_key
    with pytest.raises(CalendarPublicationAuditContractError, match="token"):
        calendar_publication_stream_id("calendar with space", EXCHANGE)


def test_public_observation_types_reject_wrong_detail_classes() -> None:
    with pytest.raises(ValueError, match="CalendarPublicationPublishedDetail"):
        CalendarPublicationPublishedObservation(
            detail=cast(CalendarPublicationPublishedDetail, object()), recorded_at=NOW
        )
    with pytest.raises(ValueError, match="CalendarPublicationBlockedDetail"):
        CalendarPublicationBlockedObservation(
            detail=cast(CalendarPublicationBlockedDetail, object()), recorded_at=NOW
        )


def test_builder_error_mapping_uses_typed_application_error() -> None:
    principal = FakePublisherPrincipal()
    principal.verified_at = datetime(2026, 10, 16, 12, 0)
    with pytest.raises(CalendarPublicationAuditDenied):
        build_calendar_publication_published_event(
            _published_observation(),
            principal=principal,
            database_alias="default",
            sequence_no=1,
            predecessor_hash=None,
        )

    observation = _published_observation()
    object.__setattr__(observation, "recorded_at", datetime(2026, 10, 16, 12, 0))
    with pytest.raises(CalendarPublicationAuditValidationError, match="recorded_at"):
        build_calendar_publication_published_event(
            observation,
            principal=FakePublisherPrincipal(),
            database_alias="default",
            sequence_no=1,
            predecessor_hash=None,
        )


def test_append_command_rejects_integer_lookalike_for_replay_flag() -> None:
    use_case = AppendCalendarPublicationAuditUseCase(
        cast(CalendarPublicationAuditOutboxWriter, object())
    )
    with pytest.raises(CalendarPublicationAuditValidationError, match="must be a boolean"):
        use_case.execute_published_in_caller_transaction(
            _published_observation(),
            principal=FakePublisherPrincipal(),
            exact_replay=cast(bool, 1),
        )


def test_unscoped_event_contract_rejects_anonymous_service_actor() -> None:
    event = _published_event()
    changed = SystemAuditEvent.create(
        event_id=event.event_id,
        event_version=event.event_version,
        schema_version=event.schema_version,
        category=event.category,
        event_type=event.event_type,
        owner=event.owner,
        write_policy=event.write_policy,
        outcome=event.outcome,
        severity=event.severity,
        reason_codes=event.reason_codes,
        occurred_at=event.occurred_at,
        recorded_at=event.recorded_at,
        observed_at=event.observed_at,
        actor=event.actor.__class__("service", "calendar-publisher"),
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
    with pytest.raises(CalendarPublicationAuditContractError, match="common calendar contract"):
        validate_calendar_publication_event(changed)


def test_registered_event_contract_rechecks_hash_clock_actor_correlation_and_identity() -> None:
    event = _published_event()
    with pytest.raises(CalendarPublicationAuditContractError, match="exact SystemAuditEvent"):
        validate_calendar_publication_event(cast(SystemAuditEvent, object()))

    with pytest.raises(CalendarPublicationAuditContractError, match="hashes are invalid"):
        validate_calendar_publication_event(replace(event, content_hash="0" * 64))

    with pytest.raises(CalendarPublicationAuditContractError, match="published event fields"):
        validate_calendar_publication_event(
            _event_with_detail(event, dict(event.detail), detail_schema="wrong.calendar.schema")
        )

    with pytest.raises(CalendarPublicationAuditContractError, match="published event fields"):
        validate_calendar_publication_event(
            _event_with_detail(
                event,
                dict(event.detail),
                recorded_at=NOW - timedelta(hours=3),
                occurred_at=NOW - timedelta(hours=3),
            )
        )

    with pytest.raises(CalendarPublicationAuditContractError, match="common calendar contract"):
        validate_calendar_publication_event(
            _event_with_detail(
                event,
                dict(event.detail),
                actor=AuditActorRef("django_user", "django-user:7", "Display Name"),
            )
        )

    with pytest.raises(CalendarPublicationAuditContractError, match="common calendar contract"):
        validate_calendar_publication_event(
            _event_with_detail(
                event,
                dict(event.detail),
                correlations=AuditCorrelations(
                    request_id="unexpected",
                    dataset_key=DATASET,
                    capability="calendar.publication",
                    publication_id="publication-001",
                    evidence_ref=f"calendar-snapshot:{CalendarPublicationPublishedDetail.from_payload(event.detail).snapshot_evidence.snapshot_id}:{'a' * 64}",
                ),
            )
        )

    with pytest.raises(
        CalendarPublicationAuditContractError, match="identity is not deterministic"
    ):
        validate_calendar_publication_event(
            _event_with_detail(event, dict(event.detail), event_id="other-event")
        )


def test_blocked_contract_selector_supports_absent_and_present_candidate_evidence() -> None:
    for evidence in (None, _evidence()):
        observation = CalendarPublicationBlockedObservation(
            detail=CalendarPublicationBlockedDetail(
                dataset_key=DATASET,
                exchange=EXCHANGE,
                request_id=f"request-{evidence is not None}",
                blocked_reason="calendar_source_unavailable",
                snapshot_evidence=evidence,
            ),
            recorded_at=NOW,
        )
        event = build_calendar_publication_blocked_event(
            observation,
            principal=FakePublisherPrincipal(),
            database_alias="default",
            sequence_no=1,
            predecessor_hash=None,
        )
        validate_calendar_publication_event(event)
        assert calendar_publication_event_selector(event) == (DATASET, EXCHANGE)

        bad_correlations = AuditCorrelations(
            request_id="another-request",
            dataset_key=DATASET,
            capability="calendar.publication",
            publication_id=None,
            evidence_ref=(
                f"calendar-snapshot:{evidence.snapshot_id}:{evidence.fact_content_hash}"
                if evidence is not None
                else f"calendar-publication-attempt:request-{evidence is not None}"
            ),
        )
        with pytest.raises(CalendarPublicationAuditContractError, match="common calendar contract"):
            validate_calendar_publication_event(
                _event_with_detail(
                    event,
                    dict(event.detail),
                    correlations=bad_correlations,
                )
            )


def test_module_contract_constants_are_distinct_from_generic_publication_events() -> None:
    assert CALENDAR_PUBLICATION_BLOCKED_EVENT != "data.publication.blocked"
    assert CALENDAR_PUBLISH_PERMISSION == "publish_exchange_calendar"
    assert len(calendar_publication_stream_id(DATASET, EXCHANGE)) <= 256
