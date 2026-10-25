"""Trusted equity valuation synchronization and quality use cases."""

import hashlib
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Protocol, TypeAlias, cast

from apps.data_center.application.dtos import SyncResult as DataCenterSyncResult
from apps.data_center.application.dtos import SyncValuationRequest as DataCenterSyncValuationRequest
from apps.data_center.application.public import (
    get_active_provider_selection_by_source,
    make_sync_valuation_use_case,
)
from apps.equity.application.repository_provider import (
    build_equity_valuation_source_gateway,
    build_quality_snapshot,
)
from apps.equity.domain.entities import ValuationMetrics

logger = logging.getLogger(__name__)

ValuationPayload: TypeAlias = dict[str, object]
ProviderSelection: TypeAlias = tuple[int, str]
ProviderResolver: TypeAlias = Callable[[str], ProviderSelection | None]

_SOURCE_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
_STOCK_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class _FrozenValuationScope:
    """One immutable, normalized stock universe shared inside one workflow."""

    stock_codes: tuple[str, ...]
    identity: str


class ValuationStockRepositoryProtocol(Protocol):
    """Equity valuation persistence required by the application use cases."""

    def list_active_stock_codes(self) -> list[str]: ...

    def save_valuation(self, valuation: ValuationMetrics) -> int:
        """Return canonical processed facts, including zero for a rejected metric."""
        ...

    def get_latest_valuation_date(self) -> date | None: ...

    def get_valuation_models_by_date(self, as_of_date: date) -> Sequence[object]: ...


class ValuationQualityRepositoryProtocol(Protocol):
    """Quality snapshot persistence boundary."""

    def upsert_snapshot(self, snapshot: ValuationPayload) -> None: ...

    def get_latest_snapshot(self) -> object | None: ...


class ValuationBatchProtocol(Protocol):
    """Provider-specific valuation facts read from the canonical store."""

    source_provider: str
    records: list[ValuationMetrics]


class ValuationGatewayProtocol(Protocol):
    """Read canonical valuation facts belonging to one configured provider."""

    def fetch(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
    ) -> ValuationBatchProtocol: ...


class DataCenterValuationSyncProtocol(Protocol):
    """Data Center valuation synchronization boundary."""

    def execute(self, request: DataCenterSyncValuationRequest) -> DataCenterSyncResult:
        """Return the canonical provider sync result with its processed count."""
        ...


class ValuationQualitySnapshotProtocol(Protocol):
    """Readable quality snapshot fields published by the application."""

    as_of_date: date
    expected_stock_count: int
    synced_stock_count: int
    valid_stock_count: int
    coverage_ratio: float
    valid_ratio: float
    missing_pb_count: int
    invalid_pb_count: int
    missing_pe_count: int
    jump_alert_count: int
    source_deviation_count: int
    primary_source: str
    fallback_used_count: int
    is_gate_passed: bool
    gate_reason: str


GatewayFactory: TypeAlias = Callable[[str], ValuationGatewayProtocol]


@dataclass(frozen=True)
class ValidateEquityValuationQualityRequest:
    """Request one quality snapshot for an existing valuation date."""

    as_of_date: date | None = None
    primary_source: str = "akshare"


@dataclass(frozen=True)
class SyncEquityValuationRequest:
    """Synchronize valuation facts for a bounded stock/date selection."""

    stock_codes: list[str] | None = None
    start_date: date | None = None
    end_date: date | None = None
    primary_source: str = "akshare"
    fallback_source: str = "tushare"
    days_back: int = 1


@dataclass(frozen=True)
class SyncEquityValuationResponse:
    """Valuation synchronization outcome."""

    success: bool
    data: ValuationPayload | None = None
    error: str | None = None
    _frozen_scope: _FrozenValuationScope | None = field(
        default=None,
        repr=False,
        compare=False,
    )


@dataclass(frozen=True)
class BackfillEquityValuationRequest:
    """Request a bounded historical valuation backfill."""

    years: int = 3
    batch_size: int = 100


@dataclass(frozen=True)
class BackfillEquityValuationResponse:
    """Historical backfill outcome."""

    success: bool
    data: ValuationPayload | None = None
    error: str | None = None


@dataclass(frozen=True)
class ValidateEquityValuationQualityResponse:
    """Quality validation outcome."""

    success: bool
    data: ValuationPayload | None = None
    error: str | None = None


