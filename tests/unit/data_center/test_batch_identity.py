"""Provider batch identity guard tests."""

from __future__ import annotations

import pytest

from apps.data_center.application.batch_identity import (
    ProviderAssetIdentityError,
    require_exact_asset_identities,
    require_single_asset_identity,
)


def test_exact_asset_identities_accept_same_canonical_set_in_provider_order() -> None:
    returned = require_exact_asset_identities(
        requested_asset_codes=("000001.SZ", "600000.SH"),
        returned_asset_codes=("600000.SH", "000001.SZ"),
        label="quote",
    )

    assert returned == ("600000.SH", "000001.SZ")


@pytest.mark.parametrize(
    "returned",
    [
        ("000001.SZ",),
        ("000001.SZ", "000001.SZ"),
        ("000001.SZ", "600001.SH"),
        ("000001.SZ", ""),
        ("000001.SZ", " 600000.SH"),
        ("000001.SZ", "600000.sh"),
        ("000001.SZ", None),
    ],
)
def test_exact_asset_identities_reject_incomplete_duplicate_or_noncanonical_rows(
    returned: tuple[object, ...],
) -> None:
    with pytest.raises(ProviderAssetIdentityError, match="quote provider asset identit"):
        require_exact_asset_identities(
            requested_asset_codes=("000001.SZ", "600000.SH"),
            returned_asset_codes=returned,
            label="quote",
        )


def test_exact_asset_identities_use_domain_normalization_for_request_only() -> None:
    returned = require_exact_asset_identities(
        requested_asset_codes=("000001.XSHE", "sh600000"),
        returned_asset_codes=("000001.SZ", "600000.SH"),
        label="quote",
    )

    assert returned == ("000001.SZ", "600000.SH")


@pytest.mark.parametrize("returned", [("FOO",), ("000001.XSHE",), ("sh600000",)])
def test_provider_identities_must_arrive_in_canonical_domain_format(
    returned: tuple[object, ...],
) -> None:
    with pytest.raises(ProviderAssetIdentityError, match="provider asset identities"):
        require_exact_asset_identities(
            requested_asset_codes=("000001.SZ",),
            returned_asset_codes=returned,
            label="quote",
        )


def test_single_asset_identity_allows_empty_or_repeated_time_series_rows() -> None:
    assert (
        require_single_asset_identity(
            requested_asset_code="000001.XSHE",
            returned_asset_codes=(),
            label="valuation",
        )
        == ()
    )
    assert require_single_asset_identity(
        requested_asset_code="000001.XSHE",
        returned_asset_codes=("000001.SZ", "000001.SZ"),
        label="valuation",
    ) == ("000001.SZ", "000001.SZ")
