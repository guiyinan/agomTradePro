import logging
import re
from collections.abc import Callable
from typing import TypeAlias, cast

from celery import shared_task
from django.conf import settings

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
_FINANCIAL_CAPACITY_RECEIPT_REQUIRED = "FINANCIAL_CAPACITY_RECEIPT_REQUIRED"


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


def _response_error(value: object, default: str) -> str:
    """Return a bounded response error without stringifying dynamic objects."""

    return value if isinstance(value, str) and value.strip() else default


def _nonnegative_count(value: object) -> int | None:
    """Narrow one optional count without accepting booleans or negative values."""

    if type(value) is not int or value < 0:
        return None
    return value


def _sync_phase_result(data: TaskPayload) -> TaskPayload:
    """Project valuation sync counts with explicit asset and fact semantics."""

    requested = _nonnegative_count(data.get("requested_stock_count"))
    succeeded = _nonnegative_count(data.get("succeeded_stock_count"))
    failed = _nonnegative_count(data.get("failed_stock_count"))
    stored = _nonnegative_count(data.get("stored_record_count"))
    return {
        "phase": "sync",
        "requested": requested,
        "succeeded": succeeded,
        "failed": failed,
        "stored": stored,
        "count_unit": "valuation_asset",
        "stored_count_unit": "canonical_fact_processed",
    }


def _sync_task_fields(data: TaskPayload) -> TaskPayload:
    """Expose sync counts at the task root for Task Monitor projection."""

    phase_result = _sync_phase_result(data)
    raw_unavailable = data.get("counts_unavailable")
    counts_unavailable = (
        raw_unavailable if isinstance(raw_unavailable, bool) else phase_result["stored"] is None
    )
    return {
        "phase": "sync",
        "requested": phase_result["requested"],
        "succeeded": phase_result["succeeded"],
        "failed": phase_result["failed"],
        "stored": phase_result["stored"],
        "count_unit": "valuation_asset",
        "stored_count_unit": "canonical_fact_processed",
        "counts_unavailable": counts_unavailable,
        "phase_results": [phase_result],
    }


def _quality_phase_result(
    *,
    completed: bool,
) -> TaskPayload:
    """Count snapshot evaluation operations, never assets passing quality gates."""
    return {
        "phase": "validate",
        "requested": 1,
        "succeeded": 1 if completed else 0,
        "failed": 0 if completed else 1,
        "stored": None,
        "count_unit": "quality_operation",
        "stored_count_unit": "quality_snapshot",
    }


def _scan_phase_result(
    *,
    scanned_count: object,
    saved_count: object,
    failed_count: object,
    completed: bool,
) -> TaskPayload:
    """Describe repair scans without mixing snapshots into fact-row counts."""

    scanned = _nonnegative_count(scanned_count)
    failed = _nonnegative_count(failed_count)
    succeeded = max(0, scanned - failed) if scanned is not None and failed is not None else None
    return {
        "phase": "scan",
        "requested": scanned,
        "succeeded": succeeded,
        "failed": failed,
        "stored": _nonnegative_count(saved_count) if completed or failed else None,
        "count_unit": "valuation_asset",
        "stored_count_unit": "repair_snapshot",
    }


def _failure_payload(
    error: str,
    *,
    stage: str | None = None,
    include_phase: bool = True,
) -> TaskPayload:
    """Build one stable task failure payload."""

    payload: TaskPayload = {
        "success": False,
        "outcome": TaskBusinessOutcome.FAILED.value,
        "error": error,
    }
    if stage is not None:
        payload["stage"] = stage
        if include_phase:
            payload["phase"] = stage
    return payload


