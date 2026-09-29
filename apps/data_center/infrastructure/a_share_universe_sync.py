"""A-share universe synchronization from market metadata providers."""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any, cast

from apps.data_center.domain.entities import AssetAlias, AssetMaster
from apps.data_center.domain.enums import AssetType, MarketExchange
from apps.data_center.infrastructure.orm_retry import retry_sqlite_locked_operation
from apps.data_center.infrastructure.repositories import AssetRepository
from core.exceptions import DataFetchError

from .a_share_universe_contracts import (
    AShareCodeNameProvider,
    AShareCodeNameRow,
    AShareUniverseSyncError,
    _EmptyProviderSegment,
    _Frame,
    _normalize_provider_listing_date,
    _parse_provider_frame,
    _provider_text,
)
from .tushare_a_share_provider import TushareAshareCodeNameProvider

logger = logging.getLogger(__name__)
__all__ = [
    "AShareCodeNameProvider",
    "AShareCodeNameRow",
    "AShareUniverseSyncError",
    "AShareUniverseSyncReport",
    "AShareUniverseSyncService",
    "AkshareAshareCodeNameProvider",
    "JsonFileAshareCodeNameProvider",
    "TushareAshareCodeNameProvider",
]
_UNIVERSE_PROVIDER_ATTEMPTS = 3
_DEFAULT_FAILOVER_TOLERANCE = 0.01


@dataclass(frozen=True, slots=True)
class _AkshareSegment:
    """One documented category endpoint and its native code/name columns."""

    name: str
    function_name: str
    symbol: str | None
    code_column: str
    name_column: str


_AKSHARE_SEGMENTS = (
    _AkshareSegment("sh_main", "stock_info_sh_name_code", "主板A股", "证券代码", "证券简称"),
    _AkshareSegment("sz_main", "stock_info_sz_name_code", "A股列表", "A股代码", "A股简称"),
    _AkshareSegment("sh_star", "stock_info_sh_name_code", "科创板", "证券代码", "证券简称"),
    _AkshareSegment("bj", "stock_info_bj_name_code", None, "证券代码", "证券简称"),
)


