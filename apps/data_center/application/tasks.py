"""Celery tasks for keeping market thermometer snapshots fresh."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from celery import shared_task
from celery.exceptions import OperationalError as CeleryOperationalError
from celery.exceptions import SoftTimeLimitExceeded
from django.core.cache import cache
from django.db import DatabaseError
from django.utils import timezone

from apps.data_center.composition import (
    get_backfill_item_attempt_store,
    get_publication_policy_repository,
    make_core_current_publication_rebuild_use_case,
    persist_sync_control_plane_snapshot,
    sync_active_a_share_universe,
)
from apps.data_center.domain.control_plane import (
    SyncBatch,
    SyncCheckpoint,
    SyncItemState,
    SyncRun,
    SyncRunStatus,
)
from apps.data_center.publication_candidate_activation_composition import (
    build_production_current_market_publication_bundle,
)
from apps.data_center.target_date_universe_composition import (
    build_target_date_a_share_universe_scope,
)
from core.exceptions import DataFetchError, DataValidationError, InvalidInputError
from core.integration import data_center_audit as audit_integration
from core.integration.task_monitor_runtime import (
    get_current_task_attempt_identity,
    record_current_task_progress,
)
from shared.domain.task_outcomes import TaskBusinessOutcome
from shared.infrastructure.operational_alert_registry import record_operational_alert

from . import financial_refresh_lease
from . import full_market_task_support as market_task
from . import market_publication_refresh as market_publication_services
from . import public as public_services
from .archive_tasks import verify_archive_manifest_task  # noqa: F401
from .backfill_control_plane import backfill_control_plane_ids
from .core_data_backfill import (
    BackfillAuthorityBinding,
    CoreDataBackfillServices,
    run_active_a_share_core_data_backfill_batch,
)
from .current_market_publication_activation import (
    CurrentMarketPublicationBundle,
    FullMarketRefreshDependencies,
)
from .data02_task_authority import Data02AuthorityLatch as _Data02AuthorityLatch
from .data02_task_authority import data02_authority_failure as _data02_authority_failure
from .data02_task_authority import (
    preflight_data02_task_authority as _preflight_data02_task_authority,
)
from .data02_task_authority import (
    same_data02_task_authority_is_current as _same_data02_task_authority_is_current,
)
from .full_market_refresh_orchestration import run_full_market_publication_refresh
from .interface_services import (
    make_backfill_sync_current_valuation_batch_use_case,
    make_backfill_sync_financial_use_case,
    make_backfill_sync_price_use_case,
    make_backfill_sync_quote_use_case,
    make_sync_market_thermometer_inputs_use_case,
    refresh_decision_quote_snapshots,
)
from .market_calendar import latest_closed_cn_market_session
from .market_thermometer_dates import resolve_market_thermometer_as_of_date
from .public import (
    get_active_provider_id_by_source,
    make_calculate_market_thermometer_use_case,
)
from .publication_rebuild_evidence import (
    publication_evidence_hash_from_result as _publication_evidence_hash_from_result,
)
from .query_services import (
    list_active_stock_codes_for_backfill,
)
from .query_use_cases import latest_completed_cn_market_session

logger = logging.getLogger(__name__)

DECISION_QUOTE_DEGRADED_STREAK_KEY = "task_monitor:decision_quote_degraded_streak:v1"
BACKFILL_DATASET_KEY = "equity.core.backfill"
BACKFILL_TASK_NAME = "celery.backfill_a_share_core"
_BACKFILL_AUTHORITY_WINDOW = timedelta(seconds=3900)
_FINANCIAL_PUBLICATIONS_AUTHORITY_WINDOW = timedelta(seconds=3900)
_AUTHORITY_FINALIZATION_WINDOW = timedelta(seconds=300)
_FULL_MARKET_AUTHORITY_WINDOW = timedelta(seconds=6300)
_BACKFILL_CURSOR_MAX_LENGTH = 500


def _make_full_market_publication_bundle(
    *, using: str = "default", created_by: str
) -> CurrentMarketPublicationBundle:
    """Build the market staging bundle explicitly on the production database alias."""

    return build_production_current_market_publication_bundle(
        using=using,
        created_by=created_by,
    )


@shared_task(name="data_center.refresh_full_market_publications", time_limit=5700, soft_time_limit=5400)  # type: ignore[misc]
def refresh_full_market_publications_task(
    source: str | None = None,
    batch_size: int = 100,
    quote_source: str = "tushare",
    valuation_source: str = "akshare",
) -> dict[str, object]:
    """Refresh all active market quotes and valuations without waiting for financial filings."""

    return run_full_market_publication_refresh(
        source=source,
        batch_size=batch_size,
        quote_source=quote_source,
        valuation_source=valuation_source,
        dependencies=FullMarketRefreshDependencies(
            authority_window=_FULL_MARKET_AUTHORITY_WINDOW,
            preflight_data02_authority=_preflight_data02_task_authority,
            get_current_task_attempt_identity=get_current_task_attempt_identity,
            authority_latch_factory=_Data02AuthorityLatch,
            data02_authority_failure=_data02_authority_failure,
            get_active_provider_id_by_source=get_active_provider_id_by_source,
            make_quote_sync_use_case=make_backfill_sync_quote_use_case,
            make_valuation_sync_use_case=(make_backfill_sync_current_valuation_batch_use_case),
            make_current_market_publication_bundle=(_make_full_market_publication_bundle),
            latest_closed_market_session=latest_closed_cn_market_session,
            sync_active_universe=sync_active_a_share_universe,
            target_date_universe_scope=build_target_date_a_share_universe_scope,
            publication_policy_repository=get_publication_policy_repository,
            record_progress=record_current_task_progress,
            model_market_data_port=public_services.get_model_market_data_port,
            refresh_market_price_inputs=market_publication_services.refresh_market_price_inputs,
            refresh_market_publications=market_publication_services.refresh_market_publications,
        ),
    )


@shared_task(  # type: ignore[misc]
    name="data_center.refresh_financial_publications_batch",
    time_limit=3600,
    soft_time_limit=3500,
)
def refresh_financial_publications_batch_task(
    *,
    offset: int = 0,
    batch_size: int = 50,
    source: str = "tushare",
    financial_periods: int = 8,
    universe_hash: str = "",
    auto_continue: bool = False,
    workflow_id: str = "",
) -> dict[str, object]:
    """Refresh one evidence-complete financial batch and publish after the full universe."""

    if (
        isinstance(offset, bool)
        or not isinstance(offset, int)
        or not 0 <= offset <= 100_000
        or isinstance(batch_size, bool)
        or not isinstance(batch_size, int)
        or not 1 <= batch_size <= 200
        or isinstance(financial_periods, bool)
        or not isinstance(financial_periods, int)
        or not 1 <= financial_periods <= 40
        or not isinstance(source, str)
        or source not in {"akshare", "tushare"}
        or not isinstance(universe_hash, str)
        or not isinstance(auto_continue, bool)
        or not isinstance(workflow_id, str)
        or len(workflow_id) > 64
        or any(character.isspace() for character in workflow_id)
        or (
            universe_hash
            and (
                len(universe_hash) != 64
                or any(character not in "0123456789abcdef" for character in universe_hash)
            )
        )
    ):
        return {
            **market_task.full_market_input_failure("invalid_financial_refresh_input"),
            "stage": "input",
        }

    started_at = datetime.now(UTC)
    authority, authority_failure = _preflight_data02_task_authority(
        as_of=started_at,
        minimum_window=_FINANCIAL_PUBLICATIONS_AUTHORITY_WINDOW,
    )
    if authority_failure is not None:
        return authority_failure
    if authority is None:  # pragma: no cover - narrowed by the failure branch
        raise RuntimeError("authority preflight returned no context")
    provider_id = get_active_provider_id_by_source(source)
    if provider_id is None:
        return {
            **market_task.full_market_input_failure("financial_provider_unavailable"),
            "stage": "provider",
        }

    active_codes = sorted(list_active_stock_codes_for_backfill())
    if (
        not active_codes
        or any(not code for code in active_codes)
        or len(set(active_codes)) != len(active_codes)
    ):
        return {
            **market_task.full_market_input_failure("financial_universe_invalid"),
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "stage": "universe",
            "must_not_use_for_decision": True,
        }
    encoded_universe = json.dumps(
        {"schema": "active-a-share-universe.v1", "asset_codes": active_codes},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    observed_universe_hash = hashlib.sha256(encoded_universe.encode("utf-8")).hexdigest()

    owner = workflow_id
    if auto_continue and not owner:
        if cache.get(financial_refresh_lease.FINANCIAL_REFRESH_LOCK_KEY):
            return financial_refresh_lease.financial_refresh_lock_noop_result()
        resume_offset = financial_refresh_lease.restore_financial_refresh_offset(
            cache,
            universe_hash=observed_universe_hash,
            source=source,
            financial_periods=financial_periods,
            batch_size=batch_size,
            total_assets=len(active_codes),
        )
        if resume_offset is not None:
            offset = resume_offset
            universe_hash = observed_universe_hash
        owner = str(uuid4())
        if not financial_refresh_lease.claim_financial_refresh_lock(cache, owner):
            return financial_refresh_lease.financial_refresh_lock_noop_result()
    elif auto_continue and not financial_refresh_lease.claim_financial_refresh_lock(cache, owner):
        return {
            **market_task.full_market_input_failure("financial_refresh_lock_lost"),
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "stage": "lock",
            "must_not_use_for_decision": True,
        }

    if offset > 0 and not universe_hash:
        financial_refresh_lease.release_financial_refresh_lock(cache, owner)
        return {
            **market_task.full_market_input_failure("financial_universe_hash_required"),
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "stage": "universe",
            "must_not_use_for_decision": True,
        }
    if universe_hash and universe_hash != observed_universe_hash:
        financial_refresh_lease.clear_financial_refresh_progress(cache)
        financial_refresh_lease.release_financial_refresh_lock(cache, owner)
        return {
            **market_task.full_market_input_failure("financial_universe_hash_mismatch"),
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "stage": "universe",
            "must_not_use_for_decision": True,
        }

    batch_codes = active_codes[offset : offset + batch_size]
    next_offset = offset + len(batch_codes)
    checkpoint = financial_refresh_lease.financial_refresh_checkpoint(
        offset=offset,
        next_offset=next_offset,
        total_assets=len(active_codes),
        universe_hash=observed_universe_hash,
    )
    if not batch_codes:
        financial_refresh_lease.clear_financial_refresh_progress(cache)
        financial_refresh_lease.release_financial_refresh_lock(cache, owner)
        return {
            "success": True,
            "outcome": TaskBusinessOutcome.NOOP.value,
            "stage": "complete",
            "requested": 0,
            "succeeded": 0,
            "failed": 0,
            "stored": 0,
            "published": 0,
            "checkpoint": checkpoint,
            "noop_reason": "no_remaining_financial_assets",
        }

    sync = make_backfill_sync_financial_use_case()
    succeeded = 0
    failed = 0
    blocked = 0
    stored = 0
    authority_changed = False
    soft_time_limit_exceeded = False
    for asset_code in batch_codes:
        if not _same_data02_task_authority_is_current(
            authority,
            as_of=datetime.now(UTC),
        ):
            authority_changed = True
            blocked += len(batch_codes) - succeeded - failed
            break
        try:
            from .dtos import SyncFinancialRequest

            result = sync.execute(
                SyncFinancialRequest(
                    provider_id=provider_id,
                    asset_code=asset_code,
                    periods=financial_periods,
                    require_decision_evidence=True,
                )
            )
            if (
                isinstance(result.stored_count, bool)
                or not isinstance(result.stored_count, int)
                or result.stored_count <= 0
            ):
                failed += 1
                continue
            succeeded += 1
            stored += result.stored_count
        except SoftTimeLimitExceeded:
            failed += len(batch_codes) - succeeded - failed - blocked
            soft_time_limit_exceeded = True
            break
        except InvalidInputError as exc:
            if exc.code == "FINANCIAL_SOURCE_EVIDENCE_REQUIRED":
                blocked += 1
            else:
                failed += 1
        except (
            DataFetchError,
            DataValidationError,
            DatabaseError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ):
            failed += 1

    if blocked:
        outcome = TaskBusinessOutcome.BLOCKED
    elif failed and succeeded:
        outcome = TaskBusinessOutcome.PARTIAL
    elif failed:
        outcome = TaskBusinessOutcome.FAILED
    else:
        outcome = TaskBusinessOutcome.SUCCESS
    published = 0
    publication_updated = False
    blocked_reason = (
        "authority_changed_or_expired"
        if authority_changed
        else ("financial_source_evidence_required" if blocked else "")
    )
    stage = (
        "provider"
        if soft_time_limit_exceeded
        else ("authority" if authority_changed else ("financial_evidence" if blocked else "batch"))
    )

    if outcome is TaskBusinessOutcome.SUCCESS and checkpoint["complete"] is True:
        try:
            rebuild = make_core_current_publication_rebuild_use_case(
                created_by=f"celery.financial_refresh:{authority.actor_id}",
                dataset_keys=("equity.financial.fact",),
            ).execute(
                asset_codes=active_codes,
                published_at=datetime.now(UTC),
            )
            published = rebuild.published_count
            publication_updated = published > 0
            if not publication_updated:
                raise DataValidationError("financial publication produced no members")
        except (
            DataFetchError,
            DataValidationError,
            DatabaseError,
            OSError,
            RuntimeError,
            audit_integration.SystemAuditCompositionUnavailable,
            TypeError,
            ValueError,
        ) as exc:
            logger.warning(
                "Financial current publication rebuild failed: %s",
                type(exc).__name__,
            )
            outcome = TaskBusinessOutcome.BLOCKED
            blocked_reason = "financial_publication_rebuild_failed"
            stage = "publication"

    response: dict[str, object] = {
        "success": outcome not in {TaskBusinessOutcome.FAILED, TaskBusinessOutcome.BLOCKED},
        "outcome": outcome.value,
        "stage": stage,
        "requested": len(batch_codes),
        "succeeded": succeeded,
        "failed": failed,
        "blocked": blocked,
        "stored": stored,
        "published": published,
        "publication_updated": publication_updated,
        "checkpoint": checkpoint,
    }
    if blocked_reason:
        response["blocked_reason"] = blocked_reason
        response["must_not_use_for_decision"] = True
    if soft_time_limit_exceeded:
        response["error_code"] = "financial_refresh_soft_time_limit_exceeded"
        response["must_not_use_for_decision"] = True

    if outcome is TaskBusinessOutcome.SUCCESS and checkpoint["complete"] is False:
        financial_refresh_lease.save_financial_refresh_progress(
            cache,
            next_offset=next_offset,
            universe_hash=observed_universe_hash,
            source=source,
            financial_periods=financial_periods,
            batch_size=batch_size,
        )
        if auto_continue:
            try:
                continuation = refresh_financial_publications_batch_task.apply_async(
                    kwargs={
                        "offset": next_offset,
                        "batch_size": batch_size,
                        "source": source,
                        "financial_periods": financial_periods,
                        "universe_hash": observed_universe_hash,
                        "auto_continue": True,
                        "workflow_id": owner,
                    },
                    countdown=5,
                )
            except (OSError, CeleryOperationalError) as exc:
                logger.warning(
                    "Financial refresh continuation enqueue failed: %s",
                    type(exc).__name__,
                )
                response.update(
                    {
                        "success": False,
                        "outcome": TaskBusinessOutcome.FAILED.value,
                        "stage": "continuation",
                        "error_code": "financial_refresh_continuation_enqueue_failed",
                        "must_not_use_for_decision": True,
                    }
                )
                financial_refresh_lease.release_financial_refresh_lock(cache, owner)
            else:
                response["continuation_task_id"] = str(continuation.id)
    else:
        if outcome is TaskBusinessOutcome.SUCCESS:
            financial_refresh_lease.clear_financial_refresh_progress(cache)
        financial_refresh_lease.release_financial_refresh_lock(cache, owner)
    return response


def _backfill_idempotency_key(
    source: object,
    offset: object,
    batch_size: object,
    history_days: object,
    financial_periods: object,
    authority_content_hash: object = "",
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
            f"authority_content_hash={authority_content_hash!r}",
        )
    )
    digest = hashlib.sha256(material.encode("utf-8", errors="replace")).hexdigest()[:16]
    visible = (
        f"{BACKFILL_DATASET_KEY}:{source_text}:"
        f"offset={str(offset)[:24]}:"
        f"window={str(batch_size)[:24]}"
    )
    return f"{visible}:{digest}"


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
    run_id, batch_id = backfill_control_plane_ids(idempotency_key)
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
    # The composition root owns the transaction spanning all three durable
    # control-plane repositories. A retry therefore cannot leave a run or
    # batch without its matching checkpoint after a process/database failure.
    persist_sync_control_plane_snapshot(run, batch, durable_checkpoint)


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
    operator: str = "",
    universe_hash: str = "",
) -> dict[str, Any]:
    """Backfill one resumable active-A-share core-data batch."""

    started_at = datetime.now(UTC)
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
        if not isinstance(source, str):
            raise ValueError("source must be a string identifier")
        normalized_source = source.strip().lower()
        if not normalized_source or len(normalized_source) > 32:
            raise ValueError("source must be a non-empty identifier")
        if not isinstance(operator, str):
            raise ValueError("operator must be a string identity")
        raw_operator = operator
        normalized_operator = raw_operator.strip()
        if (
            len(normalized_operator) > 100
            or any(character.isspace() for character in normalized_operator)
            or normalized_operator != raw_operator
        ):
            raise ValueError("operator must be a bounded canonical identity")
        if not isinstance(universe_hash, str):
            raise ValueError("universe_hash must be a string digest")
        normalized_universe_hash = universe_hash.strip()
        if normalized_universe_hash != universe_hash or (
            normalized_universe_hash
            and (
                len(normalized_universe_hash) != 64
                or any(
                    character not in "0123456789abcdef" for character in normalized_universe_hash
                )
            )
        ):
            raise ValueError("universe_hash must be an exact lowercase sha256 digest")
        if validated_offset > 0 and not normalized_universe_hash:
            raise ValueError("universe_hash is required when offset is nonzero")
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

    authority, authority_failure = _preflight_data02_task_authority(
        as_of=started_at,
        minimum_window=_BACKFILL_AUTHORITY_WINDOW,
        expected_actor=normalized_operator,
    )
    if authority_failure is not None:
        return authority_failure
    if authority is None:  # pragma: no cover - narrowed by the failure branch
        raise RuntimeError("authority preflight returned no context")
    authority_binding = BackfillAuthorityBinding(
        actor_id=authority.actor_id,
        tenant_id=authority.tenant_id,
        owner_id=authority.owner_id,
        content_hash=authority.authority_content_hash,
        valid_until=authority.authority_valid_until,
    )
    largest_checkpoint = {
        "offset": validated_offset,
        "next_offset": validated_offset + validated_batch_size,
        "total_assets": 100_000,
        "complete": False,
        "universe_hash": "f" * 64,
        "observed_universe_hash": "e" * 64,
        "authority": authority_binding.to_checkpoint(),
    }
    encoded_checkpoint = json.dumps(
        largest_checkpoint,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(encoded_checkpoint) > _BACKFILL_CURSOR_MAX_LENGTH:
        return _data02_authority_failure("authority_checkpoint_too_large")
    idempotency_key = _backfill_idempotency_key(
        normalized_source,
        validated_offset,
        validated_batch_size,
        validated_history_days,
        validated_periods,
        authority.authority_content_hash,
    )

    def revalidate_authority(as_of: datetime) -> bool:
        """Require the same current authority before advancing the checkpoint."""

        return _same_data02_task_authority_is_current(
            authority,
            as_of=as_of,
            minimum_window=_AUTHORITY_FINALIZATION_WINDOW,
        )

    return run_active_a_share_core_data_backfill_batch(
        validated_offset=validated_offset,
        validated_batch_size=validated_batch_size,
        normalized_source=normalized_source,
        validated_history_days=validated_history_days,
        validated_periods=validated_periods,
        idempotency_key=idempotency_key,
        expected_universe_hash=normalized_universe_hash,
        started_at=started_at,
        services=CoreDataBackfillServices(
            list_active_stock_codes=list_active_stock_codes_for_backfill,
            get_active_provider_id=get_active_provider_id_by_source,
            latest_completed_market_session=latest_completed_cn_market_session,
            current_time=timezone.now,
            make_sync_quote_use_case=make_backfill_sync_quote_use_case,
            make_sync_price_use_case=make_backfill_sync_price_use_case,
            make_sync_valuation_batch_use_case=(
                make_backfill_sync_current_valuation_batch_use_case
            ),
            make_sync_financial_use_case=make_backfill_sync_financial_use_case,
            rebuild_current_publications=(
                lambda *, asset_codes, published_at: (
                    make_core_current_publication_rebuild_use_case(
                        created_by=f"celery.core_data_backfill:{authority.actor_id}"
                    ).execute(
                        asset_codes=asset_codes,
                        published_at=published_at,
                    )
                )
            ),
            published_count_from_result=_published_count_from_result,
            publication_evidence_hash=_publication_evidence_hash_from_result,
            persist_control_plane=_persist_backfill_control_plane,
            item_attempt_store=get_backfill_item_attempt_store(),
            authority_binding=authority_binding,
            revalidate_authority=revalidate_authority,
        ),
    )


from .retention_tasks import (  # noqa: E402,F401
    cleanup_expired_raw_payloads_task,
    enforce_retention_task,
    plan_retention_task,
    verify_storage_budget_task,
)
