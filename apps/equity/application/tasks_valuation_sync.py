import logging
import re
from collections.abc import Callable
from typing import TypeAlias, cast

from celery import shared_task
from django.conf import settings

from apps.data_center.application.dtos import SyncFinancialRequest
from apps.data_center.application.interface_services import (
    get_active_provider_id_by_source,
    make_sync_financial_use_case,
)
from apps.equity.application.repository_provider import (
    get_equity_stock_pool_repository,
    get_equity_stock_repository,
    get_equity_valuation_data_quality_repository,
    get_equity_valuation_repair_repository,
)
from apps.equity.application.use_cases_valuation_repair import (
    ScanValuationRepairsRequest,
    ScanValuationRepairsUseCase,
)
from apps.equity.application.use_cases_valuation_sync import (
    SyncEquityValuationRequest,
    SyncEquityValuationUseCase,
    ValidateEquityValuationQualityRequest,
    ValidateEquityValuationQualityUseCase,
)
from shared.domain.task_outcomes import TaskBusinessOutcome

TaskPayload: TypeAlias = dict[str, object]

logger = logging.getLogger(__name__)

_SOURCE_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
_STOCK_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


def _validate_positive_int(
    value: object,
    *,
    field_name: str,
    maximum: int,
) -> int:
    """Validate one positive bounded integer received from Celery payloads."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} 必须是整数")
    if not 1 <= value <= maximum:
        raise ValueError(f"{field_name} 必须在 1..{maximum} 之间")
    return value


def _normalize_identifier(
    value: object,
    *,
    field_name: str,
    pattern: re.Pattern[str],
    maximum_length: int,
) -> str:
    """Normalize one bounded identifier without hard-coding provider catalogs."""

    if not isinstance(value, str):
        raise ValueError(f"{field_name} 必须是字符串")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum_length or pattern.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} 格式无效")
    return normalized


def _normalize_source(value: object, *, field_name: str) -> str:
    """Normalize a dynamically configured data-source identifier."""

    return _normalize_identifier(
        value,
        field_name=field_name,
        pattern=_SOURCE_PATTERN,
        maximum_length=64,
    ).lower()


def _copy_payload(data: object) -> TaskPayload | None:
    """Copy a use-case payload into the typed Celery response boundary."""

    if not isinstance(data, dict):
        return None
    return {str(key): value for key, value in data.items()}


def _failure_payload(error: str, *, stage: str | None = None) -> TaskPayload:
    """Build one stable task failure payload."""

    payload: TaskPayload = {
        "success": False,
        "outcome": TaskBusinessOutcome.FAILED.value,
        "error": error,
    }
    if stage is not None:
        payload["stage"] = stage
    return payload


def _has_synced_valuation_records(payload: TaskPayload) -> bool:
    """Return whether a valuation sync persisted at least one record."""

    synced_count = payload.get("synced_count")
    return isinstance(synced_count, int) and not isinstance(synced_count, bool) and synced_count > 0


def _make_sync_use_case(stock_repository: object) -> SyncEquityValuationUseCase:
    """Construct a legacy use case through an explicit typed callable boundary."""

    factory = cast(
        Callable[[object], SyncEquityValuationUseCase],
        SyncEquityValuationUseCase,
    )
    return factory(stock_repository)


def _make_validate_use_case(
    stock_repository: object,
    quality_repository: object,
) -> ValidateEquityValuationQualityUseCase:
    """Construct the legacy quality use case through a typed callable boundary."""

    factory = cast(
        Callable[[object, object], ValidateEquityValuationQualityUseCase],
        ValidateEquityValuationQualityUseCase,
    )
    return factory(stock_repository, quality_repository)


def _make_scan_use_case(
    stock_repository: object,
    valuation_repair_repository: object,
    stock_pool_adapter: object,
    valuation_quality_repository: object,
) -> ScanValuationRepairsUseCase:
    """Construct the legacy scan use case through a typed callable boundary."""

    factory = cast(
        Callable[[object, object, object, object], ScanValuationRepairsUseCase],
        ScanValuationRepairsUseCase,
    )
    return factory(
        stock_repository,
        valuation_repair_repository,
        stock_pool_adapter,
        valuation_quality_repository,
    )


@shared_task(  # type: ignore[misc]
    time_limit=getattr(settings, "EQUITY_VALUATION_SYNC_TASK_TIMEOUT", 3600),
    soft_time_limit=getattr(settings, "EQUITY_VALUATION_SYNC_TASK_SOFT_TIMEOUT", 3500),
)
def sync_equity_valuation_task(
    days_back: int = 1, primary_source: str = "akshare", fallback_source: str = "tushare"
) -> TaskPayload:
    try:
        validated_days_back = _validate_positive_int(
            days_back,
            field_name="days_back",
            maximum=3660,
        )
        normalized_primary = _normalize_source(primary_source, field_name="primary_source")
        normalized_fallback = _normalize_source(fallback_source, field_name="fallback_source")
    except ValueError as exc:
        return _failure_payload(str(exc), stage="input")

    use_case = _make_sync_use_case(get_equity_stock_repository())
    response = use_case.execute(
        SyncEquityValuationRequest(
            days_back=validated_days_back,
            primary_source=normalized_primary,
            fallback_source=normalized_fallback,
        )
    )
    if not response.success:
        return _failure_payload(response.error or "估值同步失败", stage="sync")
    payload = _copy_payload(response.data)
    if payload is None:
        return _failure_payload("估值同步未返回结果", stage="sync")
    if not _has_synced_valuation_records(payload):
        return {
            "success": False,
            "outcome": TaskBusinessOutcome.FAILED.value,
            "stage": "sync",
            "error": "估值同步未写入任何记录",
            "sync": payload,
        }
    payload["success"] = True
    payload["outcome"] = TaskBusinessOutcome.SUCCESS.value
    return payload


@shared_task(  # type: ignore[misc]
    time_limit=getattr(settings, "EQUITY_VALUATION_VALIDATE_TASK_TIMEOUT", 600),
    soft_time_limit=getattr(settings, "EQUITY_VALUATION_VALIDATE_TASK_SOFT_TIMEOUT", 570),
)
def validate_equity_valuation_quality_task(
    primary_source: str = "akshare",
) -> TaskPayload:
    try:
        normalized_primary = _normalize_source(primary_source, field_name="primary_source")
    except ValueError as exc:
        return _failure_payload(str(exc), stage="input")

    use_case = _make_validate_use_case(
        get_equity_stock_repository(),
        get_equity_valuation_data_quality_repository(),
    )
    response = use_case.execute(
        ValidateEquityValuationQualityRequest(primary_source=normalized_primary)
    )
    if not response.success:
        return _failure_payload(response.error or "估值质量校验失败", stage="validate")
    payload = _copy_payload(response.data)
    if payload is None:
        return _failure_payload("估值质量校验未返回结果", stage="validate")
    payload["success"] = True
    payload["outcome"] = TaskBusinessOutcome.SUCCESS.value
    return payload


@shared_task(  # type: ignore[misc]
    time_limit=getattr(settings, "EQUITY_VALUATION_SCAN_TASK_TIMEOUT", 3600),
    soft_time_limit=getattr(settings, "EQUITY_VALUATION_SCAN_TASK_SOFT_TIMEOUT", 3500),
)
def sync_validate_scan_equity_valuation_task(
    days_back: int = 1,
    primary_source: str = "akshare",
    fallback_source: str = "tushare",
    universe: str = "all_active",
    lookback_days: int | None = None,
) -> TaskPayload:
    """日常编排任务：同步 -> 质量校验 -> gate通过才scan。"""
    try:
        validated_days_back = _validate_positive_int(
            days_back,
            field_name="days_back",
            maximum=3660,
        )
        normalized_primary = _normalize_source(primary_source, field_name="primary_source")
        normalized_fallback = _normalize_source(fallback_source, field_name="fallback_source")
        normalized_universe = _normalize_identifier(
            universe,
            field_name="universe",
            pattern=_SOURCE_PATTERN,
            maximum_length=64,
        )
        raw_lookback_days: object = (
            lookback_days
            if lookback_days is not None
            else getattr(settings, "EQUITY_VALUATION_DEFAULT_LOOKBACK_DAYS", 756)
        )
        validated_lookback_days = _validate_positive_int(
            raw_lookback_days,
            field_name="lookback_days",
            maximum=5000,
        )
    except ValueError as exc:
        return _failure_payload(str(exc), stage="input")

    stock_repo = get_equity_stock_repository()
    quality_repo = get_equity_valuation_data_quality_repository()

    sync_response = _make_sync_use_case(stock_repo).execute(
        SyncEquityValuationRequest(
            days_back=validated_days_back,
            primary_source=normalized_primary,
            fallback_source=normalized_fallback,
        )
    )
    if not sync_response.success:
        return _failure_payload(sync_response.error or "估值同步失败", stage="sync")
    sync_payload = _copy_payload(sync_response.data)
    if sync_payload is None:
        return _failure_payload("估值同步未返回结果", stage="sync")
    if not _has_synced_valuation_records(sync_payload):
        return {
            "success": False,
            "outcome": TaskBusinessOutcome.FAILED.value,
            "stage": "sync",
            "error": "估值同步未写入任何记录",
            "sync": sync_payload,
        }

    validate_response = _make_validate_use_case(stock_repo, quality_repo).execute(
        ValidateEquityValuationQualityRequest(primary_source=normalized_primary)
    )
    if not validate_response.success:
        return {
            "success": False,
            "outcome": TaskBusinessOutcome.FAILED.value,
            "stage": "validate",
            "sync": sync_payload,
            "error": validate_response.error or "估值质量校验失败",
        }
    validate_payload = _copy_payload(validate_response.data)
    if validate_payload is None:
        return {
            "success": False,
            "outcome": TaskBusinessOutcome.FAILED.value,
            "stage": "validate",
            "sync": sync_payload,
            "error": "估值质量校验未返回结果",
        }

    if validate_payload.get("is_gate_passed") is not True:
        return {
            "success": True,
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "stage": "gate_blocked",
            "sync": sync_payload,
            "validate": validate_payload,
            "scan_skipped": True,
        }

    scan_response = _make_scan_use_case(
        stock_repo,
        get_equity_valuation_repair_repository(),
        get_equity_stock_pool_repository(),
        quality_repo,
    ).execute(
        ScanValuationRepairsRequest(
            universe=normalized_universe,
            lookback_days=validated_lookback_days,
        )
    )
    return {
        "success": scan_response.success,
        "outcome": (
            TaskBusinessOutcome.SUCCESS.value
            if scan_response.success
            else TaskBusinessOutcome.FAILED.value
        ),
        "stage": "scan",
        "sync": sync_payload,
        "validate": validate_payload,
        "scan": {
            "universe": scan_response.universe,
            "as_of_date": scan_response.as_of_date.isoformat(),
            "scanned_count": scan_response.scanned_count,
            "saved_count": scan_response.saved_count,
            "failed_count": scan_response.failed_count,
            "phase_counts": scan_response.phase_counts,
            "error": scan_response.error,
        },
    }


@shared_task(  # type: ignore[misc]
    time_limit=getattr(settings, "EQUITY_FINANCIAL_SYNC_TASK_TIMEOUT", 3600),
    soft_time_limit=getattr(settings, "EQUITY_FINANCIAL_SYNC_TASK_SOFT_TIMEOUT", 3500),
)
def sync_financial_data_task(
    source: str = "akshare",
    periods: int = 8,
    stock_codes: list[str] | None = None,
) -> TaskPayload:
    """
    同步财务数据

    Args:
        source: 数据源（akshare 或 tushare）
        periods: 获取最近几个报告期
        stock_codes: 指定股票代码列表（None 表示全部活跃股票）
    """
    try:
        normalized_source = _normalize_source(source, field_name="source")
        validated_periods = _validate_positive_int(
            periods,
            field_name="periods",
            maximum=40,
        )
        if stock_codes is not None and not isinstance(stock_codes, list):
            raise ValueError("stock_codes 必须是字符串列表")
        if stock_codes is not None and len(stock_codes) > 5000:
            raise ValueError("stock_codes 最多允许 5000 项")
    except ValueError as exc:
        return _failure_payload(str(exc), stage="input")

    stock_repo = get_equity_stock_repository()
    if stock_codes is None:
        active_stock_codes = stock_repo.list_active_stock_codes()
    else:
        active_stock_codes = []
        seen_codes: set[str] = set()
        try:
            for stock_code in stock_codes:
                normalized = _normalize_identifier(
                    stock_code,
                    field_name="stock_code",
                    pattern=_STOCK_CODE_PATTERN,
                    maximum_length=32,
                ).upper()
                if normalized not in seen_codes:
                    seen_codes.add(normalized)
                    active_stock_codes.append(normalized)
        except ValueError as exc:
            return _failure_payload(str(exc), stage="input")

    if not active_stock_codes:
        return _failure_payload("没有找到活跃股票", stage="input")

    provider_id = get_active_provider_id_by_source(normalized_source)
    if provider_id is None:
        return _failure_payload(
            f"未找到启用的数据源: {normalized_source}",
            stage="input",
        )

    sync_use_case = make_sync_financial_use_case()
    synced_count = 0
    error_count = 0
    errors: list[str] = []

    for stock_code in active_stock_codes:
        try:
            result = sync_use_case.execute(
                SyncFinancialRequest(
                    provider_id=provider_id,
                    asset_code=stock_code,
                    periods=validated_periods,
                )
            )
            stored_count = result.stored_count
            if (
                isinstance(stored_count, bool)
                or not isinstance(stored_count, int)
                or stored_count < 0
            ):
                raise ValueError("同步结果 stored_count 无效")
            synced_count += stored_count
        except Exception as exc:
            error_count += 1
            logger.warning(
                "Financial data sync failed for %s: %s",
                stock_code,
                type(exc).__name__,
            )
            if len(errors) < 10:  # 只记录前 10 个错误
                errors.append(f"{stock_code}: 同步失败")

    total_stocks = len(active_stock_codes)
    succeeded_stock_count = total_stocks - error_count
    is_partial = 0 < error_count < total_stocks
    if error_count == total_stocks:
        outcome = TaskBusinessOutcome.FAILED
    elif is_partial:
        outcome = TaskBusinessOutcome.PARTIAL
    elif synced_count == 0:
        outcome = TaskBusinessOutcome.NOOP
    else:
        outcome = TaskBusinessOutcome.SUCCESS

    payload: TaskPayload = {
        "success": outcome is not TaskBusinessOutcome.FAILED,
        "outcome": outcome.value,
        "partial_success": is_partial,
        "synced_count": synced_count,
        "stored_record_count": synced_count,
        "error_count": error_count,
        "total_stocks": total_stocks,
        "requested_stock_count": total_stocks,
        "succeeded_stock_count": succeeded_stock_count,
        "failed_stock_count": error_count,
        "errors": errors,
    }
    if outcome is TaskBusinessOutcome.NOOP:
        payload["noop_reason"] = "provider completed without new financial records"
    return payload