@dataclass(frozen=True)
class AShareUniverseSyncReport:
    """Summary of an A-share universe synchronization run."""

    source: str
    fetched_count: int
    active_count: int
    touched_count: int
    deactivated_count: int
    skipped_count: int
    sample_codes: list[str]
    active_codes_sha256: str
    list_date_metadata_source: str | None = None
    list_date_metadata_status: str = "not_configured"
    list_date_known_count: int = 0
    list_date_unknown_count: int = 0
    list_date_conflict_count: int = 0
    failover_from: str | None = None
    failover_difference_ratio: float | None = None
    failover_tolerance: float | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable payload."""

        return {
            "source": self.source,
            "fetched_count": self.fetched_count,
            "active_count": self.active_count,
            "touched_count": self.touched_count,
            "deactivated_count": self.deactivated_count,
            "skipped_count": self.skipped_count,
            "sample_codes": self.sample_codes,
            "active_codes_sha256": self.active_codes_sha256,
            "list_date_metadata_source": self.list_date_metadata_source,
            "list_date_metadata_status": self.list_date_metadata_status,
            "list_date_known_count": self.list_date_known_count,
            "list_date_unknown_count": self.list_date_unknown_count,
            "list_date_conflict_count": self.list_date_conflict_count,
            "failover_from": self.failover_from,
            "failover_difference_ratio": self.failover_difference_ratio,
            "failover_tolerance": self.failover_tolerance,
        }


class AkshareAshareCodeNameProvider:
    """Load the full A-share universe through AKShare's category endpoints."""

    source_name = "akshare.stock_info_[sh_main,sz_main,sh_star,bj]"

    def load_code_names(self) -> list[AShareCodeNameRow]:
        """Fetch each exchange/board category and preserve its native schema."""

        try:
            ak = cast(Any, importlib.import_module("akshare"))
        except ImportError as exc:
            raise AShareUniverseSyncError(
                "A_SHARE_UNIVERSE_PROVIDER_UNAVAILABLE",
                category="provider_unavailable",
                source=self.source_name,
                details={"provider": "akshare"},
            ) from exc

        rows: list[AShareCodeNameRow] = []
        for segment in _AKSHARE_SEGMENTS:
            loader = getattr(ak, segment.function_name, None)
            if not callable(loader):
                raise AShareUniverseSyncError(
                    "A_SHARE_UNIVERSE_PROVIDER_CONTRACT_INVALID",
                    category="provider_contract",
                    source=self.source_name,
                    details={"segment": segment.name, "missing_endpoint": segment.function_name},
                )
            rows.extend(self._load_segment(loader, segment))
        if not rows:
            raise AShareUniverseSyncError(
                "A_SHARE_UNIVERSE_PROVIDER_EMPTY",
                category="empty_response",
                source=self.source_name,
            )
        return rows

    def _load_segment(self, loader: Any, segment: _AkshareSegment) -> list[AShareCodeNameRow]:
        """Retry only one failed category, clearing its AKShare cache each time."""

        last_error: Exception | None = None
        for attempt in range(1, _UNIVERSE_PROVIDER_ATTEMPTS + 1):
            try:
                clear_cache = getattr(loader, "cache_clear", None)
                if not callable(clear_cache):
                    raise AShareUniverseSyncError(
                        "A_SHARE_UNIVERSE_PROVIDER_CONTRACT_INVALID",
                        category="provider_contract",
                        source=self.source_name,
                        details={"segment": segment.name, "missing_method": "cache_clear"},
                    )
                clear_cache()
                frame_value = loader() if segment.symbol is None else loader(symbol=segment.symbol)
                if frame_value is None:
                    raise _EmptyProviderSegment(segment.name)
                frame = cast(_Frame, frame_value)
                if frame.empty:
                    raise _EmptyProviderSegment(segment.name)
            except (OSError, RuntimeError, ValueError) as exc:
                last_error = exc
                logger.warning(
                    "A-share provider segment retry source=%s segment=%s attempt=%s/%s error=%s",
                    self.source_name,
                    segment.name,
                    attempt,
                    _UNIVERSE_PROVIDER_ATTEMPTS,
                    type(exc).__name__,
                )
                continue
            except AShareUniverseSyncError:
                raise
            except Exception as exc:
                raise AShareUniverseSyncError(
                    "A_SHARE_UNIVERSE_PROVIDER_REQUEST_FAILED",
                    category="provider_request",
                    source=self.source_name,
                    details={"segment": segment.name, "exception_type": type(exc).__name__},
                ) from exc

            try:
                rows = _parse_provider_frame(
                    frame,
                    source=self.source_name,
                    segment=segment.name,
                    code_column=segment.code_column,
                    name_column=segment.name_column,
                )
            except AShareUniverseSyncError:
                raise
            if rows:
                return rows
            last_error = _EmptyProviderSegment(segment.name)

        code = (
            "A_SHARE_UNIVERSE_PROVIDER_EMPTY_SEGMENT"
            if isinstance(last_error, _EmptyProviderSegment)
            else "A_SHARE_UNIVERSE_PROVIDER_UNAVAILABLE"
        )
        category = "empty_segment" if code.endswith("EMPTY_SEGMENT") else "provider_unavailable"
        raise AShareUniverseSyncError(
            code,
            category=category,
            source=self.source_name,
            details={
                "segment": segment.name,
                "attempts": _UNIVERSE_PROVIDER_ATTEMPTS,
                "exception_type": (
                    type(last_error).__name__ if last_error is not None else "unknown"
                ),
            },
        ) from last_error


