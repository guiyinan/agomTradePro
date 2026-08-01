"""Config center domain entities."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any

from shared.domain.reliability import ReliabilityContract, ReliabilityStatus


class DecisionRuntimeStatus(str, Enum):
    """Operational states controlling publication of decision conclusions."""

    ACTIVE = "active"
    MAINTENANCE = "maintenance"
    VALIDATING = "validating"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class DecisionRuntimeState:
    """Persisted global gate for all decision-facing interfaces."""

    status: DecisionRuntimeStatus = DecisionRuntimeStatus.ACTIVE
    reason: str = ""
    changed_at: datetime | None = None
    changed_by: str = ""
    release_ref: str = ""
    expected_resume_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.status is not DecisionRuntimeStatus.ACTIVE and not self.reason.strip():
            raise ValueError("Non-active decision runtime state requires a reason")
        for field_name, value in (
            ("changed_at", self.changed_at),
            ("expected_resume_at", self.expected_resume_at),
        ):
            if value is not None and value.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware")

    @property
    def must_not_use_for_decision(self) -> bool:
        """Return whether every decision surface must fail closed."""

        return self.status is not DecisionRuntimeStatus.ACTIVE

    @property
    def block_reason_code(self) -> str:
        """Return a stable machine-readable gate reason."""

        if not self.must_not_use_for_decision:
            return ""
        return f"decision_runtime_{self.status.value}"

    def to_reliability_contract(self) -> ReliabilityContract:
        """Convert the runtime gate to the shared reliability contract."""

        if self.status is DecisionRuntimeStatus.ACTIVE:
            if self.changed_at is None:
                raise ValueError("Active persisted runtime state requires changed_at")
            return ReliabilityContract.fresh(
                observed_at=self.changed_at,
                fetched_at=self.changed_at,
                source="config_center",
            )
        reliability_status = (
            ReliabilityStatus.MAINTENANCE
            if self.status
            in {
                DecisionRuntimeStatus.MAINTENANCE,
                DecisionRuntimeStatus.VALIDATING,
            }
            else ReliabilityStatus.FAILED
        )
        return ReliabilityContract.blocked(
            status=reliability_status,
            source="config_center",
            reason_code=self.block_reason_code,
            reason=self.reason,
            observed_at=self.changed_at,
            fetched_at=self.changed_at,
        )

    def to_dict(self) -> dict[str, object]:
        """Serialize the runtime gate for APIs and readiness probes."""

        return {
            "status": self.status.value,
            "reason": self.reason,
            "changed_at": self.changed_at.isoformat() if self.changed_at else None,
            "changed_by": self.changed_by,
            "release_ref": self.release_ref,
            "expected_resume_at": (
                self.expected_resume_at.isoformat() if self.expected_resume_at else None
            ),
            "must_not_use_for_decision": self.must_not_use_for_decision,
            "block_reason_code": self.block_reason_code,
        }


@dataclass(frozen=True)
class QlibRuntimeConfig:
    enabled: bool
    provider_uri: str
    region: str
    model_root: str
    default_universe: str
    default_feature_set_id: str
    default_label_id: str
    train_queue_name: str
    infer_queue_name: str
    allow_auto_activate: bool
    configured: bool
    validation_errors: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class QlibTrainingProfile:
    profile_key: str
    name: str
    model_name: str
    model_type: str
    universe: str
    start_date: date | None
    end_date: date | None
    feature_set_id: str
    label_id: str
    learning_rate: float | None
    epochs: int | None
    model_params: dict[str, Any]
    extra_train_config: dict[str, Any]
    activate_after_train: bool
    is_active: bool
    notes: str


@dataclass(frozen=True)
class QlibTrainingRun:
    run_id: str
    status: str
    model_name: str
    model_type: str
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    resolved_train_config: dict[str, Any]
    result_metrics: dict[str, Any]
    error_message: str


@dataclass(frozen=True)
class AlphaUniverseConfig:
    """Config-center owned Alpha/Qlib universe definition."""

    universe_id: str
    name: str
    source_type: str
    stock_codes: tuple[str, ...] = ()
    filters: dict[str, Any] = field(default_factory=dict)
    is_active: bool = True
    description: str = ""

    def __post_init__(self) -> None:
        if not self.universe_id:
            raise ValueError("AlphaUniverseConfig.universe_id cannot be empty")
        if not self.name:
            raise ValueError("AlphaUniverseConfig.name cannot be empty")
        if self.source_type not in {
            "manual",
            "csv",
            "data_center_filter",
            "tushare_index",
        }:
            raise ValueError(f"Unsupported Alpha universe source_type: {self.source_type}")
        if self.source_type == "tushare_index":
            index_code = str(self.filters.get("index_code") or "").strip().upper()
            if re.fullmatch(r"\d{6}\.(?:SH|SZ|BJ)", index_code) is None:
                raise ValueError("Tushare index universe requires a valid filters.index_code")

    def to_dict(self) -> dict[str, Any]:
        return {
            "universe_id": self.universe_id,
            "name": self.name,
            "source_type": self.source_type,
            "stock_codes": list(self.stock_codes),
            "filters": dict(self.filters),
            "is_active": self.is_active,
            "description": self.description,
        }
