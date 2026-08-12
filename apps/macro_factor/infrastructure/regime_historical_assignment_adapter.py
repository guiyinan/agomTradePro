"""Read-only Macro Factor adapter over Regime historical assignment receipts."""

from __future__ import annotations

from datetime import datetime

from apps.macro_factor.domain.governed_read import (
    R3RegimeObservationEvidence,
    R3RegimeSegmentReport,
    build_regime_segment_report,
)
from apps.macro_factor.domain.run_artifacts import ReproducibleMacroFactorRunArtifact
from apps.macro_factor.infrastructure.run_ledger_repository import (
    DjangoMacroFactorRunLedgerReadRepository,
)
from apps.regime.infrastructure.historical_assignment_repository import (
    DjangoHistoricalRegimeAssignmentRepository,
)


class RegimeHistoricalAssignmentReportAdapter:
    """Project only exact PIT receipts into the governed-read Regime report port."""

    __slots__ = (
        "_assignment_repository",
        "_expected_assignment_id",
        "_expected_ledger_id",
        "_expected_uow_key",
        "_ledger",
    )

    def __init__(
        self,
        *,
        assignment_repository: DjangoHistoricalRegimeAssignmentRepository,
        ledger: DjangoMacroFactorRunLedgerReadRepository,
    ) -> None:
        expected = _uow_key(assignment_repository.unit_of_work_key)
        if _uow_key(ledger.unit_of_work_key) != expected:
            raise ValueError("Regime assignment adapter requires one shared unit of work")
        self._assignment_repository = assignment_repository
        self._ledger = ledger
        self._expected_assignment_id = id(assignment_repository)
        self._expected_ledger_id = id(ledger)
        self._expected_uow_key = expected

    @property
    def unit_of_work_key(self) -> str:
        """Return the unchanged shared read/snapshot identity."""

        self._require_live_readers()
        return self._expected_uow_key

    def get_report(
        self,
        *,
        artifact_id: str,
        expected_artifact_hash: str,
        as_of: datetime,
    ) -> R3RegimeSegmentReport | None:
        """Return a recalculated exact report or ``None`` without latest guessing."""

        try:
            _digest(artifact_id, "artifact_id")
            _digest(expected_artifact_hash, "expected_artifact_hash")
            _aware(as_of, "as_of")
            self._require_live_readers()
            artifact = self._ledger.get_artifact(artifact_id)
            self._require_live_readers()
            if artifact is None or type(artifact) is not ReproducibleMacroFactorRunArtifact:
                return None
            ReproducibleMacroFactorRunArtifact.__post_init__(artifact)
            if (
                artifact.content_hash != expected_artifact_hash.lower()
                or artifact.produced_at > as_of
            ):
                return None
            receipt = self._assignment_repository.get_exact_receipt(
                artifact_id=artifact_id,
                expected_artifact_hash=expected_artifact_hash,
                as_of=as_of,
            )
            self._require_live_readers()
            if receipt is None:
                return None
            receipt = receipt.validated_copy()
            if (
                receipt.artifact_id != artifact.artifact_id
                or receipt.artifact_hash != artifact.content_hash
                or receipt.source_result_hash != artifact.source_result_hash
                or receipt.pit_manifest_id != artifact.pit_manifest_id
                or receipt.pit_manifest_hash != artifact.pit_manifest_hash
                or receipt.recorded_at > as_of
            ):
                return None
            observations = tuple(
                R3RegimeObservationEvidence(
                    owner="regime",
                    artifact_id=receipt.artifact_id,
                    artifact_hash=receipt.artifact_hash,
                    fold_id=item.fold_id,
                    row_id=item.row_id,
                    observation_at=item.observation_at,
                    actual_available_at=item.actual_fact.available_at,
                    actual_value=item.actual_value,
                    actual_fact_id=item.actual_fact.fact_id,
                    actual_fact_hash=item.actual_fact.evidence_hash,
                    predicted_value=item.predicted_value,
                    regime_code=item.regime_code,
                    regime_version=item.regime_version,
                    regime_content_hash=item.regime_content_hash,
                    regime_effective_at=max(
                        item.growth_fact.effective_at,
                        item.inflation_fact.effective_at,
                    ),
                    regime_available_at=max(
                        item.growth_fact.available_at,
                        item.inflation_fact.available_at,
                    ),
                )
                for item in receipt.assignments
            )
            report = build_regime_segment_report(
                artifact,
                observations,
                evaluated_at=receipt.recorded_at,
            )
            self._require_live_readers()
            return report
        except Exception:
            return None

    def _require_live_readers(self) -> None:
        if (
            id(self._assignment_repository) != self._expected_assignment_id
            or id(self._ledger) != self._expected_ledger_id
            or _uow_key(self._assignment_repository.unit_of_work_key) != self._expected_uow_key
            or _uow_key(self._ledger.unit_of_work_key) != self._expected_uow_key
        ):
            raise ValueError("Regime assignment adapter reader changed")


def _digest(value: object, name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in value)
    ):
        raise ValueError(f"{name} must be a SHA-256 digest")
    return value.lower()


def _aware(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _uow_key(value: object) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > 192:
        raise ValueError("unit_of_work_key must be exact")
    return value


__all__ = ["RegimeHistoricalAssignmentReportAdapter"]
