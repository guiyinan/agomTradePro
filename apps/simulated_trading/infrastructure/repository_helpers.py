"""Shared persistence helpers for simulated-trading repositories."""

from __future__ import annotations


def _require_saved_id(model_id: int | None, entity_name: str) -> int:
    """Return a persisted ORM identifier or fail at the repository boundary."""

    if model_id is None:
        raise RuntimeError(f"{entity_name} was saved without a primary key")
    return model_id
