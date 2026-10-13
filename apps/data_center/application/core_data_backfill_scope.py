"""Universe binding and initial scope checks for core-data backfills."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from shared.domain.task_outcomes import TaskBusinessOutcome

from .core_data_backfill_contracts import CoreDataBackfillServices


@dataclass(frozen=True, slots=True)
class PreparedCoreBackfillScope:
    """Frozen universe and checkpoint identity for one bounded batch."""

    asset_codes: tuple[str, ...]
    batch_codes: tuple[str, ...]
    bound_universe_hash: str
    checkpoint: dict[str, object]
    idempotency_key: str


def prepare_core_backfill_scope(
    *,
    validated_offset: int,
    validated_batch_size: int,
    normalized_source: str,
    idempotency_key: str,
    expected_universe_hash: str,
    started_at: datetime,
    services: CoreDataBackfillServices,
) -> PreparedCoreBackfillScope | dict[str, Any]:
    """Validate and freeze the active universe before provider access."""

    if expected_universe_hash and (
        len(expected_universe_hash) != 64
        or any(character not in "0123456789abcdef" for character in expected_universe_hash)
    ):
        return {
            "success": False,
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "stage": "universe",
            "blocked_reason": "invalid_expected_universe_hash",
            "requested": 0,
            "succeeded": 0,
            "failed": 0,
            "stored": 0,
            "checkpoint": {
                "offset": validated_offset,
                "next_offset": validated_offset,
                "total_assets": 0,
                "complete": False,
                "universe_hash": expected_universe_hash,
                "authority": services.authority_binding.to_checkpoint(),
            },
        }
    raw_asset_codes = services.list_active_stock_codes()
    invalid_asset_code_type = any(not isinstance(asset_code, str) for asset_code in raw_asset_codes)
    if invalid_asset_code_type:
        normalized_asset_codes: tuple[str, ...] = ()
    else:
        normalized_asset_codes = tuple(asset_code.strip().upper() for asset_code in raw_asset_codes)
    if (
        invalid_asset_code_type
        or any(not asset_code for asset_code in normalized_asset_codes)
        or len(set(normalized_asset_codes)) != len(normalized_asset_codes)
    ):
        return {
            "success": False,
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "stage": "universe",
            "blocked_reason": "invalid_active_universe",
            "requested": 0,
            "succeeded": 0,
            "failed": 0,
            "stored": 0,
            "checkpoint": {
                "offset": validated_offset,
                "next_offset": validated_offset,
                "total_assets": 0,
                "complete": False,
                "authority": services.authority_binding.to_checkpoint(),
            },
        }
    asset_codes = sorted(normalized_asset_codes)
    universe_payload = json.dumps(
        {
            "schema": "active-a-share-universe.v1",
            "asset_codes": asset_codes,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    observed_universe_hash = hashlib.sha256(universe_payload.encode("utf-8")).hexdigest()
    bound_universe_hash = expected_universe_hash or observed_universe_hash
    idempotency_prefix = idempotency_key.rsplit(":", 1)[0]
    bound_digest = hashlib.sha256(
        f"{idempotency_key}|universe_hash={bound_universe_hash}".encode()
    ).hexdigest()[:16]
    idempotency_key = f"{idempotency_prefix}:{bound_digest}"
    total_assets = len(asset_codes)
    batch_codes = asset_codes[validated_offset : validated_offset + validated_batch_size]
    next_offset = validated_offset + len(batch_codes)
    checkpoint = {
        "offset": validated_offset,
        "next_offset": next_offset,
        "total_assets": total_assets,
        "complete": next_offset >= total_assets,
        "universe_hash": bound_universe_hash,
        "authority": services.authority_binding.to_checkpoint(),
    }
    if expected_universe_hash and expected_universe_hash != observed_universe_hash:
        failed_count = len(batch_codes)
        blocked_checkpoint = {
            **checkpoint,
            "next_offset": validated_offset,
            "complete": False,
            "observed_universe_hash": observed_universe_hash,
        }
        services.persist_control_plane(
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
            error_code="universe_hash_mismatch",
            error_message="active universe differs from the frozen resume binding",
        )
        return {
            "success": False,
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "stage": "universe",
            "blocked_reason": "universe_hash_mismatch",
            "requested": failed_count,
            "succeeded": 0,
            "failed": failed_count,
            "stored": 0,
            "checkpoint": blocked_checkpoint,
        }
    if not batch_codes:
        services.persist_control_plane(
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

    return PreparedCoreBackfillScope(
        asset_codes=tuple(asset_codes),
        batch_codes=tuple(batch_codes),
        bound_universe_hash=bound_universe_hash,
        checkpoint=checkpoint,
        idempotency_key=idempotency_key,
    )


__all__ = ["PreparedCoreBackfillScope", "prepare_core_backfill_scope"]