@dataclass(frozen=True)
class GetEquityValuationFreshnessResponse:
    """Valuation freshness outcome."""

    success: bool
    data: ValuationPayload | None = None
    error: str | None = None


@dataclass(frozen=True)
class GetLatestEquityValuationQualityResponse:
    """Latest quality snapshot outcome."""

    success: bool
    data: ValuationPayload | None = None
    error: str | None = None


def _normalize_source(value: object, *, field_name: str) -> str:
    """Normalize a configured source type without hard-coding its catalog."""

    if not isinstance(value, str):
        raise ValueError(f"{field_name} 必须是字符串")
    normalized = value.strip().lower()
    if not normalized or len(normalized) > 64 or _SOURCE_PATTERN.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} 格式无效")
    return normalized


def _normalize_stock_codes(
    values: object,
    *,
    maximum_count: int | None = 5000,
) -> list[str]:
    """Validate and de-duplicate a stock universe with an optional input cap."""

    if not isinstance(values, list):
        raise ValueError("stock_codes 必须是字符串列表")
    if not values:
        raise ValueError("未找到可同步股票")
    if maximum_count is not None and len(values) > maximum_count:
        raise ValueError("stock_codes 最多允许 5000 项")

    normalized_codes: list[str] = []
    seen: set[str] = set()
    for raw_code in values:
        if not isinstance(raw_code, str):
            raise ValueError("stock_code 必须是字符串")
        stock_code = raw_code.strip().upper()
        if (
            not stock_code
            or len(stock_code) > 32
            or _STOCK_CODE_PATTERN.fullmatch(stock_code) is None
        ):
            raise ValueError("stock_code 格式无效")
        if stock_code not in seen:
            seen.add(stock_code)
            normalized_codes.append(stock_code)
    return normalized_codes


def _freeze_stock_scope(
    values: object,
    *,
    maximum_count: int | None,
) -> _FrozenValuationScope:
    """Normalize one tuple and hash its sorted, unique code set."""

    codes = tuple(_normalize_stock_codes(values, maximum_count=maximum_count))
    identity = hashlib.sha256("\n".join(sorted(codes)).encode("utf-8")).hexdigest()
    return _FrozenValuationScope(stock_codes=codes, identity=identity)


def _require_frozen_stock_scope(value: object) -> _FrozenValuationScope:
    """Validate the private immutable scope passed between workflow use cases."""

    if type(value) is not _FrozenValuationScope:
        raise ValueError("frozen stock scope is invalid")
    normalized_codes = _normalize_stock_codes(list(value.stock_codes), maximum_count=None)
    identity = hashlib.sha256("\n".join(sorted(normalized_codes)).encode("utf-8")).hexdigest()
    if tuple(normalized_codes) != value.stock_codes or identity != value.identity:
        raise ValueError("frozen stock scope identity mismatch")
    return value


def _filter_valuations_to_scope(
    valuations: Sequence[object],
    scope: _FrozenValuationScope,
) -> list[ValuationMetrics]:
    """Keep quality facts only for the exact codes in one frozen scope."""

    allowed_codes = set(scope.stock_codes)
    scoped_valuations: list[ValuationMetrics] = []
    for valuation in valuations:
        if not isinstance(valuation, ValuationMetrics):
            raise ValueError("估值仓储返回无效记录")
        stock_code = valuation.stock_code
        if not isinstance(stock_code, str) or not stock_code.strip():
            raise ValueError("估值仓储返回无效股票代码")
        if stock_code.upper() in allowed_codes:
            scoped_valuations.append(valuation)
    return scoped_valuations


def _validate_positive_int(
    value: object,
    *,
    field_name: str,
    maximum: int,
) -> int:
    """Validate a positive, bounded integer without accepting booleans."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} 必须是整数")
    if not 1 <= value <= maximum:
        raise ValueError(f"{field_name} 必须在 1..{maximum} 之间")
    return value


def _optional_nonnegative_int(value: object) -> int | None:
    """Narrow one optional nonnegative count without accepting booleans."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _resolve_provider(
    source_type: str,
    *,
    field_name: str,
    provider_resolver: ProviderResolver,
) -> ProviderSelection:
    """Resolve one active provider and fail closed when configuration is absent."""

    selection = provider_resolver(source_type)
    if selection is None:
        raise ValueError(f"{field_name} 未配置启用的数据源")
    provider_id, provider_name = selection
    if (
        isinstance(provider_id, bool)
        or not isinstance(provider_id, int)
        or provider_id <= 0
        or not isinstance(provider_name, str)
        or not provider_name.strip()
    ):
        raise ValueError(f"{field_name} 数据源配置无效")
    return provider_id, provider_name.strip()


