"""Application-level query helpers for cross-app signal access."""

from __future__ import annotations

from typing import Any

from apps.signal.infrastructure.repositories import DjangoSignalRepository


def get_signal_invalidation_payloads(signal_ids: list[int]) -> dict[str, dict[str, Any]]:
    """Return invalidation payloads keyed by signal id."""
    normalized_ids = [signal_id for signal_id in signal_ids if signal_id]
    if not normalized_ids:
        return {}
    return DjangoSignalRepository().get_invalidation_payloads(normalized_ids)
