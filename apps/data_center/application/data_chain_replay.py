"""Fail-closed replay of one canonical Data Reliability publication chain."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.data_center.application.control_plane import (
    publication_rollback_evidence_content_hash,
)
from apps.data_center.application.publication_quality import (
    PublicationQualityProjection,
    project_publication_quality,
)
from apps.data_center.application.publication_utils import publication_hash
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    PublicationFactReference,
    PublicationMember,
    PublicationRollback,
    PublicationState,
)
from apps.data_center.domain.entities import RawAudit, raw_audit_content_hash
from core.exceptions import DataValidationError, ResourceNotFoundError
from core.integration.data_center_audit import (
    AuditEvidenceRef,
    ListCorrelatedSystemAuditEventsCommand,
    ListCorrelatedSystemAuditEventsUseCase,
    SystemAuditEvent,
    SystemAuditQueryCorruption,
    SystemAuditQueryUnavailable,
    SystemAuditReaderContext,
)

_FETCH_COMPLETED = "data.fetch.completed"
_VALIDATION_REJECTED = "data.validation.rejected"
_FAILOVER_TYPES = frozenset(
    {
        "data.failover.started",
        "data.failover.succeeded",
        "data.failover.rejected",
        "data.failover.exhausted",
    }
)
_PUBLICATION_PUBLISHED = "data.publication.published"
_PUBLICATION_BLOCKED = "data.publication.blocked"
_PUBLICATION_ROLLED_BACK = "data.publication.rolled_back"
_QUALITY_CHANGED = "data.quality.changed"
_FRESHNESS_CHANGED = "data.freshness.changed"
_DECISION_READ_TYPES = frozenset({"data.decision_read.recovered", "data.decision_read.blocked"})


def _require_token(value: object, field_name: str) -> None:
    """Require one bounded canonical selector token."""

    if (
        type(value) is not str
        or not value
        or len(value) > 256
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")


def _require_aware(value: object, field_name: str) -> None:
    """Require one timezone-aware instant."""

    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


class ReplayUnavailable(ResourceNotFoundError):
    """The selected chain or one required professional record is absent."""

    default_message = "Canonical data-chain replay evidence is unavailable"
    default_code = "DATA_CHAIN_REPLAY_UNAVAILABLE"


class ReplayCorruption(DataValidationError):
    """The selected chain contains missing, ambiguous, or tampered evidence."""

    default_message = "Canonical data-chain replay evidence is inconsistent"
    default_code = "DATA_CHAIN_REPLAY_CORRUPTION"


@dataclass(frozen=True, slots=True)
class ReplayMemberPersistenceEvidence:
    """Exact persisted fact identity and its ingestion-run binding."""

    fact_table: str
    fact_pk: str
    ingested_run_id: str

    def __post_init__(self) -> None:
        for field_name in ("fact_table", "fact_pk", "ingested_run_id"):
            _require_token(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class DataChainReplayCommand:
    """Select one publication chain by exactly one run or publication key."""

    run_id: str | None
    publication_id: str | None
    as_of: datetime
    reader: SystemAuditReaderContext

    def __post_init__(self) -> None:
        selectors = (self.run_id is not None, self.publication_id is not None)
        if selectors.count(True) != 1:
            raise ValueError("exactly one data-chain replay selector is required")
        if self.run_id is not None:
            _require_token(self.run_id, "run_id")
        if self.publication_id is not None:
            _require_token(self.publication_id, "publication_id")
        _require_aware(self.as_of, "as_of")
        if not isinstance(self.reader, SystemAuditReaderContext):
            raise TypeError("reader must be a SystemAuditReaderContext")


@dataclass(frozen=True, slots=True)
class DataChainReplayResult:
    """Verified replay projection for one exact canonical publication."""

    resolved_run_id: str
    ingested_run_id: str
    publication_id: str
    publication_version: str
    publication_hash: str
    dataset_key: str
    member_count: int
    decision_outcome: str
    ordered_stage_keys: tuple[str, ...]
    rollback_ids: tuple[str, ...] = ()
    quality_state: str = "accepted"


class ReplayRawAuditReader(Protocol):
    """Read exact professional RawAudit evidence."""

    def get_by_id(self, raw_audit_id: str) -> RawAudit | None:
        """Return the exact persisted raw audit or ``None``."""


class ReplayPublicationReader(Protocol):
    """Read exact canonical publication and member evidence."""

    def get_by_id(self, publication_id: str) -> CanonicalPublication | None:
        """Return the exact publication or ``None``."""

    def list_members(self, publication_id: str) -> list[PublicationMember]:
        """Return the exact persisted member snapshot."""

    def get_rollback_by_id(self, rollback_id: str) -> PublicationRollback | None:
        """Return one exact durable publication rollback evidence row."""


class ReplayFactEvidenceReader(Protocol):
    """Resolve whitelisted publication members to persisted fact evidence."""

    def list_member_evidence(
        self, members: tuple[PublicationMember, ...]
    ) -> tuple[ReplayMemberPersistenceEvidence, ...]:
        """Return exact persisted fact identities and ingestion-run bindings."""


def _one_event(
    events: tuple[SystemAuditEvent, ...],
    *,
    event_type: str,
) -> SystemAuditEvent:
    """Return exactly one event of a required type."""

    matches = tuple(event for event in events if event.event_type == event_type)
    if not matches:
        raise ReplayUnavailable()
    if len(matches) != 1:
        raise ReplayCorruption()
    return matches[0]


def _one_evidence(event: SystemAuditEvent, artifact_type: str) -> AuditEvidenceRef:
    """Return exactly one typed professional evidence reference."""

    matches = tuple(
        evidence for evidence in event.evidence_refs if evidence.artifact_type == artifact_type
    )
    if len(matches) != 1:
        raise ReplayCorruption()
    return matches[0]


def _evidence_by_identity(
    event: SystemAuditEvent,
    *,
    artifact_type: str,
    artifact_id: str,
) -> AuditEvidenceRef:
    """Return one exact typed evidence identity from a multi-ref event."""

    matches = tuple(
        evidence
        for evidence in event.evidence_refs
        if evidence.artifact_type == artifact_type and evidence.artifact_id == artifact_id
    )
    if len(matches) != 1:
        raise ReplayCorruption()
    return matches[0]


def _validate_event_integrity(events: tuple[SystemAuditEvent, ...]) -> None:
    """Revalidate every event hash before trusting its correlations."""

    for event in events:
        try:
            event.validate_hashes()
        except (TypeError, ValueError) as error:
            raise ReplayCorruption() from error


def _validate_failover(events: tuple[SystemAuditEvent, ...]) -> None:
    """Accept no failover or one completed start/success pair."""

    failover_types = tuple(
        event.event_type for event in events if event.event_type in _FAILOVER_TYPES
    )
    if failover_types and failover_types != (
        "data.failover.started",
        "data.failover.succeeded",
    ):
        raise ReplayCorruption()


def _member_reference(member: PublicationMember) -> PublicationFactReference:
    """Restore the canonical hash input for one publication member."""

    if member.observed_at is None:
        raise ReplayCorruption()
    try:
        return PublicationFactReference(
            natural_key=member.natural_key,
            source=member.source,
            source_record_id=member.source_record_id,
            fact_table=member.fact_table,
            fact_pk=member.fact_pk,
            observed_at=member.observed_at,
            raw_payload_hash=member.raw_payload_hash,
            quality_status=member.quality_status,
            revision_number=member.revision_number,
        )
    except (TypeError, ValueError) as error:
        raise ReplayCorruption() from error


def _validate_publication_rollbacks(
    events: tuple[SystemAuditEvent, ...],
    *,
    publication: CanonicalPublication,
    publication_reader: ReplayPublicationReader,
    resolved_run_id: str,
) -> tuple[str, ...]:
    """Reconcile every rollback event with its durable row and publications."""

    rollback_ids: list[str] = []
    for event in events:
        rollback_id = event.correlations.evidence_ref
        previous_publication_id = event.detail.get("previous_publication_id")
        if type(rollback_id) is not str or type(previous_publication_id) is not str:
            raise ReplayCorruption()
        if (
            event.outcome.value != "rolled_back"
            or event.write_policy.value != "required"
            or event.severity.value != "warning"
            or event.reason_codes != ("publication_rolled_back",)
            or event.dataset_key != publication.dataset_key
            or event.publication_id != publication.publication_id
            or event.correlations.dataset_key != publication.dataset_key
            or event.correlations.publication_id != publication.publication_id
            or event.correlations.run_id != resolved_run_id
            or event.resource is None
            or event.resource.resource_type != "canonical_publication"
            or event.resource.resource_id != publication.publication_id
            or event.resource.resource_version != publication.policy_version
            or event.stream_id != f"data.publication:{publication.dataset_key}"
            or event.observed_at != event.occurred_at
            or len(event.evidence_refs) != 3
        ):
            raise ReplayCorruption()
        target_ref = _evidence_by_identity(
            event,
            artifact_type="canonical_publication",
            artifact_id=publication.publication_id,
        )
        rollback_ref = _evidence_by_identity(
            event,
            artifact_type="publication_rollback",
            artifact_id=rollback_id,
        )
        previous_ref = _evidence_by_identity(
            event,
            artifact_type="canonical_publication",
            artifact_id=previous_publication_id,
        )
        if (
            target_ref.artifact_version != publication.policy_version
            or target_ref.content_hash != publication.publication_hash
            or rollback_ref.artifact_version != "1"
        ):
            raise ReplayCorruption()
        try:
            evidence = publication_reader.get_rollback_by_id(rollback_id)
            previous = publication_reader.get_by_id(previous_publication_id)
        except Exception as error:
            raise ReplayUnavailable() from error
        if evidence is None or previous is None:
            raise ReplayUnavailable()
        try:
            evidence_hash = publication_rollback_evidence_content_hash(evidence)
        except (TypeError, ValueError) as error:
            raise ReplayCorruption() from error
        if (
            evidence.rollback_id != rollback_id
            or evidence.target_publication_id != publication.publication_id
            or evidence.previous_publication_id != previous_publication_id
            or evidence.observed_at != event.occurred_at
            or rollback_ref.content_hash != evidence_hash
            or previous.publication_id != previous_publication_id
            or previous.dataset_key != publication.dataset_key
            or previous.publication_key != publication.publication_key
            or previous.state is not PublicationState.SUPERSEDED
            or previous.policy_version != previous_ref.artifact_version
            or previous.publication_hash != previous_ref.content_hash
            or event.detail.get("publication_key") != publication.publication_key
            or event.detail.get("publication_hash") != publication.publication_hash
            or event.detail.get("rollback_id") != rollback_id
            or event.detail.get("rollback_content_hash") != evidence_hash
            or event.detail.get("previous_publication_version") != previous.policy_version
            or event.detail.get("previous_publication_hash") != previous.publication_hash
        ):
            raise ReplayCorruption()
        rollback_ids.append(rollback_id)
    if len(set(rollback_ids)) != len(rollback_ids):
        raise ReplayCorruption()
    if rollback_ids:
        try:
            latest = publication_reader.get_rollback_by_id(rollback_ids[-1])
        except Exception as error:
            raise ReplayUnavailable() from error
        if latest is None or publication.reinstated_at != latest.observed_at:
            raise ReplayCorruption()
    return tuple(rollback_ids)


def _validate_publication_quality_event(
    event: SystemAuditEvent,
    *,
    publication: CanonicalPublication,
    publication_ref: AuditEvidenceRef,
    projection: PublicationQualityProjection,
) -> None:
    """Reconcile one quality transition with its exact persisted member snapshot."""

    quality_ref = _one_evidence(event, "canonical_publication")
    previous_state = event.detail.get("previous_quality_state")
    if previous_state is not None and previous_state not in {"accepted", "degraded"}:
        raise ReplayCorruption()
    expected_outcome = "detected" if projection.quality_state == "degraded" else "recovered"
    if projection.quality_state == "accepted" and previous_state != "degraded":
        raise ReplayCorruption()
    if projection.quality_state == "degraded" and previous_state == "degraded":
        raise ReplayCorruption()
    expected_counts = [
        {"status": item.status, "count": item.count} for item in projection.quality_status_counts
    ]
    if (
        quality_ref != publication_ref
        or event.outcome.value != expected_outcome
        or event.write_policy.value != "transactional_outbox"
        or event.severity.value != "warning"
        or event.reason_codes != ("quality_changed",)
        or event.dataset_key != publication.dataset_key
        or event.provider_key != publication.selected_source
        or event.publication_id != publication.publication_id
        or event.correlations.dataset_key != publication.dataset_key
        or event.correlations.provider_key != publication.selected_source
        or event.correlations.capability != "quality"
        or event.correlations.publication_id != publication.publication_id
        or event.correlations.evidence_ref != publication.publication_id
        or event.resource is None
        or event.resource.resource_type != "canonical_publication"
        or event.resource.resource_id != publication.publication_id
        or event.resource.resource_version != publication.policy_version
        or event.capability != "quality"
        or event.stream_id
        != f"data.quality:{publication.dataset_key}:{publication.publication_key}"
        or event.observed_at != publication.published_at
        or event.detail.get("publication_key") != publication.publication_key
        or event.detail.get("publication_hash") != publication.publication_hash
        or event.detail.get("quality_state") != projection.quality_state
        or event.detail.get("member_count") != projection.member_count
        or event.detail.get("quality_status_counts") != expected_counts
    ):
        raise ReplayCorruption()


class ReplayDataChainUseCase:
    """Reconcile audit events with exact professional persistence evidence."""

    __slots__ = (
        "_correlation_query",
        "_fact_evidence_reader",
        "_publication_reader",
        "_raw_audit_reader",
    )

    def __init__(
        self,
        *,
        correlation_query: ListCorrelatedSystemAuditEventsUseCase,
        raw_audit_reader: ReplayRawAuditReader,
        publication_reader: ReplayPublicationReader,
        fact_evidence_reader: ReplayFactEvidenceReader,
    ) -> None:
        self._correlation_query = correlation_query
        self._raw_audit_reader = raw_audit_reader
        self._publication_reader = publication_reader
        self._fact_evidence_reader = fact_evidence_reader

    def execute(self, command: DataChainReplayCommand) -> DataChainReplayResult:
        """Replay one full chain and fail closed on any silent loss or drift."""

        try:
            correlation = self._correlation_query.execute(
                ListCorrelatedSystemAuditEventsCommand(
                    run_id=command.run_id,
                    publication_id=command.publication_id,
                    as_of=command.as_of,
                    reader=command.reader,
                )
            )
        except SystemAuditQueryUnavailable as error:
            raise ReplayUnavailable() from error
        except SystemAuditQueryCorruption as error:
            raise ReplayCorruption() from error
        events = correlation.events
        _validate_event_integrity(events)
        if any(event.event_type == _VALIDATION_REJECTED for event in events):
            raise ReplayCorruption()
        if any(
            event.event_type.startswith("data.fetch.") and event.event_type != _FETCH_COMPLETED
            for event in events
        ):
            raise ReplayCorruption()
        if any(event.event_type == _PUBLICATION_BLOCKED for event in events):
            raise ReplayCorruption()
        _validate_failover(events)

        fetch_events = tuple(event for event in events if event.event_type == _FETCH_COMPLETED)
        if not fetch_events:
            raise ReplayUnavailable()
        publication_event = _one_event(events, event_type=_PUBLICATION_PUBLISHED)
        decision_events = tuple(
            event for event in events if event.event_type in _DECISION_READ_TYPES
        )
        if not decision_events:
            raise ReplayUnavailable()
        if len(decision_events) != 1:
            raise ReplayCorruption()
        decision_event = decision_events[0]
        freshness_events = tuple(
            event for event in events if event.event_type == _FRESHNESS_CHANGED
        )
        if len(freshness_events) > 1:
            raise ReplayCorruption()
        quality_events = tuple(event for event in events if event.event_type == _QUALITY_CHANGED)
        if len(quality_events) > 1:
            raise ReplayCorruption()
        rollback_events = tuple(
            event for event in events if event.event_type == _PUBLICATION_ROLLED_BACK
        )

        publication_id = publication_event.publication_id
        dataset_key = publication_event.dataset_key
        if publication_id is None or dataset_key is None:
            raise ReplayCorruption()
        if (
            correlation.requested_publication_id is not None
            and publication_id != correlation.requested_publication_id
        ):
            raise ReplayCorruption()
        relevant_events = tuple(
            event
            for event in events
            if event.event_type == _FETCH_COMPLETED
            or event.event_type in _FAILOVER_TYPES
            or event.event_type == _PUBLICATION_PUBLISHED
            or event.event_type == _QUALITY_CHANGED
            or event.event_type == _FRESHNESS_CHANGED
            or event.event_type in _DECISION_READ_TYPES
        )
        ingested_run_ids = {event.correlations.ingested_run_id for event in relevant_events}
        if None in ingested_run_ids or len(ingested_run_ids) != 1:
            raise ReplayCorruption()
        ingested_run_id = next(iter(ingested_run_ids))
        if ingested_run_id is None:
            raise ReplayCorruption()
        if any(
            event.correlations.run_id != correlation.resolved_run_id
            or event.dataset_key != dataset_key
            or event.correlations.dataset_key != dataset_key
            for event in relevant_events
        ):
            raise ReplayCorruption()

        publication_raw_ref = _one_evidence(publication_event, "raw_audit")
        publication_fetch_events = tuple(
            event
            for event in fetch_events
            if _one_evidence(event, "raw_audit") == publication_raw_ref
        )
        if len(publication_fetch_events) != 1:
            raise ReplayCorruption()
        fetch_event = publication_fetch_events[0]
        fetch_raw_ref = _one_evidence(fetch_event, "raw_audit")
        if any(
            _one_evidence(event, "raw_audit") != fetch_raw_ref
            for event in relevant_events
            if event.event_type in _FAILOVER_TYPES
        ):
            raise ReplayCorruption()
        for current_fetch_event in fetch_events:
            current_raw_ref = _one_evidence(current_fetch_event, "raw_audit")
            try:
                raw_audit = self._raw_audit_reader.get_by_id(current_raw_ref.artifact_id)
            except Exception as error:
                raise ReplayUnavailable() from error
            if raw_audit is None:
                raise ReplayUnavailable()
            if (
                raw_audit.raw_audit_id != current_raw_ref.artifact_id
                or current_raw_ref.artifact_version != "1"
                or raw_audit.content_hash != current_raw_ref.content_hash
                or raw_audit_content_hash(raw_audit) != current_raw_ref.content_hash
                or raw_audit.run_id != correlation.resolved_run_id
                or raw_audit.ingested_run_id != ingested_run_id
                or raw_audit.provider_name != current_fetch_event.provider_key
                or raw_audit.capability != current_fetch_event.capability
            ):
                raise ReplayCorruption()

        publication_ref = _one_evidence(publication_event, "canonical_publication")
        decision_ref = _one_evidence(decision_event, "canonical_publication")
        if publication_ref != decision_ref or publication_ref.artifact_id != publication_id:
            raise ReplayCorruption()
        freshness_event = freshness_events[0] if freshness_events else None
        if freshness_event is not None:
            freshness_ref = _one_evidence(freshness_event, "canonical_publication")
            decision_is_blocked = decision_event.event_type == "data.decision_read.blocked"
            if (
                freshness_ref != publication_ref
                or freshness_event.publication_id != publication_id
                or freshness_event.resource is None
                or freshness_event.resource.resource_id != publication_id
                or freshness_event.resource.resource_version != publication_ref.artifact_version
                or freshness_event.detail.get("publication_hash") != publication_ref.content_hash
                or freshness_event.detail.get("publication_key")
                != publication_event.detail.get("publication_key")
                or freshness_event.detail.get("freshness_status")
                != decision_event.detail.get("freshness_status")
                or freshness_event.detail.get("must_not_use_for_decision")
                is not decision_is_blocked
                or freshness_event.detail.get("blocked_reason")
                != decision_event.detail.get("blocked_reason")
                or freshness_event.outcome.value
                != ("blocked" if decision_is_blocked else "recovered")
            ):
                raise ReplayCorruption()
        try:
            publication = self._publication_reader.get_by_id(publication_id)
        except Exception as error:
            raise ReplayUnavailable() from error
        if publication is None:
            raise ReplayUnavailable()
        if (
            publication.publication_id != publication_id
            or publication.dataset_key != dataset_key
            or publication.state is not PublicationState.PUBLISHED
            or publication.run_id != correlation.resolved_run_id
            or publication.policy_version != publication_ref.artifact_version
            or publication.publication_hash != publication_ref.content_hash
            or publication_event.detail.get("publication_hash") != publication.publication_hash
            or publication_event.detail.get("publication_key") != publication.publication_key
            or publication_event.resource is None
            or publication_event.resource.resource_id != publication_id
            or publication_event.resource.resource_version != publication.policy_version
            or decision_event.publication_id != publication_id
            or decision_event.resource is None
            or decision_event.resource.resource_id != publication_id
            or decision_event.resource.resource_version != publication.policy_version
            or decision_event.detail.get("publication_hash") != publication.publication_hash
            or decision_event.detail.get("publication_key") != publication.publication_key
        ):
            raise ReplayCorruption()

        rollback_ids = _validate_publication_rollbacks(
            rollback_events,
            publication=publication,
            publication_reader=self._publication_reader,
            resolved_run_id=correlation.resolved_run_id,
        )

        try:
            members = tuple(self._publication_reader.list_members(publication_id))
        except Exception as error:
            raise ReplayUnavailable() from error
        expected_member_count = publication.member_count
        if (
            expected_member_count <= 0
            or len(members) != expected_member_count
            or publication_event.detail.get("member_count") != expected_member_count
        ):
            raise ReplayCorruption()
        member_keys = tuple((member.fact_table, member.fact_pk) for member in members)
        if (
            len(set(member_keys)) != len(member_keys)
            or len({member.member_id for member in members}) != len(members)
            or len({member.natural_key for member in members}) != len(members)
            or any(
                member.publication_id != publication_id or member.dataset_key != dataset_key
                for member in members
            )
        ):
            raise ReplayCorruption()
        references = tuple(_member_reference(member) for member in members)
        if publication_hash(references) != publication.publication_hash:
            raise ReplayCorruption()
        try:
            quality_projection = project_publication_quality(publication, members)
        except (TypeError, ValueError) as error:
            raise ReplayCorruption() from error
        quality_event = quality_events[0] if quality_events else None
        if quality_projection.quality_state == "degraded" and quality_event is None:
            raise ReplayCorruption()
        if quality_event is not None:
            _validate_publication_quality_event(
                quality_event,
                publication=publication,
                publication_ref=publication_ref,
                projection=quality_projection,
            )

        try:
            fact_evidence = self._fact_evidence_reader.list_member_evidence(members)
        except Exception as error:
            raise ReplayUnavailable() from error
        if any(
            not isinstance(evidence, ReplayMemberPersistenceEvidence) for evidence in fact_evidence
        ):
            raise ReplayCorruption()
        evidence_by_key = {
            (evidence.fact_table, evidence.fact_pk): evidence for evidence in fact_evidence
        }
        if (
            len(evidence_by_key) != len(fact_evidence)
            or set(evidence_by_key) != set(member_keys)
            or any(
                evidence.ingested_run_id != ingested_run_id for evidence in evidence_by_key.values()
            )
        ):
            raise ReplayCorruption()

        return DataChainReplayResult(
            resolved_run_id=correlation.resolved_run_id,
            ingested_run_id=ingested_run_id,
            publication_id=publication_id,
            publication_version=publication.policy_version,
            publication_hash=publication.publication_hash,
            dataset_key=dataset_key,
            member_count=expected_member_count,
            decision_outcome=decision_event.outcome.value,
            ordered_stage_keys=(
                (_FETCH_COMPLETED,)
                + tuple(
                    event.event_type
                    for event in relevant_events
                    if event.event_type in _FAILOVER_TYPES
                )
                + (_PUBLICATION_PUBLISHED,)
                + ((_QUALITY_CHANGED,) if quality_event is not None else ())
                + ((_FRESHNESS_CHANGED,) if freshness_event is not None else ())
                + (decision_event.event_type,)
                + tuple(event.event_type for event in rollback_events)
            ),
            rollback_ids=rollback_ids,
            quality_state=quality_projection.quality_state,
        )


__all__ = [
    "DataChainReplayCommand",
    "DataChainReplayResult",
    "ReplayCorruption",
    "ReplayDataChainUseCase",
    "ReplayFactEvidenceReader",
    "ReplayMemberPersistenceEvidence",
    "ReplayPublicationReader",
    "ReplayRawAuditReader",
    "ReplayUnavailable",
]
