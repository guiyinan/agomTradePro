"""Public JSON contracts for an owner-scoped, read-only portfolio risk report."""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

PortfolioRiskOutcome = Literal["allowed", "blocked", "partial", "unknown"]


class PortfolioRiskCheckPayload(TypedDict):
    """One explained constraint; details retain unavailable values as null."""

    dimension: str
    status: PortfolioRiskOutcome
    reason_codes: list[str]
    summary: str
    details: dict[str, object]


class PortfolioRiskSourcePayload(TypedDict):
    """Unmodified source clocks, identity, precision and use restrictions."""

    source_id: str
    source_record_id: str
    raw_payload_sha256: str | None
    observed_at: str | None
    observed_on: str | None
    observation_precision: str
    available_at: str | None
    known_at: str | None
    cutoff: str
    valid_until: str | None
    purpose: str
    restrictions: list[str]
    must_not_use_for_decision: bool
    coverage_fraction: str | None
    coverage_basis: str


class PortfolioRiskOrderDecisionPayload(TypedDict):
    """One order's direction-aware result inside a preview or execution subject."""

    order_id: str
    side: Literal["buy", "sell"]
    outcome: Literal["allowed", "blocked", "unknown"]
    reason_codes: list[str]
    waived_reason_codes: list[str]


class PortfolioRiskOrderAdmissionPayload(TypedDict):
    """Aggregate and per-order admission, separate from the complete risk overview."""

    side: Literal["buy", "sell", "mixed"]
    order_ids: list[str]
    subject_id: str | None
    outcome: Literal["allowed", "blocked", "unknown"]
    reason_codes: list[str]
    waived_reason_codes: list[str]
    decisions: list[PortfolioRiskOrderDecisionPayload]


class PortfolioRiskReportPayload(TypedDict):
    """A read-only simulation constraint report, never an execution permission."""

    account_id: int
    as_of: str
    outcome: PortfolioRiskOutcome
    policy_version: str | None
    resource_snapshot_hash: str
    checks: list[PortfolioRiskCheckPayload]
    sources: list[PortfolioRiskSourcePayload]
    freshness: Literal["qualified_snapshot", "expired", "unknown"]
    reliability: Literal["source_bound", "partial", "unknown"]
    must_not_use_for_decision: bool
    order_admission: NotRequired[PortfolioRiskOrderAdmissionPayload]
    scope: Literal["simulation_only"]
    must_not_execute: Literal[True]


class PortfolioPressureOptionPayload(TypedDict):
    """A human-readable label bound to one immutable approved Scenario revision."""

    value: str
    label: str


class PortfolioPressureOptionsPayload(TypedDict):
    """Read-only choices for an already authorized simulated account."""

    account_id: int
    options: list[PortfolioPressureOptionPayload]
    scope: Literal["simulation_only"]
    read_only: Literal[True]
