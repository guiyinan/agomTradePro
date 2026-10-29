"""Read retained native daily statuses without promoting them to trading inputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Protocol
from uuid import UUID

from apps.data_center.domain.qmt_daily_status import (
    BridgeDailyStatusBatch,
    BridgeDailyStatusSample,
    QmtDailyStatusState,
    QmtDailyStatusValidationError,
)


@dataclass(frozen=True, slots=True)
class QmtDailyStatusRecord:
    """One validated normalized batch and its separate server retention clock."""

    batch: BridgeDailyStatusBatch
    recorded_at: datetime
    digest: str


@dataclass(frozen=True, slots=True)
class QmtDailyStatusReadSnapshot:
    """Owner-scoped retained inputs or a stable refusal to read the scope."""

    records: tuple[QmtDailyStatusRecord, ...]
    blocked_reason: str | None = None


class QmtDailyStatusReadPort(Protocol):
    """Read authorized batches visible by cutoff and recheck current authority."""

    def read_snapshot(
        self, *, owner_id: int, binding_id: str, asset_code: str, bar_date: date, as_of: datetime
    ) -> QmtDailyStatusReadSnapshot: ...


@dataclass(frozen=True, slots=True)
class QmtDailyStatusEvidence:
    """Exact retained identities supporting a status, never an original SDK response."""

    batch_id: str
    content_hash: str
    collected_at: datetime
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class QmtDailyStatusResult:
    """A historical source assertion with unknown supplier clocks and no authority."""

    binding_id: str
    asset_code: str
    bar_date: date
    as_of: datetime
    state: QmtDailyStatusState
    suspend_flag: int | None
    local_known_at: datetime | None
    recorded_at: datetime | None
    evidence: tuple[QmtDailyStatusEvidence, ...]
    blocked_reason: str
    source_observed_at: None = field(init=False, default=None)
    source_available_at: None = field(init=False, default=None)
    freshness: Literal["unknown"] = field(init=False, default="unknown")
    reliability: Literal["unverified"] = field(init=False, default="unverified")
    knowledge_basis: Literal["agent_reported_collection_completion"] = field(
        init=False, default="agent_reported_collection_completion"
    )
    coverage_basis: Literal["returned_native_rows_only"] = field(
        init=False, default="returned_native_rows_only"
    )
    must_not_use_for_decision: Literal[True] = field(init=False, default=True)
    must_not_execute: Literal[True] = field(init=False, default=True)


class ReadQmtDailyStatus:
    """Resolve exact asset/date observations while preserving conflicting restrictions."""

    def __init__(self, repository: QmtDailyStatusReadPort) -> None:
        self._repository = repository

    def execute(
        self,
        *,
        owner_id: int,
        binding_id: str,
        asset_code: str,
        bar_date: date,
        as_of: datetime,
    ) -> QmtDailyStatusResult:
        """Read historical assertions; a missing or later unknown observation never clears risk."""

        if type(owner_id) is not int or owner_id <= 0:
            raise QmtDailyStatusValidationError("A persistent owner is required")
        if type(binding_id) is not str:
            raise QmtDailyStatusValidationError("A canonical binding UUID is required")
        try:
            if str(UUID(binding_id)) != binding_id:
                raise ValueError("noncanonical UUID")
        except ValueError as error:
            raise QmtDailyStatusValidationError("A canonical binding UUID is required") from error
        BridgeDailyStatusSample(asset_code, bar_date, None).validate()
        if type(as_of) is not datetime or as_of.utcoffset() is None:
            raise QmtDailyStatusValidationError("An aware read cutoff is required")

        def result(
            reason: str,
            *,
            state: QmtDailyStatusState = QmtDailyStatusState.UNKNOWN,
            flag: int | None = None,
            local_known_at: datetime | None = None,
            recorded_at: datetime | None = None,
            evidence: tuple[QmtDailyStatusEvidence, ...] = (),
        ) -> QmtDailyStatusResult:
            return QmtDailyStatusResult(
                binding_id,
                asset_code,
                bar_date,
                as_of,
                state,
                flag,
                local_known_at,
                recorded_at,
                evidence,
                reason,
            )

        if bar_date >= as_of.astimezone(timezone(timedelta(hours=8))).date():
            return result("qmt_daily_status_not_historical")
        snapshot = self._repository.read_snapshot(
            owner_id=owner_id,
            binding_id=binding_id,
            asset_code=asset_code,
            bar_date=bar_date,
            as_of=as_of,
        )
        if snapshot.blocked_reason is not None:
            return result(snapshot.blocked_reason)
        matching: list[tuple[QmtDailyStatusRecord, BridgeDailyStatusSample]] = []
        for retained in snapshot.records:
            try:
                retained.batch.validate(as_of)
                if (
                    type(retained.recorded_at) is not datetime
                    or retained.recorded_at.utcoffset() is None
                    or not retained.batch.collected_at <= retained.recorded_at <= as_of
                    or retained.digest != retained.batch.content_hash
                ):
                    raise QmtDailyStatusValidationError("Retained status proof is inconsistent")
            except (QmtDailyStatusValidationError, TypeError, OverflowError):
                return result("qmt_daily_status_invalid_retained_evidence")
            for sample in retained.batch.samples:
                if sample.asset_code == asset_code and sample.bar_date == bar_date:
                    matching.append((retained, sample))
        if not matching:
            return result("qmt_daily_status_observation_missing")
        matching.sort(
            key=lambda item: (
                item[0].batch.collected_at,
                item[0].recorded_at,
                item[0].batch.batch_id,
            )
        )
        evidence = tuple(
            QmtDailyStatusEvidence(
                row.batch.batch_id, row.digest, row.batch.collected_at, row.recorded_at
            )
            for row, _ in matching
        )
        known_flags = {
            sample.suspend_flag for _, sample in matching if sample.suspend_flag is not None
        }
        if len(known_flags) > 1:
            return result("qmt_daily_status_conflicting_observations", evidence=evidence)
        latest_at = matching[-1][0].batch.collected_at
        latest = [(row, sample) for row, sample in matching if row.batch.collected_at == latest_at]
        if any(sample.suspend_flag is None for _, sample in latest):
            return result("qmt_daily_status_missing_suspend_flag", evidence=evidence)
        last_row, last_sample = latest[-1]
        return result(
            "qmt_daily_status_requires_publication_validation",
            state=last_sample.state,
            flag=last_sample.suspend_flag,
            local_known_at=last_row.batch.collected_at,
            recorded_at=last_row.recorded_at,
            evidence=evidence,
        )
