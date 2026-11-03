"""Typed proof values for source capture clocks and policy acceptance windows."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PortfolioRiskClockEvidenceMode = Literal[
    "source_clocks_required",
    "policy_bounded_date_snapshot",
    "policy_bounded_timestamp_snapshot",
    "policy_bounded_close_snapshot_state",
]


@dataclass(frozen=True, slots=True)
class PortfolioRiskCaptureReceipt:
    """Transport receipt from a trusted response-capture boundary."""

    capture_id: str
    source_id: str
    source_record_id: str
    original_body_sha256: str
    response_completed_at: datetime
    http_status: int
    body_size_bytes: int
    body_complete: bool

    def __post_init__(self) -> None:
        """Validate receipt identity, full-body success and the local receipt clock."""

        for name, value in (
            ("capture_id", self.capture_id),
            ("source_id", self.source_id),
            ("source_record_id", self.source_record_id),
        ):
            _require_token(value, name)
        _require_sha256(self.original_body_sha256, "original_body_sha256")
        _require_aware(self.response_completed_at, "response_completed_at")
        if type(self.http_status) is not int or not 100 <= self.http_status <= 599:
            raise ValueError("http_status must be a valid exact HTTP status")
        if type(self.body_size_bytes) is not int or self.body_size_bytes < 0:
            raise ValueError("body_size_bytes must be a nonnegative exact integer")
        if type(self.body_complete) is not bool:
            raise TypeError("body_complete must be an exact boolean")


@dataclass(frozen=True, slots=True)
class PortfolioRiskDateSnapshotProof:
    """Policy-bound proof for a same-day bounded industry DATE observation.

    Every clock in this proof is decision evidence. The source-origin
    ``available_at`` and ``valid_until`` fields are retained separately as null
    and are never populated from the local capture clock or policy deadline.
    """

    scope: Literal["simulation_only"]
    source_kind: Literal["industry_membership"]
    clock_evidence_mode: Literal["policy_bounded_date_snapshot"]
    profile_key: str
    profile_version: int
    profile_content_hash: str
    policy_snapshot_id: str
    policy_snapshot_hash: str
    policy_content_sha256: str
    policy_known_at: datetime
    policy_effective_at: datetime
    source_reference_hash: str
    account_id: int
    asset_code: str
    security_id: str
    source_id: str
    source_record_id: str
    capture_id: str
    original_body_sha256: str
    as_of: datetime
    business_date: date
    known_at: datetime
    proven_available_at: datetime
    http_status: int
    body_size_bytes: int
    body_complete: bool
    observed_on: date
    effective_from: date
    effective_until: date
    business_timezone_name: str
    coverage_status: Literal["complete", "partial"]
    coverage_precision_basis: str
    source_max_date_age_days: int
    date_age_deadline: datetime
    membership_deadline: datetime
    policy_deadlines: tuple[datetime, ...]
    policy_acceptance_deadline: datetime
    source_available_at: None
    source_valid_until: None

    def __post_init__(self) -> None:
        """Reject proofs with inconsistent identity, scope, date or expiry bounds."""

        if (
            self.scope != "simulation_only"
            or self.source_kind != "industry_membership"
            or self.clock_evidence_mode != "policy_bounded_date_snapshot"
        ):
            raise ValueError("date snapshot proof must be simulation-only industry membership")
        if not isinstance(self.coverage_status, str) or self.coverage_status not in (
            "complete",
            "partial",
        ):
            raise ValueError("coverage_status must be complete or partial")
        for name, value in (
            ("profile_key", self.profile_key),
            ("policy_snapshot_id", self.policy_snapshot_id),
            ("asset_code", self.asset_code),
            ("security_id", self.security_id),
            ("source_id", self.source_id),
            ("source_record_id", self.source_record_id),
            ("capture_id", self.capture_id),
            ("business_timezone_name", self.business_timezone_name),
            ("coverage_precision_basis", self.coverage_precision_basis),
        ):
            _require_token(value, name)
        for name, value in (
            ("profile_content_hash", self.profile_content_hash),
            ("policy_snapshot_hash", self.policy_snapshot_hash),
            ("policy_content_sha256", self.policy_content_sha256),
            ("original_body_sha256", self.original_body_sha256),
        ):
            _require_sha256(value, name)
        if (
            type(self.source_reference_hash) is not str
            or re.fullmatch(r"sha256:[0-9a-f]{64}", self.source_reference_hash) is None
        ):
            raise ValueError("source_reference_hash must be a prefixed SHA-256")
        if type(self.profile_version) is not int or self.profile_version < 1:
            raise ValueError("profile_version must be a positive exact integer")
        if type(self.account_id) is not int or self.account_id < 1:
            raise ValueError("account_id must be a positive exact integer")
        if type(self.source_max_date_age_days) is not int or self.source_max_date_age_days < 0:
            raise ValueError("source_max_date_age_days must be a nonnegative exact integer")
        if type(self.business_date) is not date or type(self.observed_on) is not date:
            raise TypeError("business_date and observed_on must be exact dates")
        if self.observed_on != self.business_date:
            raise ValueError("DATE observation must equal the business date")
        if self.effective_from != self.business_date or self.effective_until != self.business_date:
            raise ValueError("industry membership must be bounded to the same business date")
        if self.source_available_at is not None or self.source_valid_until is not None:
            raise ValueError("source-origin availability and expiry clocks must remain unknown")
        if type(self.body_complete) is not bool or not self.body_complete:
            raise ValueError("proof requires a complete response body")
        if type(self.http_status) is not int or not 200 <= self.http_status < 300:
            raise ValueError("proof requires a successful exact HTTP status")
        if type(self.body_size_bytes) is not int or self.body_size_bytes < 1:
            raise ValueError("proof requires a positive exact response-body size")
        for clock_name, clock_value in (
            ("as_of", self.as_of),
            ("known_at", self.known_at),
            ("proven_available_at", self.proven_available_at),
            ("policy_known_at", self.policy_known_at),
            ("policy_effective_at", self.policy_effective_at),
            ("date_age_deadline", self.date_age_deadline),
            ("membership_deadline", self.membership_deadline),
            ("policy_acceptance_deadline", self.policy_acceptance_deadline),
        ):
            _require_aware(clock_value, clock_name)
        if type(self.policy_deadlines) is not tuple or any(
            type(value) is not datetime or not _is_aware(value) for value in self.policy_deadlines
        ):
            raise ValueError("policy_deadlines must contain aware instants")
        if (
            self.known_at < self.proven_available_at
            or self.known_at > self.as_of
            or self.proven_available_at > self.as_of
        ):
            raise ValueError("capture, known-at and decision cutoffs are inconsistent")
        if self.policy_known_at > self.as_of or self.policy_effective_at > self.as_of:
            raise ValueError("policy was not known and effective at the decision cutoff")
        try:
            timezone = ZoneInfo(self.business_timezone_name)
        except (TypeError, ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("business_timezone_name must resolve to an IANA timezone") from exc
        if self.as_of.astimezone(timezone).date() != self.business_date:
            raise ValueError("business_date does not match the named business timezone")
        try:
            expected_membership_deadline = datetime.combine(
                self.business_date + timedelta(days=1), time.min, tzinfo=timezone
            ).astimezone(UTC)
            expected_date_age_deadline = datetime.combine(
                self.business_date + timedelta(days=self.source_max_date_age_days + 1),
                time.min,
                tzinfo=timezone,
            ).astimezone(UTC)
        except OverflowError as exc:
            raise ValueError("date snapshot deadline exceeds the supported date range") from exc
        if self.membership_deadline != expected_membership_deadline:
            raise ValueError("membership_deadline must follow the inclusive bounded date")
        if self.date_age_deadline != expected_date_age_deadline:
            raise ValueError("date_age_deadline must use the configured inclusive date age")
        deadlines = (self.date_age_deadline, self.membership_deadline, *self.policy_deadlines)
        if self.policy_acceptance_deadline != min(deadlines):
            raise ValueError("acceptance deadline must be the exact earliest recorded bound")
        if self.policy_acceptance_deadline <= self.as_of:
            raise ValueError("acceptance deadline must remain after the decision cutoff")


@dataclass(frozen=True, slots=True)
class PortfolioRiskTimestampSnapshotProof:
    """Policy-bound receipt and maximum-age proof for a simulation timestamp source."""

    scope: Literal["simulation_only"]
    source_kind: Literal["valuation", "capacity_window"]
    clock_evidence_mode: Literal["policy_bounded_timestamp_snapshot"]
    profile_key: str
    profile_version: int
    profile_content_hash: str
    policy_snapshot_id: str
    policy_snapshot_hash: str
    policy_content_sha256: str
    policy_known_at: datetime
    policy_effective_at: datetime
    source_reference_hash: str
    account_id: int
    asset_code: str
    security_id: str
    source_id: str
    source_record_id: str
    capture_id: str
    original_body_sha256: str
    as_of: datetime
    business_date: date
    execution_session: date
    known_at: datetime
    proven_available_at: datetime
    observed_at: datetime
    http_status: int
    body_size_bytes: int
    body_complete: bool
    business_timezone_name: str
    source_max_timestamp_age_seconds: int
    timestamp_age_deadline: datetime
    market_window_deadline: datetime
    policy_deadlines: tuple[datetime, ...]
    policy_acceptance_deadline: datetime
    valuation_quantity_unit: str | None
    valuation_price_unit: str | None
    capacity_window_kind: Literal["session_cumulative"] | None
    capacity_window_start: date | None
    capacity_window_end: date | None
    capacity_window_sessions: int | None
    capacity_volume_unit: str | None
    capacity_amount_unit: str | None
    capacity_measure: Literal["volume", "amount"] | None
    capacity_policy_unit: str | None
    source_available_at: None
    source_valid_until: None

    def __post_init__(self) -> None:
        """Reject mismatched source kind, capture, units or derived age bounds."""

        for name, value in (
            ("profile_key", self.profile_key),
            ("policy_snapshot_id", self.policy_snapshot_id),
            ("asset_code", self.asset_code),
            ("security_id", self.security_id),
            ("source_id", self.source_id),
            ("source_record_id", self.source_record_id),
            ("capture_id", self.capture_id),
            ("business_timezone_name", self.business_timezone_name),
        ):
            _require_token(value, name)
        for name, value in (
            ("profile_content_hash", self.profile_content_hash),
            ("policy_snapshot_hash", self.policy_snapshot_hash),
            ("policy_content_sha256", self.policy_content_sha256),
            ("original_body_sha256", self.original_body_sha256),
        ):
            _require_sha256(value, name)
        if (
            type(self.source_reference_hash) is not str
            or re.fullmatch(r"sha256:[0-9a-f]{64}", self.source_reference_hash) is None
        ):
            raise ValueError("source_reference_hash must be a prefixed SHA-256")
        if self.scope != "simulation_only":
            raise ValueError("timestamp snapshot proof is simulation-only")
        if self.source_kind not in ("valuation", "capacity_window"):
            raise ValueError("timestamp snapshot proof source kind is unsupported")
        if self.clock_evidence_mode != "policy_bounded_timestamp_snapshot":
            raise ValueError("timestamp snapshot proof mode is unsupported")
        if type(self.profile_version) is not int or self.profile_version < 1:
            raise ValueError("profile_version must be a positive exact integer")
        if type(self.account_id) is not int or self.account_id < 1:
            raise ValueError("account_id must be a positive exact integer")
        for clock_name, clock_value in (
            ("as_of", self.as_of),
            ("policy_known_at", self.policy_known_at),
            ("policy_effective_at", self.policy_effective_at),
            ("known_at", self.known_at),
            ("proven_available_at", self.proven_available_at),
            ("observed_at", self.observed_at),
            ("timestamp_age_deadline", self.timestamp_age_deadline),
            ("market_window_deadline", self.market_window_deadline),
            ("policy_acceptance_deadline", self.policy_acceptance_deadline),
        ):
            _require_aware(clock_value, clock_name)
        if type(self.policy_deadlines) is not tuple or any(
            type(value) is not datetime or not _is_aware(value) for value in self.policy_deadlines
        ):
            raise ValueError("policy_deadlines must contain aware instants")
        if type(self.business_date) is not date or type(self.execution_session) is not date:
            raise TypeError("business_date and execution_session must be exact dates")
        if (
            self.known_at < self.proven_available_at
            or self.known_at > self.as_of
            or self.proven_available_at > self.as_of
        ):
            raise ValueError("capture, known-at and decision cutoffs are inconsistent")
        if self.observed_at > self.as_of:
            raise ValueError("source observation cannot be after the decision cutoff")
        if self.observed_at > self.proven_available_at:
            raise ValueError("source observation cannot be after its complete capture")
        if self.policy_known_at > self.as_of or self.policy_effective_at > self.as_of:
            raise ValueError("policy was not known and effective at the decision cutoff")
        try:
            timezone = ZoneInfo(self.business_timezone_name)
        except (TypeError, ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("business_timezone_name must resolve to an IANA timezone") from exc
        if self.as_of.astimezone(timezone).date() != self.business_date:
            raise ValueError("business_date does not match the named business timezone")
        if self.observed_at.astimezone(timezone).date() != self.business_date:
            raise ValueError("source timestamp must belong to the current business date")
        expected_window_deadline = datetime.combine(
            self.business_date + timedelta(days=1), time.min, tzinfo=timezone
        ).astimezone(UTC)
        if self.market_window_deadline != expected_window_deadline:
            raise ValueError("market_window_deadline must follow the inclusive business date")
        if type(self.http_status) is not int or not 200 <= self.http_status < 300:
            raise ValueError("timestamp snapshot proof requires a successful HTTP response")
        if (
            type(self.body_size_bytes) is not int
            or self.body_size_bytes < 1
            or type(self.body_complete) is not bool
            or not self.body_complete
        ):
            raise ValueError("timestamp snapshot proof requires a complete nonempty body")
        if (
            type(self.source_max_timestamp_age_seconds) is not int
            or self.source_max_timestamp_age_seconds < 0
        ):
            raise ValueError("source_max_timestamp_age_seconds must be nonnegative")
        if self.source_available_at is not None or self.source_valid_until is not None:
            raise ValueError("timestamp proof cannot rewrite source-origin clocks")
        if self.source_kind == "valuation":
            if self.valuation_quantity_unit is None or self.valuation_price_unit is None:
                raise ValueError("valuation proof requires explicit quantity and price units")
            _require_token(self.valuation_quantity_unit, "valuation_quantity_unit")
            _require_token(self.valuation_price_unit, "valuation_price_unit")
            if any(
                value is not None
                for value in (
                    self.capacity_window_kind,
                    self.capacity_window_start,
                    self.capacity_window_end,
                    self.capacity_window_sessions,
                    self.capacity_volume_unit,
                    self.capacity_amount_unit,
                    self.capacity_measure,
                    self.capacity_policy_unit,
                )
            ):
                raise ValueError("valuation proof cannot contain capacity-window facts")
        else:
            if (
                self.valuation_quantity_unit is not None
                or self.valuation_price_unit is not None
                or self.execution_session != self.business_date
                or self.capacity_window_kind != "session_cumulative"
                or self.capacity_window_start != self.execution_session
                or self.capacity_window_end != self.execution_session
                or type(self.capacity_window_sessions) is not int
                or self.capacity_window_sessions != 1
            ):
                raise ValueError("capacity proof must identify one exact execution session")
            if self.capacity_measure not in ("volume", "amount"):
                raise ValueError("capacity_measure must be explicit")
            capacity_policy_unit = self.capacity_policy_unit
            if capacity_policy_unit is None:
                raise ValueError("capacity_policy_unit must be explicit")
            _require_token(capacity_policy_unit, "capacity_policy_unit")
            for unit_name, unit_value in (
                ("capacity_volume_unit", self.capacity_volume_unit),
                ("capacity_amount_unit", self.capacity_amount_unit),
            ):
                if unit_value is not None:
                    _require_token(unit_value, unit_name)
            selected_unit = (
                self.capacity_volume_unit
                if self.capacity_measure == "volume"
                else self.capacity_amount_unit
            )
            if selected_unit != capacity_policy_unit:
                raise ValueError("capacity source unit must match its active policy unit")
        age_deadline = self.observed_at + timedelta(seconds=self.source_max_timestamp_age_seconds)
        deadlines = (
            self.timestamp_age_deadline,
            self.market_window_deadline,
            *self.policy_deadlines,
        )
        if self.timestamp_age_deadline != age_deadline:
            raise ValueError("timestamp_age_deadline must use the configured source age")
        if self.policy_acceptance_deadline != min(deadlines):
            raise ValueError("policy_acceptance_deadline must be the exact earliest bound")
        if self.policy_acceptance_deadline <= self.as_of:
            raise ValueError("timestamp snapshot proof is already expired")


@dataclass(frozen=True, slots=True)
class PortfolioRiskCloseSnapshotStateProof:
    """Bind a quote-time vendor status to one explicitly close-only simulation.

    This proves only that the qualified Sina quote reported ``TRADING`` at its
    source observation instant. It never claims exchange-confirmed or full-day
    suspension state. Source-origin availability and expiry remain unknown.
    """

    scope: Literal["simulation_only"]
    source_kind: Literal["execution_session_state"]
    clock_evidence_mode: Literal["policy_bounded_close_snapshot_state"]
    state_basis: Literal["vendor_reported_at_quote_time"]
    reported_trading_state: Literal["TRADING"]
    full_session_state: Literal["unknown"]
    purpose: Literal["close_snapshot_simulation"]
    required_restrictions: tuple[
        Literal["vendor_reported_at_quote_time", "close_snapshot_only"], ...
    ]
    profile_key: str
    profile_version: int
    profile_content_hash: str
    policy_snapshot_id: str
    policy_snapshot_hash: str
    policy_content_sha256: str
    policy_known_at: datetime
    policy_effective_at: datetime
    source_reference_hash: str
    account_id: int
    asset_code: str
    security_id: str
    source_id: str
    source_record_id: str
    capture_id: str
    original_body_sha256: str
    as_of: datetime
    business_date: date
    execution_session: date
    known_at: datetime
    proven_available_at: datetime
    observed_at: datetime
    http_status: int
    body_size_bytes: int
    body_complete: bool
    status_mapping_sha256: str
    trusted_vendor_status_codes: tuple[str, ...]
    reported_status_code: str
    close_policy_content_hash: str
    close_calendar_content_hash: str
    close_calendar_source_hash: str
    close_calendar_session_state: Literal["CLOSED"]
    close_calendar_available_at: datetime
    close_execution_rule_content_hash: str
    close_market_content_hash: str
    close_market_source_hash: str
    close_market_session_state: Literal["CLOSED"]
    close_market_security_state_basis: Literal[
        "vendor_reported_sina_status_mapping_not_exchange_confirmation"
    ]
    close_bundle_content_hash: str
    close_decision_content_hash: str
    close_policy_available_from: datetime
    close_policy_available_until: datetime
    close_usage_ttl_seconds: int
    close_usage_deadline: datetime
    close_calendar_valid_until: datetime
    close_market_valid_until: datetime
    business_timezone_name: str
    business_date_deadline: datetime
    source_max_timestamp_age_seconds: int
    source_age_deadline: datetime
    policy_deadlines: tuple[datetime, ...]
    policy_acceptance_deadline: datetime
    source_available_at: None
    source_valid_until: None

    def __post_init__(self) -> None:
        """Reject mismatched source, close-policy, status, or derived deadlines."""

        for name, value in (
            ("profile_key", self.profile_key),
            ("policy_snapshot_id", self.policy_snapshot_id),
            ("asset_code", self.asset_code),
            ("security_id", self.security_id),
            ("source_id", self.source_id),
            ("source_record_id", self.source_record_id),
            ("capture_id", self.capture_id),
            ("reported_status_code", self.reported_status_code),
            ("business_timezone_name", self.business_timezone_name),
        ):
            _require_token(value, name)
        for name, value in (
            ("profile_content_hash", self.profile_content_hash),
            ("policy_snapshot_hash", self.policy_snapshot_hash),
            ("policy_content_sha256", self.policy_content_sha256),
            ("original_body_sha256", self.original_body_sha256),
            ("status_mapping_sha256", self.status_mapping_sha256),
            ("close_policy_content_hash", self.close_policy_content_hash),
            ("close_calendar_content_hash", self.close_calendar_content_hash),
            ("close_calendar_source_hash", self.close_calendar_source_hash),
            ("close_execution_rule_content_hash", self.close_execution_rule_content_hash),
            ("close_market_content_hash", self.close_market_content_hash),
            ("close_market_source_hash", self.close_market_source_hash),
            ("close_bundle_content_hash", self.close_bundle_content_hash),
            ("close_decision_content_hash", self.close_decision_content_hash),
        ):
            _require_sha256(value, name)
        if (
            type(self.source_reference_hash) is not str
            or re.fullmatch(r"sha256:[0-9a-f]{64}", self.source_reference_hash) is None
        ):
            raise ValueError("source_reference_hash must be prefixed SHA-256")
        if self.scope != "simulation_only" or self.source_kind != "execution_session_state":
            raise ValueError("close snapshot state proof must be simulation-only session evidence")
        if self.clock_evidence_mode != "policy_bounded_close_snapshot_state":
            raise ValueError("close snapshot state proof mode is unsupported")
        if (
            self.state_basis != "vendor_reported_at_quote_time"
            or self.reported_trading_state != "TRADING"
            or self.full_session_state != "unknown"
            or self.purpose != "close_snapshot_simulation"
        ):
            raise ValueError("close snapshot state must remain quote-time and close-only")
        required = ("vendor_reported_at_quote_time", "close_snapshot_only")
        if self.required_restrictions != required:
            raise ValueError("close snapshot state restrictions are incomplete or unordered")
        if (
            type(self.trusted_vendor_status_codes) is not tuple
            or not self.trusted_vendor_status_codes
        ):
            raise ValueError("trusted vendor status codes must be explicit")
        for code in self.trusted_vendor_status_codes:
            _require_token(code, "trusted_vendor_status_code")
        if self.reported_status_code not in self.trusted_vendor_status_codes:
            raise ValueError("reported vendor status is not trusted by the close policy")
        if (
            self.close_calendar_session_state != "CLOSED"
            or self.close_market_session_state != "CLOSED"
            or self.close_market_security_state_basis
            != "vendor_reported_sina_status_mapping_not_exchange_confirmation"
        ):
            raise ValueError("close bundle state basis must remain explicitly scoped")
        if type(self.profile_version) is not int or self.profile_version < 1:
            raise ValueError("profile_version must be positive")
        if type(self.account_id) is not int or self.account_id < 1:
            raise ValueError("account_id must be positive")
        if type(self.business_date) is not date or type(self.execution_session) is not date:
            raise TypeError("business_date and execution_session must be dates")
        if self.business_date != self.execution_session:
            raise ValueError("close snapshot state must match the execution business date")
        for clock_name, clock_value in (
            ("as_of", self.as_of),
            ("policy_known_at", self.policy_known_at),
            ("policy_effective_at", self.policy_effective_at),
            ("known_at", self.known_at),
            ("proven_available_at", self.proven_available_at),
            ("observed_at", self.observed_at),
            ("close_calendar_available_at", self.close_calendar_available_at),
            ("close_policy_available_from", self.close_policy_available_from),
            ("close_policy_available_until", self.close_policy_available_until),
            ("close_usage_deadline", self.close_usage_deadline),
            ("close_calendar_valid_until", self.close_calendar_valid_until),
            ("close_market_valid_until", self.close_market_valid_until),
            ("business_date_deadline", self.business_date_deadline),
            ("source_age_deadline", self.source_age_deadline),
            ("policy_acceptance_deadline", self.policy_acceptance_deadline),
        ):
            _require_aware(clock_value, clock_name)
        if type(self.policy_deadlines) is not tuple or any(
            type(value) is not datetime or not _is_aware(value) for value in self.policy_deadlines
        ):
            raise ValueError("policy_deadlines must contain aware instants")
        if (
            self.known_at < self.proven_available_at
            or self.known_at > self.as_of
            or self.proven_available_at > self.as_of
        ):
            raise ValueError("capture and known-at clocks are inconsistent")
        if self.policy_known_at > self.as_of or self.policy_effective_at > self.as_of:
            raise ValueError("policy was not known and effective at the decision cutoff")
        if self.observed_at > self.proven_available_at or self.observed_at > self.as_of:
            raise ValueError("vendor observation must precede complete capture and cutoff")
        if (
            self.close_calendar_available_at > self.proven_available_at
            or self.close_policy_available_from > self.as_of
            or self.close_policy_available_from >= self.close_policy_available_until
        ):
            raise ValueError("close calendar or policy availability clocks are inconsistent")
        try:
            timezone = ZoneInfo(self.business_timezone_name)
        except (TypeError, ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("business_timezone_name must resolve to an IANA timezone") from exc
        if (
            self.as_of.astimezone(timezone).date() != self.business_date
            or self.observed_at.astimezone(timezone).date() != self.business_date
        ):
            raise ValueError("close snapshot clocks must belong to the exact business date")
        expected_business_deadline = datetime.combine(
            self.business_date + timedelta(days=1), time.min, tzinfo=timezone
        ).astimezone(UTC)
        if self.business_date_deadline != expected_business_deadline:
            raise ValueError("business_date_deadline must follow the inclusive session date")
        if type(self.http_status) is not int or not 200 <= self.http_status < 300:
            raise ValueError("close snapshot proof requires a successful response")
        if type(self.body_size_bytes) is not int or self.body_size_bytes < 1:
            raise ValueError("close snapshot proof requires a nonempty captured body")
        if type(self.body_complete) is not bool or not self.body_complete:
            raise ValueError("close snapshot proof requires a complete captured body")
        if (
            type(self.close_usage_ttl_seconds) is not int
            or not 1 <= self.close_usage_ttl_seconds < 86_400
        ):
            raise ValueError("close snapshot usage TTL must be shorter than one day")
        if (
            type(self.source_max_timestamp_age_seconds) is not int
            or self.source_max_timestamp_age_seconds < 0
        ):
            raise ValueError("source timestamp age must be a nonnegative exact integer")
        if self.source_available_at is not None or self.source_valid_until is not None:
            raise ValueError("proof cannot rewrite source-origin availability or expiry")
        if self.close_usage_deadline != self.proven_available_at + timedelta(
            seconds=self.close_usage_ttl_seconds
        ):
            raise ValueError("close usage deadline must use the approved receipt TTL")
        if self.source_age_deadline != self.observed_at + timedelta(
            seconds=self.source_max_timestamp_age_seconds
        ):
            raise ValueError("source age deadline must use the configured source age")
        deadlines = (
            self.close_policy_available_until,
            self.close_usage_deadline,
            self.close_calendar_valid_until,
            self.close_market_valid_until,
            self.business_date_deadline,
            self.source_age_deadline,
            *self.policy_deadlines,
        )
        if self.policy_acceptance_deadline != min(deadlines):
            raise ValueError("policy acceptance deadline must be the exact earliest bound")
        if self.policy_acceptance_deadline <= self.as_of:
            raise ValueError("close snapshot proof is already expired")


def _require_token(value: str, field_name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a nonempty canonical token")


def _require_sha256(value: str, field_name: str) -> None:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{field_name} must be lowercase SHA-256 hex")


def _require_aware(value: datetime, field_name: str) -> None:
    if type(value) is not datetime or not _is_aware(value):
        raise ValueError(f"{field_name} must be an aware datetime")


def _is_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


__all__ = (
    "PortfolioRiskCaptureReceipt",
    "PortfolioRiskClockEvidenceMode",
    "PortfolioRiskDateSnapshotProof",
    "PortfolioRiskTimestampSnapshotProof",
    "PortfolioRiskCloseSnapshotStateProof",
)
