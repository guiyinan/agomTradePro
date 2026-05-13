"""Config center domain entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


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

