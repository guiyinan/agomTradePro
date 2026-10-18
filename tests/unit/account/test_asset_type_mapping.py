"""Strict asset-class translation must leave unknown source categories unresolved."""

from typing import cast

import pytest

from apps.account.domain.asset_type_mapping import (
    map_account_asset_type_compat,
    map_account_asset_type_strict,
)


@pytest.mark.parametrize(
    ("asset_class", "expected"),
    [("equity", "equity"), ("fund", "fund"), ("fixed_income", "bond")],
)
def test_strict_mapping_preserves_explicit_supported_asset_classes(
    asset_class: str,
    expected: str,
) -> None:
    """Known canonical Account categories map to their existing ledger types."""
    assert map_account_asset_type_strict(asset_class) == expected


@pytest.mark.parametrize(
    "asset_class",
    ["unregistered_class", "", None, 7, True],
    ids=["unknown", "empty", "none", "integer", "boolean"],
)
def test_strict_mapping_does_not_infer_a_ledger_type_for_unknown_input(
    asset_class: object,
) -> None:
    """Unknown or wrongly typed source metadata cannot silently become equity."""
    assert map_account_asset_type_strict(cast(str, asset_class)) is None


def test_compatibility_mapping_keeps_its_explicit_historical_fallback() -> None:
    """Only the compatibility API preserves the old unknown-to-equity fallback."""
    assert map_account_asset_type_compat("unregistered_class") == "equity"