def _default_gateway_factory(provider_name: str) -> ValuationGatewayProtocol:
    """Build the canonical fact reader for a configured provider."""

    return cast(
        ValuationGatewayProtocol,
        build_equity_valuation_source_gateway(provider_name=provider_name),
    )


def _default_data_center_sync_use_case() -> DataCenterValuationSyncProtocol:
    """Narrow the Data Center composition result to the application protocol."""

    return cast(DataCenterValuationSyncProtocol, make_sync_valuation_use_case())


def _validated_data_center_stored_count(result: object) -> int:
    """Require one exact valuation SyncResult before counting canonical facts."""

    if not isinstance(result, DataCenterSyncResult) or result.domain != "valuation":
        raise ValueError("Data Center returned an invalid valuation sync result")
    stored_count = result.stored_count
    if type(stored_count) is not int or stored_count < 0:
        raise ValueError("Data Center returned an invalid stored count")
    if result.status not in {"success", "noop"}:
        raise ValueError("Data Center returned an unsupported valuation sync status")
    if (stored_count > 0) != (result.status == "success"):
        raise ValueError("Data Center valuation result status/count mismatch")
    return stored_count


class ValidateEquityValuationQualityUseCase:
    """Validate local valuation coverage and persist one quality snapshot."""

    def __init__(
        self,
        stock_repository: ValuationStockRepositoryProtocol,
        quality_repository: ValuationQualityRepositoryProtocol,
        *,
        provider_resolver: ProviderResolver = get_active_provider_selection_by_source,
    ) -> None:
        self.stock_repo = stock_repository
        self.quality_repo = quality_repository
        self.provider_resolver = provider_resolver

    def execute(
        self,
        request: ValidateEquityValuationQualityRequest,
        *,
        _frozen_scope: object | None = None,
    ) -> ValidateEquityValuationQualityResponse:
        """Persist quality evaluation only for the exact frozen member scope."""
        try:
            primary_source = _normalize_source(
                request.primary_source,
                field_name="primary_source",
            )
            _, primary_provider_name = _resolve_provider(
                primary_source,
                field_name="primary_source",
                provider_resolver=self.provider_resolver,
            )
            as_of_date = request.as_of_date or self.stock_repo.get_latest_valuation_date()
            if as_of_date is None:
                raise ValueError("未找到估值数据")
            if as_of_date > date.today():
                raise ValueError("as_of_date 不能晚于今天")

            scope = (
                _freeze_stock_scope(
                    self.stock_repo.list_active_stock_codes(),
                    maximum_count=None,
                )
                if _frozen_scope is None
                else _require_frozen_stock_scope(_frozen_scope)
            )
            valuations = _filter_valuations_to_scope(
                self.stock_repo.get_valuation_models_by_date(as_of_date),
                scope,
            )
            quality_builder = cast(Callable[..., ValuationPayload], build_quality_snapshot)
            snapshot = quality_builder(
                as_of_date=as_of_date,
                expected_stock_count=len(scope.stock_codes),
                valuations=valuations,
                primary_source=primary_provider_name,
            )
            self.quality_repo.upsert_snapshot(snapshot)
            data = _snapshot_to_dict(snapshot)
            data["scope_sha256"] = scope.identity
            data["scope_count"] = len(scope.stock_codes)
            return ValidateEquityValuationQualityResponse(success=True, data=data)
        except ValueError as exc:
            logger.warning(
                "Equity valuation quality validation rejected: %s",
                type(exc).__name__,
            )
            return ValidateEquityValuationQualityResponse(
                success=False,
                error=str(exc),
            )
        except Exception as exc:
            logger.error(
                "Equity valuation quality validation failed: %s",
                type(exc).__name__,
            )
            return ValidateEquityValuationQualityResponse(
                success=False,
                error="估值数据质量校验失败",
            )


