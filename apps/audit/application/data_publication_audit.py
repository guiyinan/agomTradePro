"""Typed canonical-publication events for the unified audit ledger."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final, Protocol, cast

from apps.audit.application.system_audit_event_outbox import (
    SystemAuditEventOutboxCommit,
    SystemAuditEventOutboxWriter,
)
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
    JSONValue,
    SystemAuditEvent,
)

_EVENT_VERSION: Final[str] = "1"
_HASH_LENGTH: Final[int] = 64
_REASON_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


def _require_identifier(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError(f"{field_name} must be a bounded non-empty string")


def _require_digest(value: str, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != _HASH_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase sha256 digest")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_count(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class DataPublicationAuditObservation:
    """Immutable publication outcome with exact run and evidence references."""

    dataset_key: str
    publication_key: str
    publication_id: str
    publication_version: str
    publication_hash: str
    provider_key: str
    run_id: str
    ingested_run_id: str
    member_count: int
    coverage_requested_count: int
    coverage_eligible_count: int
    coverage_selected_count: int
    outcome: AuditOutcome
    raw_audit_id: str
    raw_audit_version: str
    raw_audit_content_hash: str
    occurred_at: datetime
    recorded_at: datetime
    blocked_reason: str | None = None
    error_class: str | None = None
    scope: AuditScopeRef | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "dataset_key",
            "publication_key",
            "publication_id",
            "publication_version",
            "provider_key",
            "run_id",
            "ingested_run_id",
            "raw_audit_id",
            "raw_audit_version",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        _require_digest(self.publication_hash, "publication_hash")
        _require_digest(self.raw_audit_content_hash, "raw_audit_content_hash")
        for field_name in (
            "member_count",
            "coverage_requested_count",
            "coverage_eligible_count",
            "coverage_selected_count",
        ):
            _require_count(getattr(self, field_name), field_name)
        if self.coverage_selected_count > self.coverage_eligible_count:
            raise ValueError("selected coverage cannot exceed eligible coverage")
        if self.coverage_eligible_count > self.coverage_requested_count:
            raise ValueError("eligible coverage cannot exceed requested coverage")
        if self.member_count != self.coverage_selected_count:
            raise ValueError("member_count must equal selected coverage")
        if self.outcome not in {AuditOutcome.PUBLISHED, AuditOutcome.BLOCKED}:
            raise ValueError("publication outcome must be published or blocked")
        if self.outcome is AuditOutcome.PUBLISHED:
            if self.member_count == 0:
                raise ValueError("published observation requires at least one member")
            if self.blocked_reason is not None:
                raise ValueError("published observation cannot carry a blocked reason")
            if self.error_class is not None:
                raise ValueError("published observation cannot carry an error class")
        else:
            if (
                not isinstance(self.blocked_reason, str)
                or len(self.blocked_reason) > 128
                or _REASON_PATTERN.fullmatch(self.blocked_reason) is None
            ):
                raise ValueError("blocked observation requires a stable reason code")
            if self.error_class is not None:
                _require_identifier(self.error_class, "error_class")
        _require_aware(self.occurred_at, "occurred_at")
        _require_aware(self.recorded_at, "recorded_at")
        if self.occurred_at > self.recorded_at:
            raise ValueError("occurred_at cannot be after recorded_at")
        if self.scope is not None and not isinstance(self.scope, AuditScopeRef):
            raise TypeError("scope must be an AuditScopeRef")


@dataclass(frozen=True, slots=True)
class DataPublicationRawAuditManifestReference:
    """One immutable RawAudit child reference carried by a manifest event."""

    raw_audit_id: str
    version: str
    content_hash: str

    def __post_init__(self) -> None:
        """Reject incomplete evidence before it is serialized into an audit event."""

        if (
            not self.raw_audit_id.isascii()
            or not self.raw_audit_id.isdecimal()
            or int(self.raw_audit_id) <= 0
            or str(int(self.raw_audit_id)) != self.raw_audit_id
        ):
            raise ValueError("raw_audit_id must be a canonical positive decimal identity")
        _require_identifier(self.version, "raw_audit_version")
        _require_digest(self.content_hash, "raw_audit_content_hash")


@dataclass(frozen=True, slots=True)
class DataPublicationManifestAuditObservation:
    """Published candidate evidence bound to its complete RawAudit manifest."""

    dataset_key: str
    publication_key: str
    publication_id: str
    publication_version: str
    publication_hash: str
    provider_key: str
    run_id: str
    member_count: int
    coverage_requested_count: int
    coverage_eligible_count: int
    coverage_selected_count: int
    manifest_id: str
    manifest_version: str
    manifest_hash: str
    raw_audit_count: int
    raw_audit_hash: str
    raw_audits: tuple[DataPublicationRawAuditManifestReference, ...]
    occurred_at: datetime
    recorded_at: datetime
    scope: AuditScopeRef

    def __post_init__(self) -> None:
        """Require exact, stably ordered manifest-bound publication evidence."""

        for field_name in (
            "dataset_key",
            "publication_key",
            "publication_id",
            "publication_version",
            "provider_key",
            "run_id",
            "manifest_id",
            "manifest_version",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        for field_name in ("publication_hash", "manifest_hash", "raw_audit_hash"):
            _require_digest(getattr(self, field_name), field_name)
        for field_name in (
            "member_count",
            "coverage_requested_count",
            "coverage_eligible_count",
            "coverage_selected_count",
            "raw_audit_count",
        ):
            _require_count(getattr(self, field_name), field_name)
        if (
            self.member_count == 0
            or self.member_count != self.coverage_selected_count
            or self.coverage_selected_count > self.coverage_eligible_count
            or self.coverage_eligible_count > self.coverage_requested_count
        ):
            raise ValueError("manifest publication coverage is inconsistent")
        if not isinstance(self.raw_audits, tuple) or not self.raw_audits:
            raise ValueError("manifest publication audit requires RawAudit references")
        if any(
            type(item) is not DataPublicationRawAuditManifestReference for item in self.raw_audits
        ):
            raise TypeError("raw_audits must contain manifest RawAudit references")
        identifiers = tuple(int(item.raw_audit_id) for item in self.raw_audits)
        if identifiers != tuple(sorted(set(identifiers))):
            raise ValueError("manifest RawAudit references must be unique and stably ordered")
        if self.raw_audit_count != len(self.raw_audits):
            raise ValueError("manifest RawAudit reference count differs")
        _require_aware(self.occurred_at, "occurred_at")
        _require_aware(self.recorded_at, "recorded_at")
        if self.occurred_at > self.recorded_at:
            raise ValueError("occurred_at cannot be after recorded_at")
        if type(self.scope) is not AuditScopeRef:
            raise TypeError("manifest publication audit requires an exact AuditScopeRef")


def _stable_event_id(observation: DataPublicationAuditObservation) -> str:
    material = "|".join(
        (
            observation.run_id,
            observation.ingested_run_id,
            observation.dataset_key,
            observation.publication_id,
            observation.outcome.value,
        )
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:48]
    return f"data-publication-{digest}"


def _stable_manifest_event_id(observation: DataPublicationManifestAuditObservation) -> str:
    """Return the deterministic event identity for one exact manifest activation."""

    material = "|".join(
        (
            observation.run_id,
            observation.dataset_key,
            observation.publication_id,
            observation.manifest_id,
            observation.manifest_hash,
        )
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:48]
    return f"data-publication-manifest-{digest}"


class DataPublicationAuditScopeProvider(Protocol):
    """Resolve the exact current scope for one publication audit write."""

    def get_scope(self, *, as_of: datetime) -> AuditScopeRef:
        """Return one authenticated, server-issued scope at ``as_of``."""


class DataPublicationAuditEventOutboxWriter(SystemAuditEventOutboxWriter, Protocol):
    """Canonical event/outbox writer with exact replay reads."""

    @property
    def database_alias(self) -> str:
        """Return the database alias shared by event and outbox writes."""

    def get_winner(
        self,
        *,
        event_id: str,
        event_version: str,
        as_of: datetime,
    ) -> SystemAuditEvent | None:
        """Return an existing exact event identity at the PIT cutoff."""

    def get_current_head(
        self,
        *,
        stream_id: str,
        as_of: datetime,
        scope: AuditScopeRef,
    ) -> SystemAuditEvent | None:
        """Return the scoped stream head used for predecessor CAS."""


class _TargetedDataPublicationAuditWriter(Protocol):
    """Bounded selectors used only by a caller-owned activation transaction."""

    def lock_stream(self, stream_id: str) -> None:
        """Serialize one audit stream."""

    def get_winner_targeted(
        self,
        *,
        event_id: str,
        event_version: str,
        as_of: datetime,
        lock: bool,
    ) -> SystemAuditEvent | None:
        """Read one exact event identity."""

    def get_current_head_targeted(
        self,
        *,
        stream_id: str,
        as_of: datetime,
        scope: AuditScopeRef,
        lock: bool,
    ) -> SystemAuditEvent | None:
        """Read one exact stream head."""

    def append_and_enqueue_targeted(
        self,
        event: SystemAuditEvent,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
        scope: AuditScopeRef,
        identity_winner: SystemAuditEvent | None,
        stream_head: SystemAuditEvent | None,
    ) -> SystemAuditEventOutboxCommit:
        """Append event and outbox rows with bounded selectors."""

    def lock_streams(self, stream_ids: tuple[str, ...]) -> None:
        """Serialize a bounded stream group in stable order."""

    def get_activation_group_state_targeted(
        self,
        *,
        identities: tuple[tuple[str, str], ...],
        stream_ids: tuple[str, ...],
        as_of: datetime,
        scope: AuditScopeRef,
    ) -> tuple[
        dict[tuple[str, str], SystemAuditEvent],
        dict[str, SystemAuditEvent],
    ]:
        """Return exact event winners and stream heads with one bounded lock read."""

    def append_and_enqueue_group_targeted(
        self,
        events: tuple[SystemAuditEvent, ...],
        *,
        identity_winners: dict[tuple[str, str], SystemAuditEvent],
        stream_heads: dict[str, SystemAuditEvent],
    ) -> tuple[SystemAuditEventOutboxCommit, ...]:
        """Append a prevalidated event group and its outbox rows."""


def build_data_publication_audit_event(
    observation: DataPublicationAuditObservation,
    *,
    sequence_no: int,
    predecessor_hash: str | None,
) -> SystemAuditEvent:
    """Build one canonical published or blocked publication event."""

    if not isinstance(sequence_no, int) or isinstance(sequence_no, bool) or sequence_no < 1:
        raise ValueError("sequence_no must be a positive integer")
    if predecessor_hash is not None:
        _require_digest(predecessor_hash, "predecessor_hash")
    published = observation.outcome is AuditOutcome.PUBLISHED
    detail: dict[str, JSONValue] = {
        "publication_key": observation.publication_key,
        "publication_hash": observation.publication_hash,
        "member_count": observation.member_count,
        "coverage_requested_count": observation.coverage_requested_count,
        "coverage_eligible_count": observation.coverage_eligible_count,
        "coverage_selected_count": observation.coverage_selected_count,
    }
    reason_codes: tuple[str, ...] = ("publication_published",)
    if not published:
        blocked_reason = observation.blocked_reason
        if blocked_reason is None:
            raise ValueError("blocked publication observation is missing its reason")
        detail["blocked_reason"] = blocked_reason
        if observation.error_class is not None:
            detail["error_class"] = observation.error_class
        reason_codes = ("publication_blocked", blocked_reason)
    evidence_refs = [
        AuditEvidenceRef(
            "data_center",
            "raw_audit",
            observation.raw_audit_id,
            observation.raw_audit_version,
            observation.raw_audit_content_hash,
        )
    ]
    if published:
        evidence_refs.append(
            AuditEvidenceRef(
                "data_center",
                "canonical_publication",
                observation.publication_id,
                observation.publication_version,
                observation.publication_hash,
            )
        )
    return SystemAuditEvent.create(
        event_id=_stable_event_id(observation),
        event_version=_EVENT_VERSION,
        schema_version="system-audit-event.v1",
        category=AuditCategory.DATA_RELIABILITY,
        event_type=("data.publication.published" if published else "data.publication.blocked"),
        owner="data_center",
        write_policy=AuditWritePolicy.REQUIRED,
        outcome=observation.outcome,
        severity=AuditSeverity.INFO if published else AuditSeverity.CRITICAL,
        reason_codes=reason_codes,
        occurred_at=observation.occurred_at,
        recorded_at=observation.recorded_at,
        observed_at=None,
        actor=AuditActorRef("service", "data-center", "data-center"),
        source_app="data_center",
        source_component="publication",
        source_surface="application",
        correlations=AuditCorrelations(
            run_id=observation.run_id,
            ingested_run_id=observation.ingested_run_id,
            dataset_key=observation.dataset_key,
            provider_key=observation.provider_key,
        ),
        resource=AuditResourceRef(
            "canonical_publication",
            observation.publication_id,
            observation.publication_version,
        ),
        dataset_key=observation.dataset_key,
        provider_key=observation.provider_key,
        capability="publication",
        publication_id=observation.publication_id,
        evidence_refs=tuple(evidence_refs),
        detail_schema=(
            "data.publication.published.v1" if published else "data.publication.blocked.v1"
        ),
        detail=detail,
        stream_id=f"data.publication:{observation.dataset_key}",
        sequence_no=sequence_no,
        predecessor_hash=predecessor_hash,
        idempotency_key=(
            f"data-publication:{observation.run_id}:{observation.ingested_run_id}:"
            f"{observation.publication_id}:{observation.outcome.value}"
        ),
        scope=observation.scope,
    )


def build_data_publication_manifest_audit_event(
    observation: DataPublicationManifestAuditObservation,
    *,
    sequence_no: int,
    predecessor_hash: str | None,
) -> SystemAuditEvent:
    """Build a publication event whose evidence is the complete manifest graph."""

    if type(observation) is not DataPublicationManifestAuditObservation:
        raise TypeError("observation must be manifest-bound publication evidence")
    if not isinstance(sequence_no, int) or isinstance(sequence_no, bool) or sequence_no < 1:
        raise ValueError("sequence_no must be a positive integer")
    if predecessor_hash is not None:
        _require_digest(predecessor_hash, "predecessor_hash")
    detail: dict[str, JSONValue] = {
        "publication_key": observation.publication_key,
        "publication_hash": observation.publication_hash,
        "member_count": observation.member_count,
        "coverage_requested_count": observation.coverage_requested_count,
        "coverage_eligible_count": observation.coverage_eligible_count,
        "coverage_selected_count": observation.coverage_selected_count,
        "raw_audit_manifest": {
            "manifest_id": observation.manifest_id,
            "manifest_version": observation.manifest_version,
            "manifest_hash": observation.manifest_hash,
            "raw_audit_count": observation.raw_audit_count,
            "raw_audit_hash": observation.raw_audit_hash,
        },
    }
    evidence_refs = [
        AuditEvidenceRef(
            "data_center",
            "candidate_raw_audit_manifest",
            observation.manifest_id,
            observation.manifest_version,
            observation.manifest_hash,
        ),
        *(
            AuditEvidenceRef(
                "data_center",
                "raw_audit",
                item.raw_audit_id,
                item.version,
                item.content_hash,
            )
            for item in observation.raw_audits
        ),
        AuditEvidenceRef(
            "data_center",
            "canonical_publication",
            observation.publication_id,
            observation.publication_version,
            observation.publication_hash,
        ),
    ]
    return SystemAuditEvent.create(
        event_id=_stable_manifest_event_id(observation),
        event_version=_EVENT_VERSION,
        schema_version="system-audit-event.v1",
        category=AuditCategory.DATA_RELIABILITY,
        event_type="data.publication.published",
        owner="data_center",
        write_policy=AuditWritePolicy.REQUIRED,
        outcome=AuditOutcome.PUBLISHED,
        severity=AuditSeverity.INFO,
        reason_codes=("publication_published",),
        occurred_at=observation.occurred_at,
        recorded_at=observation.recorded_at,
        observed_at=None,
        actor=AuditActorRef("service", "data-center", "data-center"),
        source_app="data_center",
        source_component="publication",
        source_surface="application",
        correlations=AuditCorrelations(
            run_id=observation.run_id,
            dataset_key=observation.dataset_key,
            provider_key=observation.provider_key,
            publication_id=observation.publication_id,
        ),
        resource=AuditResourceRef(
            "canonical_publication",
            observation.publication_id,
            observation.publication_version,
        ),
        dataset_key=observation.dataset_key,
        provider_key=observation.provider_key,
        capability="publication",
        publication_id=observation.publication_id,
        evidence_refs=tuple(evidence_refs),
        detail_schema="data.publication.published.v1",
        detail=detail,
        stream_id=f"data.publication:{observation.dataset_key}",
        sequence_no=sequence_no,
        predecessor_hash=predecessor_hash,
        idempotency_key=(
            f"data-publication-manifest:{observation.run_id}:{observation.publication_id}:"
            f"{observation.manifest_id}:{observation.manifest_hash}"
        ),
        scope=observation.scope,
    )


class AppendDataPublicationAuditObservationUseCase:
    """Append one scoped publication observation and its outbox record."""

    __slots__ = ("_scope_provider", "_writer")

    def __init__(
        self,
        writer: DataPublicationAuditEventOutboxWriter,
        scope_provider: DataPublicationAuditScopeProvider,
    ) -> None:
        self._writer = writer
        self._scope_provider = scope_provider

    @property
    def database_alias(self) -> str:
        """Return the alias used by the canonical writer."""

        return self._writer.database_alias

    def execute(
        self,
        observation: DataPublicationAuditObservation,
    ) -> SystemAuditEventOutboxCommit:
        """Bind current authority, preserve first-winner replay, and append."""

        if not isinstance(observation, DataPublicationAuditObservation):
            raise TypeError("observation must be a DataPublicationAuditObservation")
        scope = self._scope_provider.get_scope(as_of=observation.recorded_at)
        if not isinstance(scope, AuditScopeRef):
            raise TypeError("scope provider returned an invalid scope")
        if observation.scope is not None and observation.scope != scope:
            raise ValueError("observation scope differs from current authority")
        scoped_observation = replace(observation, scope=scope)
        return self._append_scoped(scoped_observation, self._writer.atomic, targeted=False)

    def execute_in_caller_transaction(
        self,
        observation: DataPublicationAuditObservation,
    ) -> SystemAuditEventOutboxCommit:
        """Append using a writer capability bound to the caller's outer transaction."""

        if not isinstance(observation, DataPublicationAuditObservation):
            raise TypeError("observation must be a DataPublicationAuditObservation")
        if observation.scope is None:
            raise ValueError("caller-owned publication audit requires an explicit scope")
        caller_owned_atomic = getattr(self._writer, "caller_owned_atomic", None)
        if not callable(caller_owned_atomic):
            raise ValueError("writer does not expose caller-owned publication audit UOW")
        return self._append_scoped(observation, caller_owned_atomic, targeted=True)

    def execute_manifest_in_caller_transaction(
        self,
        observation: DataPublicationManifestAuditObservation,
    ) -> SystemAuditEventOutboxCommit:
        """Append one complete-manifest publication event inside the caller's UOW."""

        if type(observation) is not DataPublicationManifestAuditObservation:
            raise TypeError("observation must be manifest-bound publication evidence")
        caller_owned_atomic = getattr(self._writer, "caller_owned_atomic", None)
        if not callable(caller_owned_atomic):
            raise ValueError("writer does not expose caller-owned publication audit UOW")
        candidate_writer = self._writer
        if not all(
            callable(getattr(candidate_writer, name, None))
            for name in (
                "append_and_enqueue_targeted",
                "lock_stream",
                "get_winner_targeted",
                "get_current_head_targeted",
            )
        ):
            raise ValueError("writer does not expose bounded publication audit selectors")
        targeted_writer = cast(_TargetedDataPublicationAuditWriter, candidate_writer)
        event_id = _stable_manifest_event_id(observation)
        stream_id = f"data.publication:{observation.dataset_key}"
        with caller_owned_atomic():
            targeted_writer.lock_stream(stream_id)
            winner = targeted_writer.get_winner_targeted(
                event_id=event_id,
                event_version=_EVENT_VERSION,
                as_of=observation.recorded_at,
                lock=True,
            )
            head: SystemAuditEvent | None = None
            if winner is not None:
                sequence_no = winner.sequence_no
                predecessor_hash = winner.predecessor_hash
            else:
                head = targeted_writer.get_current_head_targeted(
                    stream_id=stream_id,
                    as_of=observation.recorded_at,
                    scope=observation.scope,
                    lock=True,
                )
                sequence_no = head.sequence_no + 1 if head is not None else 1
                predecessor_hash = head.content_hash if head is not None else None
            event = build_data_publication_manifest_audit_event(
                observation,
                sequence_no=sequence_no,
                predecessor_hash=predecessor_hash,
            )
            commit = targeted_writer.append_and_enqueue_targeted(
                event,
                expected_predecessor_hash=event.predecessor_hash,
                recorded_at=event.recorded_at,
                scope=observation.scope,
                identity_winner=winner,
                stream_head=head,
            )
        if commit.event != event:
            raise ValueError("data publication audit writer substituted the manifest event")
        return commit

    def execute_manifest_group_in_caller_transaction(
        self,
        observations: tuple[DataPublicationManifestAuditObservation, ...],
    ) -> tuple[SystemAuditEventOutboxCommit, ...]:
        """Append a fixed manifest group with batched lock and identity reads."""

        if (
            not observations
            or any(
                type(item) is not DataPublicationManifestAuditObservation for item in observations
            )
            or len({item.dataset_key for item in observations}) != len(observations)
        ):
            raise ValueError("manifest publication audit group is invalid")
        recorded_at = observations[0].recorded_at
        scope = observations[0].scope
        if any(item.recorded_at != recorded_at or item.scope != scope for item in observations):
            raise ValueError("manifest publication audit group clock or scope differs")
        caller_owned_atomic = getattr(self._writer, "caller_owned_atomic", None)
        if not callable(caller_owned_atomic):
            raise ValueError("writer does not expose caller-owned publication audit UOW")
        candidate_writer = self._writer
        required = (
            "lock_streams",
            "get_activation_group_state_targeted",
            "append_and_enqueue_group_targeted",
        )
        if not all(callable(getattr(candidate_writer, name, None)) for name in required):
            raise ValueError("writer does not expose grouped publication audit selectors")
        targeted_writer = cast(_TargetedDataPublicationAuditWriter, candidate_writer)
        identities = tuple(
            (_stable_manifest_event_id(item), _EVENT_VERSION) for item in observations
        )
        stream_ids = tuple(f"data.publication:{item.dataset_key}" for item in observations)
        with caller_owned_atomic():
            targeted_writer.lock_streams(stream_ids)
            winners, heads = targeted_writer.get_activation_group_state_targeted(
                identities=identities,
                stream_ids=stream_ids,
                as_of=recorded_at,
                scope=scope,
            )
            events: list[SystemAuditEvent] = []
            for observation, identity, stream_id in zip(
                observations,
                identities,
                stream_ids,
                strict=True,
            ):
                winner = winners.get(identity)
                head = None if winner is not None else heads.get(stream_id)
                events.append(
                    build_data_publication_manifest_audit_event(
                        observation,
                        sequence_no=(
                            winner.sequence_no
                            if winner is not None
                            else (head.sequence_no + 1 if head is not None else 1)
                        ),
                        predecessor_hash=(
                            winner.predecessor_hash
                            if winner is not None
                            else (head.content_hash if head is not None else None)
                        ),
                    )
                )
            commits = targeted_writer.append_and_enqueue_group_targeted(
                tuple(events),
                identity_winners=winners,
                stream_heads=heads,
            )
        if len(commits) != len(events) or any(
            commit.event != event for commit, event in zip(commits, events, strict=True)
        ):
            raise ValueError("data publication audit writer substituted the manifest group")
        return commits

    def _append_scoped(
        self,
        observation: DataPublicationAuditObservation,
        atomic_factory: object,
        *,
        targeted: bool,
    ) -> SystemAuditEventOutboxCommit:
        """Append one already-scoped observation through one selected UOW."""

        if not callable(atomic_factory):
            raise TypeError("audit writer UOW factory is unavailable")
        scope = observation.scope
        if scope is None:
            raise ValueError("publication audit append requires an explicit scope")
        event_id = _stable_event_id(observation)
        stream_id = f"data.publication:{observation.dataset_key}"
        targeted_writer: _TargetedDataPublicationAuditWriter | None = None
        if targeted:
            candidate_writer = self._writer
            if all(
                callable(getattr(candidate_writer, name, None))
                for name in (
                    "append_and_enqueue_targeted",
                    "lock_stream",
                    "get_winner_targeted",
                    "get_current_head_targeted",
                )
            ):
                targeted_writer = cast(_TargetedDataPublicationAuditWriter, candidate_writer)
            if targeted_writer is None:
                raise ValueError("writer does not expose bounded publication audit selectors")
        with atomic_factory():
            if targeted_writer is not None:
                targeted_writer.lock_stream(stream_id)
                winner = targeted_writer.get_winner_targeted(
                    event_id=event_id,
                    event_version=_EVENT_VERSION,
                    as_of=observation.recorded_at,
                    lock=True,
                )
                head: SystemAuditEvent | None = None
                if winner is not None:
                    sequence_no = winner.sequence_no
                    predecessor_hash = winner.predecessor_hash
                else:
                    head = targeted_writer.get_current_head_targeted(
                        stream_id=stream_id,
                        as_of=observation.recorded_at,
                        scope=scope,
                        lock=True,
                    )
                    sequence_no = head.sequence_no + 1 if head is not None else 1
                    predecessor_hash = head.content_hash if head is not None else None
                event = build_data_publication_audit_event(
                    observation,
                    sequence_no=sequence_no,
                    predecessor_hash=predecessor_hash,
                )
                commit = targeted_writer.append_and_enqueue_targeted(
                    event,
                    expected_predecessor_hash=event.predecessor_hash,
                    recorded_at=event.recorded_at,
                    scope=scope,
                    identity_winner=winner,
                    stream_head=head,
                )
                if commit.event != event:
                    raise ValueError("data publication audit writer substituted the event")
                return commit
            winner = self._writer.get_winner(
                event_id=event_id,
                event_version=_EVENT_VERSION,
                as_of=observation.recorded_at,
            )
            if winner is not None:
                sequence_no = winner.sequence_no
                predecessor_hash = winner.predecessor_hash
            else:
                head = self._writer.get_current_head(
                    stream_id=stream_id,
                    as_of=observation.recorded_at,
                    scope=scope,
                )
                sequence_no = head.sequence_no + 1 if head is not None else 1
                predecessor_hash = head.content_hash if head is not None else None
            event = build_data_publication_audit_event(
                observation,
                sequence_no=sequence_no,
                predecessor_hash=predecessor_hash,
            )
            commit = self._writer.append_and_enqueue(
                event,
                expected_predecessor_hash=event.predecessor_hash,
                recorded_at=event.recorded_at,
            )
        if commit.event != event:
            raise ValueError("data publication audit writer substituted the event")
        return commit

    def write(
        self,
        observation: DataPublicationAuditObservation,
    ) -> SystemAuditEventOutboxCommit:
        """Write one observation through the canonical append use case."""

        return self.execute(observation)


__all__ = [
    "AppendDataPublicationAuditObservationUseCase",
    "DataPublicationAuditEventOutboxWriter",
    "DataPublicationAuditObservation",
    "DataPublicationManifestAuditObservation",
    "DataPublicationRawAuditManifestReference",
    "DataPublicationAuditScopeProvider",
    "build_data_publication_manifest_audit_event",
    "build_data_publication_audit_event",
]
