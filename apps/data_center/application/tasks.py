"""Celery tasks for keeping market thermometer snapshots fresh."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from celery import shared_task
from django.core.cache import cache
from django.db import DatabaseError
from django.utils import timezone

from apps.data_center.application.financial_publication_capacity import (
    FinancialCapacityWorkflowError,
    FinancialCapacityWorkflowResult,
)
from apps.data_center.composition import (
    get_backfill_item_attempt_store,
    get_publication_policy_repository,
    make_core_current_publication_rebuild_use_case,
    make_financial_publication_capacity_workflow,
    persist_sync_control_plane_snapshot,
    preflight_financial_capacity_isolation,
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
from core.exceptions import DataFetchError, DataValidationError
from core.integration import data_center_audit as _audit_integration
from core.integration.task_monitor_runtime import (
    get_current_task_attempt_identity,
    record_current_task_progress,
)
from shared.domain.task_outcomes import TaskBusinessOutcome
from shared.infrastructure.operational_alert_registry import record_operational_alert

from . import full_market_refresh_lease
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

# Public test/composition seam retained for callers that patch the shared audit module.
audit_integration = _audit_integration

DECISION_QUOTE_DEGRADED_STREAK_KEY = "task_monitor:decision_quote_degraded_streak:v1"
BACKFILL_DATASET_KEY = "equity.core.backfill"
BACKFILL_TASK_NAME = "celery.backfill_a_share_core"
_BACKFILL_AUTHORITY_WINDOW = timedelta(seconds=3900)
_FINANCIAL_PUBLICATIONS_AUTHORITY_WINDOW = timedelta(seconds=3900)


class _FinancialCapacityAuthorityLatch(_Data02AuthorityLatch):
    """Adapt the existing DATA-02 authority latch to workflow write boundaries."""

    def is_current(self) -> bool:
        """Revalidate the same authority before one provider or activation boundary."""

        return self.allows_next_write(as_of=datetime.now(UTC))


_AUTHORITY_FINALIZATION_WINDOW = timedelta(seconds=300)
_FULL_MARKET_AUTHORITY_WINDOW = timedelta(
    seconds=full_market_refresh_lease.FULL_MARKET_REFRESH_AUTHORITY_WINDOW_SECONDS
)
_BACKFILL_CURSOR_MAX_LENGTH = 500


def _make_full_market_publication_bundle(
    *, using: str = "default", created_by: str
) -> CurrentMarketPublicationBundle:
    """Build the market staging bundle explicitly on the production database alias."""

    return build_production_current_market_publication_bundle(
        using=using,
        created_by=created_by,
    )


@shared_task(
    name="data_center.refresh_full_market_publications",
    time_limit=full_market_refresh_lease.FULL_MARKET_REFRESH_HARD_TIME_LIMIT_SECONDS,
    soft_time_limit=full_market_refresh_lease.FULL_MARKET_REFRESH_SOFT_TIME_LIMIT_SECONDS,
)  # type: ignore[misc]
def refresh_full_market_publications_task(
    source: str | None = None,
    batch_size: int = 100,
    quote_source: str = "tushare",
    valuation_source: str = "akshare",
) -> dict[str, object]:
    """Refresh all active market quotes and valuations under a task-wide lease."""

    owner_id = uuid4().hex
    try:
        lease_acquired = full_market_refresh_lease.claim_full_market_refresh_lease(
            cache,
            owner_id,
        )
    except full_market_refresh_lease.FullMarketRefreshLeaseUnavailable as exc:
        logger.warning(
            "Full-market refresh stopped before side effects because its lease is unavailable "
            "(operation=%s)",
            exc.operation,
        )
        return full_market_refresh_lease.full_market_refresh_lease_unavailable_result()
    if not lease_acquired:
        return full_market_refresh_lease.full_market_refresh_lease_busy_result()

    try:
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
    finally:
        try:
            full_market_refresh_lease.release_full_market_refresh_lease(cache, owner_id)
        except full_market_refresh_lease.FullMarketRefreshLeaseUnavailable as exc:
            logger.warning(
                "Full-market refresh lease release failed; bounded TTL recovery remains "
                "available (operation=%s)",
                exc.operation,
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
    """Fail closed until the exact-scope, receipt-gated publication workflow is used."""

    valid_input = (
        type(offset) is int
        and 0 <= offset <= 100_000
        and type(batch_size) is int
        and 1 <= batch_size <= 200
        and type(financial_periods) is int
        and 1 <= financial_periods <= 40
        and type(source) is str
        and source in {"akshare", "tushare"}
        and type(universe_hash) is str
        and (
            not universe_hash
            or (
                len(universe_hash) == 64
                and all(character in "0123456789abcdef" for character in universe_hash)
            )
        )
        and type(auto_continue) is bool
        and type(workflow_id) is str
        and len(workflow_id) <= 64
        and not any(character.isspace() for character in workflow_id)
    )
    if not valid_input:
        return {
            **market_task.full_market_input_failure("invalid_financial_refresh_input"),
            "stage": "input",
        }
    reason = "financial_capacity_receipt_required"
    return {
        **market_task.full_market_input_failure(reason),
        "outcome": TaskBusinessOutcome.BLOCKED.value,
        "stage": "capacity",
        "requested": 0,
        "succeeded": 0,
        "failed": 0,
        "stored": 0,
        "published": 0,
        "publication_updated": False,
        "blocked_reason": reason,
        "must_not_use_for_decision": True,
    }


@shared_task(  # type: ignore[misc]
    name="data_center.refresh_financial_publication_capacity",
    time_limit=3600,
    soft_time_limit=3500,
)
def refresh_financial_publication_capacity_task(
    *,
    action: str,
    workflow_id: str,
    candidate_sha: str,
    total_provider_request_budget: int = 0,
    capacity_rehearsal_workflow_id: str = "",
    scope_capacity_import_id: str = "",
    max_slices: int = 1,
    expected_database_name: str = "",
    expected_database_host: str = "",
) -> dict[str, object]:
    """Drive qualification, full isolated rehearsal, or receipt-gated publication."""

    valid_input = (
        type(action) is str
        and action
        in {
            "qualification_start",
            "qualification_run",
            "capacity_rehearsal_start",
            "capacity_rehearsal_run",
            "formal_start",
            "formal_run",
        }
        and type(workflow_id) is str
        and 0 < len(workflow_id) <= 300
        and not any(character.isspace() for character in workflow_id)
        and type(candidate_sha) is str
        and len(candidate_sha) == 40
        and all(character in "0123456789abcdef" for character in candidate_sha)
        and type(total_provider_request_budget) is int
        and total_provider_request_budget >= 0
        and type(capacity_rehearsal_workflow_id) is str
        and len(capacity_rehearsal_workflow_id) <= 300
        and not any(character.isspace() for character in capacity_rehearsal_workflow_id)
        and type(scope_capacity_import_id) is str
        and len(scope_capacity_import_id) <= 36
        and not any(character.isspace() for character in scope_capacity_import_id)
        and type(max_slices) is int
        and max_slices > 0
        and type(expected_database_name) is str
        and type(expected_database_host) is str
    )
    if not valid_input:
        return {
            **market_task.full_market_input_failure("invalid_financial_capacity_workflow_input"),
            "outcome": TaskBusinessOutcome.FAILED.value,
            "stage": "input",
            "requested": 0,
            "succeeded": 0,
            "failed": 0,
            "stored": 0,
            "published": 0,
        }
    if action == "formal_start" and scope_capacity_import_id:
        try:
            if str(UUID(scope_capacity_import_id)) != scope_capacity_import_id:
                raise ValueError("non-canonical import ID")
        except (TypeError, ValueError):
            return {
                **market_task.full_market_input_failure(
                    "invalid_financial_capacity_scope_import_id"
                ),
                "outcome": TaskBusinessOutcome.FAILED.value,
                "stage": "input",
                "requested": 0,
                "succeeded": 0,
                "failed": 0,
                "stored": 0,
                "published": 0,
            }
    if action == "formal_start" and not scope_capacity_import_id:
        reason = "financial_capacity_scope_import_required"
        return {
            **market_task.full_market_input_failure(reason),
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "stage": "capacity",
            "requested": 0,
            "succeeded": 0,
            "failed": 0,
            "stored": 0,
            "published": 0,
            "blocked_reason": reason,
            "must_not_use_for_decision": True,
        }
    if action in {"qualification_start", "capacity_rehearsal_start"} and (
        total_provider_request_budget <= 0
    ):
        return {
            **market_task.full_market_input_failure(
                "financial_capacity_total_request_budget_required"
            ),
            "outcome": TaskBusinessOutcome.FAILED.value,
            "stage": "input",
            "requested": 0,
            "succeeded": 0,
            "failed": 0,
            "stored": 0,
            "published": 0,
        }
    isolation_attestation_sha256 = ""
    if action in {
        "qualification_start",
        "qualification_run",
        "capacity_rehearsal_start",
        "capacity_rehearsal_run",
    }:
        if not expected_database_name or not expected_database_host:
            return {
                **market_task.full_market_input_failure(
                    "financial_capacity_isolated_database_identity_required"
                ),
                "outcome": TaskBusinessOutcome.BLOCKED.value,
                "stage": "isolation",
                "requested": 0,
                "succeeded": 0,
                "failed": 0,
                "stored": 0,
                "published": 0,
                "must_not_use_for_decision": True,
            }
        try:
            isolation_attestation_sha256 = preflight_financial_capacity_isolation(
                candidate_sha=candidate_sha,
                expected_database_name=expected_database_name,
                expected_database_host=expected_database_host,
            )
        except (DataFetchError, DatabaseError, OSError, RuntimeError, TypeError, ValueError) as exc:
            return {
                **market_task.full_market_input_failure(_financial_capacity_error_code(exc)),
                "outcome": TaskBusinessOutcome.BLOCKED.value,
                "stage": "isolation",
                "requested": 0,
                "succeeded": 0,
                "failed": 0,
                "stored": 0,
                "published": 0,
                "must_not_use_for_decision": True,
            }

    authority_validator: _FinancialCapacityAuthorityLatch | None = None
    if action in {"formal_start", "formal_run"}:
        authority, authority_failure = _preflight_data02_task_authority(
            as_of=datetime.now(UTC),
            minimum_window=_FINANCIAL_PUBLICATIONS_AUTHORITY_WINDOW,
        )
        if authority_failure is not None:
            return authority_failure
        if authority is None:
            raise RuntimeError("authority preflight returned no context")
        authority_validator = _FinancialCapacityAuthorityLatch(authority)

    try:
        workflow = make_financial_publication_capacity_workflow(
            isolation_attestation_sha256=isolation_attestation_sha256,
            authority_validator=authority_validator,
        )
        if action in {"qualification_run", "capacity_rehearsal_run", "formal_run"}:
            checkpoint = workflow.get_checkpoint(workflow_id)
            expected_stage = (
                "qualification"
                if action == "qualification_run"
                else (
                    "capacity_rehearsal"
                    if action == "capacity_rehearsal_run"
                    else "formal_publication"
                )
            )
            if (
                checkpoint is None
                or checkpoint.stage != expected_stage
                or checkpoint.binding.candidate_sha != candidate_sha
            ):
                reason = "financial_capacity_checkpoint_candidate_binding_mismatch"
                return {
                    **market_task.full_market_input_failure(reason),
                    "outcome": TaskBusinessOutcome.BLOCKED.value,
                    "stage": "capacity",
                    "workflow_id": workflow_id,
                    "requested": 0,
                    "succeeded": 0,
                    "failed": 0,
                    "stored": 0,
                    "published": 0,
                    "provider_requests": 0,
                    "reserved_provider_requests": 0,
                    "blocked_reason": reason,
                    "must_not_use_for_decision": True,
                }
        if action == "qualification_start":
            result = workflow.start_qualification(
                workflow_id=workflow_id,
                candidate_sha=candidate_sha,
                total_provider_request_budget=total_provider_request_budget,
            )
        elif action == "qualification_run":
            result = workflow.run_qualification(
                workflow_id=workflow_id,
                max_slices=max_slices,
            )
        elif action == "capacity_rehearsal_start":
            result = workflow.start_capacity_rehearsal(
                workflow_id=workflow_id,
                candidate_sha=candidate_sha,
                total_provider_request_budget=total_provider_request_budget,
            )
        elif action == "capacity_rehearsal_run":
            result = workflow.run_capacity_rehearsal(
                workflow_id=workflow_id,
                max_slices=max_slices,
            )
        elif action == "formal_start":
            source_checkpoint = workflow.get_checkpoint(capacity_rehearsal_workflow_id)
            if (
                source_checkpoint is None
                or source_checkpoint.stage != "capacity_rehearsal"
                or source_checkpoint.status != "success"
                or source_checkpoint.capacity_receipt is None
            ):
                return {
                    **market_task.full_market_input_failure(
                        "financial_capacity_receipt_not_qualified"
                    ),
                    "outcome": TaskBusinessOutcome.BLOCKED.value,
                    "stage": "capacity",
                    "workflow_id": workflow_id,
                    "requested": 0,
                    "succeeded": 0,
                    "failed": 0,
                    "stored": 0,
                    "published": 0,
                    "blocked_reason": "financial_capacity_receipt_not_qualified",
                    "must_not_use_for_decision": True,
                }
            result = workflow.start_formal_publication(
                workflow_id=workflow_id,
                candidate_sha=candidate_sha,
                capacity_receipt=source_checkpoint.capacity_receipt,
                scope_capacity_import_id=scope_capacity_import_id,
            )
        else:
            result = workflow.run_formal_publication(
                workflow_id=workflow_id,
                max_slices=max_slices,
            )
    except (
        DataFetchError,
        DataValidationError,
        DatabaseError,
        FinancialCapacityWorkflowError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        reason = _financial_capacity_error_code(exc)
        return {
            **market_task.full_market_input_failure(reason),
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "stage": "capacity",
            "workflow_id": workflow_id,
            "requested": 0,
            "succeeded": 0,
            "failed": 0,
            "stored": 0,
            "published": 0,
            "blocked_reason": reason,
            "must_not_use_for_decision": True,
        }
    return _financial_capacity_result_payload(result)


def _financial_capacity_result_payload(
    result: FinancialCapacityWorkflowResult,
) -> dict[str, object]:
    """Serialize receipt-safe counters and checkpoint identity for Task Monitor."""

    checkpoint = result.checkpoint
    payload: dict[str, object] = {
        "success": result.outcome in {"success", "partial", "noop"},
        "outcome": result.outcome,
        "stage": checkpoint.stage,
        "workflow_id": checkpoint.workflow_id,
        "manifest_sha256": checkpoint.manifest_sha256,
        "requested": checkpoint.requested,
        "succeeded": checkpoint.succeeded,
        "failed": checkpoint.failed,
        "stored": checkpoint.stored,
        "provider_requests": checkpoint.observed_provider_requests,
        "reserved_provider_requests": checkpoint.reserved_provider_requests,
        "total_provider_request_budget": checkpoint.total_provider_request_budget,
        "next_slice_index": checkpoint.next_slice_index,
        "slice_count": checkpoint.manifest_count,
        "checkpoint_revision": checkpoint.revision,
        "published": int(checkpoint.publication_hash is not None),
        "publication_updated": checkpoint.publication_hash is not None,
        "must_not_use_for_decision": result.outcome in {"blocked", "failed", "partial"},
    }
    if result.blocked_reason:
        payload["blocked_reason"] = result.blocked_reason
    if checkpoint.capacity_receipt is not None:
        payload["capacity_receipt"] = checkpoint.capacity_receipt.to_dict()
        payload["capacity_receipt_sha256"] = checkpoint.capacity_receipt.sha256
    if checkpoint.publication_hash is not None:
        payload["publication_hash"] = checkpoint.publication_hash
    return payload


def _financial_capacity_error_code(exc: BaseException) -> str:
    """Return a stable public code without including provider or database details."""

    code = getattr(exc, "code", "")
    if type(code) is str and code.startswith("FINANCIAL_"):
        return code.lower()
    return "financial_capacity_workflow_unavailable"


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
