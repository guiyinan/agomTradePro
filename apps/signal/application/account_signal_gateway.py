"""Signal-owned composition adapter for Account's optional signal lookup port."""

from __future__ import annotations

from core.integration.owned_signal_asset_code import register_owned_signal_asset_code_lookup

from .owned_signal_queries import get_owned_signal_asset_code


def register_account_owned_signal_asset_code_lookup() -> None:
    """Register Signal's owner-scoped asset-code query for Account consumers."""

    register_owned_signal_asset_code_lookup(get_owned_signal_asset_code)


__all__ = ["register_account_owned_signal_asset_code_lookup"]