class SyncEquityValuationUseCase:
    """Synchronize provider-specific valuation facts into local equity storage."""

    def __init__(
        self,
        stock_repository: ValuationStockRepositoryProtocol,
        *,
        provider_resolver: ProviderResolver = get_active_provider_selection_by_source,
        gateway_factory: GatewayFactory = _default_gateway_factory,
        data_center_sync_use_case: DataCenterValuationSyncProtocol | None = None,
    ) -> None:
        self.stock_repo = stock_repository
        self.provider_resolver = provider_resolver
        self.gateway_factory = gateway_factory
        self.data_center_sync_use_case = data_center_sync_use_case

    def _freeze_repository_scope(self) -> _FrozenValuationScope:
        """Freeze the repository's complete normalized universe for one workflow."""

        return _freeze_stock_scope(
            self.stock_repo.list_active_stock_codes(),
            maximum_count=None,
        )

    def execute(self, request: SyncEquityValuationRequest) -> SyncEquityValuationResponse:
        """Sync one explicit list or freeze and process the full repository universe."""

        scope: _FrozenValuationScope | None = None
        try:
            start_date, end_date = self._resolve_date_window(request)
            primary_source = _normalize_source(
                request.primary_source,
                field_name="primary_source",
            )
            fallback_source = _normalize_source(
                request.fallback_source,
                field_name="fallback_source",
            )
            if primary_source == fallback_source:
                raise ValueError("fallback_source 必须与 primary_source 不同")

            if request.stock_codes is not None:
                scope = _freeze_stock_scope(request.stock_codes, maximum_count=5000)
            else:
                scope = self._freeze_repository_scope()

            primary_provider_id, primary_provider_name = _resolve_provider(
                primary_source,
                field_name="primary_source",
                provider_resolver=self.provider_resolver,
            )
            fallback_provider_id, fallback_provider_name = _resolve_provider(
                fallback_source,
                field_name="fallback_source",
                provider_resolver=self.provider_resolver,
            )
            stock_codes = scope.stock_codes
            primary_gateway = self.gateway_factory(primary_provider_name)
            fallback_gateway = self.gateway_factory(fallback_provider_name)

            equity_writer_count = 0
            data_center_processed_count = 0
            data_center_positive_write_counts: dict[str, int] = {}
            data_center_write_outcome_unknown = False
            equity_writer_outcome_unknown = False
            succeeded_stock_count = 0
            failed_stock_count = 0
            fallback_used_count = 0
            skipped_count = 0
            error_count = 0
            errors: list[str] = []

            for stock_code in stock_codes:
                try:
                    batch = primary_gateway.fetch(stock_code, start_date, end_date)
                    source_used = primary_provider_name
                    if not batch.records:
                        try:
                            result = self._sync_data_center_valuation(
                                stock_code=stock_code,
                                start_date=start_date,
                                end_date=end_date,
                                provider_id=primary_provider_id,
                            )
                            stored_count = _validated_data_center_stored_count(result)
                        except Exception:
                            data_center_write_outcome_unknown = True
                            raise
                        data_center_processed_count += stored_count
                        if stored_count > 0:
                            data_center_positive_write_counts[stock_code] = (
                                data_center_positive_write_counts.get(stock_code, 0) + 1
                            )
                        batch = primary_gateway.fetch(stock_code, start_date, end_date)

                    if not batch.records:
                        try:
                            result = self._sync_data_center_valuation(
                                stock_code=stock_code,
                                start_date=start_date,
                                end_date=end_date,
                                provider_id=fallback_provider_id,
                            )
                            stored_count = _validated_data_center_stored_count(result)
                        except Exception:
                            data_center_write_outcome_unknown = True
                            raise
                        data_center_processed_count += stored_count
                        if stored_count > 0:
                            data_center_positive_write_counts[stock_code] = (
                                data_center_positive_write_counts.get(stock_code, 0) + 1
                            )
                        batch = fallback_gateway.fetch(stock_code, start_date, end_date)
                        source_used = fallback_provider_name

                    if not batch.records:
                        skipped_count += 1
                        failed_stock_count += 1
                        error_count += 1
                        errors.append(f"{stock_code}: 未获取到估值记录")
                        continue

                    stock_writer_count = 0
                    stock_complete = True
                    for record in batch.records:
                        if (
                            not isinstance(record.stock_code, str)
                            or record.stock_code.upper() != stock_code
                        ):
                            raise ValueError("估值记录股票代码与请求不一致")
                        try:
                            stored_count = self.stock_repo.save_valuation(record)
                        except Exception:
                            equity_writer_outcome_unknown = True
                            raise
                        if (
                            isinstance(stored_count, bool)
                            or not isinstance(stored_count, int)
                            or stored_count < 0
                        ):
                            equity_writer_outcome_unknown = True
                            raise ValueError("估值仓储返回无效存储计数")
                        equity_writer_count += stored_count
                        stock_writer_count += stored_count
                        if stored_count == 0:
                            stock_complete = False

                    if source_used != primary_provider_name:
                        fallback_used_count += 1
                    if not stock_complete or stock_writer_count == 0:
                        failed_stock_count += 1
                        error_count += 1
                        errors.append(f"{stock_code}: 估值记录未写入")
                        continue
                    succeeded_stock_count += 1
                except Exception as exc:
                    failed_stock_count += 1
                    error_count += 1
                    errors.append(f"{stock_code}: 同步失败")
                    logger.warning(
                        "Equity valuation sync failed for %s: %s",
                        stock_code,
                        type(exc).__name__,
                    )

            unavailable_reasons: list[str] = []
            if data_center_write_outcome_unknown:
                unavailable_reasons.append("data_center_write_outcome_unknown")
            if equity_writer_outcome_unknown:
                unavailable_reasons.append("equity_writer_outcome_unknown")
            repeated_data_center_write = any(
                count > 1 for count in data_center_positive_write_counts.values()
            )
            if repeated_data_center_write or (
                data_center_processed_count > 0 and equity_writer_count > 0
            ):
                unavailable_reasons.append("canonical_write_stages_may_overlap")
            stored_record_count: int | None = (
                None if unavailable_reasons else data_center_processed_count + equity_writer_count
            )
            outcome = (
                "success"
                if succeeded_stock_count == len(stock_codes) and failed_stock_count == 0
                else "partial" if succeeded_stock_count > 0 else "failed"
            )
            data: ValuationPayload = {
                "requested_count": len(stock_codes),
                "requested_stock_count": len(stock_codes),
                "succeeded_stock_count": succeeded_stock_count,
                "failed_stock_count": failed_stock_count,
                "outcome": outcome,
                "synced_count": (None if equity_writer_outcome_unknown else equity_writer_count),
                "stored_record_count": stored_record_count,
                "confirmed_equity_writer_record_count": equity_writer_count,
                "data_center_confirmed_processed_record_count": data_center_processed_count,
                "data_center_write_outcome_unknown": data_center_write_outcome_unknown,
                "equity_writer_outcome_unknown": equity_writer_outcome_unknown,
                "counts_unavailable": stored_record_count is None,
                "stored_record_count_unavailable_reasons": unavailable_reasons,
                "scope_sha256": scope.identity,
                "scope_count": len(scope.stock_codes),
                "fallback_used_count": fallback_used_count,
                "skipped_count": skipped_count,
                "error_count": error_count,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "errors": errors[:50],
            }
            if outcome == "failed":
                error = (
                    "估值同步未写入任何记录"
                    if data_center_processed_count == 0
                    else "估值同步未完成任何可读取股票"
                )
                return SyncEquityValuationResponse(
                    success=False,
                    data=data,
                    error=error,
                    _frozen_scope=scope,
                )
            if outcome == "partial":
                return SyncEquityValuationResponse(
                    success=False,
                    data=data,
                    error="估值同步部分失败",
                    _frozen_scope=scope,
                )
            return SyncEquityValuationResponse(
                success=True,
                data=data,
                _frozen_scope=scope,
            )
        except ValueError as exc:
            logger.warning("Equity valuation sync rejected: %s", type(exc).__name__)
            return SyncEquityValuationResponse(
                success=False,
                error=str(exc),
                _frozen_scope=scope,
            )
        except Exception as exc:
            logger.error("Equity valuation sync failed: %s", type(exc).__name__)
            return SyncEquityValuationResponse(
                success=False,
                error="估值数据同步失败",
                _frozen_scope=scope,
            )

    @staticmethod
    def _resolve_date_window(
        request: SyncEquityValuationRequest,
    ) -> tuple[date, date]:
        """Resolve and validate the requested synchronization evidence window."""

        days_back = _validate_positive_int(
            request.days_back,
            field_name="days_back",
            maximum=3660,
        )
        end_date = request.end_date or date.today()
        start_date = request.start_date or (end_date - timedelta(days=days_back))
        if end_date > date.today():
            raise ValueError("end_date 不能晚于今天")
        if start_date > end_date:
            raise ValueError("start_date 不能晚于 end_date")
        return start_date, end_date

    def _sync_data_center_valuation(
        self,
        *,
        stock_code: str,
        start_date: date,
        end_date: date,
        provider_id: int,
    ) -> DataCenterSyncResult:
        """Run one provider-specific Data Center synchronization."""

        sync_use_case = self.data_center_sync_use_case or _default_data_center_sync_use_case()
        return sync_use_case.execute(
            DataCenterSyncValuationRequest(
                provider_id=provider_id,
                asset_code=stock_code,
                start=start_date,
                end=end_date,
            )
        )


