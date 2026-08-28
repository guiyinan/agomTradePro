"""Fail-closed replay of one reliability-repair parent run and all child chains."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from apps.data_center.application.data_chain_replay import (
    DataChainReplayCommand,
    DataChainReplayResult,
    ReplayCorruption,
    ReplayDataChainUseCase,
    ReplayUnavailable,
)
from apps.data_center.application.sync_identity import SyncExecutionIdentity
from core.exceptions import DataValidationError, ResourceNotFoundError
from core.integration.data_center_audit import (
    AuditCategory,
    AuditEvidenceRef,
    AuditOutcome,
    AuditSeverity,
    AuditWritePolicy,
    ListCorrelatedSystemAuditEventsCommand,
    ListCorrelatedSystemAuditEventsResult,
    RepairPublicationEvidence,
    RepairSectionEvidence,
    SystemAuditEvent,
    SystemAuditQueryCorruption,
    SystemAuditQueryUnavailable,
    SystemAuditReaderContext,
)

_REPAIR_EVENT_TYPE = "data.repair.completed"
_REPAIR_DATASET_KEY = "decision.reliability.repair"
_REPAIR_PROVIDER_KEY = "data-center-repair"


def _require_uuid(value: object, field_name: str) -> str:
    """Return canonical lowercase UUID text."""

    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(f"{field_name} must be a canonical UUID")
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise ValueError(f"{field_name} must be a canonical UUID") from error
    if str(parsed) != value.lower():
        raise ValueError(f"{field_name} must use canonical lowercase UUID text")
    return value


def _require_aware(value: object, field_name: str) -> datetime:
    """Return one timezone-aware instant."""

    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _require_detail_text(value: object, field_name: str) -> str:
    """Narrow one dynamic audit-detail field to exact string text."""

    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    return value


class RepairRunReplayUnavailable(ResourceNotFoundError):
    """The parent repair run or one required child record is unavailable."""

    default_message = "Canonical repair-run replay evidence is unavailable"
    default_code = "REPAIR_RUN_REPLAY_UNAVAILABLE"


class RepairRunReplayCorruption(DataValidationError):
    """The parent repair run or one child chain contains inconsistent evidence."""

    default_message = "Canonical repair-run replay evidence is inconsistent"
    default_code = "REPAIR_RUN_REPLAY_CORRUPTION"


@dataclass(frozen=True, slots=True)
class RepairRunReplayCommand:
    """Select one repair parent run at an authorized PIT cutoff."""

    run_id: str
    as_of: datetime
    reader: SystemAuditReaderContext

    def __post_init__(self) -> None:
        _require_uuid(self.run_id, "run_id")
        _require_aware(self.as_of, "as_of")
        if not isinstance(self.reader, SystemAuditReaderContext):
            raise TypeError("reader must be a SystemAuditReaderContext")


@dataclass(frozen=True, slots=True)
class RepairRunReplayResult:
    """Verified parent identity, outcome, and ordered child-chain replays."""

    resolved_run_id: str
    ingested_run_id: str
    identity_hash: str
    outcome: str
    target_date: date
    remaining_blocker_count: int
    publication_replays: tuple[DataChainReplayResult, ...]

    @property
    def publication_ids(self) -> tuple[str, ...]:
        """Return the verified child publication identities in canonical order."""

        return tuple(replay.publication_id for replay in self.publication_replays)


class RepairRunCorrelationQuery(Protocol):
    """Read one scoped parent run from the canonical audit ledger."""

    def execute(
        self,
        command: ListCorrelatedSystemAuditEventsCommand,
    ) -> ListCorrelatedSystemAuditEventsResult:
        """Return all events correlated to the requested parent run."""


class RepairRunIdentityReader(Protocol):
    """Read one persisted canonical execution identity by its exact hash."""

    def get_by_identity_hash(self, identity_hash: str) -> SyncExecutionIdentity | None:
        """Return the exact identity or ``None`` when it is unavailable."""


class RepairPublicationReplay(Protocol):
    """Replay one child publication through the canonical data-chain verifier."""

    def execute(self, command: DataChainReplayCommand) -> DataChainReplayResult:
        """Return one verified child chain or raise fail closed."""


def _one_parent_event(events: tuple[SystemAuditEvent, ...]) -> SystemAuditEvent:
    """Return exactly one repair-completion event and reject mixed parent runs."""

    matches = tuple(event for event in events if event.event_type == _REPAIR_EVENT_TYPE)
    if not matches:
        raise RepairRunReplayUnavailable()
    if len(matches) != 1 or len(events) != 1:
        raise RepairRunReplayCorruption()
    return matches[0]


def _identity_evidence(event: SystemAuditEvent) -> AuditEvidenceRef:
    """Return exactly one sync-execution identity reference."""

    matches = tuple(
        evidence
        for evidence in event.evidence_refs
        if evidence.artifact_type == "sync_execution_identity"
    )
    if len(matches) != 1:
        raise RepairRunReplayCorruption()
    return matches[0]


def _parse_sections(event: SystemAuditEvent) -> tuple[RepairSectionEvidence, ...]:
    """Rebuild and validate the sanitized section summary."""

    raw_sections = event.detail.get("sections")
    if not isinstance(raw_sections, list) or not raw_sections:
        raise RepairRunReplayCorruption()
    sections: list[RepairSectionEvidence] = []
    try:
        for raw_section in raw_sections:
            if not isinstance(raw_section, dict):
                raise TypeError("repair section detail must be an object")
            section_key = raw_section.get("section_key")
            status = raw_section.get("status")
            blocked = raw_section.get("must_not_use_for_decision")
            blocker_count = raw_section.get("remaining_blocker_count")
            if (
                type(section_key) is not str
                or type(status) is not str
                or type(blocked) is not bool
                or not isinstance(blocker_count, int)
                or isinstance(blocker_count, bool)
            ):
                raise TypeError("repair section detail has invalid field types")
            sections.append(
                RepairSectionEvidence(
                    section_key=section_key,
                    status=status,
                    must_not_use_for_decision=blocked,
                    remaining_blocker_count=blocker_count,
                )
            )
    except (TypeError, ValueError) as error:
        raise RepairRunReplayCorruption() from error
    canonical = tuple(sorted(sections, key=lambda item: item.section_key))
    if tuple(sections) != canonical or len({item.section_key for item in canonical}) != len(
        canonical
    ):
        raise RepairRunReplayCorruption()
    expected_outcome = AuditOutcome.SUCCESS
    if any(section.status == "failed" for section in canonical):
        expected_outcome = AuditOutcome.FAILED
    elif any(section.must_not_use_for_decision for section in canonical):
        expected_outcome = AuditOutcome.PARTIAL
    if event.outcome is not expected_outcome:
        raise RepairRunReplayCorruption()
    total = sum(section.remaining_blocker_count for section in canonical)
    if event.detail.get("remaining_blocker_count") != total:
        raise RepairRunReplayCorruption()
    return canonical


def _parse_publications(event: SystemAuditEvent) -> tuple[RepairPublicationEvidence, ...]:
    """Rebuild exact publication evidence and compare it to event references."""

    raw_publications = event.detail.get("publications")
    if not isinstance(raw_publications, list):
        raise RepairRunReplayCorruption()
    publications: list[RepairPublicationEvidence] = []
    try:
        for raw_publication in raw_publications:
            if not isinstance(raw_publication, dict):
                raise TypeError("repair publication detail must be an object")
            publication_id = _require_detail_text(
                raw_publication.get("publication_id"),
                "publication_id",
            )
            publication_version = _require_detail_text(
                raw_publication.get("publication_version"),
                "publication_version",
            )
            publication_hash = _require_detail_text(
                raw_publication.get("publication_hash"),
                "publication_hash",
            )
            dataset_key = _require_detail_text(
                raw_publication.get("dataset_key"),
                "dataset_key",
            )
            publications.append(
                RepairPublicationEvidence(
                    publication_id=publication_id,
                    publication_version=publication_version,
                    publication_hash=publication_hash,
                    dataset_key=dataset_key,
                )
            )
    except (TypeError, ValueError) as error:
        raise RepairRunReplayCorruption() from error
    canonical = tuple(
        sorted(publications, key=lambda item: (item.dataset_key, item.publication_id))
    )
    if tuple(publications) != canonical or len({item.publication_id for item in canonical}) != len(
        canonical
    ):
        raise RepairRunReplayCorruption()
    if event.detail.get("publication_count") != len(canonical):
        raise RepairRunReplayCorruption()
    publication_refs = tuple(
        evidence
        for evidence in event.evidence_refs
        if evidence.artifact_type == "canonical_publication"
    )
    expected_refs = tuple(
        AuditEvidenceRef(
            "data_center",
            "canonical_publication",
            publication.publication_id,
            publication.publication_version,
            publication.publication_hash,
        )
        for publication in canonical
    )
    if publication_refs != expected_refs:
        raise RepairRunReplayCorruption()
    if len(event.evidence_refs) != len(canonical) + 1:
        raise RepairRunReplayCorruption()
    return canonical


class ReplayRepairRunUseCase:
    """Verify one parent repair event, its identity, and every child chain."""

    __slots__ = ("_correlation_query", "_identity_reader", "_publication_replay")

    def __init__(
        self,
        *,
        correlation_query: RepairRunCorrelationQuery,
        identity_reader: RepairRunIdentityReader,
        publication_replay: RepairPublicationReplay | ReplayDataChainUseCase,
    ) -> None:
        self._correlation_query = correlation_query
        self._identity_reader = identity_reader
        self._publication_replay = publication_replay

    def execute(self, command: RepairRunReplayCommand) -> RepairRunReplayResult:
        """Replay one complete repair run and reject any missing or substituted evidence."""

        try:
            correlation = self._correlation_query.execute(
                ListCorrelatedSystemAuditEventsCommand(
                    run_id=command.run_id,
                    publication_id=None,
                    as_of=command.as_of,
                    reader=command.reader,
                )
            )
        except SystemAuditQueryUnavailable as error:
            raise RepairRunReplayUnavailable() from error
        except SystemAuditQueryCorruption as error:
            raise RepairRunReplayCorruption() from error
        if correlation.resolved_run_id != command.run_id:
            raise RepairRunReplayCorruption()
        event = _one_parent_event(correlation.events)
        try:
            event.validate_hashes()
        except (TypeError, ValueError) as error:
            raise RepairRunReplayCorruption() from error
        if event.scope != command.reader.scope or event.recorded_at > command.as_of:
            raise RepairRunReplayCorruption()
        if (
            event.category is not AuditCategory.DATA_RELIABILITY
            or event.write_policy is not AuditWritePolicy.REQUIRED
            or event.severity is not AuditSeverity.INFO
            or event.reason_codes != ("repair_completed",)
            or event.dataset_key != _REPAIR_DATASET_KEY
            or event.provider_key != _REPAIR_PROVIDER_KEY
            or event.capability != "repair"
            or event.correlations.run_id != command.run_id
            or event.correlations.dataset_key != _REPAIR_DATASET_KEY
            or event.correlations.provider_key != _REPAIR_PROVIDER_KEY
            or event.correlations.capability != "repair"
            or event.resource is None
            or event.resource.resource_type != "repair_run"
            or event.resource.resource_id != command.run_id
            or event.resource.resource_version != "1"
        ):
            raise RepairRunReplayCorruption()

        identity_ref = _identity_evidence(event)
        if (
            event.evidence_refs[0] != identity_ref
            or identity_ref.owner != "data_center"
            or identity_ref.artifact_version != "1"
            or identity_ref.artifact_id != identity_ref.content_hash
            or event.correlations.evidence_ref != identity_ref.artifact_id
            or event.detail.get("sync_identity_id") != identity_ref.artifact_id
            or event.detail.get("sync_identity_version") != identity_ref.artifact_version
            or event.detail.get("sync_identity_hash") != identity_ref.content_hash
        ):
            raise RepairRunReplayCorruption()
        try:
            identity = self._identity_reader.get_by_identity_hash(identity_ref.artifact_id)
        except Exception as error:
            raise RepairRunReplayUnavailable() from error
        if identity is None:
            raise RepairRunReplayUnavailable()
        if not isinstance(identity, SyncExecutionIdentity):
            raise RepairRunReplayCorruption()
        if (
            identity.identity_hash != identity_ref.content_hash
            or identity.run_id != command.run_id
            or identity.ingested_run_id != event.correlations.ingested_run_id
            or identity.dataset_key != _REPAIR_DATASET_KEY
            or identity.provider_name != _REPAIR_PROVIDER_KEY
        ):
            raise RepairRunReplayCorruption()

        _parse_sections(event)
        publications = _parse_publications(event)
        if event.outcome is AuditOutcome.SUCCESS and not publications:
            raise RepairRunReplayCorruption()
        raw_target_date = event.detail.get("target_date")
        if type(raw_target_date) is not str:
            raise RepairRunReplayCorruption()
        try:
            target_date = date.fromisoformat(raw_target_date)
        except ValueError as error:
            raise RepairRunReplayCorruption() from error
        if target_date.isoformat() != raw_target_date:
            raise RepairRunReplayCorruption()

        child_replays: list[DataChainReplayResult] = []
        for publication in publications:
            try:
                replay = self._publication_replay.execute(
                    DataChainReplayCommand(
                        run_id=None,
                        publication_id=publication.publication_id,
                        as_of=command.as_of,
                        reader=command.reader,
                    )
                )
            except ReplayUnavailable as error:
                raise RepairRunReplayUnavailable() from error
            except ReplayCorruption as error:
                raise RepairRunReplayCorruption() from error
            if not isinstance(replay, DataChainReplayResult):
                raise RepairRunReplayCorruption()
            if (
                replay.publication_id != publication.publication_id
                or replay.publication_version != publication.publication_version
                or replay.publication_hash != publication.publication_hash
                or replay.dataset_key != publication.dataset_key
            ):
                raise RepairRunReplayCorruption()
            child_replays.append(replay)

        remaining_blocker_count = event.detail.get("remaining_blocker_count")
        if (
            not isinstance(remaining_blocker_count, int)
            or isinstance(remaining_blocker_count, bool)
            or remaining_blocker_count < 0
        ):
            raise RepairRunReplayCorruption()
        return RepairRunReplayResult(
            resolved_run_id=command.run_id,
            ingested_run_id=identity.ingested_run_id,
            identity_hash=identity.identity_hash,
            outcome=event.outcome.value,
            target_date=target_date,
            remaining_blocker_count=remaining_blocker_count,
            publication_replays=tuple(child_replays),
        )


__all__ = [
    "RepairPublicationReplay",
    "RepairRunCorrelationQuery",
    "RepairRunIdentityReader",
    "RepairRunReplayCommand",
    "RepairRunReplayCorruption",
    "RepairRunReplayResult",
    "RepairRunReplayUnavailable",
    "ReplayRepairRunUseCase",
]
