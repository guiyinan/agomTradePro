"""Celery tasks for keeping market thermometer snapshots fresh."""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from celery import shared_task
from django.core.cache import cache
from django.utils import timezone

from apps.data_center.composition import (
    get_archive_coverage_gateway,
    get_raw_landing_repository,
    get_retention_policy_repository,
    get_retention_run_repository,
    get_storage_hold_repository,
    get_sync_batch_repository,
    get_sync_checkpoint_repository,
    get_sync_run_repository,
)
from apps.data_center.domain.control_plane import (
    SyncBatch,
    SyncCheckpoint,
    SyncItemState,
    SyncRun,
    SyncRunStatus,
)
from core.integration.config_center_runtime import evaluate_storage_pressure
from shared.domain.task_outcomes import TaskBusinessOutcome
from shared.infrastructure.operational_alert_registry import record_operational_alert

from .archive_tasks import verify_archive_manifest_task  # noqa: F401
from .dtos import (
    SyncFinancialRequest,
    SyncPriceRequest,
    SyncQuoteRequest,
    SyncResult,
)
from .interface_services import (
    get_active_provider_id_by_source,
    make_calculate_market_thermometer_use_case,
    make_sync_current_valuation_batch_use_case,
    make_sync_financial_use_case,
    make_sync_market_thermometer_inputs_use_case,
    make_sync_price_use_case,
    make_sync_quote_use_case,
    refresh_decision_quote_snapshots,
)
from .market_thermometer_dates import resolve_market_thermometer_as_of_date
from .query_services import list_active_stock_codes_for_backfill
from .query_use_cases import latest_completed_cn_market_session
from .retention import RetentionCleanupUseCase

logger = logging.getLogger(__name__)

DECISION_QUOTE_DEGRADED_STREAK_KEY = "task_monitor:decision_quote_degraded_streak:v1"
BACKFILL_DATASET_KEY = "equity.core.backfill"
BACKFILL_TASK_NAME = "celery.backfill_a_share_core"


def _backfill_idempotency_key(
    source: object,
    offset: object,
    batch_size: object,
    history_days: object,
    financial_periods: object,
) -> str:
    """Build a bounded, deterministic key for one requested backfill window.

    The visible portion keeps the dataset/source/offset/window dimensions
    operator-readable.  A digest retains the complete raw request for invalid
    inputs without exceeding the database's 240-character key limit.
    """

    try:
        source_text = str(source or "").strip().lower() or "unknown"
    except Exception:
        source_text = "unknown"
    source_text = source_text[:32]
    material = "|".join(
        (
            BACKFILL_DATASET_KEY,
            f"source={source!r}",
            f"offset={offset!r}",
            f"batch_size={batch_size!r}",
            f"history_days={history_days!r}",
            f"financial_periods={financial_periods!r}",
        )
    )
    digest = hashlib.sha256(material.encode("utf-8", errors="replace")).hexdigest()[:16]
    visible = (
        f"{BACKFILL_DATASET_KEY}:{source_text}:"
        f"offset={str(offset)[:24]}:"
        f"window={str(batch_size)[:24]}"
    )
    return f"{visible}:{digest}"


def _backfill_control_plane_ids(idempotency_key: str) -> tuple[str, str]:
    """Return stable run and batch UUIDs for one idempotent task window."""

    run_id = str(uuid5(NAMESPACE_URL, f"agomtradepro:sync-run:{idempotency_key}"))
    batch_id = str(uuid5(NAMESPACE_URL, f"agomtradepro:sync-batch:{idempotency_key}"))
    return run_id, batch_id


