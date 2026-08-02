"""Pure macro-series semantic rules shared by data-center consumers."""

from __future__ import annotations

from typing import Any

DIRECT_INPUT_ALLOWED = "direct_allowed"
DERIVE_REQUIRED = "derive_required"


def is_direct_consumer_input_allowed(
    extra: dict[str, Any] | None,
    *,
    consumer: str,
) -> bool:
    """Return whether one macro series may feed a consumer directly."""

    metadata = dict(extra or {})
    semantics = str(metadata.get("series_semantics") or "").strip()
    default_policy = DERIVE_REQUIRED if semantics == "cumulative_level" else DIRECT_INPUT_ALLOWED
    key = f"{consumer}_input_policy"
    return str(metadata.get(key) or default_policy).strip() == DIRECT_INPUT_ALLOWED


__all__ = ["is_direct_consumer_input_allowed"]
