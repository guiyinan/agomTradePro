"""App-neutral typed registry for owner-scoped Signal asset-code queries."""

from __future__ import annotations

from typing import Protocol


class OwnedSignalAssetCodeLookup(Protocol):
    """Return a Signal asset code only after checking its owner."""

    def __call__(self, *, signal_id: int, user_id: int) -> str | None:
        """Resolve the owner's asset code, or None when inaccessible."""
        ...


_owned_signal_asset_code_lookup: OwnedSignalAssetCodeLookup | None = None


def register_owned_signal_asset_code_lookup(
    lookup: OwnedSignalAssetCodeLookup,
) -> None:
    """Register the Signal-owned lookup during Django application startup."""

    global _owned_signal_asset_code_lookup
    _owned_signal_asset_code_lookup = lookup


def get_owned_signal_asset_code(*, signal_id: int, user_id: int) -> str | None:
    """Resolve a Signal asset code without importing its owning App."""

    if signal_id <= 0 or user_id <= 0:
        return None
    lookup = _owned_signal_asset_code_lookup
    if lookup is None:
        return None
    return lookup(signal_id=signal_id, user_id=user_id)


__all__ = [
    "OwnedSignalAssetCodeLookup",
    "get_owned_signal_asset_code",
    "register_owned_signal_asset_code_lookup",
]
