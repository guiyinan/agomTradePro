"""Point-in-time A-share universe selection from persisted listing evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from apps.data_center.domain.entities import AssetMaster
from apps.data_center.domain.enums import AssetType, MarketExchange

_A_SHARE_EXCHANGES = frozenset({MarketExchange.SSE, MarketExchange.SZSE, MarketExchange.BSE})


@dataclass(frozen=True, slots=True)
class NotYetListedAsset:
    """One asset excluded by a persisted listing date after the requested trade date."""

    asset_code: str
    list_date: date
    evidence_source: str
    reason_code: str = "listed_after_target_date"


@dataclass(frozen=True, slots=True)
class TargetDateAssetUniverseScope:
    """Current active A-share candidates partitioned by target-date listing evidence."""

    target_date: date
    candidate_codes: tuple[str, ...]
    requested_codes: tuple[str, ...]
    excluded_not_yet_listed: tuple[NotYetListedAsset, ...]
    unknown_listing_date_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.target_date, date) or isinstance(self.target_date, datetime):
            raise ValueError("Target-date universe scope requires a date without time")
        all_codes = self.candidate_codes
        requested_codes = self.requested_codes
        excluded_codes = tuple(item.asset_code for item in self.excluded_not_yet_listed)
        if (
            any(not code or code != code.strip().upper() for code in all_codes)
            or len(set(all_codes)) != len(all_codes)
            or any(not code or code != code.strip().upper() for code in requested_codes)
            or len(set(requested_codes)) != len(requested_codes)
            or len(set(excluded_codes)) != len(excluded_codes)
            or set(requested_codes).intersection(excluded_codes)
            or set(requested_codes).union(excluded_codes) != set(all_codes)
            or any(item.list_date <= self.target_date for item in self.excluded_not_yet_listed)
        ):
            raise ValueError("Target-date universe scope is not a complete canonical partition")
        if any(code not in all_codes for code in self.unknown_listing_date_codes):
            raise ValueError("Unknown listing-date evidence contains an unexpected asset")


def build_target_date_a_share_scope(
    target_date: date,
    active_assets: tuple[AssetMaster, ...] | list[AssetMaster],
) -> TargetDateAssetUniverseScope:
    """Exclude only active A-shares with an explicit, non-conflicting later listing date."""

    if not isinstance(target_date, date) or isinstance(target_date, datetime):
        raise ValueError("Target-date universe scope requires a date without time")

    candidates = sorted(
        (
            asset
            for asset in active_assets
            if asset.is_active
            and asset.asset_type is AssetType.STOCK
            and asset.exchange in _A_SHARE_EXCHANGES
        ),
        key=lambda asset: asset.code,
    )
    candidate_codes = tuple(asset.code for asset in candidates)
    if any(not code or code != code.strip().upper() for code in candidate_codes) or len(
        set(candidate_codes)
    ) != len(candidate_codes):
        raise ValueError("Active A-share master contains invalid or duplicate identities")

    requested_codes: list[str] = []
    exclusions: list[NotYetListedAsset] = []
    unknown_listing_date_codes: list[str] = []
    for asset in candidates:
        listing_date = asset.list_date
        evidence_status = asset.extra.get("list_date_evidence_status")
        source_value = asset.extra.get("list_date_source")
        evidence_source = source_value.strip() if isinstance(source_value, str) else ""
        has_verified_listing_source = evidence_status == "verified" and bool(evidence_source)
        if (
            isinstance(listing_date, date)
            and not isinstance(listing_date, datetime)
            and has_verified_listing_source
        ):
            if listing_date > target_date:
                exclusions.append(
                    NotYetListedAsset(
                        asset_code=asset.code,
                        list_date=listing_date,
                        evidence_source=evidence_source,
                    )
                )
                continue
            requested_codes.append(asset.code)
            continue
        unknown_listing_date_codes.append(asset.code)
        requested_codes.append(asset.code)

    return TargetDateAssetUniverseScope(
        target_date=target_date,
        candidate_codes=candidate_codes,
        requested_codes=tuple(requested_codes),
        excluded_not_yet_listed=tuple(exclusions),
        unknown_listing_date_codes=tuple(unknown_listing_date_codes),
    )
