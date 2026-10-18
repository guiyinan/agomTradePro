"""Strict ledger classification and historical compatibility mappings."""

from typing import cast

import pytest

from apps.account.domain.asset_type_mapping import (
    map_account_asset_type_compat,
    map_account_asset_type_strict,
)


@pytest.mark.parametrize("asset_class", ["other", "derivative", "commodity", "cash", "currency"])
def test_strict_mapping_rejects_ambiguous_asset_classes(asset_class: str) -> None:
    """Ambiguous legacy labels cannot authorize an account quantity projection."""
    assert map_account_asset_type_strict(asset_class) is None


@pytest.mark.parametrize(
    ("asset_class", "expected"),
    [("equity", "equity"), ("fund", "fund"), ("fixed_income", "bond")],
)
def test_strict_mapping_keeps_explicit_canonical_asset_classes(
    asset_class: str,
    expected: str,
) -> None:
    """The three explicit account classes retain their ledger classification."""
    assert map_account_asset_type_strict(asset_class) == expected


@pytest.mark.parametrize(
    ("asset_class", "expected"),
    [
        ("equity", "equity"),
        ("fund", "fund"),
        ("fixed_income", "bond"),
        ("commodity", "equity"),
        ("currency", "fund"),
        ("cash", "fund"),
        ("derivative", "equity"),
        ("other", "equity"),
    ],
)
def test_compat_mapping_preserves_all_historical_asset_classes(
    asset_class: str,
    expected: str,
) -> None:
    """Existing compatibility callers keep the complete eight-class mapping."""
    assert map_account_asset_type_compat(asset_class) == expected


def test_compat_mapping_keeps_the_unknown_equity_fallback() -> None:
    """Unknown historical labels continue to use the compatibility fallback."""
    assert map_account_asset_type_strict("unrecognized") is None
    assert map_account_asset_type_compat("unrecognized") == "equity"


@pytest.mark.parametrize("asset_class", [None, 17, True])
def test_compat_mapping_keeps_nonstrings_as_historical_fallback(asset_class: object) -> None:
    """Malformed historical categories retain the old compatibility response."""
    assert map_account_asset_type_compat(cast(str, asset_class)) == "equity"
