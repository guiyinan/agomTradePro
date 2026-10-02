"""Shared typed state contract for the model-market application mixins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from threading import Lock
from typing import TypeVar

from apps.data_center.application.model_history_preparation import (
    ModelHistoryFetchAuditPort,
    ModelHistoryPreparationAuditPort,
    ModelHistoryPreparedFetch,
    ModelHistoryRawAuditBinding,
    ModelHistoryReferenceSnapshot,
)
from apps.data_center.domain.entities import RawAuditReference
from apps.data_center.domain.model_market_data import (
    ModelDailyBar,
    ModelMarketDataPort,
)
from core.exceptions import DataFetchError

_T = TypeVar("_T")


@dataclass(frozen=True)
class ModelMarketRoute:
    """One configured, capability-qualified Data Center provider route."""

    name: str
    port: ModelMarketDataPort
    requires_reference: bool = False
    provider_id: int | None = None


class ModelMarketDataServiceState(ABC):
    """Type the state and cross-mixin calls owned by the model-market façade."""

    _routes: tuple[ModelMarketRoute, ...]
    _tolerance: float
    _reference_history: Callable[[str, date, date], tuple[ModelDailyBar, ...]]
    _reference_history_snapshot: (
        Callable[[tuple[str, ...], date, date], ModelHistoryReferenceSnapshot] | None
    )
    _history_fetch_audit: ModelHistoryFetchAuditPort | None
    _max_per_asset_preparation_assets: int | None
    _history_audit_references: list[ModelHistoryRawAuditBinding]
    _history_row_references: dict[tuple[str, date, str], ModelHistoryRawAuditBinding]
    _explicit_prepared_rows: dict[tuple[str, date, date], tuple[ModelDailyBar, ...]]
    _preparation_reference_rows: dict[tuple[str, date, date], tuple[ModelDailyBar, ...]]
    _preparation_reference_snapshots: dict[tuple[str, date, date], ModelHistoryReferenceSnapshot]
    _explicit_preparation_errors: dict[tuple[str, date, date], DataFetchError]
    _preparation_active: bool
    _calendar_cache: dict[tuple[date, date], tuple[date, ...]]
    _calendar_lock: Lock
    _disabled: dict[str, DataFetchError]
    _lock: Lock

    @abstractmethod
    def _history(
        self,
        asset_code: str,
        start_date: date,
        end_date: date,
        *,
        is_index: bool,
        audit_fetch: bool = False,
        skip_routes: frozenset[str] = frozenset(),
        allow_per_asset_fetch: bool = False,
    ) -> tuple[ModelDailyBar, ...]:
        raise NotImplementedError

    @abstractmethod
    def _record_history_fetch_success(
        self,
        route: ModelMarketRoute,
        rows: tuple[ModelDailyBar, ...],
        *,
        asset_code: str,
        start_date: date,
        end_date: date,
        cache_port: ModelHistoryPreparationAuditPort | None = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def _record_history_fetch_failure(
        self,
        route: ModelMarketRoute,
        *,
        asset_codes: tuple[str, ...],
        start_date: date,
        end_date: date,
        error: BaseException,
        request_details: Mapping[str, object] | None = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def _persist_prepared_fetch(
        self,
        route: ModelMarketRoute,
        fetch: ModelHistoryPreparedFetch,
        *,
        requested_asset_codes: tuple[str, ...],
        snapshot: ModelHistoryReferenceSnapshot,
    ) -> ModelHistoryRawAuditBinding:
        raise NotImplementedError

    @abstractmethod
    def _validate_prepared_fetch(
        self,
        route: ModelMarketRoute,
        fetch: ModelHistoryPreparedFetch,
        snapshot: ModelHistoryReferenceSnapshot,
    ) -> None:
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def _safe_request_details(
        request_details: Mapping[str, object] | None,
    ) -> Mapping[str, object]:
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def _model_reference_rows(
        asset_code: str, snapshot: ModelHistoryReferenceSnapshot
    ) -> tuple[ModelDailyBar, ...]:
        raise NotImplementedError

    @abstractmethod
    def _reference_snapshot_for(
        self, asset_codes: tuple[str, ...], start_date: date, end_date: date
    ) -> ModelHistoryReferenceSnapshot:
        raise NotImplementedError

    @abstractmethod
    def _reference_history_for(
        self, asset_code: str, start_date: date, end_date: date
    ) -> tuple[ModelDailyBar, ...]:
        raise NotImplementedError

    @abstractmethod
    def _covering_reference_snapshot(
        self, asset_code: str, start_date: date, end_date: date
    ) -> ModelHistoryReferenceSnapshot | None:
        raise NotImplementedError

    @abstractmethod
    def _bind_history_rows(
        self, rows: tuple[ModelDailyBar, ...], reference: ModelHistoryRawAuditBinding
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def _extend_history_audit_references(
        self, references: tuple[ModelHistoryRawAuditBinding, ...]
    ) -> None:
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def _unique_history_audit_references(
        references: list[ModelHistoryRawAuditBinding],
    ) -> tuple[ModelHistoryRawAuditBinding, ...]:
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def _validate(
        rows: tuple[ModelDailyBar, ...],
        asset_code: str,
        start: date,
        end: date,
        *,
        is_index: bool,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def _check_consistency(
        self,
        reference: tuple[ModelDailyBar, ...],
        candidate: tuple[ModelDailyBar, ...],
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def _lookup(self, read: Callable[[ModelMarketDataPort], tuple[_T, ...]]) -> tuple[_T, ...]:
        raise NotImplementedError

    @abstractmethod
    def _disable_quota(self, route: ModelMarketRoute, exc: DataFetchError) -> None:
        raise NotImplementedError

    @abstractmethod
    def model_history_audit_references(
        self, rows: tuple[ModelDailyBar, ...]
    ) -> tuple[RawAuditReference, ...]:
        raise NotImplementedError

    @abstractmethod
    def take_model_history_audit_references(self) -> tuple[RawAuditReference, ...]:
        raise NotImplementedError

    @abstractmethod
    def model_history_audit_bindings(
        self, rows: tuple[ModelDailyBar, ...]
    ) -> tuple[ModelHistoryRawAuditBinding, ...]:
        raise NotImplementedError

    @abstractmethod
    def take_model_history_audit_bindings(self) -> tuple[ModelHistoryRawAuditBinding, ...]:
        raise NotImplementedError

    @abstractmethod
    def prepare_stock_history(
        self, asset_codes: tuple[str, ...], start_date: date, end_date: date
    ) -> None:
        raise NotImplementedError