def _financial_capacity_blocked_payload(*, requested_stock_count: int) -> TaskPayload:
    """Return a stable zero-egress response for the retired legacy financial sync lane."""

    return {
        "success": False,
        "outcome": TaskBusinessOutcome.BLOCKED.value,
        "stage": "capacity",
        "error_code": _FINANCIAL_CAPACITY_RECEIPT_REQUIRED,
        "blocked_reason": "financial_capacity_receipt_required",
        "partial_success": False,
        "synced_count": 0,
        "stored_record_count": 0,
        "error_count": 0,
        "requested_stock_count": requested_stock_count,
        "succeeded_stock_count": 0,
        "failed_stock_count": 0,
        "blocked_stock_count": requested_stock_count,
        "must_not_use_for_decision": True,
    }


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
    """Sync the complete repository scope and publish truthful monitored outcomes."""
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
    payload = _copy_payload(response.data)
    if payload is None:
        failure = _failure_payload("估值同步未返回结果", stage="sync")
        failure.update(_sync_task_fields({}))
        return failure
    if payload.get("outcome") == TaskBusinessOutcome.PARTIAL.value:
        payload.update(_sync_task_fields(payload))
        payload["success"] = True
        payload["outcome"] = TaskBusinessOutcome.PARTIAL.value
        return payload
    if not response.success:
        failure = _failure_payload(_response_error(response.error, "估值同步失败"), stage="sync")
        failure["sync"] = payload
        failure.update(_sync_task_fields(payload))
        return failure
    if payload.get("outcome") not in {None, TaskBusinessOutcome.SUCCESS.value}:
        failure = _failure_payload(_response_error(response.error, "估值同步未成功"), stage="sync")
        failure["sync"] = payload
        failure.update(_sync_task_fields(payload))
        return failure
    if not _has_synced_valuation_records(payload):
        failure = _failure_payload(
            _response_error(response.error, "估值同步未写入任何记录"),
            stage="sync",
        )
        failure["sync"] = payload
        failure.update(_sync_task_fields(payload))
        return failure
    payload.update(_sync_task_fields(payload))
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
    """Evaluate scoped quality and keep snapshot write counts explicitly unknown."""
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
        failure = _failure_payload(
            _response_error(response.error, "估值质量校验失败"),
            stage="validate",
        )
        failure.update(
            {
                "requested": 1,
                "succeeded": 0,
                "failed": 1,
                "stored": None,
                "count_unit": "quality_operation",
                "stored_count_unit": "quality_snapshot",
                "counts_unavailable": True,
                "phase_results": [_quality_phase_result(completed=False)],
            }
        )
        return failure
    payload = _copy_payload(response.data)
    if payload is None:
        failure = _failure_payload("估值质量校验未返回结果", stage="validate")
        failure.update(
            {
                "requested": 1,
                "succeeded": 0,
                "failed": 1,
                "stored": None,
                "count_unit": "quality_operation",
                "stored_count_unit": "quality_snapshot",
                "counts_unavailable": True,
                "phase_results": [_quality_phase_result(completed=False)],
            }
        )
        return failure
    quality_phase = _quality_phase_result(completed=True)
    payload.update(
        {
            "phase": "validate",
            "requested": quality_phase["requested"],
            "succeeded": quality_phase["succeeded"],
            "failed": quality_phase["failed"],
            "stored": quality_phase["stored"],
            "count_unit": "quality_operation",
            "stored_count_unit": "quality_snapshot",
            "counts_unavailable": True,
            "phase_results": [quality_phase],
        }
    )
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

    sync_use_case = _make_sync_use_case(stock_repo)
    sync_response = sync_use_case.execute(
        SyncEquityValuationRequest(
            days_back=validated_days_back,
            primary_source=normalized_primary,
            fallback_source=normalized_fallback,
        )
    )
    frozen_scope = sync_response._frozen_scope
    sync_payload = _copy_payload(sync_response.data)
    if sync_payload is None:
        failure = _failure_payload(
            _response_error(sync_response.error, "估值同步未返回结果"),
            stage="sync",
        )
        failure.update(_sync_task_fields({}))
        return failure
    sync_fields = _sync_task_fields(sync_payload)
    sync_phase = _sync_phase_result(sync_payload)
    if sync_payload.get("outcome") == TaskBusinessOutcome.PARTIAL.value:
        return {
            **sync_fields,
            "success": True,
            "outcome": TaskBusinessOutcome.PARTIAL.value,
            "stage": "sync",
            "phase": "sync",
            "sync": sync_payload,
            "scan_skipped": True,
            "error": _response_error(sync_response.error, "估值同步部分失败"),
        }
    if not sync_response.success:
        failure = _failure_payload(
            _response_error(sync_response.error, "估值同步失败"),
            stage="sync",
        )
        failure.update(sync_fields)
        failure["sync"] = sync_payload
        return failure
    if sync_payload.get("outcome") not in {None, TaskBusinessOutcome.SUCCESS.value}:
        failure = _failure_payload(
            _response_error(sync_response.error, "估值同步未成功"),
            stage="sync",
        )
        failure.update(sync_fields)
        failure["sync"] = sync_payload
        return failure
    if not _has_synced_valuation_records(sync_payload):
        failure = _failure_payload(
            _response_error(sync_response.error, "估值同步未写入任何记录"),
            stage="sync",
        )
        failure.update(sync_fields)
        failure["sync"] = sync_payload
        return failure
    if frozen_scope is None:
        failure = _failure_payload("估值同步未返回冻结范围", stage="sync")
        failure.update(sync_fields)
        failure["sync"] = sync_payload
        return failure

    validate_response = _make_validate_use_case(stock_repo, quality_repo).execute(
        ValidateEquityValuationQualityRequest(primary_source=normalized_primary),
        _frozen_scope=frozen_scope,
    )
    if not validate_response.success:
        failure = _failure_payload(
            _response_error(validate_response.error, "估值质量校验失败"),
            stage="validate",
        )
        failure.update(sync_fields)
        failure["phase"] = "validate"
        failure["phase_results"] = [
            sync_phase,
            _quality_phase_result(completed=False),
        ]
        failure["sync"] = sync_payload
        return failure
    validate_payload = _copy_payload(validate_response.data)
    if validate_payload is None:
        failure = _failure_payload("估值质量校验未返回结果", stage="validate")
        failure.update(sync_fields)
        failure["phase"] = "validate"
        failure["phase_results"] = [
            sync_phase,
            _quality_phase_result(completed=False),
        ]
        failure["sync"] = sync_payload
        return failure

    quality_phase = _quality_phase_result(completed=True)

    if validate_payload.get("is_gate_passed") is not True:
        return {
            **sync_fields,
            "success": True,
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "stage": "gate_blocked",
            "phase": "gate_blocked",
            "sync": sync_payload,
            "validate": validate_payload,
            "phase_results": [sync_phase, quality_phase],
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
    scan_outcome = (
        TaskBusinessOutcome.SUCCESS
        if scan_response.success and scan_response.failed_count == 0
        else (
            TaskBusinessOutcome.PARTIAL
            if scan_response.failed_count > 0
            and scan_response.scanned_count > scan_response.failed_count
            else TaskBusinessOutcome.FAILED
        )
    )
    return {
        **sync_fields,
        "success": scan_outcome in {TaskBusinessOutcome.SUCCESS, TaskBusinessOutcome.PARTIAL},
        "outcome": scan_outcome.value,
        "stage": "scan",
        "phase": "scan",
        "sync": sync_payload,
        "validate": validate_payload,
        "phase_results": [
            sync_phase,
            quality_phase,
            _scan_phase_result(
                scanned_count=scan_response.scanned_count,
                saved_count=scan_response.saved_count,
                failed_count=scan_response.failed_count,
                completed=scan_outcome is TaskBusinessOutcome.SUCCESS,
            ),
        ],
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
    """Block legacy fact-sync requests that do not carry a governed capacity receipt."""

    try:
        _normalize_source(source, field_name="source")
        _validate_positive_int(periods, field_name="periods", maximum=40)
        if stock_codes is not None and not isinstance(stock_codes, list):
            raise ValueError("stock_codes 必须是字符串列表")
        if stock_codes is not None and len(stock_codes) > 5000:
            raise ValueError("stock_codes 最多允许 5000 项")
    except ValueError as exc:
        return _failure_payload(str(exc), stage="input", include_phase=False)

    if stock_codes is None:
        return _financial_capacity_blocked_payload(requested_stock_count=0)

    active_stock_codes: list[str] = []
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
        return _failure_payload(str(exc), stage="input", include_phase=False)

    if not active_stock_codes:
        return _failure_payload("没有找到活跃股票", stage="input", include_phase=False)

    return _financial_capacity_blocked_payload(requested_stock_count=len(active_stock_codes))
