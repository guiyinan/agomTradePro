"""Celery tasks for keeping market thermometer snapshots fresh."""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from celery import shared_task
from django.core.cache import cache
from django.utils import timezone

from apps.audit.application.system_audit_composition import SystemAuditCompositionUnavailable
from apps.audit.application.system_audit_query import SystemAuditReaderContext
from apps.data_center.composition import (
    get_archive_coverage_gateway,
    get_backfill_item_attempt_store,
    get_raw_landing_repository,
    get_retention_plan_repository,
    get_retention_policy_repository,
    get_retention_run_repository,
    get_storage_hold_repository,
    make_core_current_publication_rebuild_use_case,
    persist_sync_control_plane_snapshot,
)
from apps.data_center.domain.control_plane import (
    SyncBatch,
    SyncCheckpoint,
    SyncItemState,
    SyncRun,
    SyncRunStatus,
)
from apps.data_center.domain.market_time import cn_market_date_from_observation
from core.integration.config_center_runtime import evaluate_storage_pressure
from core.integration.data_center_audit import preflight_data_reliability_audit_runtime
from shared.domain.task_outcomes import TaskBusinessOutcome
from shared.infrastructure.operational_alert_registry import record_operational_alert

from .archive_tasks import verify_archive_manifest_task  # noqa: F401
from .backfill_control_plane import backfill_control_plane_ids
from .core_data_backfill import (
    BackfillAuthorityBinding,
    CoreDataBackfillServices,
    run_active_a_share_core_data_backfill_batch,
)
from .interface_services import (
    make_backfill_sync_current_valuation_batch_use_case,
    make_backfill_sync_financial_use_case,
    make_backfill_sync_price_use_case,
    make_backfill_sync_quote_use_case,
    make_sync_market_thermometer_inputs_use_case,
    refresh_decision_quote_snapshots,
)
from .market_thermometer_dates import resolve_market_thermometer_as_of_date
from .public import (
    get_active_provider_id_by_source,
    make_calculate_market_thermometer_use_case,
)
from .publication_rebuild_evidence import (
    publication_evidence_hash_from_result as _publication_evidence_hash_from_result,
)
from .query_services import list_active_stock_codes_for_backfill
from .query_use_cases import latest_completed_cn_market_session
from .retention import (
    CreateRetentionPlanUseCase,
    EnforceRetentionPlanUseCase,
    RetentionCleanupUseCase,
)

logger = logging.getLogger(__name__)

DECISION_QUOTE_DEGRADED_STREAK_KEY = "task_monitor:decision_quote_degraded_streak:v1"
BACKFILL_DATASET_KEY = "equity.core.backfill"
BACKFILL_TASK_NAME = "celery.backfill_a_share_core"
_BACKFILL_AUTHORITY_WINDOW = timedelta(seconds=3900)
_FULL_MARKET_AUTHORITY_WINDOW = timedelta(seconds=2100)
_AUTHORITY_FINALIZATION_WINDOW = timedelta(seconds=300)
_BACKFILL_CURSOR_MAX_LENGTH = 500


def _data02_authority_failure(reason: str) -> dict[str, object]:
    """Return a stable zero-write authority denial for DATA-02 tasks."""

    return {
        "success": False,
        "outcome": TaskBusinessOutcome.BLOCKED.value,
        "stage": "authority",
        "blocked_reason": reason,
        "must_not_use_for_decision": True,
        "requested": 0,
        "succeeded": 0,
        "failed": 0,
        "stored": 0,
        "published": 0,
        "checkpoint": {
            "offset": 0,
            "next_offset": 0,
            "total_assets": 0,
            "complete": False,
        },
    }


def _preflight_data02_task_authority(
    *,
    as_of: datetime,
    minimum_window: timedelta,
    expected_actor: str = "",
) -> tuple[SystemAuditReaderContext | None, dict[str, object] | None]:
    """Resolve current authority and prove it covers the task's bounded runtime."""

    try:
        context = preflight_data_reliability_audit_runtime(
            environment="production",
            using="default",
            as_of=as_of,
        )
    except SystemAuditCompositionUnavailable as exc:
        return None, _data02_authority_failure(f"system_audit_{exc.reason_code}")
    if expected_actor and expected_actor != context.actor_id:
        return None, _data02_authority_failure("operator_actor_mismatch")
    if context.authority_valid_until < as_of + minimum_window:
        return None, _data02_authority_failure("authority_window_too_short")
    return context, None