class BackfillEquityValuationUseCase:
    """Backfill historical valuation facts in bounded batches."""

    def __init__(
        self,
        stock_repository: ValuationStockRepositoryProtocol,
        *,
        sync_use_case: SyncEquityValuationUseCase | None = None,
    ) -> None:
        self.stock_repo = stock_repository
        self.sync_use_case = sync_use_case or SyncEquityValuationUseCase(stock_repository)

    def execute(
        self,
        request: BackfillEquityValuationRequest,
    ) -> BackfillEquityValuationResponse:
        """Process bounded batches while retaining the complete repository scope."""
        try:
            years = _validate_positive_int(
                request.years,
                field_name="years",
                maximum=30,
            )
            batch_size = _validate_positive_int(
                request.batch_size,
                field_name="batch_size",
                maximum=5000,
            )
            scope = _freeze_stock_scope(
                self.stock_repo.list_active_stock_codes(),
                maximum_count=None,
            )
            stock_codes = scope.stock_codes

            end_date = date.today()
            start_date = end_date - timedelta(days=years * 366)
            total_batches = (len(stock_codes) + batch_size - 1) // batch_size
            batch_results: list[ValuationPayload] = []
            failed_batches = 0
            succeeded_stock_count = 0
            failed_stock_count = 0
            confirmed_equity_writer_count = 0
            equity_count_known = True
            data_center_processed_count = 0
            data_center_count_known = True
            stored_record_count = 0
            stored_count_known = True
            unavailable_reasons: list[str] = []

            for batch_index in range(total_batches):
                batch_codes = list(
                    stock_codes[batch_index * batch_size : (batch_index + 1) * batch_size]
                )
                try:
                    result = self.sync_use_case.execute(
                        SyncEquityValuationRequest(
                            stock_codes=batch_codes,
                            start_date=start_date,
                            end_date=end_date,
                        )
                    )
                except Exception as exc:
                    logger.warning(
                        "Equity valuation backfill batch outcome unknown: %s",
                        type(exc).__name__,
                    )
                    failed_batches += 1
                    failed_stock_count += len(batch_codes)
                    equity_count_known = False
                    data_center_count_known = False
                    stored_count_known = False
                    unavailable_reasons.append("batch_sync_outcome_unknown")
                    batch_results.append(
                        {
                            "batch": batch_index + 1,
                            "success": False,
                            "synced_count": None,
                            "requested_stock_count": len(batch_codes),
                            "succeeded_stock_count": None,
                            "failed_stock_count": len(batch_codes),
                            "stored_record_count": None,
                            "error": "批次同步结果未知",
                        }
                    )
                    continue
                batch_data = result.data if isinstance(result.data, dict) else None
                raw_synced_count = (
                    _optional_nonnegative_int(batch_data.get("synced_count"))
                    if batch_data is not None
                    else None
                )
                raw_succeeded_count = (
                    _optional_nonnegative_int(batch_data.get("succeeded_stock_count"))
                    if batch_data is not None
                    else None
                )
                raw_failed_count = (
                    _optional_nonnegative_int(batch_data.get("failed_stock_count"))
                    if batch_data is not None
                    else None
                )
                raw_equity_count = (
                    _optional_nonnegative_int(
                        batch_data.get("confirmed_equity_writer_record_count")
                    )
                    if batch_data is not None
                    else None
                )
                raw_data_center_count = (
                    _optional_nonnegative_int(
                        batch_data.get("data_center_confirmed_processed_record_count")
                    )
                    if batch_data is not None
                    else None
                )
                raw_stored_count = (
                    _optional_nonnegative_int(batch_data.get("stored_record_count"))
                    if batch_data is not None
                    else None
                )
                if raw_succeeded_count is None:
                    succeeded_stock_count += len(batch_codes) if result.success else 0
                else:
                    succeeded_stock_count += raw_succeeded_count
                if raw_failed_count is None:
                    failed_stock_count += 0 if result.success else len(batch_codes)
                else:
                    failed_stock_count += raw_failed_count
                if raw_equity_count is None:
                    equity_count_known = False
                else:
                    confirmed_equity_writer_count += raw_equity_count
                if raw_data_center_count is None:
                    data_center_count_known = False
                else:
                    data_center_processed_count += raw_data_center_count
                if raw_stored_count is None:
                    stored_count_known = False
                else:
                    stored_record_count += raw_stored_count
                if batch_data is None:
                    stored_count_known = False
                    unavailable_reasons.append("batch_result_unavailable")
                else:
                    raw_reasons = batch_data.get("stored_record_count_unavailable_reasons")
                    if isinstance(raw_reasons, list):
                        unavailable_reasons.extend(
                            reason for reason in raw_reasons if isinstance(reason, str)
                        )
                    if raw_stored_count is None and (
                        not isinstance(raw_reasons, list) or not raw_reasons
                    ):
                        stored_count_known = False
                        unavailable_reasons.append("batch_stored_count_unavailable")
                if not result.success:
                    failed_batches += 1
                batch_results.append(
                    {
                        "batch": batch_index + 1,
                        "success": result.success,
                        "synced_count": raw_synced_count,
                        "requested_stock_count": len(batch_codes),
                        "succeeded_stock_count": raw_succeeded_count,
                        "failed_stock_count": raw_failed_count,
                        "stored_record_count": raw_stored_count,
                        "data": batch_data,
                        "error": None if result.success else "批次估值同步失败",
                    }
                )

            outcome = (
                "success"
                if failed_batches == 0
                else "partial" if succeeded_stock_count > 0 else "failed"
            )
            unique_reasons = list(dict.fromkeys(unavailable_reasons))
            total_stored_record_count = (
                stored_record_count if stored_count_known and not unique_reasons else None
            )
            data: ValuationPayload = {
                "years": years,
                "batch_size": batch_size,
                "total_batches": total_batches,
                "failed_batches": failed_batches,
                "requested_stock_count": len(stock_codes),
                "succeeded_stock_count": succeeded_stock_count,
                "failed_stock_count": failed_stock_count,
                "outcome": outcome,
                "stored_record_count": total_stored_record_count,
                "confirmed_equity_writer_record_count": confirmed_equity_writer_count,
                "data_center_confirmed_processed_record_count": data_center_processed_count,
                "equity_writer_outcome_unknown": not equity_count_known,
                "data_center_write_outcome_unknown": not data_center_count_known,
                "counts_unavailable": total_stored_record_count is None,
                "stored_record_count_unavailable_reasons": unique_reasons,
                "scope_sha256": scope.identity,
                "scope_count": len(scope.stock_codes),
                "results": batch_results,
            }
            if failed_batches:
                return BackfillEquityValuationResponse(
                    success=False,
                    data=data,
                    error="部分估值回填批次失败",
                )
            return BackfillEquityValuationResponse(success=True, data=data)
        except ValueError as exc:
            logger.warning("Equity valuation backfill rejected: %s", type(exc).__name__)
            return BackfillEquityValuationResponse(success=False, error=str(exc))
        except Exception as exc:
            logger.error("Equity valuation backfill failed: %s", type(exc).__name__)
            return BackfillEquityValuationResponse(
                success=False,
                error="估值数据回填失败",
            )