class JsonFileAshareCodeNameProvider:
    """Load A-share code-name rows from a local JSON file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.source_name = f"json_file:{self.path.name}"

    def load_code_names(self) -> list[AShareCodeNameRow]:
        """Read code-name rows from a JSON file."""

        with self.path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        rows = payload.get("rows") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ValueError("A-share universe input file must contain a row list")
        result: list[AShareCodeNameRow] = []
        for row_index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            prepared: AShareCodeNameRow = {
                "code": str(row.get("code") or "").strip(),
                "name": str(row.get("name") or "").strip(),
            }
            if "list_date" in row:
                list_date_value, list_date_status = _normalize_provider_listing_date(
                    row.get("list_date"),
                    source=self.source_name,
                    segment="json_file",
                    row_index=row_index,
                )
                prepared["list_date"] = list_date_value
                prepared["list_date_status"] = list_date_status
                prepared["list_date_source"] = "json_file.list_date"
            result.append(prepared)
        return result


class AShareUniverseSyncService:
    """Synchronize the Data Center active A-share universe."""

    def __init__(
        self,
        *,
        provider: AShareCodeNameProvider | None = None,
        fallback_provider: AShareCodeNameProvider | None = None,
        listing_metadata_provider: AShareCodeNameProvider | None = None,
        asset_repo: AssetRepository | None = None,
        failover_tolerance: float = _DEFAULT_FAILOVER_TOLERANCE,
    ) -> None:
        use_default_provider = provider is None
        default_tushare_provider = TushareAshareCodeNameProvider() if use_default_provider else None
        self._provider = provider or AkshareAshareCodeNameProvider()
        self._fallback_provider = fallback_provider or (default_tushare_provider)
        self._listing_metadata_provider = listing_metadata_provider or (default_tushare_provider)
        self._asset_repo = asset_repo or AssetRepository()
        if not 0 <= failover_tolerance <= 1:
            raise ValueError("failover_tolerance must be between 0 and 1")
        self._failover_tolerance = failover_tolerance

    def sync(self, *, deactivate_missing: bool = False) -> AShareUniverseSyncReport:
        """Upsert active A-share master rows and optionally deactivate stale rows."""

        primary_source = getattr(self._provider, "source_name", self._provider.__class__.__name__)
        provider, rows, prepared_rows, skipped_count, failover_from, difference_ratio = (
            self._load_current_rows(primary_source)
        )
        source = getattr(provider, "source_name", provider.__class__.__name__)
        metadata_provider = self._listing_metadata_provider
        metadata_status = getattr(provider, "list_date_enrichment_status", "not_configured")
        metadata_source: str | None = source if metadata_status != "not_configured" else None
        if metadata_provider is not None and metadata_provider is not provider:
            try:
                metadata_rows = metadata_provider.load_code_names()
                metadata_source = getattr(
                    metadata_provider,
                    "source_name",
                    metadata_provider.__class__.__name__,
                )
                metadata_prepared, _ = self._prepare_rows(metadata_rows, metadata_source)
            except Exception as exc:
                metadata_status = "unavailable"
                logger.warning(
                    "A-share listing metadata refresh unavailable source=%s error=%s",
                    metadata_source,
                    type(exc).__name__,
                )
            else:
                metadata_status = getattr(
                    metadata_provider,
                    "list_date_enrichment_status",
                    "partial",
                )
                prepared_rows = self._merge_listing_date_metadata(
                    prepared_rows,
                    metadata_prepared,
                )
        touched_codes: set[str] = set()
        persisted_assets: dict[str, AssetMaster] = {}

        for row in prepared_rows:
            code = row["code"]
            name = row["name"]
            existing = self._asset_repo.get_by_code(code)
            incoming_list_date = self._parse_prepared_list_date(row)
            extra = {**(existing.extra if existing is not None else {}), "universe_source": source}
            listing_date = existing.list_date if existing is not None else None
            if listing_date == date(1970, 1, 1):
                listing_date = None
                extra["list_date_evidence_status"] = "placeholder"
                extra["list_date_refresh_status"] = "placeholder"
                extra.pop("list_date_source", None)
            if "list_date" in row:
                incoming_status = row.get("list_date_status", "unknown")
                if incoming_status == "conflict":
                    extra["list_date_evidence_status"] = "conflict"
                    extra["list_date_conflict"] = {
                        "incoming_source": row.get("list_date_source", "provider.list_date"),
                        "reason": "provider_metadata_conflict",
                    }
                elif incoming_list_date is None:
                    if existing is None:
                        extra["list_date_evidence_status"] = "unknown"
                    extra["list_date_refresh_status"] = incoming_status
                elif (
                    existing is not None
                    and incoming_list_date is not None
                    and listing_date is not None
                    and listing_date != incoming_list_date
                ):
                    extra["list_date_evidence_status"] = "conflict"
                    extra["list_date_conflict"] = {
                        "existing_list_date": listing_date.isoformat(),
                        "incoming_list_date": incoming_list_date.isoformat(),
                        "incoming_source": row.get("list_date_source", "provider.list_date"),
                    }
                else:
                    listing_date = incoming_list_date
                    extra["list_date_evidence_status"] = "verified"
                    extra["list_date_source"] = row.get(
                        "list_date_source",
                        "provider.list_date",
                    )
                    extra.pop("list_date_conflict", None)
                    extra.pop("list_date_refresh_status", None)
            if existing is not None:
                asset = replace(
                    existing,
                    name=name,
                    short_name=name,
                    is_active=True,
                    list_date=listing_date,
                    extra=extra,
                )
            else:
                asset = AssetMaster(
                    code=code,
                    name=name,
                    short_name=name,
                    asset_type=AssetType.STOCK,
                    exchange=self._infer_exchange(code),
                    is_active=True,
                    list_date=listing_date,
                    extra=extra,
                )

            def upsert_asset(asset_to_save: AssetMaster = asset) -> AssetMaster:
                return self._asset_repo.upsert(asset_to_save)

            persisted_asset = retry_sqlite_locked_operation(upsert_asset)
            persisted_assets[code] = persisted_asset

            def upsert_alias(asset_code: str = code) -> AssetAlias:
                alias_provider = (
                    "json_file" if source.startswith("json_file:") else source.split(".", 1)[0]
                )
                return self._asset_repo.upsert_alias(
                    AssetAlias(
                        asset_code=asset_code,
                        provider_name=alias_provider,
                        alias_code=asset_code.split(".", 1)[0],
                    )
                )

            retry_sqlite_locked_operation(upsert_alias)
            touched_codes.add(code)

        deactivated_count = 0
        if deactivate_missing:
            deactivated_count = self._deactivate_missing(touched_codes)

        return AShareUniverseSyncReport(
            source=source,
            fetched_count=len(rows),
            active_count=len(touched_codes),
            touched_count=len(touched_codes),
            deactivated_count=deactivated_count,
            skipped_count=skipped_count,
            sample_codes=sorted(touched_codes)[:20],
            active_codes_sha256=hashlib.sha256(
                json.dumps(
                    sorted(touched_codes),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            list_date_metadata_source=metadata_source,
            list_date_metadata_status=metadata_status,
            list_date_known_count=sum(
                1
                for asset in persisted_assets.values()
                if asset.list_date is not None
                and asset.extra.get("list_date_evidence_status") == "verified"
            ),
            list_date_unknown_count=sum(
                1
                for asset in persisted_assets.values()
                if asset.list_date is None
                or asset.extra.get("list_date_evidence_status") != "verified"
            ),
            list_date_conflict_count=sum(
                1
                for asset in persisted_assets.values()
                if asset.extra.get("list_date_evidence_status") == "conflict"
            ),
            failover_from=failover_from,
            failover_difference_ratio=difference_ratio,
            failover_tolerance=(self._failover_tolerance if failover_from is not None else None),
        )

    def _load_current_rows(
        self,
        primary_source: str,
    ) -> tuple[
        AShareCodeNameProvider,
        list[AShareCodeNameRow],
        list[AShareCodeNameRow],
        int,
        str | None,
        float | None,
    ]:
        """Load and validate a complete source before allowing any asset write."""

        primary_error: Exception | None = None
        try:
            rows = self._provider.load_code_names()
            prepared, skipped = self._prepare_rows(rows, primary_source)
            return self._provider, rows, prepared, skipped, None, None
        except Exception as exc:
            primary_error = exc

        assert primary_error is not None
        fallback = self._fallback_provider
        if fallback is None:
            if isinstance(primary_error, AShareUniverseSyncError):
                raise primary_error
            raise AShareUniverseSyncError(
                "A_SHARE_UNIVERSE_PRIMARY_FAILED",
                category="primary_provider",
                source=primary_source,
                details={"exception_type": type(primary_error).__name__},
            ) from primary_error

        fallback_source = getattr(fallback, "source_name", fallback.__class__.__name__)
        try:
            fallback_rows = fallback.load_code_names()
            fallback_source = getattr(fallback, "source_name", fallback.__class__.__name__)
            prepared, skipped = self._prepare_rows(fallback_rows, fallback_source)
            reference_codes = self._asset_repo.list_active_stock_codes()
            ratio = self._validate_failover_scope(
                {row["code"] for row in prepared},
                reference_codes,
                source=fallback_source,
            )
            return fallback, fallback_rows, prepared, skipped, primary_source, ratio
        except Exception as fallback_error:
            if isinstance(fallback_error, AShareUniverseSyncError):
                details = {
                    **fallback_error.details,
                    "primary_source": primary_source,
                    "primary_error_code": self._error_code(primary_error),
                }
                raise AShareUniverseSyncError(
                    fallback_error.code,
                    category=fallback_error.details.get("category", "failover"),
                    source=fallback_error.details.get("source", fallback_source),
                    details=details,
                ) from ExceptionGroup(
                    "A-share primary and fallback source validation failed",
                    [primary_error, fallback_error],
                )
            raise AShareUniverseSyncError(
                "A_SHARE_UNIVERSE_FAILOVER_FAILED",
                category="failover",
                source=fallback_source,
                details={
                    "primary_source": primary_source,
                    "primary_error_code": self._error_code(primary_error),
                    "fallback_exception_type": type(fallback_error).__name__,
                },
            ) from ExceptionGroup(
                "A-share primary and fallback source validation failed",
                [primary_error, fallback_error],
            )

    def _prepare_rows(
        self,
        rows: list[AShareCodeNameRow],
        source: str,
    ) -> tuple[list[AShareCodeNameRow], int]:
        """Canonicalize the complete source response before the sync writes."""

        prepared_by_code: dict[str, AShareCodeNameRow] = {}
        skipped_count = 0
        for index, row in enumerate(rows):
            raw_code = _provider_text(row.get("code"))
            name = _provider_text(row.get("name"))
            code = self._canonicalize_a_share_code(raw_code)
            if not code and raw_code.isascii() and raw_code.isdigit():
                known = self._asset_repo.get_by_code(raw_code.zfill(6))
                if known is not None and known.asset_type is AssetType.STOCK:
                    code = self._canonicalize_a_share_code(known.code)
            if not code or not name:
                raise AShareUniverseSyncError(
                    "A_SHARE_UNIVERSE_PROVIDER_SCOPE_INVALID",
                    category="provider_scope",
                    source=source,
                    details={"row_index": index, "invalid_identity": True},
                )
            if self._looks_delisted(name):
                skipped_count += 1
                continue
            if code in prepared_by_code:
                raise AShareUniverseSyncError(
                    "A_SHARE_UNIVERSE_PROVIDER_DUPLICATE_CODE",
                    category="provider_scope",
                    source=source,
                    details={"row_index": index},
                )
            prepared_row: AShareCodeNameRow = {"code": code, "name": name}
            if "list_date" in row:
                normalized_date, parsed_status = _normalize_provider_listing_date(
                    row.get("list_date"),
                    source=source,
                    segment="list_date",
                    row_index=index,
                )
                supplied_status = row.get("list_date_status")
                if supplied_status in {"unknown", "placeholder", "unverified", "invalid"}:
                    parsed_status = supplied_status
                    normalized_date = None
                prepared_row["list_date"] = normalized_date
                prepared_row["list_date_status"] = parsed_status
                supplied_source = row.get("list_date_source")
                prepared_row["list_date_source"] = (
                    supplied_source.strip()
                    if isinstance(supplied_source, str) and supplied_source.strip()
                    else f"{source}.list_date"
                )
            prepared_by_code[code] = prepared_row
        if not prepared_by_code:
            raise AShareUniverseSyncError(
                "A_SHARE_UNIVERSE_PROVIDER_EMPTY",
                category="empty_response",
                source=source,
            )
        return list(prepared_by_code.values()), skipped_count

    @staticmethod
    def _merge_listing_date_metadata(
        current_rows: list[AShareCodeNameRow],
        metadata_rows: list[AShareCodeNameRow],
    ) -> list[AShareCodeNameRow]:
        """Attach only explicit valid listing dates without changing active identities."""

        metadata_by_code = {
            row["code"]: row
            for row in metadata_rows
            if row.get("list_date_status") == "verified" and row.get("list_date")
        }
        merged_rows: list[AShareCodeNameRow] = []
        for row in current_rows:
            merged: AShareCodeNameRow = {"code": row["code"], "name": row["name"]}
            if row.get("list_date") is not None:
                merged["list_date"] = row["list_date"]
            if row.get("list_date_status") is not None:
                merged["list_date_status"] = row["list_date_status"]
            if row.get("list_date_source") is not None:
                merged["list_date_source"] = row["list_date_source"]
            metadata = metadata_by_code.get(row["code"])
            if metadata is not None:
                current_date = merged.get("list_date")
                metadata_date = metadata["list_date"]
                if current_date is not None and current_date != metadata_date:
                    merged["list_date"] = None
                    merged["list_date_status"] = "conflict"
                    merged["list_date_source"] = (
                        f"{merged.get('list_date_source', 'provider.list_date')}|"
                        f"{metadata.get('list_date_source', 'provider.list_date')}"
                    )
                else:
                    merged["list_date"] = metadata_date
                    merged["list_date_status"] = metadata["list_date_status"]
                    merged["list_date_source"] = metadata.get(
                        "list_date_source",
                        "tushare.stock_basic.list_date",
                    )
            merged_rows.append(merged)
        return merged_rows

    @staticmethod
    def _parse_prepared_list_date(row: AShareCodeNameRow) -> date | None:
        """Convert a provider-normalized ISO listing date to a Domain date."""

        value = row.get("list_date")
        if value is None:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise AShareUniverseSyncError(
                "A_SHARE_UNIVERSE_LISTING_DATE_INVALID",
                category="listing_date",
                source=row.get("list_date_source", "provider.list_date"),
            ) from exc

    def _validate_failover_scope(
        self,
        candidate_codes: set[str],
        reference_codes: set[str],
        *,
        source: str,
    ) -> float:
        """Reject a fallback whose identity scope differs by more than 1%."""

        normalized_reference: set[str] = set()
        for code in reference_codes:
            normalized_code = self._canonicalize_a_share_code(code)
            if not normalized_code:
                raise AShareUniverseSyncError(
                    "A_SHARE_UNIVERSE_FAILOVER_REFERENCE_INVALID",
                    category="failover_consistency",
                    source=source,
                    details={"invalid_reference_identity": True},
                )
            normalized_reference.add(normalized_code)
        if not normalized_reference:
            raise AShareUniverseSyncError(
                "A_SHARE_UNIVERSE_FAILOVER_REFERENCE_UNAVAILABLE",
                category="failover_consistency",
                source=source,
            )
        difference_count = len(candidate_codes.symmetric_difference(normalized_reference))
        denominator = max(len(candidate_codes), len(normalized_reference))
        difference_ratio = difference_count / denominator
        if difference_ratio > self._failover_tolerance:
            raise AShareUniverseSyncError(
                "A_SHARE_UNIVERSE_FAILOVER_INCONSISTENT",
                category="failover_consistency",
                source=source,
                details={
                    "candidate_size": len(candidate_codes),
                    "reference_size": len(normalized_reference),
                    "difference_count": difference_count,
                    "difference_ratio": difference_ratio,
                    "tolerance": self._failover_tolerance,
                },
            )
        return difference_ratio

    @staticmethod
    def _error_code(error: Exception) -> str:
        """Return stable error identity without exposing the exception message."""

        if isinstance(error, DataFetchError):
            return error.code
        return type(error).__name__

    @staticmethod
    def _canonicalize_a_share_code(raw_code: str) -> str:
        """Preserve source exchange identifiers instead of re-inferring known suffixes."""
        base = str(raw_code or "").strip().upper()
        if not base:
            return ""
        if "." in base:
            symbol, suffix = base.rsplit(".", 1)
            if (
                suffix in {"SH", "SZ", "BJ"}
                and symbol.isascii()
                and symbol.isdigit()
                and len(symbol) <= 6
            ):
                return f"{symbol.zfill(6)}.{suffix}"
            return ""
        if base.startswith("SH") or base.startswith("SZ") or base.startswith("BJ"):
            prefix = base[:2]
            symbol = base[2:]
            if not symbol.isascii() or not symbol.isdigit() or len(symbol) > 6:
                return ""
            suffix = {"SH": "SH", "SZ": "SZ", "BJ": "BJ"}[prefix]
            return f"{symbol.zfill(6)}.{suffix}"
        symbol = base.zfill(6)
        if not symbol.isascii() or not symbol.isdigit() or len(symbol) != 6:
            return ""
        if symbol.startswith(("600", "601", "603", "605", "688", "689", "900")):
            return f"{symbol}.SH"
        if symbol.startswith(("000", "001", "002", "003", "200", "300", "301")):
            return f"{symbol}.SZ"
        if symbol.startswith(("4", "8", "920")):
            return f"{symbol}.BJ"
        return ""

    @staticmethod
    def _infer_exchange(code: str) -> MarketExchange:
        if code.endswith(".SH"):
            return MarketExchange.SSE
        if code.endswith(".SZ"):
            return MarketExchange.SZSE
        if code.endswith(".BJ"):
            return MarketExchange.BSE
        return MarketExchange.OTHER

    @staticmethod
    def _looks_delisted(name: str) -> bool:
        normalized = str(name or "").strip()
        return normalized.endswith("退") or "退市" in normalized

    @staticmethod
    def _deactivate_missing(active_codes: set[str]) -> int:
        from apps.data_center.infrastructure.models import AssetMasterModel

        if not active_codes:
            return 0
        queryset = AssetMasterModel._default_manager.filter(
            asset_type="stock",
            exchange__in=["SSE", "SZSE", "BSE"],
            is_active=True,
        ).exclude(code__in=active_codes)
        return int(queryset.update(is_active=False))