def _same_data02_task_authority_is_current(
    authority: SystemAuditReaderContext,
    *,
    as_of: datetime,
    minimum_window: timedelta = _AUTHORITY_FINALIZATION_WINDOW,
) -> bool:
    """Return whether the same current authority still covers the next boundary."""

    current, failure = _preflight_data02_task_authority(
        as_of=as_of,
        minimum_window=minimum_window,
        expected_actor=authority.actor_id,
    )
    return (
        failure is None
        and current is not None
        and current.authority_content_hash == authority.authority_content_hash
        and current.tenant_id == authority.tenant_id
        and current.owner_id == authority.owner_id
    )


def _exact_provider_batch_count(
    *,
    requested_asset_codes: Sequence[str],
    stored_count: object,
    returned_asset_codes: object,
    succeeded_asset_codes: object | None = None,
) -> int:
    """Require one distinct returned identity for every requested asset."""

    if isinstance(stored_count, bool) or not isinstance(stored_count, int):
        raise ValueError("provider batch stored_count must be an integer")
    if isinstance(returned_asset_codes, (str, bytes)) or not isinstance(
        returned_asset_codes, Sequence
    ):
        raise ValueError("provider batch asset identities are unavailable")
    requested = tuple(str(code or "").strip().upper() for code in requested_asset_codes)
    returned = tuple(str(code or "").strip().upper() for code in returned_asset_codes)
    succeeded = returned
    if succeeded_asset_codes is not None:
        if isinstance(succeeded_asset_codes, (str, bytes)) or not isinstance(
            succeeded_asset_codes, Sequence
        ):
            raise ValueError("provider batch succeeded identities are unavailable")
        succeeded = tuple(str(code or "").strip().upper() for code in succeeded_asset_codes)
    if (
        any(not code for code in (*requested, *returned, *succeeded))
        or len(set(requested)) != len(requested)
        or len(set(returned)) != len(returned)
        or len(set(succeeded)) != len(succeeded)
        or stored_count != len(requested)
        or len(returned) != len(requested)
        or len(succeeded) != len(requested)
        or set(returned) != set(requested)
        or set(succeeded) != set(requested)
    ):
        raise ValueError("provider batch asset identities are incomplete")
    return stored_count


