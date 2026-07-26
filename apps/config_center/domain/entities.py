"""Config center domain entities."""

from __future__ import annotations

import re
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
