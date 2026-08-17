"""Read-only batch revalidation for stored TUI metadata registry rows."""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from apps.terminal.application.tui_metadata import TuiMetadataValidationError

from .models import TuiMetadataRegistryORM
from .tui_metadata_repository import PublishedTuiMetadataRepository

logger = logging.getLogger(__name__)

RevalidationOutcome = Literal["success", "partial", "failed", "noop"]
RevalidationRecommendation = Literal[
    "no_rows_to_revalidate",
    "no_action_required",
    "repair_or_archive_invalid_rows_before_publish",
    "investigate_revalidation_errors_before_repair_or_archive",
]

VALID_ROW_RECOMMENDATION = "retain"
INVALID_ROW_RECOMMENDATION = "repair_or_archive_before_publish"
ERROR_ROW_RECOMMENDATION = "investigate_revalidation_error"


class TuiMetadataRuntimeRepository(Protocol):
    """Minimal repository port required by the read-only revalidator."""

    def validate_and_normalize_runtime_payload(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Validate and normalize one runtime payload."""
        ...

    def payload_hash(self, payload: dict[str, Any]) -> str:
        """Return the deterministic payload hash."""
        ...


@dataclass(frozen=True)
class TuiMetadataRevalidationRow:
    """Stable read-only result for one stored metadata registry row."""

    registry_id: int
    registry_key: str
    status: str
    version: str
    valid: bool
    reason_code: str | None
    error_type: str | None
    normalized_hash: str | None
    recommendation: str

    def as_dict(self) -> dict[str, Any]:
        """Return the row result as a JSON-safe mapping."""

        return {
            "registry_id": self.registry_id,
            "registry_key": self.registry_key,
            "status": self.status,
            "version": self.version,
            "valid": self.valid,
            "reason_code": self.reason_code,
            "error_type": self.error_type,
            "normalized_hash": self.normalized_hash,
            "recommendation": self.recommendation,
        }


@dataclass(frozen=True)
class TuiMetadataRevalidationReport:
    """Stable dry-run summary for all stored metadata registry rows."""

    outcome: RevalidationOutcome
    recommendation: RevalidationRecommendation
    dry_run: bool
    writes_performed: int
    total_count: int
    valid_count: int
    invalid_count: int
    error_count: int
    status_counts: dict[str, int]
    rows: tuple[TuiMetadataRevalidationRow, ...]

    def as_dict(self) -> dict[str, Any]:
        """Return the report as a deterministic JSON-safe mapping."""

        return {
            "outcome": self.outcome,
            "recommendation": self.recommendation,
            "dry_run": self.dry_run,
            "writes_performed": self.writes_performed,
            "counts": {
                "total": self.total_count,
                "valid": self.valid_count,
                "invalid": self.invalid_count,
                "errors": self.error_count,
            },
            "status_counts": dict(sorted(self.status_counts.items())),
            "rows": [row.as_dict() for row in self.rows],
        }


class TuiMetadataRegistryRevalidationService:
    """Revalidate every stored registry row without mutating the database."""

    def __init__(self, repository: TuiMetadataRuntimeRepository | None = None) -> None:
        self.repository = repository or PublishedTuiMetadataRepository()

    def run(self) -> TuiMetadataRevalidationReport:
        """Validate all statuses in primary-key order and return a dry-run report."""

        rows: list[TuiMetadataRevalidationRow] = []
        status_counts: dict[str, int] = {}
        valid_count = 0
        invalid_count = 0
        error_count = 0

        records = TuiMetadataRegistryORM._default_manager.all().order_by("pk")
        for record in records:
            status = str(record.status or "")
            status_counts[status] = status_counts.get(status, 0) + 1
            try:
                normalized = self.repository.validate_and_normalize_runtime_payload(
                    copy.deepcopy(dict(record.payload or {}))
                )
            except (TuiMetadataValidationError, TypeError, ValueError, KeyError) as exc:
                invalid_count += 1
                rows.append(
                    TuiMetadataRevalidationRow(
                        registry_id=int(record.pk),
                        registry_key=str(record.registry_key or ""),
                        status=status,
                        version=str(record.version or ""),
                        valid=False,
                        reason_code="payload_contract_invalid",
                        error_type=type(exc).__name__,
                        normalized_hash=None,
                        recommendation=INVALID_ROW_RECOMMENDATION,
                    )
                )
                continue
            except Exception as exc:  # pragma: no cover - defensive per-row isolation.
                error_count += 1
                logger.warning(
                    "TUI metadata registry row revalidation failed",
                    extra={
                        "event": "tui_metadata_revalidation_error",
                        "registry_id": record.pk,
                        "registry_key": record.registry_key,
                        "exception_type": type(exc).__name__,
                    },
                )
                rows.append(
                    TuiMetadataRevalidationRow(
                        registry_id=int(record.pk),
                        registry_key=str(record.registry_key or ""),
                        status=status,
                        version=str(record.version or ""),
                        valid=False,
                        reason_code="revalidation_error",
                        error_type=type(exc).__name__,
                        normalized_hash=None,
                        recommendation=ERROR_ROW_RECOMMENDATION,
                    )
                )
                continue

            valid_count += 1
            rows.append(
                TuiMetadataRevalidationRow(
                    registry_id=int(record.pk),
                    registry_key=str(record.registry_key or ""),
                    status=status,
                    version=str(record.version or ""),
                    valid=True,
                    reason_code=None,
                    error_type=None,
                    normalized_hash=self.repository.payload_hash(normalized),
                    recommendation=VALID_ROW_RECOMMENDATION,
                )
            )

        total_count = len(rows)
        if total_count == 0:
            outcome: RevalidationOutcome = "noop"
            recommendation: RevalidationRecommendation = "no_rows_to_revalidate"
        elif error_count:
            outcome = "failed"
            recommendation = "investigate_revalidation_errors_before_repair_or_archive"
        elif invalid_count:
            outcome = "partial"
            recommendation = "repair_or_archive_invalid_rows_before_publish"
        else:
            outcome = "success"
            recommendation = "no_action_required"

        return TuiMetadataRevalidationReport(
            outcome=outcome,
            recommendation=recommendation,
            dry_run=True,
            writes_performed=0,
            total_count=total_count,
            valid_count=valid_count,
            invalid_count=invalid_count,
            error_count=error_count,
            status_counts=status_counts,
            rows=tuple(rows),
        )
