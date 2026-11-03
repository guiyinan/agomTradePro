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


class PortfolioRiskDateSnapshotClockProofPayload(TypedDict):
    """Separate, policy-derived decision clock; never source available/expiry data."""

    scope: Literal["simulation_only"]
    source_kind: Literal["industry_membership"]
    clock_evidence_mode: Literal["policy_bounded_date_snapshot"]
    profile_key: str
    profile_version: int
    profile_content_hash: str
    policy_snapshot_id: str
    policy_snapshot_hash: str
    policy_content_sha256: str
    policy_known_at: str
    policy_effective_at: str
    source_reference_hash: str
    account_id: int
    asset_code: str
    security_id: str
    source_id: str
    source_record_id: str
    capture_id: str
    original_body_sha256: str
    as_of: str
    business_date: str
    known_at: str
    proven_available_at: str
    http_status: int
    body_size_bytes: int
    body_complete: Literal[True]
    observed_on: str
    effective_from: str
    effective_until: str
    business_timezone_name: str
    coverage_status: Literal["complete", "partial"]
    coverage_precision_basis: str
    source_max_date_age_days: int
    date_age_deadline: str
    membership_deadline: str
    policy_deadlines: list[str]
    policy_acceptance_deadline: str
    source_available_at: None
    source_valid_until: None


class PortfolioRiskTimestampSnapshotClockProofPayload(TypedDict):
    """Timestamp source capture proof with separate policy-derived deadlines."""

    scope: Literal["simulation_only"]
    source_kind: Literal["valuation", "capacity_window"]
    clock_evidence_mode: Literal["policy_bounded_timestamp_snapshot"]
    profile_key: str
    profile_version: int
    profile_content_hash: str
    policy_snapshot_id: str
    policy_snapshot_hash: str
    policy_content_sha256: str
    policy_known_at: str
    policy_effective_at: str
    source_reference_hash: str
    account_id: int
    asset_code: str
    security_id: str
    source_id: str
    source_record_id: str
    capture_id: str
    original_body_sha256: str
    as_of: str
    business_date: str
    execution_session: str
    known_at: str
    proven_available_at: str
    observed_at: str
    http_status: int
    body_size_bytes: int
    body_complete: Literal[True]
    business_timezone_name: str
    source_max_timestamp_age_seconds: int
    timestamp_age_deadline: str
    market_window_deadline: str
    policy_deadlines: list[str]
    policy_acceptance_deadline: str
    valuation_quantity_unit: str | None
    valuation_price_unit: str | None
    capacity_window_kind: Literal["session_cumulative"] | None
    capacity_window_start: str | None
    capacity_window_end: str | None
    capacity_window_sessions: int | None
    capacity_volume_unit: str | None
    capacity_amount_unit: str | None
    capacity_measure: Literal["volume", "amount"] | None
    capacity_policy_unit: str | None
    source_available_at: None
    source_valid_until: None


class PortfolioRiskCloseSnapshotStateClockProofPayload(TypedDict):
    """ASH-03 quote-time status proof; full-session state remains unknown."""

    scope: Literal["simulation_only"]
    source_kind: Literal["execution_session_state"]
    clock_evidence_mode: Literal["policy_bounded_close_snapshot_state"]
    state_basis: Literal["vendor_reported_at_quote_time"]
    reported_trading_state: Literal["TRADING"]
    full_session_state: Literal["unknown"]
    purpose: Literal["close_snapshot_simulation"]
    required_restrictions: list[Literal["vendor_reported_at_quote_time", "close_snapshot_only"]]
    profile_key: str
    profile_version: int
    profile_content_hash: str
    policy_snapshot_id: str
    policy_snapshot_hash: str
    policy_content_sha256: str
    policy_known_at: str
    policy_effective_at: str
    source_reference_hash: str
    account_id: int
    asset_code: str
    security_id: str
    source_id: str
    source_record_id: str
    capture_id: str
    original_body_sha256: str
    as_of: str
    business_date: str
    execution_session: str
    known_at: str
    proven_available_at: str
    observed_at: str
    http_status: int
    body_size_bytes: int
    body_complete: Literal[True]
    status_mapping_sha256: str
    trusted_vendor_status_codes: list[str]
    reported_status_code: str
    close_policy_content_hash: str
    close_calendar_content_hash: str
    close_calendar_source_hash: str
    close_calendar_session_state: Literal["CLOSED"]
    close_calendar_available_at: str
    close_execution_rule_content_hash: str
    close_market_content_hash: str
    close_market_source_hash: str
    close_market_session_state: Literal["CLOSED"]
    close_market_security_state_basis: Literal[
        "vendor_reported_sina_status_mapping_not_exchange_confirmation"
    ]
    close_bundle_content_hash: str
    close_decision_content_hash: str
    close_policy_available_from: str
    close_policy_available_until: str
    close_usage_ttl_seconds: int
    close_usage_deadline: str
    close_calendar_valid_until: str
    close_market_valid_until: str
    business_timezone_name: str
    business_date_deadline: str
    source_max_timestamp_age_seconds: int
    source_age_deadline: str
    policy_deadlines: list[str]
    policy_acceptance_deadline: str
    source_available_at: None
    source_valid_until: None


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
    clock_evidence_proof: NotRequired[
        PortfolioRiskDateSnapshotClockProofPayload
        | PortfolioRiskTimestampSnapshotClockProofPayload
        | PortfolioRiskCloseSnapshotStateClockProofPayload
    ]


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
