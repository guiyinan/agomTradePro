"""A-share universe synchronization from market metadata providers."""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol, TypedDict, cast

from apps.data_center.domain.entities import AssetAlias, AssetMaster
from apps.data_center.domain.enums import AssetType, MarketExchange
from apps.data_center.domain.protocols import ProviderConfigRepositoryProtocol
from apps.data_center.infrastructure.orm_retry import retry_sqlite_locked_operation
from apps.data_center.infrastructure.provider_state_repositories import ProviderConfigRepository
from apps.data_center.infrastructure.repositories import AssetRepository
from apps.data_center.infrastructure.tushare_client import create_tushare_pro_client
from core.exceptions import DataFetchError

logger = logging.getLogger(__name__)
_UNIVERSE_PROVIDER_ATTEMPTS = 3
_DEFAULT_FAILOVER_TOLERANCE = 0.01


class AShareCodeNameRow(TypedDict):
    """One canonical code and its provider-supplied display name."""

    code: str
    name: str


class AShareUniverseSyncError(DataFetchError):
    """Stable, redacted error for an A-share universe refresh failure."""

    default_message = "A-share universe refresh could not establish a current scope"
    default_code = "A_SHARE_UNIVERSE_SYNC_FAILED"

    def __init__(
        self,
        code: str,
        *,
        category: str,
        source: str,
        details: Mapping[str, object] | None = None,
    ) -> None:
        error_details: dict[str, Any] = {"category": category, "source": source}
        error_details.update(details or {})
        super().__init__(self.default_message, code=code, details=error_details)


class _Frame(Protocol):
    """Narrow the DataFrame surface used at provider boundaries."""

    empty: bool
    columns: object

    def to_dict(self, orient: str) -> object: ...


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


class AShareCodeNameProvider(Protocol):
    """Provider contract for current A-share code-name rows."""

    def load_code_names(self) -> list[dict[str, str]]:
        """Return rows with ``code`` and ``name`` keys."""


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
            "failover_from": self.failover_from,
            "failover_difference_ratio": self.failover_difference_ratio,
            "failover_tolerance": self.failover_tolerance,
        }


class AkshareAshareCodeNameProvider:
    """Load the full A-share universe through AKShare's category endpoints."""

    source_name = "akshare.stock_info_[sh_main,sz_main,sh_star,bj]"

    def load_code_names(self) -> list[dict[str, str]]:
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

        rows: list[dict[str, str]] = []
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

    def _load_segment(self, loader: Any, segment: _AkshareSegment) -> list[dict[str, str]]:
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


class _EmptyProviderSegment(ValueError):
    """Retryable indication that one required provider category had no rows."""


def _parse_provider_frame(
    frame: _Frame,
    *,
    source: str,
    segment: str,
    code_column: str,
    name_column: str,
    expected_exchange: str | None = None,
) -> list[dict[str, str]]:
    """Validate native provider columns and return only canonical row fields."""

    columns = {str(column) for column in cast(Iterable[object], frame.columns)}
    required = {code_column, name_column}
    if expected_exchange is not None:
        required.update({"exchange", "list_status"})
    if not required.issubset(columns):
        raise AShareUniverseSyncError(
            "A_SHARE_UNIVERSE_PROVIDER_SCHEMA_INVALID",
            category="provider_schema",
            source=source,
            details={"segment": segment, "missing_columns": sorted(required - columns)},
        )

    raw_records = cast(list[object], frame.to_dict("records"))
    records: list[dict[str, str]] = []
    for index, raw_record in enumerate(raw_records):
        if not isinstance(raw_record, Mapping):
            raise AShareUniverseSyncError(
                "A_SHARE_UNIVERSE_PROVIDER_SCHEMA_INVALID",
                category="provider_schema",
                source=source,
                details={"segment": segment, "row_index": index},
            )
        record = cast(Mapping[str, object], raw_record)
        raw_code = _provider_text(record.get(code_column))
        raw_name = _provider_text(record.get(name_column))
        if not raw_code or not raw_name:
            raise AShareUniverseSyncError(
                "A_SHARE_UNIVERSE_PROVIDER_SCHEMA_INVALID",
                category="provider_schema",
                source=source,
                details={"segment": segment, "row_index": index, "invalid_fields": True},
            )
        if expected_exchange is not None:
            exchange = _provider_text(record.get("exchange"))
            listing_status = _provider_text(record.get("list_status"))
            if exchange != expected_exchange or listing_status != "L":
                raise AShareUniverseSyncError(
                    "A_SHARE_UNIVERSE_PROVIDER_SCOPE_INVALID",
                    category="provider_scope",
                    source=source,
                    details={"segment": segment, "row_index": index},
                )
        records.append({"code": raw_code, "name": raw_name})
    return records


def _provider_text(value: object) -> str:
    """Convert a provider scalar to text while rejecting null-like values."""

    if value is None or isinstance(value, bool):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"", "nan", "none", "null"} else text


