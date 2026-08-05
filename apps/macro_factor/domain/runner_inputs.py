"""Manifest-bound in-memory inputs for reproducible R3 research runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from apps.macro_factor.domain.entities import PITSelectedFactVersion

from ._runner_support import (
    decimal_text,
    hash_payload,
    require_aware,
    require_finite,
    require_sha256,
    require_token,
    utc_text,
)


@dataclass(frozen=True)
class VersionedResearchContract:
    """Exact version/hash identity for one externally governed contract."""

    version: str
    content_hash: str

    def __post_init__(self) -> None:
        require_token(self.version, "VersionedResearchContract.version")
        require_sha256(self.content_hash, "VersionedResearchContract.content_hash")


@dataclass(frozen=True)
class ProxyObservation:
    """One proxy value on an immutable PIT research row."""

    asset_code: str
    value: Decimal
    fact_version: PITSelectedFactVersion

    def __post_init__(self) -> None:
        require_token(self.asset_code, "ProxyObservation.asset_code")
        require_finite(self.value, "ProxyObservation.value")


@dataclass(frozen=True)
class PITResearchRow:
    """One design row with observation and label-availability chronology."""

    row_id: str
    observation_date: date
    target_period_start: date
    target_period_end: date
    available_at: datetime
    label_available_at: datetime
    target_value: Decimal
    target_fact_version: PITSelectedFactVersion
    proxies: tuple[ProxyObservation, ...]

    def __post_init__(self) -> None:
        require_token(self.row_id, "PITResearchRow.row_id")
        require_aware(self.available_at, "PITResearchRow.available_at")
        require_aware(self.label_available_at, "PITResearchRow.label_available_at")
        require_finite(self.target_value, "PITResearchRow.target_value")
        if self.target_period_start > self.target_period_end:
            raise ValueError("PITResearchRow target period is invalid")
        if self.observation_date > self.target_period_end:
            raise ValueError("PITResearchRow target cannot precede observation")
        if self.label_available_at < self.available_at:
            raise ValueError("PITResearchRow label cannot be available before its design row")
        if not (
            self.target_period_start
            <= self.target_fact_version.effective_at.date()
            <= self.target_period_end
        ):
            raise ValueError("PITResearchRow target fact effective time is outside target period")
        if self.target_fact_version.available_at != self.label_available_at:
            raise ValueError("PITResearchRow label availability must match target fact")
        if not self.proxies:
            raise ValueError("PITResearchRow.proxies cannot be empty")
        codes = tuple(item.asset_code for item in self.proxies)
        if len(codes) != len(set(codes)):
            raise ValueError("PITResearchRow proxy identities must be unique")
        if any(
            item.fact_version.effective_at.date() != self.observation_date for item in self.proxies
        ):
            raise ValueError("proxy fact effective times must match observation_date")
        if self.available_at != max(item.fact_version.available_at for item in self.proxies):
            raise ValueError("row available_at must equal latest proxy fact availability")

    def canonical_payload(self) -> dict[str, object]:
        """Return stable row content used by dataset and fold design hashes."""

        return {
            "row_id": self.row_id,
            "observation_date": self.observation_date.isoformat(),
            "target_period_start": self.target_period_start.isoformat(),
            "target_period_end": self.target_period_end.isoformat(),
            "available_at": utc_text(self.available_at),
            "label_available_at": utc_text(self.label_available_at),
            "target_value": decimal_text(self.target_value),
            "target_fact_version": {
                "version_id": self.target_fact_version.version_id,
                "content_hash": self.target_fact_version.content_hash,
                "effective_at": utc_text(self.target_fact_version.effective_at),
                "available_at": utc_text(self.target_fact_version.available_at),
            },
            "proxies": [
                {
                    "asset_code": item.asset_code,
                    "value": decimal_text(item.value),
                    "fact_version": {
                        "version_id": item.fact_version.version_id,
                        "content_hash": item.fact_version.content_hash,
                        "effective_at": utc_text(item.fact_version.effective_at),
                        "available_at": utc_text(item.fact_version.available_at),
                    },
                }
                for item in sorted(self.proxies, key=lambda value: value.asset_code)
            ],
        }

    def proxy_value(self, asset_code: str) -> Decimal:
        """Return the exact proxy value for an already validated asset code."""

        return next(item.value for item in self.proxies if item.asset_code == asset_code)


@dataclass(frozen=True)
class PITResearchDataset:
    """In-memory, manifest-bound design rows; never a second fact store."""

    manifest_id: str
    manifest_hash: str
    manifest_as_of: datetime
    target_code: str
    candidate_asset_codes: tuple[str, ...]
    rows: tuple[PITResearchRow, ...]

    def __post_init__(self) -> None:
        require_token(self.manifest_id, "PITResearchDataset.manifest_id")
        require_sha256(self.manifest_hash, "PITResearchDataset.manifest_hash")
        require_aware(self.manifest_as_of, "PITResearchDataset.manifest_as_of")
        require_token(self.target_code, "PITResearchDataset.target_code")
        if not self.candidate_asset_codes:
            raise ValueError("PITResearchDataset.candidate_asset_codes cannot be empty")
        for asset_code in self.candidate_asset_codes:
            require_token(asset_code, "PITResearchDataset.candidate_asset_code")
        if len(self.candidate_asset_codes) != len(set(self.candidate_asset_codes)):
            raise ValueError("PITResearchDataset candidate identities must be unique")
        if not self.rows:
            raise ValueError("PITResearchDataset.rows cannot be empty")
        row_ids = tuple(item.row_id for item in self.rows)
        if len(row_ids) != len(set(row_ids)):
            raise ValueError("PITResearchDataset row identities must be unique")
        expected_codes = frozenset(self.candidate_asset_codes)
        for row in self.rows:
            if frozenset(item.asset_code for item in row.proxies) != expected_codes:
                raise ValueError(
                    f"PIT row {row.row_id} does not cover the exact candidate universe"
                )
            if (
                row.available_at > self.manifest_as_of
                or row.label_available_at > self.manifest_as_of
            ):
                raise ValueError(f"PIT row {row.row_id} exceeds manifest knowledge time")

    @property
    def content_hash(self) -> str:
        """Seal exact PIT row IDs, values, and availability timestamps."""

        return hash_payload(
            {
                "manifest_id": self.manifest_id,
                "manifest_hash": self.manifest_hash.lower(),
                "manifest_as_of": utc_text(self.manifest_as_of),
                "target_code": self.target_code,
                "candidate_asset_codes": list(self.candidate_asset_codes),
                "rows": [
                    row.canonical_payload()
                    for row in sorted(self.rows, key=lambda item: item.row_id)
                ],
            }
        )

    @property
    def rows_by_id(self) -> dict[str, PITResearchRow]:
        """Return an ephemeral lookup for pure runner calculations."""

        return {item.row_id: item for item in self.rows}


__all__ = [
    "PITResearchDataset",
    "PITResearchRow",
    "ProxyObservation",
    "VersionedResearchContract",
]
