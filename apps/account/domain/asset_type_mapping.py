"""Canonical mapping from Account asset classes to unified ledger types."""

from __future__ import annotations

_ACCOUNT_ASSET_TYPE_BY_CLASS: dict[str, str] = {
    "equity": "equity",
    "fund": "fund",
    "fixed_income": "bond",
    "commodity": "equity",
    "currency": "fund",
    "cash": "fund",
    "derivative": "equity",
    "other": "equity",
}


_CANONICAL_ACCOUNT_ASSET_TYPE_BY_CLASS: dict[str, str] = {
    "equity": "equity",
    "fund": "fund",
    "fixed_income": "bond",
}


def map_account_asset_type_strict(asset_class: str) -> str | None:
    """Map only explicit canonical classes, returning ``None`` when ambiguous."""

    if type(asset_class) is not str:
        return None
    return _CANONICAL_ACCOUNT_ASSET_TYPE_BY_CLASS.get(asset_class)


def map_account_asset_type_compat(asset_class: str) -> str:
    """Preserve the historical eight-class mapping and unknown fallback."""

    if type(asset_class) is not str:
        return "equity"
    return _ACCOUNT_ASSET_TYPE_BY_CLASS.get(asset_class, "equity")