@shared_task(name="data_center.refresh_full_market_publications", time_limit=1800, soft_time_limit=1700)  # type: ignore[misc]
def refresh_full_market_publications_task(
    source: str = "akshare", batch_size: int = 100
) -> dict[str, object]:
    """Refresh all active market quotes and valuations without waiting for financial filings."""
    from .dtos import SyncQuoteRequest
    from .market_publication_refresh import (
        MarketPublicationRefreshPorts,
        refresh_market_price_inputs,
        refresh_market_publications,
    )
    from .public import get_model_market_data_port

    if not isinstance(source, str) or source not in {"akshare", "tushare"}:
        return _full_market_input_failure("unsupported_market_source")
    if (
        isinstance(batch_size, bool)
        or not isinstance(batch_size, int)
        or not 1 <= batch_size <= 200
    ):
        return _full_market_input_failure("invalid_batch_size")
    started_at = datetime.now(UTC)
    authority, authority_failure = _preflight_data02_task_authority(
        as_of=started_at,
        minimum_window=_FULL_MARKET_AUTHORITY_WINDOW,
    )
    if authority_failure is not None:
        return authority_failure
    if authority is None:  # pragma: no cover - narrowed by the failure branch
        raise RuntimeError("authority preflight returned no context")
    provider_id = get_active_provider_id_by_source(source)
    if provider_id is None:
        return _full_market_input_failure("market_provider_unavailable")
    try:
        quotes = make_backfill_sync_quote_use_case()
    except SystemAuditCompositionUnavailable as exc:
        return {
            **_full_market_input_failure(f"system_audit_{exc.reason_code}"),
            "outcome": "blocked",
            "must_not_use_for_decision": True,
        }
    valuations = make_backfill_sync_current_valuation_batch_use_case()
    publications = make_core_current_publication_rebuild_use_case(
        created_by=f"celery.full_market_refresh:{authority.actor_id}",
        dataset_keys=("equity.quote.snapshot", "equity.valuation.fact", "equity.price.bar"),
    )
    target_date = latest_completed_cn_market_session(timezone.now())
    if target_date is None:
        return {
            "outcome": "blocked",
            "success": False,
            "requested": 0,
            "succeeded": 0,
            "failed": 0,
            "stored": 0,
            "blocked_reason": "market_calendar_unavailable",
        }

    price_evidence: dict[str, object] = {}
    authority_current = True

    def authority_allows_next_write() -> bool:
        """Revalidate at every write boundary and stay closed after drift."""

        nonlocal authority_current
        if authority_current:
            authority_current = _same_data02_task_authority_is_current(
                authority,
                as_of=datetime.now(UTC),
            )
        return authority_current

    def sync_quote_batch(codes: list[str]) -> int:
        if not authority_allows_next_write():
            raise ValueError("current Audit authority changed before quote batch")
        result = quotes.execute(
            SyncQuoteRequest(provider_id, codes, require_exact_asset_codes=True)
        )
        return _exact_provider_batch_count(
            requested_asset_codes=codes,
            stored_count=result.stored_count,
            returned_asset_codes=result.stored_asset_codes,
        )

    def sync_valuation_batch(codes: list[str], day: date) -> int:
        if not authority_allows_next_write():
            raise ValueError("current Audit authority changed before valuation batch")
        result = valuations.execute(
            provider_id=provider_id,
            asset_codes=codes,
            as_of_date=day,
            require_exact_asset_codes=True,
        )
        return _exact_provider_batch_count(
            requested_asset_codes=codes,
            stored_count=result.stored_count,
            returned_asset_codes=result.returned_asset_codes,
            succeeded_asset_codes=result.succeeded_asset_codes,
        )

    def publish_complete_session(codes: list[str]) -> int:
        if not authority_allows_next_write():
            raise ValueError("current Audit authority changed before publication")
        preview = publications.preview(asset_codes=codes)
        current_snapshots = tuple(
            dataset for dataset in preview.datasets if dataset.dataset_key != "equity.price.bar"
        )
        if len(current_snapshots) != 2 or any(
            not dataset.ready
            or dataset.oldest_observed_at is None
            or cn_market_date_from_observation(dataset.oldest_observed_at) != target_date
            or dataset.newest_observed_at is None
            or cn_market_date_from_observation(dataset.newest_observed_at) != target_date
            for dataset in current_snapshots
        ):
            raise ValueError("Market publication observations do not match the completed session")
        suspended = refresh_market_price_inputs(get_model_market_data_port(), codes, target_date)
        price_evidence.update(
            price_scope_verified=len(codes),
            price_target_date=target_date.isoformat(),
            suspended_codes=list(suspended),
        )
        return publications.execute(asset_codes=codes).published_count

    result = refresh_market_publications(
        as_of_date=target_date,
        batch_size=batch_size,
        ports=MarketPublicationRefreshPorts(
            list_codes=list_active_stock_codes_for_backfill,
            sync_quotes=sync_quote_batch,
            sync_valuations=sync_valuation_batch,
            publish=publish_complete_session,
        ),
    )
    if not authority_current:
        return {
            **result,
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "success": False,
            "must_not_use_for_decision": True,
            "blocked_reason": "authority_changed_or_expired",
            "publication_updated": False,
            "published_members": 0,
        }
    return {**result, **price_evidence}


