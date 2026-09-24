"""Pure validation and outcome helpers for the full-market Celery task."""

from __future__ import annotations

from collections.abc import Sequence


def exact_provider_batch_count(
    *,
    requested_asset_codes: Sequence[str],
    stored_count: object,
    returned_asset_codes: object,
    succeeded_asset_codes: object | None = None,
) -> int:
    """Return the stored count only when every requested identity is exact."""

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


def full_market_input_failure(reason: str) -> dict[str, object]:
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
