"""Stateless validation and identity helpers for the core backfill task."""

from __future__ import annotations

import hashlib

from apps.data_center.domain.control_plane import SyncItemState, SyncRunStatus
from shared.domain.task_outcomes import TaskBusinessOutcome

BACKFILL_DATASET_KEY = "equity.core.backfill"
BACKFILL_TASK_NAME = "celery.backfill_a_share_core"


def _backfill_idempotency_key(
    source: object,
    offset: object,
    batch_size: object,
    history_days: object,
    financial_periods: object,
    authority_content_hash: object = "",
    historical_market_date: object = "",
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
            f"historical_market_date={historical_market_date!r}",
        )
    )
    digest = hashlib.sha256(material.encode("utf-8", errors="replace")).hexdigest()[:16]
    visible = (
        f"{BACKFILL_DATASET_KEY}:{source_text}:"
        f"offset={str(offset)[:24]}:"
        f"window={str(batch_size)[:24]}"
    )
    if historical_market_date:
        visible += f":date={str(historical_market_date)[:10]}"
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
