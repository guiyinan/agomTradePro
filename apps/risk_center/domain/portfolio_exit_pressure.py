"""Pure, source-bound portfolio exit-pressure assessment for Risk Center."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from apps.risk_center.domain.portfolio_risk_serialization import portfolio_risk_content_hash
from apps.risk_center.domain.portfolio_risk_sources import PortfolioRiskSourceEvidence
from apps.risk_center.domain.scenarios import (
    ScenarioImpact,
    ScenarioRevision,
    ScenarioRevisionStatus,
)


class ExitPressureStatus(StrEnum):
    """Explainability state for a hypothetical exit-pressure result."""

    EXITABLE = "exitable"
    LIMITED = "limited"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


def _require_nonblank(field_name: str, value: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} is required")


def _require_unique_nonblank(field_name: str, values: tuple[str, ...]) -> None:
    if type(values) is not tuple:
        raise ValueError(f"{field_name} cannot contain blank values")
    for value in values:
        _require_nonblank(field_name, value)
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must be unique")


def _require_sha256(field_name: str, value: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a SHA-256 digest")


def _require_aware(field_name: str, value: datetime) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_finite_nonnegative(field_name: str, value: Decimal) -> None:
    if type(value) is not Decimal or not value.is_finite() or value < 0:
        raise ValueError(f"{field_name} must be a finite non-negative decimal")


@dataclass(frozen=True)
class ExitCapacityWindow:
    """One scenario-bound session window of additional hypothetical sell capacity.

    ``exitable_quantity`` is a capacity estimate, not a fill. A missing value
    means unknown; zero is a known no-exit result and must carry a reason.
    """

    session_date: date
    exitable_quantity: Decimal | None
    quantity_unit: str
    reason_codes: tuple[str, ...] = ()
    source_evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.session_date) is not date:
            raise ValueError("capacity session_date must be a date")
        _require_nonblank("capacity quantity_unit", self.quantity_unit)
        _require_unique_nonblank("capacity reason_codes", self.reason_codes)
        _require_unique_nonblank("capacity source_evidence_ids", self.source_evidence_ids)
        if self.exitable_quantity is not None:
            _require_finite_nonnegative("capacity exitable_quantity", self.exitable_quantity)
            if not self.source_evidence_ids:
                raise ValueError("known capacity requires source evidence")
            if self.exitable_quantity == 0 and not self.reason_codes:
                raise ValueError("known zero capacity requires an explanatory reason")
        elif not self.reason_codes:
            raise ValueError("unknown capacity requires an explanatory reason")


@dataclass(frozen=True)
class ExitPressurePosition:
    """A current position plus ordered stress-window capacity inputs."""

    asset_code: str
    quantity: Decimal
    quantity_unit: str
    market_value: Decimal
    pending_sell_quantity: Decimal
    capacity_windows: tuple[ExitCapacityWindow, ...]

    def __post_init__(self) -> None:
        _require_nonblank("exit-pressure asset_code", self.asset_code)
        _require_nonblank("exit-pressure quantity_unit", self.quantity_unit)
        _require_finite_nonnegative("exit-pressure quantity", self.quantity)
        _require_finite_nonnegative("exit-pressure market_value", self.market_value)
        _require_finite_nonnegative(
            "exit-pressure pending_sell_quantity", self.pending_sell_quantity
        )
        if self.quantity == 0 or self.market_value == 0:
            raise ValueError("exit-pressure positions require positive quantity and market value")
        if self.pending_sell_quantity > self.quantity:
            raise ValueError("pending sell quantity cannot exceed current position quantity")
        if type(self.capacity_windows) is not tuple or any(
            type(item) is not ExitCapacityWindow for item in self.capacity_windows
        ):
            raise TypeError("capacity_windows must be a tuple of ExitCapacityWindow")
        if any(item.quantity_unit != self.quantity_unit for item in self.capacity_windows):
            raise ValueError("capacity quantity_unit mismatch")
        session_dates = tuple(item.session_date for item in self.capacity_windows)
        if session_dates != tuple(sorted(session_dates)):
            raise ValueError("capacity windows must be ordered by session_date")
        if len(session_dates) != len(set(session_dates)):
            raise ValueError("capacity windows must have unique session_date values")


@dataclass(frozen=True)
class PortfolioExitPressureInput:
    """Immutable link between one approved Scenario run and account projection."""

    scenario_revision: ScenarioRevision
    scenario_impact: ScenarioImpact
    portfolio_snapshot_id: str
    portfolio_snapshot_hash: str
    as_of_time: datetime
    allocation_policy_version: str
    code_version: str
    scenario_market_data_hash: str
    source_evidence: tuple[PortfolioRiskSourceEvidence, ...]
    source_evidence_ids: tuple[str, ...]
    positions: tuple[ExitPressurePosition, ...]

    def __post_init__(self) -> None:
        if type(self.scenario_revision) is not ScenarioRevision:
            raise TypeError("scenario_revision must be a ScenarioRevision")
        if type(self.scenario_impact) is not ScenarioImpact:
            raise TypeError("scenario_impact must be a ScenarioImpact")
        _require_nonblank("portfolio_snapshot_id", self.portfolio_snapshot_id)
        _require_sha256("portfolio_snapshot_hash", self.portfolio_snapshot_hash)
        _require_sha256("scenario revision content_hash", self.scenario_revision.content_hash)
        _require_sha256("scenario impact result_hash", self.scenario_impact.result_hash)
        _require_aware("PortfolioExitPressureInput.as_of_time", self.as_of_time)
        _require_nonblank("allocation_policy_version", self.allocation_policy_version)
        _require_nonblank("code_version", self.code_version)
        _require_sha256("scenario_market_data_hash", self.scenario_market_data_hash)
        if type(self.source_evidence) is not tuple or any(
            type(item) is not PortfolioRiskSourceEvidence for item in self.source_evidence
        ):
            raise TypeError("source_evidence must be a tuple of PortfolioRiskSourceEvidence")
        evidence_identities = tuple(
            (item.source_id, item.source_record_id) for item in self.source_evidence
        )
        if len(evidence_identities) != len(set(evidence_identities)):
            raise ValueError("source_evidence must have unique source and record identities")
        if any(item.decision_cutoff != self.as_of_time for item in self.source_evidence):
            raise ValueError("source evidence must use the exact pressure cutoff")
        _require_unique_nonblank("source_evidence_ids", self.source_evidence_ids)
        if type(self.positions) is not tuple or any(
            type(item) is not ExitPressurePosition for item in self.positions
        ):
            raise TypeError("positions must be a tuple of ExitPressurePosition")
        asset_codes = tuple(item.asset_code for item in self.positions)
        if len(asset_codes) != len(set(asset_codes)):
            raise ValueError("exit-pressure positions must have unique asset_code values")


@dataclass(frozen=True)
class ExitPressureFinding:
    """Explain one asset's stress-window exit capacity without posting a fill."""

    asset_code: str
    quantity_unit: str
    status: ExitPressureStatus
    current_quantity: Decimal
    current_market_value: Decimal
    pending_sell_quantity: Decimal
    unreleased_exposure_quantity: Decimal
    unreleased_exposure_market_value: Decimal
    hypothetical_exitable_quantity: Decimal
    stress_window_residual_quantity: Decimal | None
    exit_sessions_required: int | None
    reason_codes: tuple[str, ...]
    source_evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class PortfolioExitPressureAssessment:
    """Scenario-linked exit constraints and deterministic result digest."""

    scenario_revision_id: str
    scenario_revision_hash: str
    portfolio_snapshot_id: str
    portfolio_snapshot_hash: str
    as_of_time: datetime
    allocation_policy_version: str
    code_version: str
    scenario_market_data_hash: str
    source_manifest_hash: str
    scenario_result_hash: str
    status: ExitPressureStatus
    findings: tuple[ExitPressureFinding, ...]
    source_evidence_ids: tuple[str, ...]
    result_hash: str


