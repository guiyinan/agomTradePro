"""Typed application contracts for explicitly prepared model history."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from apps.data_center.domain.entities import PriceBar, RawAuditReference
from apps.data_center.domain.model_market_data import ModelDailyBar
from apps.data_center.domain.raw_audit_manifest import validate_raw_audit_source_type


@dataclass(frozen=True)
class ModelHistoryReferenceSnapshot:
    """Immutable, hash-bound PriceBar reference state captured before provider writes."""

    asset_codes: tuple[str, ...]
    start_date: date
    end_date: date
    bars_by_asset: Mapping[str, tuple[PriceBar, ...]]
    content_hash: str

    def __post_init__(self) -> None:
        """Validate scope and freeze the exact repository rows used for comparison."""

        if (
            self.start_date > self.end_date
            or tuple(sorted(set(self.asset_codes))) != self.asset_codes
            or set(self.bars_by_asset) != set(self.asset_codes)
            or len(self.content_hash) != 64
            or any(value not in "0123456789abcdef" for value in self.content_hash)
        ):
            raise ValueError("Model history reference snapshot is invalid")
        frozen: dict[str, tuple[PriceBar, ...]] = {}
        for asset_code in self.asset_codes:
            rows = tuple(self.bars_by_asset[asset_code])
            if any(not self.start_date <= row.bar_date <= self.end_date for row in rows):
                raise ValueError("Reference snapshot contains a row outside its exact window")
            frozen[asset_code] = rows
        object.__setattr__(self, "bars_by_asset", MappingProxyType(frozen))
        if self.content_hash != self.calculate_hash(
            self.asset_codes, self.start_date, self.end_date, frozen
        ):
            raise ValueError("Model history reference snapshot hash does not match its rows")

    @classmethod
    def from_bars(
        cls,
        asset_codes: tuple[str, ...],
        start_date: date,
        end_date: date,
        bars_by_asset: Mapping[str, tuple[PriceBar, ...]],
    ) -> ModelHistoryReferenceSnapshot:
        """Create a canonical snapshot whose digest binds scope and persisted PriceBars."""

        codes = tuple(sorted(set(asset_codes)))
        rows = {code: tuple(bars_by_asset.get(code, ())) for code in codes}
        content_hash = cls.calculate_hash(codes, start_date, end_date, rows)
        return cls(
            asset_codes=codes,
            start_date=start_date,
            end_date=end_date,
            bars_by_asset=rows,
            content_hash=content_hash,
        )

    def subset(
        self, asset_codes: tuple[str, ...], start_date: date, end_date: date
    ) -> ModelHistoryReferenceSnapshot:
        """Return the exact code/date subset needed by one provider fetch batch."""

        codes = tuple(sorted(set(asset_codes)))
        if (
            not set(codes).issubset(self.asset_codes)
            or start_date < self.start_date
            or end_date > self.end_date
        ):
            raise ValueError("Requested reference subset falls outside its captured scope")
        rows = {
            code: tuple(
                row for row in self.bars_by_asset[code] if start_date <= row.bar_date <= end_date
            )
            for code in codes
        }
        return self.from_bars(codes, start_date, end_date, rows)

    @staticmethod
    def calculate_hash(
        asset_codes: tuple[str, ...],
        start_date: date,
        end_date: date,
        bars_by_asset: Mapping[str, tuple[PriceBar, ...]],
    ) -> str:
        """Hash sorted asset/date/value/source/ingestion state without request-order noise."""

        payload: dict[str, object] = {
            "asset_codes": list(asset_codes),
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "bars": {
                code: [
                    {
                        "asset_code": row.asset_code,
                        "bar_date": row.bar_date.isoformat(),
                        "freq": row.freq,
                        "adjustment": row.adjustment.value,
                        "open": row.open.hex(),
                        "high": row.high.hex(),
                        "low": row.low.hex(),
                        "close": row.close.hex(),
                        "volume": row.volume.hex() if row.volume is not None else None,
                        "amount": row.amount.hex() if row.amount is not None else None,
                        "source": row.source,
                        "ingested_run_id": row.ingested_run_id,
                    }
                    for row in sorted(
                        bars_by_asset.get(code, ()),
                        key=lambda item: (
                            item.bar_date,
                            item.freq,
                            item.adjustment.value,
                            item.source,
                            item.ingested_run_id,
                        ),
                    )
                ]
                for code in asset_codes
            },
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ModelHistoryPreparedFetch:
    """One normalized provider response pending consistency validation and atomic persistence."""

    asset_codes: tuple[str, ...]
    start_date: date
    end_date: date
    rows: tuple[ModelDailyBar, ...]
    request_details: Mapping[str, object]

    def __post_init__(self) -> None:
        """Freeze bounded request metadata and reject rows outside the provider response scope."""

        if (
            self.start_date > self.end_date
            or not self.asset_codes
            or tuple(sorted(set(self.asset_codes))) != self.asset_codes
            or any(
                row.asset_code not in self.asset_codes
                or not self.start_date <= row.trade_date <= self.end_date
                for row in self.rows
            )
        ):
            raise ValueError("Prepared model history fetch scope is invalid")
        object.__setattr__(self, "request_details", MappingProxyType(dict(self.request_details)))


@dataclass(frozen=True)
class ModelHistoryRawAuditBinding:
    """Bind one price-history RawAudit reference to its persisted provider source type."""

    reference: RawAuditReference
    source_type: str

    def __post_init__(self) -> None:
        """Require an exact RawAudit and canonical source token for price lineage."""

        if not isinstance(self.reference, RawAuditReference):
            raise ValueError("model history RawAudit reference is invalid")
        validate_raw_audit_source_type(self.source_type)


@dataclass(frozen=True)
class ModelHistoryFetchAuditResult:
    """Required lineage returned after one model-history fetch was committed."""

    provider_name: str
    stored_count: int
    stored_asset_codes: tuple[str, ...]
    raw_audit_reference: RawAuditReference
    source_type: str

    def __post_init__(self) -> None:
        """Reject a result whose fact scope is not bound to its exact RawAudit."""

        if not self.provider_name.strip():
            raise ValueError("model history provider name is required")
        if (
            isinstance(self.stored_count, bool)
            or not isinstance(self.stored_count, int)
            or self.stored_count < 0
        ):
            raise ValueError("model history stored count is invalid")
        if tuple(sorted(set(self.stored_asset_codes))) != self.stored_asset_codes:
            raise ValueError("model history stored asset codes must be sorted and unique")
        if (self.stored_count == 0) != (not self.stored_asset_codes):
            raise ValueError("model history count and stored asset scope disagree")
        ModelHistoryRawAuditBinding(self.raw_audit_reference, self.source_type)

    @property
    def raw_audit_binding(self) -> ModelHistoryRawAuditBinding:
        """Return the price-specific binding made from the persisted write result."""

        return ModelHistoryRawAuditBinding(self.raw_audit_reference, self.source_type)


class ModelHistoryFetchAuditPort(Protocol):
    """Persist one accepted model-history fetch through the canonical sync use case."""

    def record_model_history_fetch_success(
        self,
        *,
        provider_id: int,
        asset_codes: tuple[str, ...],
        start_date: date,
        end_date: date,
        rows: tuple[ModelDailyBar, ...],
        request_details: Mapping[str, object],
        reference_snapshot: ModelHistoryReferenceSnapshot,
    ) -> ModelHistoryFetchAuditResult:
        """Persist rows and exact RawAudit evidence in one sync unit of work."""
        ...

    def record_model_history_fetch_failure(
        self,
        *,
        provider_id: int,
        asset_codes: tuple[str, ...],
        start_date: date,
        end_date: date,
        error: BaseException,
        request_details: Mapping[str, object],
    ) -> RawAuditReference:
        """Persist a sanitized failed-fetch audit in its own sync unit of work."""
        ...


@runtime_checkable
class ModelHistoryAuditEvidencePort(Protocol):
    """Resolve the exact RawAudit references for validated model-history rows."""

    def model_history_audit_references(
        self, rows: tuple[ModelDailyBar, ...]
    ) -> tuple[RawAuditReference, ...]:
        """Return every exact fetch reference that supplied the given rows."""
        ...

    def take_model_history_audit_references(self) -> tuple[RawAuditReference, ...]:
        """Return and clear references accumulated by the current refresh operation."""
        ...

    def model_history_audit_bindings(
        self, rows: tuple[ModelDailyBar, ...]
    ) -> tuple[ModelHistoryRawAuditBinding, ...]:
        """Return exact source-bound audit references for the requested rows."""
        ...

    def take_model_history_audit_bindings(self) -> tuple[ModelHistoryRawAuditBinding, ...]:
        """Return and clear source-bound references accumulated by this refresh operation."""
        ...


@runtime_checkable
class ModelHistoryPreparationAuditPort(Protocol):
    """Expose exact audit links for a provider's private preparation cache."""

    def has_prepared_model_history(self, asset_code: str, start_date: date, end_date: date) -> bool:
        """Return whether the exact requested history window is already cached."""
        ...

    def drain_model_history_prepared_fetches(
        self,
    ) -> tuple[ModelHistoryPreparedFetch, ...]:
        """Return exact normalized provider fetches for service validation and persistence."""
        ...


@runtime_checkable
class ModelHistorySingleFetchAuditPort(Protocol):
    """Expose an explicit real provider fetch for bounded per-asset preparation."""

    def fetch_stock_history(
        self, asset_code: str, start_date: date, end_date: date
    ) -> ModelHistoryPreparedFetch:
        """Fetch one normalized asset window without persisting facts or audit rows."""
        ...