def _full_market_input_failure(reason: str) -> dict[str, object]:
    """Publish a stable zero-write failure before any market fetch."""
    return {
        "outcome": "failed",
        "success": False,
        "requested": 0,
        "succeeded": 0,
        "failed": 0,
        "stored": 0,
        "blocked_reason": reason,
    }


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
        "succeeded": 0,
        "failed": 1,
        "stored": 0,
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
def plan_retention_task(
    *,
    dataset_key: str,
    limit: int = 100,
    operation_id: str = "",
    ttl_hours: int = 24,
) -> dict[str, object]:
    """Persist an immutable exact-member plan without deleting anything."""

    if not isinstance(dataset_key, str) or not dataset_key.strip():
        return _retention_failure(operation="plan", requested=0, error="dataset_key is required")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10_000:
        return _retention_failure(
            operation="plan", requested=0, error="limit must be between 1 and 10000"
        )
    if not isinstance(operation_id, str):
        return _retention_failure(
            operation="plan", requested=limit, error="operation_id must be a string"
        )
    if isinstance(ttl_hours, bool) or not isinstance(ttl_hours, int) or not 1 <= ttl_hours <= 168:
        return _retention_failure(
            operation="plan", requested=limit, error="ttl_hours must be between 1 and 168"
        )
    try:
        disk = shutil.disk_usage(Path.cwd())
        pressure = evaluate_storage_pressure(
            used_bytes=int(disk.used), actual_capacity_bytes=int(disk.total)
        )
    except Exception:
        logger.exception("Storage pressure evaluation failed before retention planning")
        return _retention_failure(
            operation="plan", requested=limit, error="storage_pressure_evaluation_failed"
        )
    if pressure.get("state") == "blocked":
        return {
            **_retention_failure(
                operation="plan",
                requested=limit,
                error=str(pressure.get("reason") or "storage_budget_policy_missing_or_inactive"),
            ),
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "failed": 0,
            "storage": pressure,
        }
    try:
        result = CreateRetentionPlanUseCase(
            get_retention_policy_repository(),
            get_storage_hold_repository(),
            get_archive_coverage_gateway(),
            get_raw_landing_repository(),
            get_retention_plan_repository(),
        ).execute(
            dataset_key=dataset_key.strip(),
            limit=limit,
            operation_id=operation_id.strip() or str(uuid4()),
            ttl_hours=ttl_hours,
        )
    except Exception:
        logger.exception("Retention plan creation failed for dataset=%s", dataset_key.strip())
        return _retention_failure(
            operation="plan", requested=limit, error="retention_plan_creation_failed"
        )
    payload = result.to_dict()
    payload["operation"] = "plan"
    payload["storage"] = pressure
    return payload


@shared_task(  # type: ignore[misc]
    name="apps.data_center.application.tasks.enforce_retention_task",
    time_limit=900,
    soft_time_limit=840,
)
def enforce_retention_task(
    *,
    plan_run_id: str = "",
    operation_id: str = "",
    confirm: bool = False,
) -> dict[str, object]:
    """Consume only an exact persisted plan after explicit confirmation."""

    if not isinstance(confirm, bool):
        return _retention_failure(
            operation="enforce", requested=0, error="confirm must be a boolean"
        )
    if not confirm:
        return {
            **_retention_failure(
                operation="enforce", requested=0, error="explicit_confirmation_required"
            ),
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "failed": 0,
        }
    if not isinstance(plan_run_id, str) or not plan_run_id.strip():
        return _retention_failure(
            operation="enforce", requested=0, error="retention_plan_run_id_required"
        )
    if not isinstance(operation_id, str) or not operation_id.strip():
        return _retention_failure(
            operation="enforce", requested=0, error="operation_id is required"
        )
    try:
        result = EnforceRetentionPlanUseCase(
            get_retention_policy_repository(),
            get_storage_hold_repository(),
            get_archive_coverage_gateway(),
            get_raw_landing_repository(),
            get_retention_plan_repository(),
        ).execute(plan_id=plan_run_id.strip(), operation_id=operation_id.strip())
    except ValueError as exc:
        reason = str(exc)
        if reason in {"retention_plan_already_claimed", "retention_plan_already_completed"}:
            return {
                **_retention_failure(operation="enforce", requested=0, error=reason),
                "outcome": TaskBusinessOutcome.BLOCKED.value,
                "failed": 0,
            }
        logger.exception("Retention plan validation failed for plan=%s", plan_run_id.strip())
        return _retention_failure(
            operation="enforce", requested=0, error="retention_plan_enforcement_failed"
        )
    except Exception:
        logger.exception("Retention plan enforcement failed for plan=%s", plan_run_id.strip())
        return _retention_failure(
            operation="enforce", requested=0, error="retention_plan_enforcement_failed"
        )
    payload = result.to_dict()
    payload["operation"] = "enforce"
    return payload


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
