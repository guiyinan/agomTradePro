"""Typed requests and results for policy-pinned simulated portfolio-risk inputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, tzinfo
from decimal import Decimal
from typing import Literal, Protocol

from apps.data_center.domain.sina_quote_capture import SinaQuoteCapture
from apps.risk_center.application.portfolio_risk_policy import (
    PortfolioRiskPolicyBundle,
    PortfolioRiskSourceReference,
)
from apps.risk_center.domain.close_snapshot_simulation import (
    CloseSnapshotSimulationEvaluation,
)
from apps.risk_center.domain.portfolio_capacity import CapacityWindowObservation
from apps.risk_center.domain.portfolio_exposure_types import (
    ETFConstituentReport,
    IndustryMembership,
    PortfolioAssetKind,
)
from apps.risk_center.domain.portfolio_risk_clock_evidence import PortfolioRiskCaptureReceipt
from apps.risk_center.domain.portfolio_risk_sources import PortfolioRiskSourceEvidence

PortfolioRiskAssetReadStatus = Literal["complete", "partial", "blocked"]


@dataclass(frozen=True, slots=True)
class PortfolioRiskAssetIdentity:
    """One exact asset/security pair requested by the owning portfolio projection."""

    asset_code: str
    security_id: str | None

    def __post_init__(self) -> None:
        """Require canonical exact identifiers without guessing a security mapping."""

        _require_token(self.asset_code, "asset_code")
        if self.security_id is not None:
            _require_token(self.security_id, "security_id")


@dataclass(frozen=True, slots=True)
class PortfolioRiskAssetsReadRequest:
    """Inputs needed to read policy-bound retained facts at one service cutoff."""

    policy: PortfolioRiskPolicyBundle
    requested_assets: tuple[PortfolioRiskAssetIdentity, ...]
    as_of: datetime
    business_date: date
    execution_session: date
    capacity_requested_purpose: str
    account_id: int | None = None
    business_timezone: tzinfo | None = None
    business_timezone_name: str | None = None
    close_snapshot_session_provider: CloseSnapshotSessionEvidenceProvider | None = None

    def __post_init__(self) -> None:
        """Validate exact pairs and explicit clocks/purpose while preserving empty scope."""

        if type(self.policy) is not PortfolioRiskPolicyBundle:
            raise TypeError("policy must be PortfolioRiskPolicyBundle")
        _validate_asset_identities(self.requested_assets, "requested_assets")
        _require_aware(self.as_of, "as_of")
        _require_date(self.business_date, "business_date")
        _require_date(self.execution_session, "execution_session")
        _require_token(self.capacity_requested_purpose, "capacity_requested_purpose")
        if self.account_id is not None and (
            type(self.account_id) is not int or self.account_id < 1
        ):
            raise ValueError("account_id must be a positive exact integer or None")
        if self.business_timezone is not None and not isinstance(self.business_timezone, tzinfo):
            raise TypeError("business_timezone must be a timezone or None")
        if self.business_timezone_name is not None:
            _require_token(self.business_timezone_name, "business_timezone_name")
        provider = self.close_snapshot_session_provider
        if provider is not None and not callable(getattr(provider, "read_evidence", None)):
            raise TypeError("close_snapshot_session_provider must expose read_evidence")


@dataclass(frozen=True, slots=True)
class CloseSnapshotSessionEvidence:
    """One evaluation produced by the existing close-only simulation use case."""

    evaluation: CloseSnapshotSimulationEvaluation

    def __post_init__(self) -> None:
        """Reject payload-shaped or unqualified substitutes for the typed result."""

        if type(self.evaluation) is not CloseSnapshotSimulationEvaluation:
            raise TypeError("evaluation must be CloseSnapshotSimulationEvaluation")


class CloseSnapshotSessionEvidenceProvider(Protocol):
    """Supply exact existing ASH-03 close evaluations to a risk input read."""

    def read_evidence(
        self,
        *,
        capture: SinaQuoteCapture,
        source_reference: PortfolioRiskSourceReference,
        receipt: PortfolioRiskCaptureReceipt,
        retained_payload_hash: str,
        account_id: int,
        asset_code: str,
        security_id: str,
        trading_date: date,
        as_of: datetime,
    ) -> CloseSnapshotSessionEvidence | None:
        """Return a cutoff-bound evaluation or None when that close source is absent."""


@dataclass(frozen=True, slots=True)
class PortfolioRiskAssetInputs:
    """Source-qualified facts available for one exact asset/security pair."""

    asset_code: str
    security_id: str | None
    kind: PortfolioAssetKind | None
    price: Decimal | None
    quantity_unit: str | None
    price_unit: str | None
    valuation_evidence: PortfolioRiskSourceEvidence | None
    industry_membership: IndustryMembership | None
    etf_report: ETFConstituentReport | None
    capacity_observation: CapacityWindowObservation | None

    def __post_init__(self) -> None:
        """Keep raw units, missing values, and per-kind typed inputs explicit."""

        _require_token(self.asset_code, "asset_code")
        if self.security_id is not None:
            _require_token(self.security_id, "security_id")
        if self.kind is not None and not isinstance(self.kind, PortfolioAssetKind):
            raise TypeError("kind must be PortfolioAssetKind or None")
        if self.price is not None and (
            type(self.price) is not Decimal or not self.price.is_finite() or self.price < 0
        ):
            raise ValueError("price must be a finite nonnegative Decimal or None")
        for field_name, value in (
            ("quantity_unit", self.quantity_unit),
            ("price_unit", self.price_unit),
        ):
            if value is not None:
                _require_token(value, field_name)
        if (
            self.valuation_evidence is not None
            and type(self.valuation_evidence) is not PortfolioRiskSourceEvidence
        ):
            raise TypeError("valuation_evidence must be PortfolioRiskSourceEvidence or None")
        if (
            self.industry_membership is not None
            and type(self.industry_membership) is not IndustryMembership
        ):
            raise TypeError("industry_membership must be IndustryMembership or None")
        if self.etf_report is not None and type(self.etf_report) is not ETFConstituentReport:
            raise TypeError("etf_report must be ETFConstituentReport or None")
        if (
            self.capacity_observation is not None
            and type(self.capacity_observation) is not CapacityWindowObservation
        ):
            raise TypeError("capacity_observation must be CapacityWindowObservation or None")
        if self.kind is PortfolioAssetKind.ETF and self.industry_membership is not None:
            raise ValueError("ETF issuer membership cannot replace constituent look-through")
        if self.kind is PortfolioAssetKind.EQUITY and self.etf_report is not None:
            raise ValueError("equity asset cannot carry an ETF constituent report")
        if self.capacity_observation is not None and (
            self.security_id is None
            or self.capacity_observation.asset_code != self.asset_code
            or self.capacity_observation.security_id != self.security_id
        ):
            raise ValueError("capacity observation identity must match its asset input")


@dataclass(frozen=True, slots=True)
class PortfolioRiskAssetsReadResult:
    """Typed source inputs, every verified evidence record, and stable read issues."""

    status: PortfolioRiskAssetReadStatus
    assets: tuple[PortfolioRiskAssetInputs, ...]
    all_source_evidence: tuple[PortfolioRiskSourceEvidence, ...]
    reason_codes: tuple[str, ...]
    policy_snapshot_id: str | None = None
    policy_snapshot_hash: str | None = None
    source_reference_bindings: tuple[PortfolioRiskSourceReference, ...] = ()

    def __post_init__(self) -> None:
        """Require a complete/partial/blocked result consistent with its reasons."""

        if self.status not in ("complete", "partial", "blocked"):
            raise ValueError("status must be complete, partial, or blocked")
        if type(self.assets) is not tuple or any(
            type(asset) is not PortfolioRiskAssetInputs for asset in self.assets
        ):
            raise TypeError("assets must be a tuple of PortfolioRiskAssetInputs")
        if type(self.all_source_evidence) is not tuple or any(
            type(evidence) is not PortfolioRiskSourceEvidence
            for evidence in self.all_source_evidence
        ):
            raise TypeError("all_source_evidence must contain PortfolioRiskSourceEvidence")
        if type(self.source_reference_bindings) is not tuple or any(
            type(reference) is not PortfolioRiskSourceReference
            for reference in self.source_reference_bindings
        ):
            raise TypeError("source_reference_bindings must contain policy source references")
        binding_keys = tuple(
            (item.kind, item.asset_code, item.security_id)
            for item in self.source_reference_bindings
        )
        if len(binding_keys) != len(set(binding_keys)):
            raise ValueError("source_reference_bindings cannot repeat a source identity")
        if type(self.reason_codes) is not tuple or any(
            type(reason) is not str or not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must be a tuple of stable nonempty tokens")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("reason_codes cannot contain duplicates")
        if (self.status == "complete") == bool(self.reason_codes):
            raise ValueError("complete results require no reasons; other results require reasons")
        if (self.policy_snapshot_id is None) != (self.policy_snapshot_hash is None):
            raise ValueError("policy snapshot ID and hash must be provided together")
        if self.policy_snapshot_id is None:
            if self.status != "blocked":
                raise ValueError("an unbound policy result must be blocked")
            if self.source_reference_bindings:
                raise ValueError("an unbound result cannot claim policy source bindings")
        else:
            _require_token(self.policy_snapshot_id, "policy_snapshot_id")
            if (
                type(self.policy_snapshot_hash) is not str
                or len(self.policy_snapshot_hash) != 64
                or any(
                    character not in "0123456789abcdef" for character in self.policy_snapshot_hash
                )
            ):
                raise ValueError("policy_snapshot_hash must be lowercase SHA-256 hex")


class PortfolioRiskAssetsReader(Protocol):
    """Read exact retained asset facts selected by an active policy bundle."""

    def read_assets(
        self,
        request: PortfolioRiskAssetsReadRequest,
    ) -> PortfolioRiskAssetsReadResult:
        """Return source-pinned facts and fail-closed issues at the request cutoff."""


def _require_token(value: str, field_name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a nonempty canonical token")


def _require_date(value: date, field_name: str) -> None:
    if type(value) is not date:
        raise TypeError(f"{field_name} must be a date, not datetime")


def _require_aware(value: datetime, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _validate_asset_identities(
    assets: tuple[PortfolioRiskAssetIdentity, ...],
    field_name: str,
) -> None:
    if type(assets) is not tuple or any(
        type(asset) is not PortfolioRiskAssetIdentity for asset in assets
    ):
        raise TypeError(f"{field_name} must be a tuple of PortfolioRiskAssetIdentity")
    identities = tuple((item.asset_code, item.security_id) for item in assets)
    if len(set(identities)) != len(identities):
        raise ValueError(f"{field_name} cannot contain duplicate asset/security pairs")


__all__ = (
    "CloseSnapshotSessionEvidence",
    "CloseSnapshotSessionEvidenceProvider",
    "PortfolioRiskAssetIdentity",
    "PortfolioRiskAssetInputs",
    "PortfolioRiskAssetReadStatus",
    "PortfolioRiskAssetsReadRequest",
    "PortfolioRiskAssetsReadResult",
    "PortfolioRiskAssetsReader",
)