def _ordered_unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _assess_position(
    position: ExitPressurePosition,
) -> tuple[ExitPressureFinding, tuple[str, ...]]:
    reason_codes: list[str] = []
    source_evidence_ids: list[str] = []
    known_capacity = Decimal("0")
    exit_sessions_required: int | None = None
    unknown_capacity = False

    for session_number, window in enumerate(position.capacity_windows, start=1):
        reason_codes.extend(window.reason_codes)
        source_evidence_ids.extend(window.source_evidence_ids)
        if window.exitable_quantity is None:
            unknown_capacity = True
            break
        remaining_quantity = position.quantity - known_capacity
        known_capacity += min(window.exitable_quantity, remaining_quantity)
        if known_capacity >= position.quantity:
            exit_sessions_required = session_number
            break

    if not position.capacity_windows:
        status = ExitPressureStatus.UNKNOWN
        reason_codes.append("exit_capacity_window_missing")
        residual_quantity = None
    elif unknown_capacity:
        status = ExitPressureStatus.UNKNOWN
        residual_quantity = None
    elif known_capacity >= position.quantity:
        status = ExitPressureStatus.EXITABLE
        residual_quantity = Decimal("0")
    elif known_capacity == 0:
        status = ExitPressureStatus.BLOCKED
        residual_quantity = position.quantity
    else:
        status = ExitPressureStatus.LIMITED
        residual_quantity = position.quantity - known_capacity
        reason_codes.append("stress_capacity_below_position")

    finding = ExitPressureFinding(
        asset_code=position.asset_code,
        quantity_unit=position.quantity_unit,
        status=status,
        current_quantity=position.quantity,
        current_market_value=position.market_value,
        pending_sell_quantity=position.pending_sell_quantity,
        unreleased_exposure_quantity=position.quantity,
        unreleased_exposure_market_value=position.market_value,
        hypothetical_exitable_quantity=known_capacity,
        stress_window_residual_quantity=residual_quantity,
        exit_sessions_required=exit_sessions_required,
        reason_codes=_ordered_unique(tuple(reason_codes)),
        source_evidence_ids=_ordered_unique(tuple(source_evidence_ids)),
    )
    return finding, tuple(source_evidence_ids)


