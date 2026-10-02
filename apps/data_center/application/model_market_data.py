"""Data Center owns model-market routing, freshness and source consistency."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import date
from threading import Lock

from apps.data_center.application.model_history_preparation import (
    ModelHistoryAuditEvidencePort,
    ModelHistoryFetchAuditPort,
    ModelHistoryFetchAuditResult,
    ModelHistoryPreparationAuditPort,
    ModelHistoryPreparedFetch,
    ModelHistoryReferenceSnapshot,
)
from apps.data_center.application.model_market_data_preparation import ModelMarketDataPreparation
from apps.data_center.application.model_market_data_reads import ModelMarketDataReads
from apps.data_center.application.model_market_data_state import ModelMarketRoute
from apps.data_center.application.model_market_history_lineage import ModelMarketHistoryLineage
from apps.data_center.domain.entities import RawAuditReference
from apps.data_center.domain.model_market_data import ModelDailyBar
from core.exceptions import DataFetchError

__all__ = [
    "ModelHistoryAuditEvidencePort",
    "ModelHistoryFetchAuditPort",
    "ModelHistoryFetchAuditResult",
    "ModelHistoryPreparedFetch",
    "ModelHistoryPreparationAuditPort",
    "ModelHistoryReferenceSnapshot",
    "ModelMarketDataService",
    "ModelMarketRoute",
]


class ModelMarketDataService(
    ModelMarketDataPreparation, ModelMarketDataReads, ModelMarketHistoryLineage
):
    """Expose normalized inputs while keeping all source decisions in Data Center."""

    def __init__(
        self,
        routes: tuple[ModelMarketRoute, ...],
        *,
        enable_failover: bool,
        tolerance: float,
        reference_history: Callable[[str, date, date], tuple[ModelDailyBar, ...]],
        reference_history_snapshot: (
            Callable[[tuple[str, ...], date, date], ModelHistoryReferenceSnapshot] | None
        ) = None,
        history_fetch_audit: ModelHistoryFetchAuditPort | None = None,
        max_per_asset_preparation_assets: int | None = None,
    ) -> None:
        if not math.isfinite(tolerance) or not 0 <= tolerance <= 1:
            raise ValueError("Invalid source consistency tolerance")
        if max_per_asset_preparation_assets is not None and (
            isinstance(max_per_asset_preparation_assets, bool)
            or not isinstance(max_per_asset_preparation_assets, int)
            or max_per_asset_preparation_assets <= 0
        ):
            raise ValueError("Per-asset model-history preparation limit must be positive")
        self._routes = routes if enable_failover else routes[:1]
        self._tolerance = tolerance
        self._reference_history = reference_history
        self._reference_history_snapshot = reference_history_snapshot
        self._history_fetch_audit = history_fetch_audit
        self._max_per_asset_preparation_assets = max_per_asset_preparation_assets
        self._history_audit_references: list[RawAuditReference] = []
        self._history_row_references: dict[tuple[str, date, str], RawAuditReference] = {}
        self._explicit_prepared_rows: dict[tuple[str, date, date], tuple[ModelDailyBar, ...]] = {}
        self._preparation_reference_rows: dict[
            tuple[str, date, date], tuple[ModelDailyBar, ...]
        ] = {}
        self._preparation_reference_snapshots: dict[
            tuple[str, date, date], ModelHistoryReferenceSnapshot
        ] = {}
        self._explicit_preparation_errors: dict[tuple[str, date, date], DataFetchError] = {}
        self._preparation_active = False
        self._calendar_cache: dict[tuple[date, date], tuple[date, ...]] = {}
        self._calendar_lock = Lock()
        self._disabled: dict[str, DataFetchError] = {}
        self._lock = Lock()
