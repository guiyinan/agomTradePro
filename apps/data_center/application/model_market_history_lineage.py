"""Fetch audit binding and reference consistency for prepared model history."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

from apps.data_center.application.model_history_preparation import (
    ModelHistoryPreparationAuditPort,
    ModelHistoryPreparedFetch,
    ModelHistoryRawAuditBinding,
    ModelHistoryReferenceSnapshot,
)
from apps.data_center.application.model_market_data_state import (
    ModelMarketDataServiceState,
    ModelMarketRoute,
)
from apps.data_center.domain.entities import PriceBar
from apps.data_center.domain.model_market_data import ModelDailyBar
from core.exceptions import DataFetchError


class ModelMarketHistoryLineage(ModelMarketDataServiceState):
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
        """Persist one real provider fetch or associate validated cached rows."""

        if cache_port is not None and cache_port.has_prepared_model_history(
            asset_code, start_date, end_date
        ):
            references: dict[str, ModelHistoryRawAuditBinding] = {}
            for row in rows:
                reference = self._history_row_references.get(
                    (row.asset_code, row.trade_date, row.source)
                )
                if reference is None:
                    raise DataFetchError(
                        "Prepared model history cache lacks exact audit evidence",
                        code="MODEL_MARKET_AUDIT_EVIDENCE_MISSING",
                    )
                self._history_row_references[(row.asset_code, row.trade_date, row.source)] = (
                    reference
                )
                references[reference.reference.raw_audit_id] = reference
            self._extend_history_audit_references(
                tuple(references[key] for key in sorted(references))
            )
            return
        audit_port = self._history_fetch_audit
        if audit_port is None:
            return
        if route.provider_id is None:
            raise DataFetchError(
                "Model history route lacks configured provider identity",
                code="MODEL_MARKET_AUDIT_PROVIDER_ID_MISSING",
            )
        result = audit_port.record_model_history_fetch_success(
            provider_id=route.provider_id,
            asset_codes=(asset_code,),
            start_date=start_date,
            end_date=end_date,
            rows=rows,
            request_details={"provider_fetch_kind": "model_stock_history"},
            reference_snapshot=self._reference_snapshot_for((asset_code,), start_date, end_date),
        )
        if rows:
            self._bind_history_rows(rows, result.raw_audit_binding)

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
        """Persist a stable failure audit for one actual provider attempt."""

        audit_port = self._history_fetch_audit
        if audit_port is None:
            return
        if route.provider_id is None:
            raise DataFetchError(
                "Model history route lacks configured provider identity",
                code="MODEL_MARKET_AUDIT_PROVIDER_ID_MISSING",
            )
        audit_port.record_model_history_fetch_failure(
            provider_id=route.provider_id,
            asset_codes=asset_codes,
            start_date=start_date,
            end_date=end_date,
            error=error,
            request_details=self._safe_request_details(request_details),
        )

    def _persist_prepared_fetch(
        self,
        route: ModelMarketRoute,
        fetch: ModelHistoryPreparedFetch,
        *,
        requested_asset_codes: tuple[str, ...],
        snapshot: ModelHistoryReferenceSnapshot,
    ) -> ModelHistoryRawAuditBinding:
        """Validate one staged provider response, then atomically persist its exact batch."""

        audit_port = self._history_fetch_audit
        provider_id = route.provider_id
        if audit_port is None or provider_id is None:
            raise DataFetchError(
                "Prepared model history lacks an audited writer or provider identity",
                code="MODEL_MARKET_AUDIT_PROVIDER_ID_MISSING",
            )
        if not set(fetch.asset_codes).issubset(requested_asset_codes):
            error = DataFetchError(
                "Prepared model history response exceeded its requested asset scope",
                code="MODEL_MARKET_AUDIT_SCOPE_INVALID",
            )
            self._record_history_fetch_failure(
                route,
                asset_codes=requested_asset_codes,
                start_date=snapshot.start_date,
                end_date=snapshot.end_date,
                error=error,
                request_details={"provider_fetch_kind": "model_history_preparation_invalid"},
            )
            raise error
        try:
            reference_snapshot = snapshot.subset(
                fetch.asset_codes, fetch.start_date, fetch.end_date
            )
            self._validate_prepared_fetch(route, fetch, reference_snapshot)
        except (DataFetchError, ValueError) as error:
            if isinstance(error, DataFetchError):
                failure = error
            else:
                failure = DataFetchError(
                    "Prepared model history reference scope is invalid",
                    code="MODEL_MARKET_REFERENCE_SNAPSHOT_SCOPE_INVALID",
                )
            self._record_history_fetch_failure(
                route,
                asset_codes=fetch.asset_codes or requested_asset_codes,
                start_date=fetch.start_date,
                end_date=fetch.end_date,
                error=failure,
                request_details=self._safe_request_details(fetch.request_details),
            )
            if isinstance(error, DataFetchError):
                raise
            raise failure from error
        result = audit_port.record_model_history_fetch_success(
            provider_id=provider_id,
            asset_codes=fetch.asset_codes,
            start_date=fetch.start_date,
            end_date=fetch.end_date,
            rows=fetch.rows,
            request_details=self._safe_request_details(fetch.request_details),
            reference_snapshot=reference_snapshot,
        )
        return result.raw_audit_binding

    def _validate_prepared_fetch(
        self,
        route: ModelMarketRoute,
        fetch: ModelHistoryPreparedFetch,
        snapshot: ModelHistoryReferenceSnapshot,
    ) -> None:
        """Validate every normalized row and any required source-switch overlap before writes."""

        rows_by_asset: dict[str, list[ModelDailyBar]] = {
            asset_code: [] for asset_code in fetch.asset_codes
        }
        for row in fetch.rows:
            rows_by_asset[row.asset_code].append(row)
        for asset_code in fetch.asset_codes:
            candidate = tuple(rows_by_asset[asset_code])
            self._validate(
                candidate,
                asset_code,
                fetch.start_date,
                fetch.end_date,
                is_index=False,
            )
            reference = self._model_reference_rows(asset_code, snapshot)
            source_changed = (
                any(row.source != candidate[0].source for row in reference) if candidate else False
            )
            if candidate and (route.requires_reference or source_changed):
                self._check_consistency(reference, candidate)

    @staticmethod
    def _safe_request_details(
        request_details: Mapping[str, object] | None,
    ) -> Mapping[str, object]:
        """Keep only bounded model-history audit keys supplied by a provider adapter."""

        if request_details is None:
            return {"provider_fetch_kind": "model_stock_history"}
        allowed = {"provider_fetch_kind", "provider_trade_date"}
        sanitized = {
            key: value
            for key, value in request_details.items()
            if key in allowed and isinstance(value, str) and value and len(value) <= 64
        }
        if not sanitized:
            sanitized["provider_fetch_kind"] = "model_history_preparation"
        return sanitized

    @staticmethod
    def _model_reference_rows(
        asset_code: str, snapshot: ModelHistoryReferenceSnapshot
    ) -> tuple[ModelDailyBar, ...]:
        """Project raw unadjusted repository references into the model-history contract."""

        return tuple(
            ModelDailyBar(
                asset_code=asset_code,
                trade_date=bar.bar_date,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                change_percent=0.0,
                adjustment_factor=None,
                source=bar.source,
                amount=bar.amount,
            )
            for bar in snapshot.bars_by_asset.get(asset_code, ())
            if bar.adjustment.value == "none" and bar.source and bar.volume is not None
        )

    def _reference_snapshot_for(
        self, asset_codes: tuple[str, ...], start_date: date, end_date: date
    ) -> ModelHistoryReferenceSnapshot:
        """Return a hash-bound subset of the reference state captured before provider calls."""

        snapshots = {
            code: self._covering_reference_snapshot(code, start_date, end_date)
            for code in asset_codes
        }
        if any(item is None for item in snapshots.values()):
            raise DataFetchError(
                "Model history reference snapshot is unavailable for the exact fetch scope",
                code="MODEL_MARKET_REFERENCE_SNAPSHOT_REQUIRED",
            )
        rows: dict[str, tuple[PriceBar, ...]] = {}
        for code in asset_codes:
            covering_snapshot = snapshots[code]
            if covering_snapshot is None:
                raise DataFetchError(
                    "Model history reference snapshot is unavailable for the exact fetch scope",
                    code="MODEL_MARKET_REFERENCE_SNAPSHOT_REQUIRED",
                )
            rows[code] = covering_snapshot.subset((code,), start_date, end_date).bars_by_asset[code]
        return ModelHistoryReferenceSnapshot.from_bars(asset_codes, start_date, end_date, rows)

    def _reference_history_for(
        self, asset_code: str, start_date: date, end_date: date
    ) -> tuple[ModelDailyBar, ...]:
        """Use the explicit preparation's batched snapshot when it covers this window."""

        key = (asset_code, start_date, end_date)
        if key in self._preparation_reference_rows:
            return self._preparation_reference_rows[key]
        snapshot = self._covering_reference_snapshot(asset_code, start_date, end_date)
        if snapshot is not None:
            return self._model_reference_rows(
                asset_code, snapshot.subset((asset_code,), start_date, end_date)
            )
        return self._reference_history(asset_code, start_date, end_date)

    def _covering_reference_snapshot(
        self, asset_code: str, start_date: date, end_date: date
    ) -> ModelHistoryReferenceSnapshot | None:
        """Find the narrowest explicit snapshot containing one provider fetch window."""

        candidates = [
            snapshot
            for (code, snapshot_start, snapshot_end), snapshot in (
                self._preparation_reference_snapshots.items()
            )
            if code == asset_code and snapshot_start <= start_date and end_date <= snapshot_end
        ]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda item: (item.end_date - item.start_date).days,
        )

    def _bind_history_rows(
        self, rows: tuple[ModelDailyBar, ...], reference: ModelHistoryRawAuditBinding
    ) -> None:
        """Bind each returned natural key to the RawAudit from its write UOW."""

        for row in rows:
            self._history_row_references[(row.asset_code, row.trade_date, row.source)] = reference
        self._extend_history_audit_references((reference,))

    def _extend_history_audit_references(
        self, references: tuple[ModelHistoryRawAuditBinding, ...]
    ) -> None:
        """Accumulate exact references and reject conflicting source lineage."""

        existing = {item.reference.raw_audit_id: item for item in self._history_audit_references}
        for reference in references:
            reference_id = reference.reference.raw_audit_id
            prior = existing.get(reference_id)
            if prior is not None and prior != reference:
                code = (
                    "MODEL_MARKET_AUDIT_SOURCE_TYPE_CONFLICT"
                    if prior.source_type != reference.source_type
                    else "MODEL_MARKET_AUDIT_REFERENCE_CONFLICT"
                )
                raise DataFetchError(
                    "Repeated model-history RawAudit reference has conflicting lineage",
                    code=code,
                    details={"raw_audit_id": reference_id},
                )
            if prior is None:
                self._history_audit_references.append(reference)
                existing[reference_id] = reference

    @staticmethod
    def _unique_history_audit_references(
        references: list[ModelHistoryRawAuditBinding],
    ) -> tuple[ModelHistoryRawAuditBinding, ...]:
        """Return references sorted by their exact persisted audit identity."""

        unique: dict[str, ModelHistoryRawAuditBinding] = {}
        for item in references:
            reference_id = item.reference.raw_audit_id
            prior = unique.get(reference_id)
            if prior is not None and prior != item:
                code = (
                    "MODEL_MARKET_AUDIT_SOURCE_TYPE_CONFLICT"
                    if prior.source_type != item.source_type
                    else "MODEL_MARKET_AUDIT_REFERENCE_CONFLICT"
                )
                raise DataFetchError(
                    "Repeated model-history RawAudit reference has conflicting lineage",
                    code=code,
                    details={"raw_audit_id": reference_id},
                )
            unique[reference_id] = item
        return tuple(unique[key] for key in sorted(unique))
