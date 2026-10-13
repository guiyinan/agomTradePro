"""Stable control-plane identities for DATA-02 backfill batches."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5


@dataclass(frozen=True, slots=True)
class BackfillAuthorityBinding:
    """Server-issued authority identity persisted with every batch checkpoint."""

    actor_id: str
    tenant_id: str
    owner_id: str
    content_hash: str
    valid_until: datetime

    def to_checkpoint(self) -> dict[str, str]:
        """Return the immutable, non-secret authority checkpoint projection."""

        return {
            "actor_id": self.actor_id,
            "tenant_id": self.tenant_id,
            "owner_id": self.owner_id,
            "content_hash": self.content_hash,
            "valid_until": self.valid_until.isoformat(),
        }


def backfill_control_plane_ids(idempotency_key: str) -> tuple[str, str]:
    """Return stable run and batch UUIDs for one idempotent task window."""

    run_id = str(uuid5(NAMESPACE_URL, f"agomtradepro:sync-run:{idempotency_key}"))
    batch_id = str(uuid5(NAMESPACE_URL, f"agomtradepro:sync-batch:{idempotency_key}"))
    return run_id, batch_id


def backfill_execution_token(idempotency_key: str) -> str:
    """Return the stable logical execution token retained across task retries."""

    return str(uuid5(NAMESPACE_URL, f"agomtradepro:sync-execution:{idempotency_key}"))


__all__ = [
    "BackfillAuthorityBinding",
    "backfill_control_plane_ids",
    "backfill_execution_token",
]
