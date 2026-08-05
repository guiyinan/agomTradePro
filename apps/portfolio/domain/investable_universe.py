"""Published investable-universe evidence for governed optimization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ._optimization_canonical import (
    hash_components,
    require_aware,
    require_ordered_unique,
    require_sha256,
    require_text,
    require_token,
    utc_text,
)


class AssetMarket(str, Enum):
    """Supported market tags; numeric rule values remain external evidence."""

    A_SHARE = "a_share"
    FUND = "fund"
    BOND = "bond"
    COMMODITY = "commodity"


@dataclass(frozen=True)
class InvestableUniverseMember:
    """One Published membership with explicit trading and retention rights."""

    asset_code: str
    market: AssetMarket
    currency: str
    membership_ref: str
    membership_version: str
    membership_content_hash: str
    can_buy: bool
    can_sell: bool
    retain_if_held: bool

    def __post_init__(self) -> None:
        """Reject ungoverned or unusable membership rows."""

        require_token(self.asset_code, "asset_code")
        require_token(self.currency, "currency")
        require_text(self.membership_ref, "membership_ref")
        require_token(self.membership_version, "membership_version")
        require_sha256(self.membership_content_hash, "membership_content_hash")
        if not isinstance(self.market, AssetMarket):
            raise ValueError("universe member market is invalid")
        for field_name, value in (
            ("can_buy", self.can_buy),
            ("can_sell", self.can_sell),
            ("retain_if_held", self.retain_if_held),
        ):
            if not isinstance(value, bool):
                raise ValueError(f"{field_name} must be a boolean")
        if not (self.can_buy or self.can_sell or self.retain_if_held):
            raise ValueError("universe member must have a governed trade or retention right")


@dataclass(frozen=True)
class InvestableUniverseSnapshot:
    """Portfolio-owned snapshot of exact Published investable membership."""

    universe_id: str
    version: str
    owner: str
    membership_publication_id: str
    membership_publication_version: str
    membership_publication_content_hash: str
    observed_at: datetime
    available_at: datetime
    valid_until: datetime
    members: tuple[InvestableUniverseMember, ...]
    universe_hash: str
    owner_attestation_hash: str

    def __post_init__(self) -> None:
        """Recompute membership and owner hashes without inferring any asset."""

        for field_name, value in (
            ("universe_id", self.universe_id),
            ("version", self.version),
            ("owner", self.owner),
            ("membership_publication_version", self.membership_publication_version),
        ):
            require_token(value, field_name)
        if self.owner != "portfolio":
            raise ValueError("investable universe owner must be portfolio")
        require_text(self.membership_publication_id, "membership_publication_id")
        require_sha256(
            self.membership_publication_content_hash,
            "membership_publication_content_hash",
        )
        require_aware(self.observed_at, "universe observed_at")
        require_aware(self.available_at, "universe available_at")
        require_aware(self.valid_until, "universe valid_until")
        if not self.observed_at <= self.available_at < self.valid_until:
            raise ValueError("universe bitemporal availability window is invalid")
        require_ordered_unique(
            tuple(item.asset_code for item in self.members),
            "universe members",
        )
        expected_hash = investable_universe_hash(self)
        require_sha256(self.universe_hash, "universe_hash")
        if self.universe_hash != expected_hash:
            raise ValueError("universe content hash mismatch")
        expected_owner_hash = universe_owner_hash(self, expected_hash)
        require_sha256(self.owner_attestation_hash, "universe owner_attestation_hash")
        if self.owner_attestation_hash != expected_owner_hash:
            raise ValueError("universe owner attestation hash mismatch")


def build_investable_universe_snapshot(
    *,
    universe_id: str,
    version: str,
    owner: str,
    membership_publication_id: str,
    membership_publication_version: str,
    membership_publication_content_hash: str,
    observed_at: datetime,
    available_at: datetime,
    valid_until: datetime,
    members: tuple[InvestableUniverseMember, ...],
) -> InvestableUniverseSnapshot:
    """Build a canonical universe from an explicit publication-availability time."""

    ordered = tuple(sorted(members, key=lambda item: item.asset_code))
    values = (
        universe_id,
        version,
        owner,
        membership_publication_id,
        membership_publication_version,
        membership_publication_content_hash,
        observed_at,
        available_at,
        valid_until,
        ordered,
    )
    universe_hash = _universe_hash_values(*values)
    owner_hash = _universe_owner_hash_values(
        owner=owner,
        version=version,
        publication_id=membership_publication_id,
        publication_hash=membership_publication_content_hash,
        universe_hash=universe_hash,
        observed_at=observed_at,
        available_at=available_at,
        valid_until=valid_until,
    )
    return InvestableUniverseSnapshot(
        universe_id=universe_id,
        version=version,
        owner=owner,
        membership_publication_id=membership_publication_id,
        membership_publication_version=membership_publication_version,
        membership_publication_content_hash=membership_publication_content_hash,
        observed_at=observed_at,
        available_at=available_at,
        valid_until=valid_until,
        members=ordered,
        universe_hash=universe_hash,
        owner_attestation_hash=owner_hash,
    )


def investable_universe_hash(universe: InvestableUniverseSnapshot) -> str:
    """Recompute the exact Published membership payload hash."""

    return _universe_hash_values(
        universe.universe_id,
        universe.version,
        universe.owner,
        universe.membership_publication_id,
        universe.membership_publication_version,
        universe.membership_publication_content_hash,
        universe.observed_at,
        universe.available_at,
        universe.valid_until,
        universe.members,
    )


def _universe_hash_values(
    universe_id: str,
    version: str,
    owner: str,
    publication_id: str,
    publication_version: str,
    publication_hash: str,
    observed_at: datetime,
    available_at: datetime,
    valid_until: datetime,
    members: tuple[InvestableUniverseMember, ...],
) -> str:
    member_parts = tuple(
        "|".join(
            (
                item.asset_code,
                item.market.value,
                item.currency,
                item.membership_ref,
                item.membership_version,
                item.membership_content_hash,
                str(item.can_buy),
                str(item.can_sell),
                str(item.retain_if_held),
            )
        )
        for item in members
    )
    return hash_components(
        "investable-universe-snapshot.v1",
        universe_id,
        version,
        owner,
        publication_id,
        publication_version,
        publication_hash,
        utc_text(observed_at),
        utc_text(available_at),
        utc_text(valid_until),
        *member_parts,
    )


def universe_owner_hash(
    universe: InvestableUniverseSnapshot,
    universe_hash: str | None = None,
) -> str:
    """Recompute the Portfolio owner attestation over Published membership."""

    return _universe_owner_hash_values(
        owner=universe.owner,
        version=universe.version,
        publication_id=universe.membership_publication_id,
        publication_hash=universe.membership_publication_content_hash,
        universe_hash=universe.universe_hash if universe_hash is None else universe_hash,
        observed_at=universe.observed_at,
        available_at=universe.available_at,
        valid_until=universe.valid_until,
    )


def _universe_owner_hash_values(
    *,
    owner: str,
    version: str,
    publication_id: str,
    publication_hash: str,
    universe_hash: str,
    observed_at: datetime,
    available_at: datetime,
    valid_until: datetime,
) -> str:
    return hash_components(
        "investable-universe-owner-attestation.v1",
        owner,
        version,
        publication_id,
        publication_hash,
        universe_hash,
        utc_text(observed_at),
        utc_text(available_at),
        utc_text(valid_until),
    )


__all__ = [
    "AssetMarket",
    "InvestableUniverseMember",
    "InvestableUniverseSnapshot",
    "build_investable_universe_snapshot",
    "investable_universe_hash",
    "universe_owner_hash",
]
