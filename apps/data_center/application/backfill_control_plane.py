"""Stable control-plane identities for DATA-02 backfill batches."""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5


def backfill_control_plane_ids(idempotency_key: str) -> tuple[str, str]:
    """Return stable run and batch UUIDs for one idempotent task window."""

    run_id = str(uuid5(NAMESPACE_URL, f"agomtradepro:sync-run:{idempotency_key}"))
    batch_id = str(uuid5(NAMESPACE_URL, f"agomtradepro:sync-batch:{idempotency_key}"))
    return run_id, batch_id


def backfill_execution_token(idempotency_key: str) -> str:
    """Return the stable logical execution token retained across task retries."""

    return str(uuid5(NAMESPACE_URL, f"agomtradepro:sync-execution:{idempotency_key}"))


__all__ = ["backfill_control_plane_ids", "backfill_execution_token"]
