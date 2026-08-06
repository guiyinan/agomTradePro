"""Domain contracts for database-backup delivery policy and state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class BackupDeliveryState:
    """Mutable operational state kept separately from delivery policy."""

    last_sent_at: datetime | None = None
    download_token_digest: str = ""
    download_token_expires_at: datetime | None = None
    download_token_consumed_at: datetime | None = None


__all__ = ["BackupDeliveryState"]