class TushareAshareCodeNameProvider:
    """Load current listed A-shares from Tushare by documented exchange scope."""

    source_name = "tushare.stock_basic"

    def __init__(self, config_repo: ProviderConfigRepositoryProtocol | None = None) -> None:
        self._config_repo = config_repo or ProviderConfigRepository()

    def load_code_names(self) -> list[dict[str, str]]:
        """Request each exchange with Tushare's current-listed stock contract."""

        configs = self._config_repo.get_active_by_type("tushare")
        if not configs:
            raise AShareUniverseSyncError(
                "A_SHARE_UNIVERSE_FAILOVER_UNAVAILABLE",
                category="failover_unavailable",
                source=self.source_name,
                details={"provider": "tushare", "reason": "no_active_configuration"},
            )
        config = configs[0]
        if config.id is None:
            raise AShareUniverseSyncError(
                "A_SHARE_UNIVERSE_FAILOVER_CONFIG_INVALID",
                category="failover_configuration",
                source=self.source_name,
                details={"reason": "provider_id_missing"},
            )
        source = (
            f"tushare.stock_basic[provider_id={config.id};" "exchanges=SSE,SZSE,BSE;list_status=L]"
        )
        self.source_name = source
        request_mode_value = config.extra_config.get("tushare_request_mode")
        request_mode = request_mode_value.strip() if isinstance(request_mode_value, str) else None
        deployment_region = (
            (
                os.environ.get("DATA_CENTER_DEPLOYMENT_REGION")
                or os.environ.get("AGOMTRADEPRO_DEPLOYMENT_REGION")
                or "unknown"
            )
            .strip()
            .lower()
        )
        try:
            client = cast(
                Any,
                create_tushare_pro_client(
                    token=config.api_key,
                    http_url=config.http_url,
                    request_mode=request_mode,
                    provider_id=config.id,
                    deployment_region=deployment_region or "unknown",
                    dataset_key="tushare.stock_basic",
                ),
            )
        except Exception as exc:
            raise AShareUniverseSyncError(
                "A_SHARE_UNIVERSE_FAILOVER_UNAVAILABLE",
                category="failover_unavailable",
                source=source,
                details={"exception_type": type(exc).__name__},
            ) from exc

        rows: list[dict[str, str]] = []
        for exchange in ("SSE", "SZSE", "BSE"):
            try:
                frame_value = client.stock_basic(
                    exchange=exchange,
                    list_status="L",
                    fields="ts_code,name,exchange,list_status",
                )
                if frame_value is None:
                    raise _EmptyProviderSegment(exchange)
                frame = cast(_Frame, frame_value)
                if frame.empty:
                    raise _EmptyProviderSegment(exchange)
                rows.extend(
                    _parse_provider_frame(
                        frame,
                        source=source,
                        segment=exchange,
                        code_column="ts_code",
                        name_column="name",
                        expected_exchange=exchange,
                    )
                )
            except AShareUniverseSyncError:
                raise
            except Exception as exc:
                code = (
                    "A_SHARE_UNIVERSE_FAILOVER_EMPTY_SEGMENT"
                    if isinstance(exc, _EmptyProviderSegment)
                    else "A_SHARE_UNIVERSE_FAILOVER_UNAVAILABLE"
                )
                raise AShareUniverseSyncError(
                    code,
                    category="failover_provider",
                    source=source,
                    details={"segment": exchange, "exception_type": type(exc).__name__},
                ) from exc
        if not rows:
            raise AShareUniverseSyncError(
                "A_SHARE_UNIVERSE_FAILOVER_EMPTY",
                category="failover_provider",
                source=source,
            )
        return rows


class JsonFileAshareCodeNameProvider:
    """Load A-share code-name rows from a local JSON file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.source_name = f"json_file:{self.path.name}"

    def load_code_names(self) -> list[dict[str, str]]:
        """Read code-name rows from a JSON file."""

        with self.path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        rows = payload.get("rows") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ValueError("A-share universe input file must contain a row list")
        return [
            {
                "code": str(row.get("code") or "").strip(),
                "name": str(row.get("name") or "").strip(),
            }
            for row in rows
            if isinstance(row, dict)
        ]


class AShareUniverseSyncService:
    """Synchronize the Data Center active A-share universe."""

    def __init__(
        self,
        *,
        provider: AShareCodeNameProvider | None = None,
        fallback_provider: AShareCodeNameProvider | None = None,
        asset_repo: AssetRepository | None = None,
        failover_tolerance: float = _DEFAULT_FAILOVER_TOLERANCE,
    ) -> None:
        use_default_provider = provider is None
        self._provider = provider or AkshareAshareCodeNameProvider()
        self._fallback_provider = fallback_provider or (
            TushareAshareCodeNameProvider() if use_default_provider else None
        )
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
        touched_codes: set[str] = set()

        for row in prepared_rows:
            code = row["code"]
            name = row["name"]
            existing = self._asset_repo.get_by_code(code)
            if existing is not None:
                asset = replace(
                    existing,
                    name=name,
                    short_name=name,
                    is_active=True,
                    extra={**existing.extra, "universe_source": source},
                )
            else:
                asset = AssetMaster(
                    code=code,
                    name=name,
                    short_name=name,
                    asset_type=AssetType.STOCK,
                    exchange=self._infer_exchange(code),
                    is_active=True,
                    extra={"universe_source": source},
                )

            def upsert_asset(asset_to_save: AssetMaster = asset) -> AssetMaster:
                return self._asset_repo.upsert(asset_to_save)

            retry_sqlite_locked_operation(upsert_asset)

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
            failover_from=failover_from,
            failover_difference_ratio=difference_ratio,
            failover_tolerance=(self._failover_tolerance if failover_from is not None else None),
        )

    def _load_current_rows(
        self,
        primary_source: str,
    ) -> tuple[
        AShareCodeNameProvider,
        list[dict[str, str]],
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
        rows: list[dict[str, str]],
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
            prepared_by_code[code] = {"code": code, "name": name}
        if not prepared_by_code:
            raise AShareUniverseSyncError(
                "A_SHARE_UNIVERSE_PROVIDER_EMPTY",
                category="empty_response",
                source=source,
            )
        return list(prepared_by_code.values()), skipped_count

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
