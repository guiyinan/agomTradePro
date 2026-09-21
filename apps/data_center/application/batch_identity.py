"""Exact provider asset-identity validation before fact mutation."""

from __future__ import annotations

import re
from collections.abc import Sequence

from apps.data_center.domain.rules import normalize_asset_code
from core.exceptions import DataValidationError


class ProviderAssetIdentityError(DataValidationError):
    """Reject provider rows whose canonical identities do not match the request."""

    default_message = "provider asset identities mismatch"
    default_code = "PROVIDER_ASSET_IDENTITY_MISMATCH"


def require_exact_asset_identities(
    *,
    requested_asset_codes: Sequence[str],
    returned_asset_codes: Sequence[object],
    label: str,
) -> tuple[str, ...]:
    """Return canonical identities or fail before any provider fact is persisted."""

    requested = tuple(
        _canonical_requested_code(code, label=label) for code in requested_asset_codes
    )
    if not requested:
        raise ProviderAssetIdentityError(f"{label} requested asset identities are empty")
    if len(set(requested)) != len(requested):
        raise ProviderAssetIdentityError(
            f"{label} requested asset identities contain duplicates",
            details={"duplicate_count": len(requested) - len(set(requested))},
        )

    returned: list[str] = []
    for value in returned_asset_codes:
        returned.append(_canonical_provider_code(value, label=label))

    duplicate_count = len(returned) - len(set(returned))
    missing = set(requested) - set(returned)
    unexpected = set(returned) - set(requested)
    if len(returned) != len(requested) or duplicate_count or missing or unexpected:
        raise ProviderAssetIdentityError(
            f"{label} provider asset identities mismatch",
            details={
                "requested_count": len(requested),
                "returned_count": len(returned),
                "duplicate_count": duplicate_count,
                "missing_count": len(missing),
                "unexpected_count": len(unexpected),
            },
        )
    return tuple(returned)


def require_single_asset_identity(
    *,
    requested_asset_code: str,
    returned_asset_codes: Sequence[object],
    label: str,
) -> tuple[str, ...]:
    """Validate zero or more time-series rows for one requested asset."""

    requested = _canonical_requested_code(requested_asset_code, label=label)
    returned = tuple(_canonical_provider_code(value, label=label) for value in returned_asset_codes)
    if any(value != requested for value in returned):
        raise ProviderAssetIdentityError(
            f"{label} provider asset identities mismatch",
            details={
                "requested_count": 1,
                "returned_count": len(returned),
                "unexpected_count": sum(value != requested for value in returned),
            },
        )
    return returned


def _canonical_requested_code(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise ProviderAssetIdentityError(f"{label} requested asset identity is invalid")
    canonical = normalize_asset_code(value)
    if not _is_canonical_asset_code(canonical):
        raise ProviderAssetIdentityError(f"{label} requested asset identity is invalid")
    return canonical


def _canonical_provider_code(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise ProviderAssetIdentityError(f"{label} provider asset identity is invalid")
    canonical = normalize_asset_code(value)
    if value != canonical or not _is_canonical_asset_code(canonical):
        raise ProviderAssetIdentityError(f"{label} provider asset identities are not canonical")
    return canonical


def _is_canonical_asset_code(value: str) -> bool:
    return bool(re.fullmatch(r"\d+\.(?:SH|SZ|BJ|HK)", value)) and len(value) <= 20