class GetEquityValuationFreshnessUseCase:
    """Calculate freshness while requiring same-date quality evidence."""

    def __init__(
        self,
        stock_repository: ValuationStockRepositoryProtocol,
        quality_repository: ValuationQualityRepositoryProtocol,
    ) -> None:
        self.stock_repo = stock_repository
        self.quality_repo = quality_repository

    def execute(self) -> GetEquityValuationFreshnessResponse:
        try:
            latest_date = self.stock_repo.get_latest_valuation_date()
            if latest_date is None:
                raise ValueError("未找到估值数据")
            if latest_date > date.today():
                raise ValueError("最新估值日期不能晚于今天")

            latest_snapshot = self.quality_repo.get_latest_snapshot()
            snapshot_date, coverage_ratio, is_gate_passed = _snapshot_summary(latest_snapshot)
            has_current_quality_evidence = snapshot_date == latest_date

            lag_days = (date.today() - latest_date).days
            freshness_status = "fresh"
            if lag_days >= 3:
                freshness_status = "critical"
            elif lag_days >= 2:
                freshness_status = "warning"

            if not has_current_quality_evidence or is_gate_passed is not True:
                freshness_status = "critical"
                coverage_ratio = None
                is_gate_passed = False

            return GetEquityValuationFreshnessResponse(
                success=True,
                data={
                    "latest_trade_date": latest_date.isoformat(),
                    "lag_days": lag_days,
                    "freshness_status": freshness_status,
                    "coverage_ratio": coverage_ratio,
                    "is_gate_passed": is_gate_passed,
                },
            )
        except ValueError as exc:
            logger.warning("Equity valuation freshness rejected: %s", type(exc).__name__)
            return GetEquityValuationFreshnessResponse(
                success=False,
                error=str(exc),
            )
        except Exception as exc:
            logger.error("Equity valuation freshness failed: %s", type(exc).__name__)
            return GetEquityValuationFreshnessResponse(
                success=False,
                error="估值数据新鲜度查询失败",
            )