def _backfill_sync_status(
    outcome: TaskBusinessOutcome,
    *,
    published: int,
) -> tuple[SyncRunStatus, SyncItemState]:
    """Map task business outcomes to durable control-plane lifecycle states."""

    if outcome is TaskBusinessOutcome.SUCCESS:
        return (
            SyncRunStatus.PUBLISHED if published > 0 else SyncRunStatus.STORED,
            SyncItemState.SUCCEEDED,
        )
    if outcome is TaskBusinessOutcome.NOOP:
        return SyncRunStatus.STORED, SyncItemState.SKIPPED
    if outcome is TaskBusinessOutcome.BLOCKED:
        return SyncRunStatus.BLOCKED, SyncItemState.FAILED
    if outcome is TaskBusinessOutcome.PARTIAL:
        return SyncRunStatus.STORED, SyncItemState.FAILED
    return SyncRunStatus.FAILED, SyncItemState.FAILED


def _published_count_from_result(result: object) -> int:
    """Extract an optional publication count without inventing one.

    Current domain sync DTOs expose ``stored_count`` only, so the durable
    control-plane record deliberately persists zero until a result or attached
    publication explicitly exposes a selected member count.
    """

    for candidate in (
        getattr(result, "published_count", None),
        getattr(result, "published", None),
    ):
        if isinstance(candidate, int) and not isinstance(candidate, bool) and candidate >= 0:
            return candidate
    publication = getattr(result, "publication", None)
    member_count = getattr(publication, "member_count", None)
    if isinstance(member_count, int) and not isinstance(member_count, bool) and member_count >= 0:
        return member_count
    return 0


