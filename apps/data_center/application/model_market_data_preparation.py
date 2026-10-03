"""Explicit, audited model-history preparation orchestration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from apps.data_center.application.model_history_preparation import (
    ModelHistoryPreparationAuditPort,
    ModelHistoryPreparedFetch,
    ModelHistoryRawAuditBinding,
    ModelHistorySingleFetchAuditPort,
)
from apps.data_center.application.model_market_data_state import (
    ModelMarketDataServiceState,
    ModelMarketRoute,
)
from apps.data_center.domain.entities import RawAuditReference
from apps.data_center.domain.model_market_data import (
    ModelDailyBar,
    ModelHistoryPreparationPort,
)
from core.exceptions import DataFetchError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ModelMarketRouteCapability:
    """Read-only audited capability view of one configured model-market route."""

    route: str
    batch_preparation: bool
    audited_per_asset_fetch: bool
    provider_identity: bool

    def to_dict(self) -> dict[str, object]:
        """Return the stable JSON-safe capability payload used in error details."""

        return {
            "route": self.route,
            "batch_preparation": self.batch_preparation,
            "audited_per_asset_fetch": self.audited_per_asset_fetch,
            "provider_identity": self.provider_identity,
        }


@dataclass(frozen=True, slots=True)
class ModelMarketBulkPreparationGate:
    """Fail-closed capability verdict for one explicit preparation scope."""

    requested_count: int
    per_asset_preparation_limit: int | None
    per_asset_scope_allowed: bool
    preferred_route: str | None
    preferred_route_is_batch: bool
    route_capabilities: tuple[ModelMarketRouteCapability, ...]
    non_auditable_routes: tuple[str, ...]

    @property
    def allows_requested_scope(self) -> bool:
        """Return whether the requested scope can be prepared without fallback loss."""

        return self.preferred_route_is_batch or self.per_asset_scope_allowed


def evaluate_model_market_bulk_preparation(
    *,
    routes: tuple[ModelMarketRoute, ...],
    requested_count: int,
    max_per_asset_preparation_assets: int | None,
) -> ModelMarketBulkPreparationGate:
    """Evaluate the audited bulk-preparation gate without any provider I/O.

    This pure capability check is shared by the explicit preparation
    orchestration and the read-only full-market publication preflight so both
    enforce exactly one rule with the same stable error codes.
    """

    route_capabilities: list[ModelMarketRouteCapability] = []
    non_auditable_routes: list[str] = []
    for route in routes:
        batch_capable = isinstance(route.port, ModelHistoryPreparationPort) and isinstance(
            route.port, ModelHistoryPreparationAuditPort
        )
        single_fetch_capable = isinstance(route.port, ModelHistorySingleFetchAuditPort)
        route_capabilities.append(
            ModelMarketRouteCapability(
                route=route.name,
                batch_preparation=batch_capable,
                audited_per_asset_fetch=single_fetch_capable,
                provider_identity=route.provider_id is not None,
            )
        )
        if not batch_capable and not single_fetch_capable:
            non_auditable_routes.append(route.name)
        if (batch_capable or single_fetch_capable) and route.provider_id is None:
            raise DataFetchError(
                "Audited model-history route lacks configured provider identity",
                code="MODEL_MARKET_AUDIT_PROVIDER_ID_MISSING",
                details={"available_routes": [item.to_dict() for item in route_capabilities]},
            )
    per_asset_scope_allowed = (
        max_per_asset_preparation_assets is not None
        and requested_count <= max_per_asset_preparation_assets
    )
    preferred_route = routes[0] if routes else None
    preferred_route_is_batch = preferred_route is not None and (
        isinstance(preferred_route.port, ModelHistoryPreparationPort)
        and isinstance(preferred_route.port, ModelHistoryPreparationAuditPort)
    )
    gate = ModelMarketBulkPreparationGate(
        requested_count=requested_count,
        per_asset_preparation_limit=max_per_asset_preparation_assets,
        per_asset_scope_allowed=per_asset_scope_allowed,
        preferred_route=(preferred_route.name if preferred_route is not None else None),
        preferred_route_is_batch=preferred_route_is_batch,
        route_capabilities=tuple(route_capabilities),
        non_auditable_routes=tuple(sorted(non_auditable_routes)),
    )
    if not gate.allows_requested_scope:
        raise DataFetchError(
            "The preferred route must support audited batch preparation for this scope",
            code="MODEL_MARKET_BULK_PREPARATION_REQUIRED",
            details={
                "requested_count": requested_count,
                "available_routes": [item.to_dict() for item in route_capabilities],
                "non_auditable_routes": gate.non_auditable_routes,
                "per_asset_preparation_limit": max_per_asset_preparation_assets,
            },
        )
    return gate


class ModelMarketDataPreparation(ModelMarketDataServiceState):
    def stock_history(
        self, asset_code: str, start_date: date, end_date: date
    ) -> tuple[ModelDailyBar, ...]:
        """Read raw prices and factors together; stale results continue failover."""
        key = (asset_code, start_date, end_date)
        prepared_error = self._explicit_preparation_errors.get(key)
        if prepared_error is not None:
            raise prepared_error
        prepared = self._explicit_prepared_rows.get(key)
        if prepared is not None:
            return prepared
        return self._history(asset_code, start_date, end_date, is_index=False)

    def prepare_stock_history(
        self, asset_codes: tuple[str, ...], start_date: date, end_date: date
    ) -> None:
        """Prepare explicitly requested prices with audited batches and bounded fallback."""
        normalized_asset_codes = tuple(sorted(set(asset_codes)))
        if not normalized_asset_codes:
            return
        if start_date > end_date:
            raise ValueError("History start_date must not exceed end_date")
        if self._history_fetch_audit is None:
            raise DataFetchError(
                "Explicit model history preparation requires an audited writer",
                code="MODEL_MARKET_AUDIT_EVIDENCE_MISSING",
            )
        reference_snapshot_factory = self._reference_history_snapshot
        if reference_snapshot_factory is None:
            raise DataFetchError(
                "Explicit model history preparation requires a batched reference snapshot",
                code="MODEL_MARKET_REFERENCE_SNAPSHOT_REQUIRED",
            )

        gate = evaluate_model_market_bulk_preparation(
            routes=self._routes,
            requested_count=len(normalized_asset_codes),
            max_per_asset_preparation_assets=self._max_per_asset_preparation_assets,
        )
        per_asset_scope_allowed = gate.per_asset_scope_allowed
        preferred_route_is_batch = gate.preferred_route_is_batch

        if not self._preparation_active:
            self._explicit_prepared_rows.clear()
            self._explicit_preparation_errors.clear()
            self._history_audit_references.clear()
            self._history_row_references.clear()
            self._preparation_reference_rows.clear()
            self._preparation_reference_snapshots.clear()
            self._preparation_active = True

        snapshot = reference_snapshot_factory(normalized_asset_codes, start_date, end_date)
        if (
            snapshot.asset_codes != normalized_asset_codes
            or snapshot.start_date != start_date
            or snapshot.end_date != end_date
        ):
            raise DataFetchError(
                "Model history reference snapshot does not match the requested scope",
                code="MODEL_MARKET_REFERENCE_SNAPSHOT_SCOPE_INVALID",
            )
        for asset_code in normalized_asset_codes:
            key = (asset_code, start_date, end_date)
            asset_snapshot = snapshot.subset((asset_code,), start_date, end_date)
            self._preparation_reference_snapshots[key] = asset_snapshot
            self._preparation_reference_rows[key] = self._model_reference_rows(
                asset_code, asset_snapshot
            )

        failed_preparation_routes: set[str] = set()
        preparation_failures: list[DataFetchError] = []
        unresolved_codes = set(normalized_asset_codes)
        for route in self._routes:
            if route.name in self._disabled or not unresolved_codes or not preferred_route_is_batch:
                continue
            if not isinstance(route.port, ModelHistoryPreparationPort) or not isinstance(
                route.port, ModelHistoryPreparationAuditPort
            ):
                continue
            route_codes = tuple(sorted(unresolved_codes))
            route_error: DataFetchError | None = None
            prepared_fetches: tuple[ModelHistoryPreparedFetch, ...] = ()
            try:
                route.port.prepare_stock_history(route_codes, start_date, end_date)
            except DataFetchError as exc:
                route_error = exc
                self._disable_quota(route, exc)
                logger.warning("Model history prefetch rejected: %s", exc.code)
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                route_error = DataFetchError(
                    "Model history provider batch preparation failed",
                    code="MODEL_MARKET_UNAVAILABLE",
                )
                logger.warning("Model history prefetch unavailable: %s", type(exc).__name__)
            finally:
                preparation_audit: object = route.port
                if isinstance(preparation_audit, ModelHistoryPreparationAuditPort):
                    prepared_fetches = preparation_audit.drain_model_history_prepared_fetches()
            for fetch in prepared_fetches:
                try:
                    reference = self._persist_prepared_fetch(
                        route,
                        fetch,
                        requested_asset_codes=route_codes,
                        snapshot=snapshot,
                    )
                except DataFetchError as exc:
                    route_error = exc
                    logger.warning("Model history prepared batch rejected: %s", exc.code)
                    break
                self._extend_history_audit_references((reference,))
                if fetch.rows:
                    self._bind_history_rows(fetch.rows, reference)
            if route_error is not None:
                preparation_failures.append(route_error)
                failed_preparation_routes.add(route.name)
                continue
            if not prepared_fetches:
                failed_preparation_routes.add(route.name)
                continue
            if route_error is None:
                cache_port: object = route.port
                if isinstance(cache_port, ModelHistoryPreparationAuditPort):
                    for asset_code in route_codes:
                        if not cache_port.has_prepared_model_history(
                            asset_code, start_date, end_date
                        ):
                            failed_preparation_routes.add(route.name)
                            continue
                        try:
                            cached_rows = route.port.stock_history(asset_code, start_date, end_date)
                            if cached_rows:
                                self._validate(
                                    cached_rows,
                                    asset_code,
                                    start_date,
                                    end_date,
                                    is_index=False,
                                )
                                unresolved_codes.discard(asset_code)
                        except (DataFetchError, OSError, RuntimeError, TypeError, ValueError):
                            continue

        for asset_code in normalized_asset_codes:
            try:
                rows = self._history(
                    asset_code,
                    start_date,
                    end_date,
                    is_index=False,
                    audit_fetch=True,
                    skip_routes=frozenset(failed_preparation_routes),
                    allow_per_asset_fetch=(per_asset_scope_allowed),
                )
            except DataFetchError as exc:
                if preparation_failures and exc.code in {
                    "MODEL_MARKET_UNAVAILABLE",
                    "MODEL_MARKET_BULK_PREPARATION_REQUIRED",
                }:
                    exc = preparation_failures[-1]
                if exc.code != "MODEL_MARKET_SUSPENDED":
                    logger.warning(
                        "Model history preparation failed: asset=%s code=%s",
                        asset_code,
                        exc.code,
                    )
                self._explicit_preparation_errors[(asset_code, start_date, end_date)] = exc
                continue
            self._explicit_prepared_rows[(asset_code, start_date, end_date)] = rows

    def model_history_audit_references(
        self, rows: tuple[ModelDailyBar, ...]
    ) -> tuple[RawAuditReference, ...]:
        """Return exact ingestion audits that supplied every requested row."""

        return tuple(binding.reference for binding in self.model_history_audit_bindings(rows))

    def model_history_audit_bindings(
        self, rows: tuple[ModelDailyBar, ...]
    ) -> tuple[ModelHistoryRawAuditBinding, ...]:
        """Return exact ingestion audits and persisted source types for requested rows."""

        if rows and self._history_fetch_audit is None:
            raise DataFetchError(
                "Model history audit writer is not configured",
                code="MODEL_MARKET_AUDIT_EVIDENCE_MISSING",
            )
        if not rows:
            return ()
        references: dict[str, ModelHistoryRawAuditBinding] = {}
        missing: list[tuple[str, date, str]] = []
        for row in rows:
            key = (row.asset_code, row.trade_date, row.source)
            reference = self._history_row_references.get(key)
            if reference is None:
                missing.append(key)
            else:
                references[reference.reference.raw_audit_id] = reference
        if missing:
            raise DataFetchError(
                "Model history rows lack exact ingestion audit references",
                code="MODEL_MARKET_AUDIT_EVIDENCE_MISSING",
                details={
                    "missing_rows": [
                        f"{code}:{day.isoformat()}:{source}" for code, day, source in missing
                    ]
                },
            )
        return tuple(references[key] for key in sorted(references))

    def take_model_history_audit_references(self) -> tuple[RawAuditReference, ...]:
        """Return and clear exact audits written during the current refresh request."""

        return tuple(binding.reference for binding in self.take_model_history_audit_bindings())

    def take_model_history_audit_bindings(
        self,
    ) -> tuple[ModelHistoryRawAuditBinding, ...]:
        """Return and clear exact source-bound audits from the current refresh request."""

        references = self._unique_history_audit_references(self._history_audit_references)
        self._history_audit_references.clear()
        self._history_row_references.clear()
        self._explicit_prepared_rows.clear()
        self._explicit_preparation_errors.clear()
        self._preparation_reference_rows.clear()
        self._preparation_reference_snapshots.clear()
        self._preparation_active = False
        return references
