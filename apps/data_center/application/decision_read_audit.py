"""Record publication-bound decision-read outcomes for canonical replay."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol

from apps.data_center.application.dtos import SyncResult
from apps.data_center.application.sync_transaction import (
    DataCenterSyncClock,
    DataDecisionReadAuditWriter,
    DataFreshnessAuditWriter,
)
from core.exceptions import DataValidationError
from core.integration.data_center_audit import (
    AuditOutcome,
    DataDecisionReadAuditObservation,
    DataFreshnessAuditObservation,
)

_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")


class DecisionReadAuditUnavailable(DataValidationError):
    """Required publication or gate evidence cannot be recorded safely."""

    default_message = "Decision-read audit evidence is unavailable"
    default_code = "DECISION_READ_AUDIT_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class RecordPublicationDecisionReadCommand:
    """Describe one decision gate evaluated against an exact publication."""

    sync_result: SyncResult
    dataset_key: str
    publication_key: str
    decision_key: str
    freshness_status: str
    must_not_use_for_decision: bool
    blocked_reason: str | None

    def __post_init__(self) -> None:
        for field_name in (
            "dataset_key",
            "publication_key",
            "decision_key",
            "freshness_status",
        ):
            value = getattr(self, field_name)
            if type(value) is not str or _TOKEN_PATTERN.fullmatch(value) is None:
                raise ValueError(f"{field_name} must be a bounded canonical identifier")


def _require_identity(value: object) -> str:
    """Return one present string identity or fail without echoing its value."""

    if type(value) is not str or not value:
        raise DecisionReadAuditUnavailable()
    return value


def _require_aware(value: object) -> datetime:
    """Return one timezone-aware instant or fail closed."""

    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise DecisionReadAuditUnavailable()
    return value


class RecordPublicationDecisionReadUseCase:
    """Write one recovered or blocked decision read against exact sync evidence."""

    __slots__ = ("_clock", "_freshness_writer", "_writer")

    def __init__(
        self,
        writer: DataDecisionReadAuditWriter,
        clock: DataCenterSyncClock,
        *,
        freshness_writer: DataFreshnessAuditWriter,
    ) -> None:
        self._writer = writer
        self._clock = clock
        self._freshness_writer = freshness_writer

    def execute(self, command: RecordPublicationDecisionReadCommand) -> object | None:
        """Record the gate outcome, or skip a genuine unpublished no-op."""

        if not isinstance(command, RecordPublicationDecisionReadCommand):
            raise TypeError("command must be a RecordPublicationDecisionReadCommand")
        result = command.sync_result
        if not isinstance(result, SyncResult):
            raise DecisionReadAuditUnavailable()
        if result.status == "noop" and result.publication_id is None:
            if result.publication_version is not None or result.publication_hash is not None:
                raise DecisionReadAuditUnavailable()
            return None

        recorded_at = _require_aware(self._clock.now())
        outcome = (
            AuditOutcome.BLOCKED if command.must_not_use_for_decision else AuditOutcome.RECOVERED
        )
        if outcome is AuditOutcome.BLOCKED and command.blocked_reason is None:
            raise DecisionReadAuditUnavailable()
        if outcome is AuditOutcome.RECOVERED and command.blocked_reason is not None:
            raise DecisionReadAuditUnavailable()

        try:
            dataset_key = _require_identity(command.dataset_key)
            publication_key = _require_identity(command.publication_key)
            publication_id = _require_identity(result.publication_id)
            publication_version = _require_identity(result.publication_version)
            publication_hash = _require_identity(result.publication_hash)
            provider_key = _require_identity(result.provider_name)
            run_id = _require_identity(result.run_id)
            ingested_run_id = _require_identity(result.ingested_run_id)
            freshness_status = _require_identity(command.freshness_status)
            freshness_observation = DataFreshnessAuditObservation(
                dataset_key=dataset_key,
                publication_key=publication_key,
                publication_id=publication_id,
                publication_version=publication_version,
                publication_hash=publication_hash,
                provider_key=provider_key,
                run_id=run_id,
                ingested_run_id=ingested_run_id,
                freshness_status=freshness_status,
                must_not_use_for_decision=command.must_not_use_for_decision,
                recorded_at=recorded_at,
                occurred_at=recorded_at,
                blocked_reason=command.blocked_reason,
            )
            observation = DataDecisionReadAuditObservation(
                dataset_key=dataset_key,
                publication_key=publication_key,
                publication_id=publication_id,
                publication_version=publication_version,
                publication_hash=publication_hash,
                provider_key=provider_key,
                run_id=run_id,
                ingested_run_id=ingested_run_id,
                decision_key=_require_identity(command.decision_key),
                freshness_status=freshness_status,
                outcome=outcome,
                recorded_at=recorded_at,
                occurred_at=recorded_at,
                blocked_reason=command.blocked_reason,
            )
        except (TypeError, ValueError) as exc:
            raise DecisionReadAuditUnavailable() from exc
        self._freshness_writer.write(freshness_observation)
        return self._writer.write(observation)


class PublicationDecisionReadRecorder(Protocol):
    """Application port for recording one publication-bound read gate."""

    def execute(self, command: RecordPublicationDecisionReadCommand) -> object | None:
        """Record the exact gate outcome or return ``None`` for an unpublished no-op."""


__all__ = [
    "DecisionReadAuditUnavailable",
    "PublicationDecisionReadRecorder",
    "RecordPublicationDecisionReadCommand",
    "RecordPublicationDecisionReadUseCase",
]