def _persist_backfill_control_plane(
    *,
    idempotency_key: str,
    provider_name: str,
    outcome: TaskBusinessOutcome,
    requested: int,
    succeeded: int,
    failed: int,
    stored: int,
    published: int,
    checkpoint: Mapping[str, object],
    window_start: date | None,
    window_end: date | None,
    started_at: datetime,
    error_code: str = "",
    error_message: str = "",
) -> None:
    """Persist one backfill run, batch and cursor using application ports.

    Repository ``save`` methods are update-or-create operations, so Celery
    retries converge on the same rows identified by the deterministic UUIDs
    and idempotency key instead of creating duplicate batches.
    """

    finished_at = datetime.now(UTC)
    run_id, batch_id = _backfill_control_plane_ids(idempotency_key)
    run_status, batch_state = _backfill_sync_status(outcome, published=published)
    if run_status is SyncRunStatus.BLOCKED and not error_code:
        error_code = "blocked"
    elif outcome is TaskBusinessOutcome.FAILED and not error_code:
        error_code = "failed"
    elif outcome is TaskBusinessOutcome.PARTIAL and not error_code:
        error_code = "partial_failure"
    run = SyncRun(
        run_id=run_id,
        dataset_key=BACKFILL_DATASET_KEY,
        trigger=BACKFILL_TASK_NAME,
        status=run_status,
        outcome=outcome.value,
        requested=requested,
        fetched=stored,
        validated=succeeded,
        succeeded=succeeded,
        failed=failed,
        stored=stored,
        published=published,
        provider_name=provider_name or "unknown",
        contract_version="1.0",
        started_at=started_at,
        finished_at=finished_at,
        error_code=error_code,
        error_message=error_message,
    )
    batch = SyncBatch(
        batch_id=batch_id,
        run_id=run_id,
        dataset_key=BACKFILL_DATASET_KEY,
        provider_name=provider_name or "unknown",
        idempotency_key=idempotency_key,
        state=batch_state,
        requested=requested,
        fetched=stored,
        validated=succeeded,
        succeeded=succeeded,
        failed=failed,
        stored=stored,
        published=published,
        window_start=window_start,
        window_end=window_end,
        started_at=started_at,
        finished_at=finished_at,
        error_code=error_code,
        error_message=error_message,
    )
    cursor_value = json.dumps(checkpoint, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    checkpoint_id = str(
        uuid5(NAMESPACE_URL, f"agomtradepro:sync-checkpoint:{batch_id}:asset_offset:{cursor_value}")
    )
    checkpoint_state = (
        SyncItemState.SUCCEEDED
        if outcome in {TaskBusinessOutcome.SUCCESS, TaskBusinessOutcome.NOOP}
        else SyncItemState.FAILED
    )
    durable_checkpoint = SyncCheckpoint(
        checkpoint_id=checkpoint_id,
        run_id=run_id,
        batch_id=batch_id,
        cursor_name="asset_offset",
        cursor_value=cursor_value,
        state=checkpoint_state,
        processed=succeeded,
        failed=failed,
        recorded_at=finished_at,
        error_code=error_code,
    )
    get_sync_run_repository().save(run)
    get_sync_batch_repository().save(batch)
    get_sync_checkpoint_repository().save(durable_checkpoint)


def _resolve_market_thermometer_as_of_date(raw_as_of_date: str = "") -> date:
    """Backward-compatible wrapper for existing tests and call sites."""

    return resolve_market_thermometer_as_of_date(raw_as_of_date)


@shared_task(  # type: ignore[misc]
    name="apps.data_center.application.tasks.refresh_market_thermometer_task",
    time_limit=1800,
    soft_time_limit=1700,
)
def refresh_market_thermometer_task(as_of_date: str = "") -> dict[str, Any]:
    """Sync thermometer inputs and persist one fresh snapshot."""

    target_date = resolve_market_thermometer_as_of_date(as_of_date)
    sync_payload = make_sync_market_thermometer_inputs_use_case().execute(as_of_date=target_date)
    snapshot = make_calculate_market_thermometer_use_case().execute(as_of_date=target_date)
    payload = snapshot.to_dict()
    logger.info(
        "Market thermometer refreshed for %s with score=%s valid_components=%s data_source=%s",
        target_date.isoformat(),
        payload["score"],
        payload["valid_component_count"],
        payload["data_source"],
    )
    return {
        "success": not bool(payload.get("must_not_use_for_decision")),
        "outcome": (
            TaskBusinessOutcome.BLOCKED.value
            if payload.get("must_not_use_for_decision")
            else TaskBusinessOutcome.SUCCESS.value
        ),
        "as_of_date": target_date.isoformat(),
        "sync": sync_payload,
        "snapshot": payload,
    }


@shared_task(  # type: ignore[misc]
    name="apps.data_center.application.tasks.refresh_decision_quote_snapshots_task",
    time_limit=900,
    soft_time_limit=840,
)
def refresh_decision_quote_snapshots_task(
    asset_codes: list[str] | None = None,
    quote_max_age_hours: float | None = None,
) -> dict[str, Any]:
    """Refresh quote snapshots required by decision-grade outputs."""

    payload = refresh_decision_quote_snapshots(
        asset_codes=asset_codes,
        quote_max_age_hours=quote_max_age_hours,
    )
    logger.info(
        "Decision quote snapshots refreshed status=%s synced=%s blocked=%s",
        payload["status"],
        payload["synced_count"],
        payload["must_not_use_for_decision"],
    )
    readiness = payload.get("readiness") or {}
    thermometer = readiness.get("market_thermometer") or {}
    degraded = bool(
        payload.get("degraded")
        or thermometer.get("data_source") == "degraded"
        or readiness.get("data_source") == "degraded"
    )
    blocked = bool(payload.get("must_not_use_for_decision"))
    if degraded or blocked:
        streak = int(cache.get(DECISION_QUOTE_DEGRADED_STREAK_KEY, 0) or 0) + 1
        cache.set(DECISION_QUOTE_DEGRADED_STREAK_KEY, streak, timeout=7 * 86400)
        if blocked or streak == 3:
            record_operational_alert(
                level="critical" if blocked else "warning",
                task_name=(
                    "apps.data_center.application.tasks.refresh_decision_quote_snapshots_task"
                ),
                title=(
                    "Decision quote data is blocked"
                    if blocked
                    else "Decision quote data degraded for three consecutive runs"
                ),
                message=(
                    "Decision-grade quote refresh requires operator review."
                    if blocked
                    else "Fallback data remained active for three consecutive refreshes."
                ),
                metadata={
                    "degraded_streak": streak,
                    "must_not_use_for_decision": blocked,
                    "asset_codes": payload.get("asset_codes") or asset_codes or [],
                },
            )
    else:
        cache.delete(DECISION_QUOTE_DEGRADED_STREAK_KEY)
    payload["degraded"] = degraded
    payload["success"] = not blocked
    payload["outcome"] = (
        TaskBusinessOutcome.BLOCKED.value
        if blocked
        else (TaskBusinessOutcome.PARTIAL.value if degraded else TaskBusinessOutcome.SUCCESS.value)
    )
    return payload


def _validated_backfill_int(
    value: object,
    *,
    field_name: str,
    minimum: int,
    maximum: int,
) -> int:
    """Validate a bounded integer at the Celery task boundary."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{field_name} must be between {minimum} and {maximum}")
    return value


@shared_task(  # type: ignore[misc]
    name="apps.data_center.application.tasks.backfill_active_a_share_core_data_batch_task",
    time_limit=3600,
    soft_time_limit=3500,
)
def backfill_active_a_share_core_data_batch_task(
    *,
    offset: int = 0,
    batch_size: int = 50,
    source: str = "tushare",
    history_days: int = 756,
    financial_periods: int = 8,
) -> dict[str, Any]:
    """Backfill one resumable active-A-share core-data batch."""

    started_at = datetime.now(UTC)
    idempotency_key = _backfill_idempotency_key(
        source,
        offset,
        batch_size,
        history_days,
        financial_periods,
    )
    try:
        validated_offset = _validated_backfill_int(
            offset,
            field_name="offset",
            minimum=0,
            maximum=100_000,
        )
        validated_batch_size = _validated_backfill_int(
            batch_size,
            field_name="batch_size",
            minimum=1,
            maximum=200,
        )
        validated_history_days = _validated_backfill_int(
            history_days,
            field_name="history_days",
            minimum=30,
            maximum=3660,
        )
        validated_periods = _validated_backfill_int(
            financial_periods,
            field_name="financial_periods",
            minimum=1,
            maximum=40,
        )
        normalized_source = str(source or "").strip().lower()
        if not normalized_source or len(normalized_source) > 32:
            raise ValueError("source must be a non-empty identifier")
    except ValueError as exc:
        checkpoint = {
            "offset": 0,
            "next_offset": 0,
            "total_assets": 0,
            "complete": False,
        }
        return {
            "success": False,
            "outcome": TaskBusinessOutcome.FAILED.value,
            "stage": "input",
            "error": str(exc),
            "requested": 0,
            "succeeded": 0,
            "failed": 0,
            "stored": 0,
            "checkpoint": checkpoint,
        }

    asset_codes = list_active_stock_codes_for_backfill()
    total_assets = len(asset_codes)
    batch_codes = asset_codes[validated_offset : validated_offset + validated_batch_size]
    next_offset = validated_offset + len(batch_codes)
    checkpoint = {
        "offset": validated_offset,
        "next_offset": next_offset,
        "total_assets": total_assets,
        "complete": next_offset >= total_assets,
    }
    if not batch_codes:
        _persist_backfill_control_plane(
            idempotency_key=idempotency_key,
            provider_name=normalized_source,
            outcome=TaskBusinessOutcome.NOOP,
            requested=0,
            succeeded=0,
            failed=0,
            stored=0,
            published=0,
            checkpoint=checkpoint,
            window_start=None,
            window_end=None,
            started_at=started_at,
        )
        return {
            "success": True,
            "outcome": TaskBusinessOutcome.NOOP.value,
            "stage": "complete",
            "requested": 0,
            "succeeded": 0,
            "failed": 0,
            "stored": 0,
            "noop_reason": "no remaining active A-share assets",
            "checkpoint": checkpoint,
        }

    provider_id = get_active_provider_id_by_source(normalized_source)
    if provider_id is None:
        failed_count = len(batch_codes)
        blocked_checkpoint = {**checkpoint, "complete": False}
        _persist_backfill_control_plane(
            idempotency_key=idempotency_key,
            provider_name=normalized_source,
            outcome=TaskBusinessOutcome.FAILED,
            requested=failed_count,
            succeeded=0,
            failed=failed_count,
            stored=0,
            published=0,
            checkpoint=blocked_checkpoint,
            window_start=None,
            window_end=None,
            started_at=started_at,
            error_code="provider_unavailable",
            error_message=f"no active provider for source: {normalized_source}",
        )
        return {
            "success": False,
            "outcome": TaskBusinessOutcome.FAILED.value,
            "stage": "provider",
            "error": f"no active provider for source: {normalized_source}",
            "requested": failed_count,
            "succeeded": 0,
            "failed": failed_count,
            "stored": 0,
            "checkpoint": blocked_checkpoint,
        }

    end_date = latest_completed_cn_market_session(timezone.now())
    if end_date is None:
        failed_count = len(batch_codes)
        blocked_checkpoint = {**checkpoint, "complete": False}
        _persist_backfill_control_plane(
            idempotency_key=idempotency_key,
            provider_name=normalized_source,
            outcome=TaskBusinessOutcome.BLOCKED,
            requested=failed_count,
            succeeded=0,
            failed=failed_count,
            stored=0,
            published=0,
            checkpoint=blocked_checkpoint,
            window_start=None,
            window_end=None,
            started_at=started_at,
            error_code="market_calendar_unavailable",
            error_message="latest completed China market session is unavailable",
        )
        return {
            "success": False,
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "stage": "market_calendar",
            "error": "latest completed China market session is unavailable",
            "requested": failed_count,
            "succeeded": 0,
            "failed": failed_count,
            "stored": 0,
            "checkpoint": blocked_checkpoint,
        }
    start_date = end_date - timedelta(days=validated_history_days)
    quote_use_case = make_sync_quote_use_case()
    price_use_case = make_sync_price_use_case()
    valuation_batch_use_case = make_sync_current_valuation_batch_use_case()
    financial_use_case = make_sync_financial_use_case()

    domain_counts: dict[str, dict[str, int]] = {
        name: {"requested": len(batch_codes), "succeeded": 0, "failed": 0, "stored": 0}
        for name in ("quote", "price", "valuation", "financial")
    }
    published_total = 0
    errors: list[dict[str, str]] = []
    failed_asset_codes: set[str] = set()
    try:
        quote_result = quote_use_case.execute(
            SyncQuoteRequest(provider_id=provider_id, asset_codes=batch_codes)
        )
        published_total += _published_count_from_result(quote_result)
        quote_stored = int(quote_result.stored_count)
        domain_counts["quote"]["stored"] = quote_stored
        domain_counts["quote"]["succeeded"] = min(quote_stored, len(batch_codes))
        domain_counts["quote"]["failed"] = max(len(batch_codes) - quote_stored, 0)
    except Exception:
        domain_counts["quote"]["failed"] = len(batch_codes)
        errors.append({"domain": "quote", "asset_code": "batch", "error": "sync_failed"})

    try:
        valuation_result = valuation_batch_use_case.execute(
            provider_id=provider_id,
            asset_codes=batch_codes,
            as_of_date=end_date,
        )
        published_total += _published_count_from_result(valuation_result)
        valuation_succeeded = set(valuation_result.succeeded_asset_codes)
        valuation_missing = set(batch_codes) - valuation_succeeded
        domain_counts["valuation"]["stored"] = int(valuation_result.stored_count)
        domain_counts["valuation"]["succeeded"] = len(valuation_succeeded)
        domain_counts["valuation"]["failed"] = len(valuation_missing)
        failed_asset_codes.update(valuation_missing)
        for asset_code in sorted(valuation_missing)[:20]:
            errors.append({"domain": "valuation", "asset_code": asset_code, "error": "zero_output"})
    except Exception:
        domain_counts["valuation"]["failed"] = len(batch_codes)
        failed_asset_codes.update(batch_codes)
        errors.append({"domain": "valuation", "asset_code": "batch", "error": "sync_failed"})

    for asset_code in batch_codes:
        domain_names = ("price", "financial")
        for domain_name in domain_names:
            try:
                result: SyncResult
                if domain_name == "price":
                    result = price_use_case.execute(
                        SyncPriceRequest(
                            provider_id=provider_id,
                            asset_code=asset_code,
                            start=start_date,
                            end=end_date,
                        )
                    )
                else:
                    result = financial_use_case.execute(
                        SyncFinancialRequest(
                            provider_id=provider_id,
                            asset_code=asset_code,
                            periods=validated_periods,
                        )
                    )
                published_total += _published_count_from_result(result)
                stored_count = int(result.stored_count)
                domain_counts[domain_name]["stored"] += stored_count
                if stored_count > 0:
                    domain_counts[domain_name]["succeeded"] += 1
                else:
                    domain_counts[domain_name]["failed"] += 1
                    failed_asset_codes.add(asset_code)
                    if len(errors) < 20:
                        errors.append(
                            {
                                "domain": domain_name,
                                "asset_code": asset_code,
                                "error": "zero_output",
                            }
                        )
            except Exception:
                domain_counts[domain_name]["failed"] += 1
                failed_asset_codes.add(asset_code)
                if len(errors) < 20:
                    errors.append(
                        {
                            "domain": domain_name,
                            "asset_code": asset_code,
                            "error": "sync_failed",
                        }
                    )
    quote_missing = domain_counts["quote"]["failed"]
    failed_total = max(len(failed_asset_codes), quote_missing)
    succeeded_total = max(len(batch_codes) - failed_total, 0)
    stored_total = sum(item["stored"] for item in domain_counts.values())
    if failed_total == len(batch_codes):
        outcome = TaskBusinessOutcome.FAILED
    elif failed_total > 0:
        outcome = TaskBusinessOutcome.PARTIAL
    elif stored_total == 0:
        outcome = TaskBusinessOutcome.NOOP
    else:
        outcome = TaskBusinessOutcome.SUCCESS

    _persist_backfill_control_plane(
        idempotency_key=idempotency_key,
        provider_name=normalized_source,
        outcome=outcome,
        requested=len(batch_codes),
        succeeded=succeeded_total,
        failed=failed_total,
        stored=stored_total,
        published=published_total,
        checkpoint=checkpoint,
        window_start=start_date,
        window_end=end_date,
        started_at=started_at,
        error_code=(
            "zero_output"
            if outcome is TaskBusinessOutcome.FAILED and stored_total == 0
            else ("partial_failure" if outcome is TaskBusinessOutcome.PARTIAL else "")
        ),
        error_message=(errors[0]["error"] if errors else ""),
    )
    return {
        "success": outcome not in {TaskBusinessOutcome.FAILED, TaskBusinessOutcome.BLOCKED},
        "outcome": outcome.value,
        "stage": "batch",
        "source": normalized_source,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "asset_codes": batch_codes,
        "requested": len(batch_codes),
        "succeeded": succeeded_total,
        "failed": failed_total,
        "stored": stored_total,
        "published": published_total,
        "domains": domain_counts,
        "errors": errors,
        "checkpoint": checkpoint,
    }


def _retention_failure(
    *,
    operation: str,
    requested: int,
    error: str,
) -> dict[str, object]:
    """Build a stable failed retention-task contract without mutating data."""

    return {
        "success": False,
        "outcome": TaskBusinessOutcome.FAILED.value,
        "operation": operation,
        "requested": requested,
        "candidates": 0,
        "planned": 0,
        "deleted": 0,
        "held": 0,
        "blocked": 0,
        "bytes_planned": 0,
        "bytes_deleted": 0,
        "error": error,
    }


def _run_retention_pass(
    *,
    dataset_key: object,
    limit: object,
    dry_run: object,
    operation: str,
    confirm: object = True,
) -> dict[str, object]:
    """Run one bounded retention pass with task-boundary fail-closed guards."""

    if not isinstance(dataset_key, str) or not dataset_key.strip():
        return _retention_failure(operation=operation, requested=0, error="dataset_key is required")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10_000:
        return _retention_failure(
            operation=operation,
            requested=0,
            error="limit must be between 1 and 10000",
        )
    if not isinstance(dry_run, bool):
        return _retention_failure(
            operation=operation,
            requested=limit,
            error="dry_run must be a boolean",
        )
    if not isinstance(confirm, bool):
        return _retention_failure(
            operation=operation,
            requested=limit,
            error="confirm must be a boolean",
        )
    if operation == "enforce" and not dry_run and not confirm:
        return {
            "success": False,
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "operation": operation,
            "requested": limit,
            "candidates": 0,
            "planned": 0,
            "deleted": 0,
            "held": 0,
            "blocked": 0,
            "bytes_planned": 0,
            "bytes_deleted": 0,
            "error": "explicit_confirmation_required",
        }

    try:
        disk = shutil.disk_usage(Path.cwd())
        pressure = evaluate_storage_pressure(
            used_bytes=int(disk.used),
            actual_capacity_bytes=int(disk.total),
        )
    except Exception:
        logger.exception("Storage pressure evaluation failed before %s retention", operation)
        return _retention_failure(
            operation=operation,
            requested=limit,
            error="storage_pressure_evaluation_failed",
        )
    if pressure.get("state") == "blocked":
        return {
            "success": False,
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "operation": operation,
            "requested": limit,
            "candidates": 0,
            "planned": 0,
            "deleted": 0,
            "held": 0,
            "blocked": 0,
            "bytes_planned": 0,
            "bytes_deleted": 0,
            "storage": pressure,
            "error": str(pressure.get("reason") or "storage_budget_policy_missing_or_inactive"),
        }

    try:
        result = RetentionCleanupUseCase(
            get_retention_policy_repository(),
            get_storage_hold_repository(),
            get_archive_coverage_gateway(),
            get_raw_landing_repository(),
            get_retention_run_repository(),
        ).execute(dataset_key=dataset_key.strip(), limit=limit, dry_run=dry_run)
    except Exception:
        logger.exception("Retention %s failed for dataset=%s", operation, dataset_key.strip())
        return _retention_failure(
            operation=operation,
            requested=limit,
            error="retention_execution_failed",
        )
    payload = result.to_dict()
    payload["operation"] = operation
    payload["storage"] = pressure
    return payload


@shared_task(  # type: ignore[misc]
    name="apps.data_center.application.tasks.cleanup_expired_raw_payloads_task",
    time_limit=900,
    soft_time_limit=840,
)
def cleanup_expired_raw_payloads_task(
    *,
    dataset_key: str,
    limit: int = 100,
    dry_run: bool = True,
) -> dict[str, object]:
    """Keep the legacy task path as a non-mutating retention preview."""

    if dry_run is False:
        return {
            "success": False,
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "operation": "cleanup",
            "requested": limit if isinstance(limit, int) and not isinstance(limit, bool) else 0,
            "candidates": 0,
            "planned": 0,
            "deleted": 0,
            "held": 0,
            "blocked": 0,
            "bytes_planned": 0,
            "bytes_deleted": 0,
            "error": "legacy_cleanup_mutation_disabled_use_enforce",
        }

    return _run_retention_pass(
        dataset_key=dataset_key,
        limit=limit,
        dry_run=True,
        operation="cleanup",
    )


@shared_task(  # type: ignore[misc]
    name="apps.data_center.application.tasks.plan_retention_task",
    time_limit=900,
    soft_time_limit=840,
)
def plan_retention_task(*, dataset_key: str, limit: int = 100) -> dict[str, object]:
    """Persist a bounded retention dry-run plan without deleting anything."""

    return _run_retention_pass(
        dataset_key=dataset_key,
        limit=limit,
        dry_run=True,
        operation="plan",
    )


@shared_task(  # type: ignore[misc]
    name="apps.data_center.application.tasks.enforce_retention_task",
    time_limit=900,
    soft_time_limit=840,
)
def enforce_retention_task(
    *,
    dataset_key: str,
    limit: int = 100,
    dry_run: bool = True,
    confirm: bool = False,
) -> dict[str, object]:
    """Preview retention; keep deletion closed until exact plan members are persisted."""

    if dry_run is False and confirm is True:
        return {
            "success": False,
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "operation": "enforce",
            "requested": limit if isinstance(limit, int) and not isinstance(limit, bool) else 0,
            "candidates": 0,
            "planned": 0,
            "deleted": 0,
            "held": 0,
            "blocked": 0,
            "bytes_planned": 0,
            "bytes_deleted": 0,
            "error": "retention_plan_member_gate_not_implemented",
        }

    return _run_retention_pass(
        dataset_key=dataset_key,
        limit=limit,
        dry_run=dry_run,
        operation="enforce",
        confirm=confirm,
    )


@shared_task(  # type: ignore[misc]
    name="apps.data_center.application.tasks.verify_storage_budget_task",
    time_limit=300,
    soft_time_limit=240,
)
def verify_storage_budget_task(*, storage_path: str = "") -> dict[str, object]:
    """Check current filesystem pressure before another mutating batch."""

    if not isinstance(storage_path, str):
        return {
            "success": False,
            "outcome": TaskBusinessOutcome.FAILED.value,
            "requested": 1,
            "succeeded": 0,
            "failed": 1,
            "blocked": 0,
            "error": "storage_path must be a string",
        }
    path = Path(storage_path.strip() or Path.cwd())
    try:
        disk = shutil.disk_usage(path)
        pressure = evaluate_storage_pressure(
            used_bytes=int(disk.used),
            actual_capacity_bytes=int(disk.total),
        )
    except Exception:
        logger.exception("Storage budget verification failed for path=%s", path)
        return {
            "success": False,
            "outcome": TaskBusinessOutcome.FAILED.value,
            "requested": 1,
            "succeeded": 0,
            "failed": 1,
            "blocked": 0,
            "storage_path": str(path),
            "error": "storage_budget_verification_failed",
        }
    state = str(pressure.get("state") or "")
    if state == "blocked":
        outcome = TaskBusinessOutcome.BLOCKED
        succeeded = 0
        blocked = 1
        failed = 0
        error = str(pressure.get("reason") or "storage_budget_policy_missing_or_inactive")
    elif state in {"critical", "emergency"}:
        outcome = TaskBusinessOutcome.BLOCKED
        succeeded = 0
        blocked = 1
        failed = 0
        error = f"storage_pressure_{state}"
    elif state == "warning":
        outcome = TaskBusinessOutcome.PARTIAL
        succeeded = 1
        blocked = 0
        failed = 0
        error = "storage_pressure_warning"
    elif state == "healthy":
        outcome = TaskBusinessOutcome.SUCCESS
        succeeded = 1
        blocked = 0
        failed = 0
        error = ""
    else:
        outcome = TaskBusinessOutcome.FAILED
        succeeded = 0
        blocked = 0
        failed = 1
        error = "storage_pressure_state_invalid"
    return {
        "success": outcome in {TaskBusinessOutcome.SUCCESS, TaskBusinessOutcome.NOOP},
        "outcome": outcome.value,
        "requested": 1,
        "succeeded": succeeded,
        "failed": failed,
        "blocked": blocked,
        "storage_path": str(path),
        "storage": pressure,
        "error": error,
    }
