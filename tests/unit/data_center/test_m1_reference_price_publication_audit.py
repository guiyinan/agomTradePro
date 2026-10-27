"""Unit contracts for the M1 reference-price activation audit adapter."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

import pytest

from apps.audit.application.data_publication_audit import (
    DataPublicationManifestAuditObservation,
)
from apps.audit.application.data_quality_audit import AppendDataQualityAuditObservationUseCase
from apps.audit.application.system_audit_event_outbox import SystemAuditEventOutboxConflict
from apps.audit.domain.system_audit_event import AuditOutcome, SystemAuditEvent
from apps.data_center.application.publication_activation import (
    PublicationActivationError,
    PublicationActivationGroupCandidate,
    PublicationActivationGroupRequest,
    PublicationActivationManifestAuditWrite,
)
from apps.data_center.application.publication_quality import RecordPublicationQualityUseCase
from apps.data_center.application.publication_utils import member_reference, publication_hash
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    CoverageSnapshot,
    PublicationMember,
    PublicationState,
)
from apps.data_center.domain.publication_lanes import M1_REBALANCE_REFERENCE_PUBLICATION_KEY
from apps.data_center.domain.raw_audit_manifest import (
    CandidateRawAuditManifest,
    CandidateRawAuditReference,
)
from apps.data_center.infrastructure.m1_reference_price_publication_audit import (
    M1ReferencePricePublicationAuditWriter,
)
from core.integration.data_center_audit import (
    AuditScopeRef,
    DataPublicationRawAuditManifestReference,
    DataQualityAuditObservation,
    DataQualityStatusCount,
    SystemAuditEventOutboxCommit,
)

_NOW = datetime(2026, 10, 28, 8, 0, tzinfo=UTC)


@dataclass(frozen=True)
class _AuditCommit:
    marker: str


class _Delegate:
    database_alias = "default"

    def __init__(
        self, events: list[str], commits: tuple[SystemAuditEventOutboxCommit, ...]
    ) -> None:
        self.events = events
        self.commits = commits

    def append_manifest_required(self, **_kwargs: object) -> SystemAuditEventOutboxCommit:
        self.events.append("single-manifest")
        return self.commits[0]

    def append_manifest_group_required(
        self,
        *,
        request: PublicationActivationGroupRequest,
        writes: tuple[PublicationActivationManifestAuditWrite, ...],
    ) -> tuple[SystemAuditEventOutboxCommit, ...]:
        del request, writes
        self.events.append("manifest-group")
        return self.commits


class _QualityRecorder:
    database_alias = "default"

    def __init__(self, events: list[str], *, failure: Exception | None = None) -> None:
        self.events = events
        self.failure = failure
        self.calls: list[dict[str, str]] = []

    def execute(
        self,
        *,
        publication_id: str,
        run_id: str,
        ingested_run_id: str,
        provider_key: str,
    ) -> object:
        self.events.append("quality")
        self.calls.append(
            {
                "publication_id": publication_id,
                "run_id": run_id,
                "ingested_run_id": ingested_run_id,
                "provider_key": provider_key,
            }
        )
        if self.failure is not None:
            raise self.failure
        return object()


class _QualityPublicationReader:
    """Read the post-switch immutable publication snapshot for quality recording."""

    unit_of_work_key = "django:default"

    def __init__(self) -> None:
        self.publications: dict[str, CanonicalPublication] = {}
        self.members: dict[str, tuple[PublicationMember, ...]] = {}

    def get_by_id(self, publication_id: str) -> CanonicalPublication | None:
        return self.publications.get(publication_id)

    def list_members(self, publication_id: str) -> tuple[PublicationMember, ...]:
        return self.members[publication_id]


class _QualityScopeProvider:
    def __init__(self) -> None:
        self.current_scope = AuditScopeRef(tenant_id="tenant-1", owner_id="owner-1")
        self.fail = False
        self.calls: list[datetime] = []

    def get_scope(self, *, as_of: datetime) -> AuditScopeRef:
        self.calls.append(as_of)
        if self.fail:
            raise PermissionError("quality audit scope is no longer authorized")
        return self.current_scope


class _MutableClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def now(self) -> datetime:
        return self.current


class _MemoryQualityEventWriter:
    """Model immutable event identity and winner replay without Django or a database."""

    database_alias = "default"

    def __init__(self) -> None:
        self.events: list[SystemAuditEvent] = []

    def atomic(self) -> object:
        return nullcontext()

    def get_winner(
        self,
        *,
        event_id: str,
        event_version: str,
        as_of: datetime,
    ) -> SystemAuditEvent | None:
        del as_of
        return next(
            (
                event
                for event in self.events
                if event.event_id == event_id and event.event_version == event_version
            ),
            None,
        )

    def get_current_head(
        self,
        *,
        stream_id: str,
        as_of: datetime,
        scope: AuditScopeRef,
    ) -> SystemAuditEvent | None:
        del as_of
        matching = [
            event for event in self.events if event.stream_id == stream_id and event.scope == scope
        ]
        return max(matching, key=lambda event: event.sequence_no, default=None)

    def append_and_enqueue(
        self,
        event: SystemAuditEvent,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> SystemAuditEventOutboxCommit:
        if event.recorded_at != recorded_at:
            raise SystemAuditEventOutboxConflict("recorded_at differs from event winner")
        existing = self.get_winner(
            event_id=event.event_id,
            event_version=event.event_version,
            as_of=recorded_at,
        )
        if existing is not None:
            if existing != event:
                raise SystemAuditEventOutboxConflict(
                    "quality event identity already has another payload"
                )
            return _quality_event_commit(existing)
        head = self.get_current_head(
            stream_id=event.stream_id,
            as_of=recorded_at,
            scope=cast(AuditScopeRef, event.scope),
        )
        if head is None:
            if event.sequence_no != 1 or expected_predecessor_hash is not None:
                raise SystemAuditEventOutboxConflict("quality stream start differs")
        elif (
            event.sequence_no != head.sequence_no + 1
            or expected_predecessor_hash != head.content_hash
        ):
            raise SystemAuditEventOutboxConflict("quality stream head changed")
        self.events.append(event)
        return _quality_event_commit(event)


def _quality_event_commit(event: SystemAuditEvent) -> SystemAuditEventOutboxCommit:
    return SystemAuditEventOutboxCommit(
        event=event,
        outbox_id=uuid4(),
        event_id=event.event_id,
        idempotency_key=event.idempotency_key,
    )


def _write_inputs(
    *,
    raw_audit_count: int = 1,
    member_count: int = 1,
    quality_status: str = "accepted",
) -> tuple[PublicationActivationGroupRequest, PublicationActivationManifestAuditWrite]:
    """Build one sealed candidate, one member, and its exact manifest observation."""

    publication_id = str(uuid4())
    run_id = str(uuid4())
    ingested_run_id = str(uuid4())
    members = tuple(
        PublicationMember(
            member_id=str(uuid4()),
            publication_id=publication_id,
            dataset_key="equity.price.bar",
            natural_key=f"00000{index}.SZ:2026-10-27:1d:none:provider-source-key",
            source="provider-source-key",
            source_record_id=f"bar-{index}",
            fact_table="data_center_price_bar",
            fact_pk=str(index),
            observed_at=_NOW,
            quality_status=quality_status,
        )
        for index in range(1, member_count + 1)
    )
    publication_digest = publication_hash(tuple(member_reference(member) for member in members))
    publication = CanonicalPublication(
        publication_id=publication_id,
        dataset_key="equity.price.bar",
        publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
        policy_version="price-bar-v1",
        state=PublicationState.CANDIDATE,
        selected_source="provider-source-key",
        publication_hash=publication_digest,
        coverage=CoverageSnapshot(
            coverage_id=str(uuid4()),
            publication_id=publication_id,
            requested_count=member_count,
            eligible_count=member_count,
            selected_count=member_count,
            generated_at=_NOW,
        ),
        member_count=member_count,
        as_of=_NOW,
        run_id=run_id,
    )
    raw_references = tuple(
        CandidateRawAuditReference(
            raw_audit_id=str(index + 1),
            version="1",
            content_hash=f"{index + 1:064x}",
            provider_name="Tushare",
            capability="historical_price",
            run_id=run_id,
            ingested_run_id=ingested_run_id,
        )
        for index in range(raw_audit_count)
    )
    manifest = CandidateRawAuditManifest.create(
        publication_id=publication_id,
        publication_hash=publication_digest,
        run_id=run_id,
        dataset_key="equity.price.bar",
        publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
        task_attempt_id="m1-reference-attempt",
        raw_audits=raw_references,
        manifest_id=str(uuid4()),
    )
    observation = DataPublicationManifestAuditObservation(
        dataset_key="equity.price.bar",
        publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
        publication_id=publication_id,
        publication_version=publication.policy_version,
        publication_hash=publication_digest,
        provider_key=publication.selected_source,
        run_id=run_id,
        member_count=member_count,
        coverage_requested_count=member_count,
        coverage_eligible_count=member_count,
        coverage_selected_count=member_count,
        manifest_id=manifest.manifest_id,
        manifest_version=manifest.manifest_version,
        manifest_hash=manifest.manifest_hash,
        raw_audit_count=manifest.raw_audit_count,
        raw_audit_hash=manifest.raw_audit_hash,
        raw_audits=tuple(
            DataPublicationRawAuditManifestReference(
                raw_audit_id=item.raw_audit_id,
                version=item.version,
                content_hash=item.content_hash,
            )
            for item in manifest.raw_audits
        ),
        occurred_at=_NOW,
        recorded_at=_NOW,
        scope=AuditScopeRef(tenant_id="tenant-1", owner_id="owner-1"),
    )
    write = PublicationActivationManifestAuditWrite(
        publication=publication,
        members=members,
        manifest=manifest,
        observation=observation,
    )
    candidate = PublicationActivationGroupCandidate(
        dataset_key="equity.price.bar",
        publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
        candidate_publication_id=publication_id,
        candidate_publication_hash=publication_digest,
    )
    request = PublicationActivationGroupRequest(
        activation_id="m1-activation-1",
        candidates=(candidate,),
    )
    return request, write


def _build_writer(
    events: list[str],
    commits: tuple[SystemAuditEventOutboxCommit, ...],
    *,
    failure: Exception | None = None,
) -> tuple[M1ReferencePricePublicationAuditWriter, _QualityRecorder]:
    recorder = _QualityRecorder(events, failure=failure)
    writer = M1ReferencePricePublicationAuditWriter(
        delegate=cast(_Delegate, _Delegate(events, commits)),
        quality_recorder=cast(RecordPublicationQualityUseCase, recorder),
    )
    return writer, recorder


def test_exact_m1_group_delegates_manifest_then_records_exact_quality_source() -> None:
    events: list[str] = []
    commit = cast(SystemAuditEventOutboxCommit, _AuditCommit("manifest"))
    request, write = _write_inputs()
    writer, recorder = _build_writer(events, (commit,))

    result = writer.append_manifest_group_required(request=request, writes=(write,))

    assert result == (commit,)
    assert events == ["manifest-group", "quality"]
    assert recorder.calls == [
        {
            "publication_id": write.publication.publication_id,
            "run_id": write.manifest.raw_audits[0].run_id,
            "ingested_run_id": write.manifest.raw_audits[0].ingested_run_id,
            "provider_key": write.publication.selected_source,
        }
    ]


@pytest.mark.parametrize(
    ("dataset_key", "publication_key"),
    [
        ("equity.price.bar", "current"),
        ("equity.quote.snapshot", "execution"),
        ("equity.valuation.fact", M1_REBALANCE_REFERENCE_PUBLICATION_KEY),
    ],
)
def test_non_m1_scope_fails_before_manifest_or_quality_write(
    dataset_key: str,
    publication_key: str,
) -> None:
    events: list[str] = []
    commit = cast(SystemAuditEventOutboxCommit, _AuditCommit("manifest"))
    request, write = _write_inputs()
    write = replace(
        write,
        publication=replace(
            write.publication,
            dataset_key=dataset_key,
            publication_key=publication_key,
        ),
    )
    writer, recorder = _build_writer(events, (commit,))

    with pytest.raises(PublicationActivationError, match="M1 reference-price"):
        writer.append_manifest_group_required(request=request, writes=(write,))

    assert events == []
    assert recorder.calls == []


def test_multiple_raw_audits_fail_closed_before_any_audit_write() -> None:
    events: list[str] = []
    commit = cast(SystemAuditEventOutboxCommit, _AuditCommit("manifest"))
    request, write = _write_inputs(raw_audit_count=2)
    writer, recorder = _build_writer(events, (commit,))

    with pytest.raises(PublicationActivationError, match="exactly one RawAudit"):
        writer.append_manifest_group_required(request=request, writes=(write,))

    assert events == []
    assert recorder.calls == []


def test_multiple_manifest_writes_fail_closed_before_any_audit_write() -> None:
    events: list[str] = []
    commit = cast(SystemAuditEventOutboxCommit, _AuditCommit("manifest"))
    request, write = _write_inputs()
    writer, recorder = _build_writer(events, (commit,))

    with pytest.raises(PublicationActivationError, match="one exact candidate and manifest"):
        writer.append_manifest_group_required(request=request, writes=(write, write))

    assert events == []
    assert recorder.calls == []


def test_multi_member_publication_fails_closed_for_single_security_lane() -> None:
    events: list[str] = []
    commit = cast(SystemAuditEventOutboxCommit, _AuditCommit("manifest"))
    request, write = _write_inputs(member_count=2)
    writer, recorder = _build_writer(events, (commit,))

    with pytest.raises(PublicationActivationError, match="publication evidence is invalid"):
        writer.append_manifest_group_required(request=request, writes=(write,))

    assert events == []
    assert recorder.calls == []


def test_same_candidate_quality_replay_keeps_degraded_and_recovery_events_unchanged() -> None:
    """A later activation replay must not rewrite an event with a new audit clock."""

    delegate_events: list[str] = []
    commit = cast(SystemAuditEventOutboxCommit, _AuditCommit("manifest"))
    audit_event_writer = _MemoryQualityEventWriter()
    scope_provider = _QualityScopeProvider()
    append_quality = AppendDataQualityAuditObservationUseCase(
        audit_event_writer,
        scope_provider,
    )
    reader = _QualityPublicationReader()
    clock = _MutableClock(_NOW + timedelta(seconds=1))
    quality_recorder = RecordPublicationQualityUseCase(
        publication_reader=reader,
        quality_writer=append_quality,
        clock=clock,
    )
    wrapper = M1ReferencePricePublicationAuditWriter(
        delegate=cast(_Delegate, _Delegate(delegate_events, (commit,))),
        quality_recorder=quality_recorder,
    )

    degraded_request, degraded_write = _write_inputs(quality_status="estimated")
    degraded_published = replace(
        degraded_write.publication,
        state=PublicationState.PUBLISHED,
        published_at=_NOW,
    )
    reader.publications[degraded_published.publication_id] = degraded_published
    reader.members[degraded_published.publication_id] = degraded_write.members
    wrapper.append_manifest_group_required(
        request=degraded_request,
        writes=(degraded_write,),
    )
    assert len(audit_event_writer.events) == 1
    degraded_event = audit_event_writer.events[0]
    assert degraded_event.outcome is AuditOutcome.DETECTED
    assert degraded_event.recorded_at == clock.current

    clock.current += timedelta(seconds=1)
    degraded_replay = replace(degraded_write, publication=degraded_published)
    wrapper.append_manifest_group_required(
        request=degraded_request,
        writes=(degraded_replay,),
    )
    assert audit_event_writer.events == [degraded_event]
    assert scope_provider.calls[-1] == clock.current

    recovery_request, recovery_write = _write_inputs(quality_status="verified")
    recovery_published = replace(
        recovery_write.publication,
        state=PublicationState.PUBLISHED,
        published_at=_NOW + timedelta(seconds=2),
    )
    reader.publications[recovery_published.publication_id] = recovery_published
    reader.members[recovery_published.publication_id] = recovery_write.members
    clock.current += timedelta(seconds=1)
    wrapper.append_manifest_group_required(
        request=recovery_request,
        writes=(recovery_write,),
    )
    assert len(audit_event_writer.events) == 2
    recovery_event = audit_event_writer.events[1]
    assert recovery_event.outcome is AuditOutcome.RECOVERED
    assert recovery_event.detail["previous_quality_state"] == "degraded"

    clock.current += timedelta(seconds=1)
    recovery_replay = replace(recovery_write, publication=recovery_published)
    wrapper.append_manifest_group_required(
        request=recovery_request,
        writes=(recovery_replay,),
    )
    assert audit_event_writer.events == [degraded_event, recovery_event]
    assert scope_provider.calls[-1] == clock.current


def test_quality_replay_rechecks_current_scope_before_reusing_winner() -> None:
    """A revoked scope rejects replay before any event or outbox append."""

    audit_event_writer = _MemoryQualityEventWriter()
    scope_provider = _QualityScopeProvider()
    use_case = AppendDataQualityAuditObservationUseCase(audit_event_writer, scope_provider)
    observation = DataQualityAuditObservation(
        dataset_key="equity.price.bar",
        publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
        publication_id="publication-revoke-test",
        publication_version="price-bar-v1",
        publication_hash="b" * 64,
        provider_key="provider-source-key",
        run_id=str(uuid4()),
        ingested_run_id=str(uuid4()),
        quality_state="degraded",
        member_count=1,
        quality_status_counts=(DataQualityStatusCount(status="degraded", count=1),),
        occurred_at=_NOW,
        recorded_at=_NOW,
    )

    first = use_case.execute(observation)
    assert first is not None
    persisted = tuple(audit_event_writer.events)
    scope_provider.fail = True

    with pytest.raises(PermissionError, match="no longer authorized"):
        use_case.execute(replace(observation, recorded_at=_NOW + timedelta(seconds=5)))

    assert audit_event_writer.events == list(persisted)
    scope_provider.fail = False
    scope_provider.current_scope = AuditScopeRef(tenant_id="tenant-2", owner_id="owner-2")
    with pytest.raises(SystemAuditEventOutboxConflict, match="another observation"):
        use_case.execute(replace(observation, recorded_at=_NOW + timedelta(seconds=10)))

    assert audit_event_writer.events == list(persisted)
    assert scope_provider.calls == [
        _NOW,
        _NOW + timedelta(seconds=5),
        _NOW + timedelta(seconds=10),
    ]


def test_quality_replay_rejects_changed_content_under_same_event_identity() -> None:
    """A winner is reused only when all event content still matches exactly."""

    audit_event_writer = _MemoryQualityEventWriter()
    scope_provider = _QualityScopeProvider()
    use_case = AppendDataQualityAuditObservationUseCase(audit_event_writer, scope_provider)
    observation = DataQualityAuditObservation(
        dataset_key="equity.price.bar",
        publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
        publication_id="publication-content-test",
        publication_version="price-bar-v1",
        publication_hash="c" * 64,
        provider_key="provider-source-key",
        run_id=str(uuid4()),
        ingested_run_id=str(uuid4()),
        quality_state="degraded",
        member_count=1,
        quality_status_counts=(DataQualityStatusCount(status="degraded", count=1),),
        occurred_at=_NOW,
        recorded_at=_NOW,
    )
    first = use_case.execute(observation)
    assert first is not None
    persisted = tuple(audit_event_writer.events)

    with pytest.raises(SystemAuditEventOutboxConflict, match="another observation"):
        use_case.execute(
            replace(
                observation,
                provider_key="different-source-key",
                recorded_at=_NOW + timedelta(seconds=5),
            )
        )

    assert audit_event_writer.events == list(persisted)


def test_quality_failure_propagates_after_manifest_delegate() -> None:
    events: list[str] = []
    commit = cast(SystemAuditEventOutboxCommit, _AuditCommit("manifest"))
    request, write = _write_inputs()
    expected = RuntimeError("quality audit unavailable")
    writer, recorder = _build_writer(events, (commit,), failure=expected)

    with pytest.raises(RuntimeError, match="quality audit unavailable") as error:
        writer.append_manifest_group_required(request=request, writes=(write,))

    assert error.value is expected
    assert events == ["manifest-group", "quality"]
    assert len(recorder.calls) == 1


def test_quality_writer_and_manifest_delegate_must_share_database_alias() -> None:
    class _OtherAliasRecorder(_QualityRecorder):
        database_alias = "analytics"

    with pytest.raises(PublicationActivationError, match="database alias"):
        M1ReferencePricePublicationAuditWriter(
            delegate=cast(_Delegate, object()),
            quality_recorder=cast(RecordPublicationQualityUseCase, _OtherAliasRecorder([])),
        )


def test_single_manifest_method_fails_closed_without_quality_group() -> None:
    events: list[str] = []
    commit = cast(SystemAuditEventOutboxCommit, _AuditCommit("manifest"))
    request, write = _write_inputs()
    writer, recorder = _build_writer(events, (commit,))

    with pytest.raises(PublicationActivationError, match="group activation"):
        writer.append_manifest_required(
            request=request,
            publication=write.publication,
            members=write.members,
            manifest=write.manifest,
            observation=write.observation,
        )

    assert events == []
    assert recorder.calls == []