class GetLatestEquityValuationQualityUseCase:
    """Read the most recent persisted valuation quality snapshot."""

    def __init__(
        self,
        quality_repository: ValuationQualityRepositoryProtocol,
    ) -> None:
        self.quality_repo = quality_repository

    def execute(self) -> GetLatestEquityValuationQualityResponse:
        try:
            snapshot = self.quality_repo.get_latest_snapshot()
            if snapshot is None:
                raise ValueError("尚未生成估值质量快照")
            return GetLatestEquityValuationQualityResponse(
                success=True,
                data=_snapshot_to_dict(snapshot),
            )
        except ValueError as exc:
            logger.warning(
                "Latest equity valuation quality query rejected: %s",
                type(exc).__name__,
            )
            return GetLatestEquityValuationQualityResponse(
                success=False,
                error=str(exc),
            )
        except Exception as exc:
            logger.error(
                "Latest equity valuation quality query failed: %s",
                type(exc).__name__,
            )
            return GetLatestEquityValuationQualityResponse(
                success=False,
                error="最近估值质量快照查询失败",
            )


def _snapshot_to_dict(snapshot: object) -> ValuationPayload:
    """Convert a mapping or ORM-like snapshot into a stable payload."""

    if isinstance(snapshot, Mapping):
        data = {str(key): value for key, value in snapshot.items()}
    else:
        typed_snapshot = cast(ValuationQualitySnapshotProtocol, snapshot)
        data = {
            "as_of_date": typed_snapshot.as_of_date,
            "expected_stock_count": typed_snapshot.expected_stock_count,
            "synced_stock_count": typed_snapshot.synced_stock_count,
            "valid_stock_count": typed_snapshot.valid_stock_count,
            "coverage_ratio": typed_snapshot.coverage_ratio,
            "valid_ratio": typed_snapshot.valid_ratio,
            "missing_pb_count": typed_snapshot.missing_pb_count,
            "invalid_pb_count": typed_snapshot.invalid_pb_count,
            "missing_pe_count": typed_snapshot.missing_pe_count,
            "jump_alert_count": typed_snapshot.jump_alert_count,
            "source_deviation_count": typed_snapshot.source_deviation_count,
            "primary_source": typed_snapshot.primary_source,
            "fallback_used_count": typed_snapshot.fallback_used_count,
            "is_gate_passed": typed_snapshot.is_gate_passed,
            "gate_reason": typed_snapshot.gate_reason,
        }

    as_of_date = data.get("as_of_date")
    if isinstance(as_of_date, date):
        data["as_of_date"] = as_of_date.isoformat()
    return data


def _coerce_snapshot_date(raw_date: object) -> date | None:
    """Parse one snapshot date value."""

    if isinstance(raw_date, date):
        return raw_date
    if isinstance(raw_date, str):
        try:
            return date.fromisoformat(raw_date)
        except ValueError:
            return None
    return None


def _snapshot_summary(snapshot: object | None) -> tuple[date | None, object, object]:
    """Read only freshness fields without requiring a complete snapshot."""

    if snapshot is None:
        return None, None, None
    if isinstance(snapshot, Mapping):
        raw_date = snapshot.get("as_of_date")
        coverage_ratio = snapshot.get("coverage_ratio")
        is_gate_passed = snapshot.get("is_gate_passed")
    else:
        raw_date = getattr(snapshot, "as_of_date", None)
        coverage_ratio = getattr(snapshot, "coverage_ratio", None)
        is_gate_passed = getattr(snapshot, "is_gate_passed", None)
    return _coerce_snapshot_date(raw_date), coverage_ratio, is_gate_passed