def _overall_status(findings: tuple[ExitPressureFinding, ...]) -> ExitPressureStatus:
    if not findings or any(item.status is ExitPressureStatus.UNKNOWN for item in findings):
        return ExitPressureStatus.UNKNOWN
    if any(item.status is ExitPressureStatus.BLOCKED for item in findings):
        return ExitPressureStatus.BLOCKED
    if any(item.status is ExitPressureStatus.LIMITED for item in findings):
        return ExitPressureStatus.LIMITED
    return ExitPressureStatus.EXITABLE


def _finding_hash_payload(finding: ExitPressureFinding) -> dict[str, object]:
    return {
        "asset_code": finding.asset_code,
        "quantity_unit": finding.quantity_unit,
        "status": finding.status.value,
        "current_quantity": finding.current_quantity,
        "current_market_value": finding.current_market_value,
        "pending_sell_quantity": finding.pending_sell_quantity,
        "unreleased_exposure_quantity": finding.unreleased_exposure_quantity,
        "unreleased_exposure_market_value": finding.unreleased_exposure_market_value,
        "hypothetical_exitable_quantity": finding.hypothetical_exitable_quantity,
        "stress_window_residual_quantity": finding.stress_window_residual_quantity,
        "exit_sessions_required": finding.exit_sessions_required,
        "reason_codes": finding.reason_codes,
        "source_evidence_ids": finding.source_evidence_ids,
    }


def evaluate_portfolio_exit_pressure(
    request: PortfolioExitPressureInput,
) -> PortfolioExitPressureAssessment:
    """Evaluate stress-window exit constraints without mutating portfolio facts.

    The result reports hypothetical capacity only. Pending sells remain part of
    current exposure until an actual fill changes the owner projection; a
    Scenario result never creates cash, releases a reservation, or places orders.
    """

    revision = request.scenario_revision
    impact = request.scenario_impact
    if revision.status not in {ScenarioRevisionStatus.APPROVED, ScenarioRevisionStatus.ACTIVE}:
        raise ValueError("only an approved scenario revision can produce pressure")
    if impact.scenario_revision_id != revision.revision_id:
        raise ValueError("scenario revision mismatch between revision and impact")

    assessed = tuple(_assess_position(item) for item in request.positions)
    findings = tuple(item[0] for item in assessed)
    source_evidence_ids = _ordered_unique(
        request.source_evidence_ids + tuple(source_id for item in assessed for source_id in item[1])
    )
    status = _overall_status(findings)
    source_manifest_hash = portfolio_risk_content_hash(
        {
            "source_evidence": request.source_evidence,
            "scenario_market_data_hash": request.scenario_market_data_hash,
        }
    )
    result_hash = portfolio_risk_content_hash(
        {
            "scenario_revision_id": revision.revision_id,
            "scenario_revision_hash": revision.content_hash,
            "portfolio_snapshot_id": request.portfolio_snapshot_id,
            "portfolio_snapshot_hash": request.portfolio_snapshot_hash,
            "as_of_time": request.as_of_time,
            "allocation_policy_version": request.allocation_policy_version,
            "code_version": request.code_version,
            "scenario_market_data_hash": request.scenario_market_data_hash,
            "source_manifest_hash": source_manifest_hash,
            "scenario_result_hash": impact.result_hash,
            "status": status.value,
            "source_evidence_ids": source_evidence_ids,
            "findings": tuple(_finding_hash_payload(item) for item in findings),
        }
    )
    return PortfolioExitPressureAssessment(
        scenario_revision_id=revision.revision_id,
        scenario_revision_hash=revision.content_hash,
        portfolio_snapshot_id=request.portfolio_snapshot_id,
        portfolio_snapshot_hash=request.portfolio_snapshot_hash,
        as_of_time=request.as_of_time,
        allocation_policy_version=request.allocation_policy_version,
        code_version=request.code_version,
        scenario_market_data_hash=request.scenario_market_data_hash,
        source_manifest_hash=source_manifest_hash,
        scenario_result_hash=impact.result_hash,
        status=status,
        findings=findings,
        source_evidence_ids=source_evidence_ids,
        result_hash=result_hash,
    )


__all__ = [
    "ExitCapacityWindow",
    "ExitPressureFinding",
    "ExitPressurePosition",
    "ExitPressureStatus",
    "PortfolioExitPressureAssessment",
    "PortfolioExitPressureInput",
    "evaluate_portfolio_exit_pressure",
]
