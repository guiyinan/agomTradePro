"""Strict JSON validation for captured policy-bound source-clock proofs."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from typing import cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apps.risk_center.application.portfolio_risk_disclosed_etf_report_codec import (
    is_disclosed_etf_report_clock_payload,
)

_SOURCE_CLOCK_PROOF_KEYS = frozenset(
    {
        "scope",
        "source_kind",
        "clock_evidence_mode",
        "profile_key",
        "profile_version",
        "profile_content_hash",
        "policy_snapshot_id",
        "policy_snapshot_hash",
        "policy_content_sha256",
        "policy_known_at",
        "policy_effective_at",
        "source_reference_hash",
        "account_id",
        "asset_code",
        "security_id",
        "source_id",
        "source_record_id",
        "capture_id",
        "original_body_sha256",
        "as_of",
        "business_date",
        "known_at",
        "proven_available_at",
        "http_status",
        "body_size_bytes",
        "body_complete",
        "observed_on",
        "effective_from",
        "effective_until",
        "business_timezone_name",
        "coverage_status",
        "coverage_precision_basis",
        "source_max_date_age_days",
        "date_age_deadline",
        "membership_deadline",
        "policy_deadlines",
        "policy_acceptance_deadline",
        "source_available_at",
        "source_valid_until",
    }
)
_TIMESTAMP_SOURCE_CLOCK_PROOF_KEYS = frozenset(
    {
        "scope",
        "source_kind",
        "clock_evidence_mode",
        "profile_key",
        "profile_version",
        "profile_content_hash",
        "policy_snapshot_id",
        "policy_snapshot_hash",
        "policy_content_sha256",
        "policy_known_at",
        "policy_effective_at",
        "source_reference_hash",
        "account_id",
        "asset_code",
        "security_id",
        "source_id",
        "source_record_id",
        "capture_id",
        "original_body_sha256",
        "as_of",
        "business_date",
        "execution_session",
        "known_at",
        "proven_available_at",
        "observed_at",
        "http_status",
        "body_size_bytes",
        "body_complete",
        "business_timezone_name",
        "source_max_timestamp_age_seconds",
        "timestamp_age_deadline",
        "market_window_deadline",
        "policy_deadlines",
        "policy_acceptance_deadline",
        "valuation_quantity_unit",
        "valuation_price_unit",
        "capacity_window_kind",
        "capacity_window_start",
        "capacity_window_end",
        "capacity_window_sessions",
        "capacity_volume_unit",
        "capacity_amount_unit",
        "capacity_measure",
        "capacity_policy_unit",
        "source_available_at",
        "source_valid_until",
    }
)
_CLOSE_STATE_SOURCE_CLOCK_PROOF_KEYS = frozenset(
    {
        "scope",
        "source_kind",
        "clock_evidence_mode",
        "state_basis",
        "reported_trading_state",
        "full_session_state",
        "purpose",
        "required_restrictions",
        "profile_key",
        "profile_version",
        "profile_content_hash",
        "policy_snapshot_id",
        "policy_snapshot_hash",
        "policy_content_sha256",
        "policy_known_at",
        "policy_effective_at",
        "source_reference_hash",
        "account_id",
        "asset_code",
        "security_id",
        "source_id",
        "source_record_id",
        "capture_id",
        "original_body_sha256",
        "as_of",
        "business_date",
        "execution_session",
        "known_at",
        "proven_available_at",
        "observed_at",
        "http_status",
        "body_size_bytes",
        "body_complete",
        "status_mapping_sha256",
        "trusted_vendor_status_codes",
        "reported_status_code",
        "close_policy_content_hash",
        "close_calendar_content_hash",
        "close_calendar_source_hash",
        "close_calendar_session_state",
        "close_calendar_available_at",
        "close_execution_rule_content_hash",
        "close_market_content_hash",
        "close_market_source_hash",
        "close_market_session_state",
        "close_market_security_state_basis",
        "close_bundle_content_hash",
        "close_decision_content_hash",
        "close_policy_available_from",
        "close_policy_available_until",
        "close_usage_ttl_seconds",
        "close_usage_deadline",
        "close_calendar_valid_until",
        "close_market_valid_until",
        "business_timezone_name",
        "business_date_deadline",
        "source_max_timestamp_age_seconds",
        "source_age_deadline",
        "policy_deadlines",
        "policy_acceptance_deadline",
        "source_available_at",
        "source_valid_until",
    }
)


def is_source_clock_evidence_proof(value: object, source: Mapping[str, object]) -> bool:
    """Validate the derived proof independently and bind it to source clocks."""

    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        return False
    proof = cast(Mapping[str, object], value)
    if proof.get("clock_evidence_mode") == "policy_bounded_disclosed_report":
        return is_disclosed_etf_report_clock_payload(proof, source)
    if proof.get("clock_evidence_mode") == "policy_bounded_timestamp_snapshot":
        return _is_timestamp_clock_evidence_proof(proof, source)
    if proof.get("clock_evidence_mode") == "policy_bounded_close_snapshot_state":
        return _is_close_state_clock_evidence_proof(proof, source)
    return _is_date_clock_evidence_proof(proof, source)


def _is_date_clock_evidence_proof(
    proof: Mapping[str, object], source: Mapping[str, object]
) -> bool:
    """Validate the same-day industry DATE proof and its distinct deadline bounds."""

    if set(proof) != _SOURCE_CLOCK_PROOF_KEYS:
        return False
    text_fields = (
        "profile_key",
        "policy_snapshot_id",
        "asset_code",
        "security_id",
        "source_id",
        "source_record_id",
        "capture_id",
        "business_timezone_name",
        "coverage_precision_basis",
        "business_date",
        "observed_on",
        "effective_from",
        "effective_until",
        "policy_known_at",
        "policy_effective_at",
        "as_of",
        "known_at",
        "proven_available_at",
        "date_age_deadline",
        "membership_deadline",
        "policy_acceptance_deadline",
    )
    if any(type(proof.get(name)) is not str or not proof[name] for name in text_fields):
        return False
    profile_version = proof.get("profile_version")
    account_id = proof.get("account_id")
    http_status = proof.get("http_status")
    body_size_bytes = proof.get("body_size_bytes")
    source_max_date_age_days = proof.get("source_max_date_age_days")
    if (
        proof.get("scope") != "simulation_only"
        or proof.get("source_kind") != "industry_membership"
        or proof.get("clock_evidence_mode") != "policy_bounded_date_snapshot"
        or proof.get("body_complete") is not True
        or proof.get("source_available_at") is not None
        or proof.get("source_valid_until") is not None
        or proof.get("coverage_status") not in {"complete", "partial"}
        or type(profile_version) is not int
        or profile_version < 1
        or type(account_id) is not int
        or account_id < 1
        or type(http_status) is not int
        or not 200 <= http_status < 300
        or type(body_size_bytes) is not int
        or body_size_bytes < 1
        or type(source_max_date_age_days) is not int
        or source_max_date_age_days < 0
    ):
        return False
    for name in (
        "profile_content_hash",
        "policy_snapshot_hash",
        "policy_content_sha256",
        "original_body_sha256",
    ):
        if not _is_sha256(proof.get(name)):
            return False
    if not _is_prefixed_sha256(proof.get("source_reference_hash")):
        return False
    date_values = {
        name: _parse_date(proof.get(name))
        for name in ("business_date", "observed_on", "effective_from", "effective_until")
    }
    instant_names = (
        "policy_known_at",
        "policy_effective_at",
        "as_of",
        "known_at",
        "proven_available_at",
        "date_age_deadline",
        "membership_deadline",
        "policy_acceptance_deadline",
    )
    instants = {name: _parse_aware_instant(proof.get(name)) for name in instant_names}
    raw_policy_deadlines = proof.get("policy_deadlines")
    if type(raw_policy_deadlines) is not list:
        return False
    policy_deadlines = [_parse_aware_instant(item) for item in raw_policy_deadlines]
    if any(item is None for item in (*date_values.values(), *instants.values(), *policy_deadlines)):
        return False
    business_date = cast(date, date_values["business_date"])
    as_of = cast(datetime, instants["as_of"])
    try:
        timezone = ZoneInfo(cast(str, proof["business_timezone_name"]))
        inclusive_end = cast(date, date_values["effective_until"])
        age_end = business_date + timedelta(days=cast(int, proof["source_max_date_age_days"]))
        expected_age_deadline = datetime.combine(
            age_end + timedelta(days=1), time.min, tzinfo=timezone
        ).astimezone(UTC)
        expected_membership_deadline = datetime.combine(
            inclusive_end + timedelta(days=1), time.min, tzinfo=timezone
        ).astimezone(UTC)
        expected_deadline = min(
            (
                expected_age_deadline,
                expected_membership_deadline,
                *(cast(datetime, item).astimezone(UTC) for item in policy_deadlines),
            )
        )
    except (ArithmeticError, OverflowError, TypeError, ValueError, ZoneInfoNotFoundError):
        return False
    cutoff = cast(datetime, instants["as_of"])
    known_at = cast(datetime, instants["known_at"])
    captured_at = cast(datetime, instants["proven_available_at"])
    acceptance_deadline = cast(datetime, instants["policy_acceptance_deadline"])
    return (
        date_values["observed_on"] == business_date
        and date_values["effective_from"] == business_date
        and date_values["effective_until"] == business_date
        and as_of.astimezone(timezone).date() == business_date
        and cast(datetime, instants["policy_known_at"]) <= cutoff
        and cast(datetime, instants["policy_effective_at"]) <= cutoff
        and captured_at <= known_at <= cutoff
        and expected_age_deadline == cast(datetime, instants["date_age_deadline"]).astimezone(UTC)
        and expected_membership_deadline
        == cast(datetime, instants["membership_deadline"]).astimezone(UTC)
        and expected_deadline == acceptance_deadline.astimezone(UTC)
        and acceptance_deadline > cutoff
        and proof.get("source_id") == source.get("source_id")
        and proof.get("source_record_id") == source.get("source_record_id")
        and proof.get("original_body_sha256") == source.get("raw_payload_sha256")
        and proof.get("observed_on") == source.get("observed_on")
        and proof.get("known_at") == source.get("known_at")
        and proof.get("business_date") == source.get("cutoff")
        and source.get("observation_precision") == "date"
        and proof.get("coverage_precision_basis") == source.get("coverage_basis")
        and source.get("available_at") is None
        and source.get("valid_until") is None
        and source.get("must_not_use_for_decision") is False
    )


def _is_timestamp_clock_evidence_proof(
    proof: Mapping[str, object], source: Mapping[str, object]
) -> bool:
    """Validate a captured valuation or exact current-session capacity proof."""

    if set(proof) != _TIMESTAMP_SOURCE_CLOCK_PROOF_KEYS:
        return False
    required_text = (
        "profile_key",
        "policy_snapshot_id",
        "asset_code",
        "security_id",
        "source_id",
        "source_record_id",
        "capture_id",
        "business_timezone_name",
        "business_date",
        "execution_session",
        "policy_known_at",
        "policy_effective_at",
        "as_of",
        "known_at",
        "proven_available_at",
        "observed_at",
        "timestamp_age_deadline",
        "market_window_deadline",
        "policy_acceptance_deadline",
    )

    if any(not _is_token(proof.get(name)) for name in required_text):
        return False
    profile_version = proof.get("profile_version")
    account_id = proof.get("account_id")
    http_status = proof.get("http_status")
    body_size_bytes = proof.get("body_size_bytes")
    source_max_timestamp_age_seconds = proof.get("source_max_timestamp_age_seconds")
    if (
        proof.get("scope") != "simulation_only"
        or proof.get("source_kind") not in {"valuation", "capacity_window"}
        or proof.get("clock_evidence_mode") != "policy_bounded_timestamp_snapshot"
        or proof.get("body_complete") is not True
        or proof.get("source_available_at") is not None
        or proof.get("source_valid_until") is not None
        or type(profile_version) is not int
        or profile_version < 1
        or type(account_id) is not int
        or account_id < 1
        or type(http_status) is not int
        or not 200 <= http_status < 300
        or type(body_size_bytes) is not int
        or body_size_bytes < 1
        or type(source_max_timestamp_age_seconds) is not int
        or source_max_timestamp_age_seconds < 0
    ):
        return False
    for name in (
        "profile_content_hash",
        "policy_snapshot_hash",
        "policy_content_sha256",
        "original_body_sha256",
    ):
        if not _is_sha256(proof.get(name)):
            return False
    if not _is_prefixed_sha256(proof.get("source_reference_hash")):
        return False
    business_date = _parse_date(proof.get("business_date"))
    execution_session = _parse_date(proof.get("execution_session"))
    instant_names = (
        "policy_known_at",
        "policy_effective_at",
        "as_of",
        "known_at",
        "proven_available_at",
        "observed_at",
        "timestamp_age_deadline",
        "market_window_deadline",
        "policy_acceptance_deadline",
    )
    instants = {name: _parse_aware_instant(proof.get(name)) for name in instant_names}
    raw_policy_deadlines = proof.get("policy_deadlines")
    if type(raw_policy_deadlines) is not list:
        return False
    policy_deadlines = [_parse_aware_instant(item) for item in raw_policy_deadlines]
    if (
        business_date is None
        or execution_session is None
        or any(item is None for item in (*instants.values(), *policy_deadlines))
    ):
        return False
    as_of = cast(datetime, instants["as_of"])
    observed_at = cast(datetime, instants["observed_at"])
    known_at = cast(datetime, instants["known_at"])
    captured_at = cast(datetime, instants["proven_available_at"])
    try:
        timezone = ZoneInfo(cast(str, proof["business_timezone_name"]))
        age_deadline = observed_at + timedelta(
            seconds=cast(int, proof["source_max_timestamp_age_seconds"])
        )
        market_deadline = datetime.combine(
            business_date + timedelta(days=1), time.min, tzinfo=timezone
        ).astimezone(UTC)
        expected_deadline = min(
            (
                age_deadline,
                market_deadline,
                *(cast(datetime, item).astimezone(UTC) for item in policy_deadlines),
            )
        )
    except (ArithmeticError, OverflowError, TypeError, ValueError, ZoneInfoNotFoundError):
        return False
    if proof.get("source_kind") == "valuation":
        if not _is_token(proof.get("valuation_quantity_unit")) or not _is_token(
            proof.get("valuation_price_unit")
        ):
            return False
        if any(
            proof.get(name) is not None
            for name in (
                "capacity_window_kind",
                "capacity_window_start",
                "capacity_window_end",
                "capacity_window_sessions",
                "capacity_volume_unit",
                "capacity_amount_unit",
                "capacity_measure",
                "capacity_policy_unit",
            )
        ):
            return False
    else:
        capacity_start = _parse_date(proof.get("capacity_window_start"))
        capacity_end = _parse_date(proof.get("capacity_window_end"))
        measure = proof.get("capacity_measure")
        selected_unit = proof.get(
            "capacity_volume_unit" if measure == "volume" else "capacity_amount_unit"
        )
        if (
            proof.get("valuation_quantity_unit") is not None
            or proof.get("valuation_price_unit") is not None
            or proof.get("capacity_window_kind") != "session_cumulative"
            or capacity_start != execution_session
            or capacity_end != execution_session
            or type(proof.get("capacity_window_sessions")) is not int
            or proof.get("capacity_window_sessions") != 1
            or measure not in {"volume", "amount"}
            or not _is_token(proof.get("capacity_policy_unit"))
            or selected_unit != proof.get("capacity_policy_unit")
        ):
            return False
    return (
        execution_session == business_date
        and as_of.astimezone(timezone).date() == business_date
        and observed_at.astimezone(timezone).date() == business_date
        and cast(datetime, instants["policy_known_at"]) <= as_of
        and cast(datetime, instants["policy_effective_at"]) <= as_of
        and observed_at <= captured_at <= known_at <= as_of
        and age_deadline == cast(datetime, instants["timestamp_age_deadline"])
        and market_deadline == cast(datetime, instants["market_window_deadline"])
        and expected_deadline
        == cast(datetime, instants["policy_acceptance_deadline"]).astimezone(UTC)
        and cast(datetime, instants["policy_acceptance_deadline"]) > as_of
        and proof.get("as_of") == source.get("cutoff")
        and proof.get("source_id") == source.get("source_id")
        and proof.get("source_record_id") == source.get("source_record_id")
        and proof.get("original_body_sha256") == source.get("raw_payload_sha256")
        and proof.get("observed_at") == source.get("observed_at")
        and proof.get("known_at") == source.get("known_at")
        and source.get("observation_precision") == "timestamp"
        and source.get("observed_on") is None
        and source.get("available_at") is None
        and source.get("valid_until") is None
        and source.get("must_not_use_for_decision") is False
    )


def _is_close_state_clock_evidence_proof(
    proof: Mapping[str, object], source: Mapping[str, object]
) -> bool:
    """Validate close-only proof hashes and preserve the limited status meaning."""

    if set(proof) != _CLOSE_STATE_SOURCE_CLOCK_PROOF_KEYS:
        return False
    token_fields = (
        "profile_key",
        "policy_snapshot_id",
        "asset_code",
        "security_id",
        "source_id",
        "source_record_id",
        "capture_id",
        "business_timezone_name",
        "reported_status_code",
    )
    if any(not _is_token(proof.get(name)) for name in token_fields):
        return False
    profile_version = proof.get("profile_version")
    account_id = proof.get("account_id")
    http_status = proof.get("http_status")
    body_size_bytes = proof.get("body_size_bytes")
    close_usage_ttl_seconds = proof.get("close_usage_ttl_seconds")
    source_max_timestamp_age_seconds = proof.get("source_max_timestamp_age_seconds")
    if (
        proof.get("scope") != "simulation_only"
        or proof.get("source_kind") != "execution_session_state"
        or proof.get("clock_evidence_mode") != "policy_bounded_close_snapshot_state"
        or proof.get("state_basis") != "vendor_reported_at_quote_time"
        or proof.get("reported_trading_state") != "TRADING"
        or proof.get("full_session_state") != "unknown"
        or proof.get("purpose") != "close_snapshot_simulation"
        or proof.get("close_calendar_session_state") != "CLOSED"
        or proof.get("close_market_session_state") != "CLOSED"
        or proof.get("close_market_security_state_basis")
        != "vendor_reported_sina_status_mapping_not_exchange_confirmation"
        or proof.get("required_restrictions")
        != ["vendor_reported_at_quote_time", "close_snapshot_only"]
        or proof.get("body_complete") is not True
        or proof.get("source_available_at") is not None
        or proof.get("source_valid_until") is not None
        or type(profile_version) is not int
        or profile_version < 1
        or type(account_id) is not int
        or account_id < 1
        or type(http_status) is not int
        or not 200 <= http_status < 300
        or type(body_size_bytes) is not int
        or body_size_bytes < 1
        or type(close_usage_ttl_seconds) is not int
        or not 1 <= close_usage_ttl_seconds < 86_400
        or type(source_max_timestamp_age_seconds) is not int
        or source_max_timestamp_age_seconds < 0
    ):
        return False
    for name in (
        "profile_content_hash",
        "policy_snapshot_hash",
        "policy_content_sha256",
        "original_body_sha256",
        "status_mapping_sha256",
        "close_policy_content_hash",
        "close_calendar_content_hash",
        "close_calendar_source_hash",
        "close_execution_rule_content_hash",
        "close_market_content_hash",
        "close_market_source_hash",
        "close_bundle_content_hash",
        "close_decision_content_hash",
    ):
        if not _is_sha256(proof.get(name)):
            return False
    if not _is_prefixed_sha256(proof.get("source_reference_hash")):
        return False
    status_codes = proof.get("trusted_vendor_status_codes")
    if (
        type(status_codes) is not list
        or not status_codes
        or any(not _is_token(code) for code in status_codes)
        or len(status_codes) != len(set(status_codes))
        or proof.get("reported_status_code") not in status_codes
    ):
        return False
    business_date = _parse_date(proof.get("business_date"))
    execution_session = _parse_date(proof.get("execution_session"))
    instant_names = (
        "as_of",
        "policy_known_at",
        "policy_effective_at",
        "known_at",
        "proven_available_at",
        "observed_at",
        "close_calendar_available_at",
        "close_policy_available_from",
        "close_policy_available_until",
        "close_usage_deadline",
        "close_calendar_valid_until",
        "close_market_valid_until",
        "business_date_deadline",
        "source_age_deadline",
        "policy_acceptance_deadline",
    )
    instants = {name: _parse_aware_instant(proof.get(name)) for name in instant_names}
    raw_deadlines = proof.get("policy_deadlines")
    if type(raw_deadlines) is not list:
        return False
    policy_deadlines = [_parse_aware_instant(item) for item in raw_deadlines]
    if (
        business_date is None
        or execution_session is None
        or any(item is None for item in (*instants.values(), *policy_deadlines))
    ):
        return False
    as_of = cast(datetime, instants["as_of"])
    known_at = cast(datetime, instants["known_at"])
    captured_at = cast(datetime, instants["proven_available_at"])
    observed_at = cast(datetime, instants["observed_at"])
    try:
        timezone = ZoneInfo(cast(str, proof["business_timezone_name"]))
        source_age_deadline = observed_at + timedelta(
            seconds=cast(int, proof["source_max_timestamp_age_seconds"])
        )
        usage_deadline = captured_at + timedelta(
            seconds=cast(int, proof["close_usage_ttl_seconds"])
        )
        business_date_deadline = datetime.combine(
            business_date + timedelta(days=1), time.min, tzinfo=timezone
        ).astimezone(UTC)
        expected_deadline = min(
            (
                source_age_deadline,
                usage_deadline,
                business_date_deadline,
                cast(datetime, instants["close_policy_available_until"]),
                cast(datetime, instants["close_calendar_valid_until"]),
                cast(datetime, instants["close_market_valid_until"]),
                *(cast(datetime, value) for value in policy_deadlines),
            )
        )
    except (ArithmeticError, OverflowError, TypeError, ValueError, ZoneInfoNotFoundError):
        return False
    return (
        execution_session == business_date
        and cast(str, proof["business_timezone_name"]) == "Asia/Shanghai"
        and as_of.astimezone(timezone).date() == business_date
        and observed_at.astimezone(timezone).date() == business_date
        and observed_at <= captured_at <= known_at <= as_of
        and cast(datetime, instants["policy_known_at"]) <= as_of
        and cast(datetime, instants["policy_effective_at"]) <= as_of
        and cast(datetime, instants["close_calendar_available_at"]) <= captured_at
        and cast(datetime, instants["close_policy_available_from"]) <= as_of
        and cast(datetime, instants["close_policy_available_from"])
        < cast(datetime, instants["close_policy_available_until"])
        and cast(datetime, instants["close_policy_available_until"]) > as_of
        and cast(datetime, instants["close_calendar_valid_until"]) > as_of
        and cast(datetime, instants["close_market_valid_until"]) > as_of
        and source_age_deadline == cast(datetime, instants["source_age_deadline"])
        and usage_deadline == cast(datetime, instants["close_usage_deadline"])
        and business_date_deadline == cast(datetime, instants["business_date_deadline"])
        and expected_deadline
        == cast(datetime, instants["policy_acceptance_deadline"]).astimezone(UTC)
        and cast(datetime, instants["policy_acceptance_deadline"]) > as_of
        and proof.get("as_of") == source.get("cutoff")
        and proof.get("source_id") == source.get("source_id")
        and proof.get("source_record_id") == source.get("source_record_id")
        and proof.get("original_body_sha256") == source.get("raw_payload_sha256")
        and proof.get("observed_at") == source.get("observed_at")
        and proof.get("known_at") == source.get("known_at")
        and source.get("observation_precision") == "timestamp"
        and source.get("observed_on") is None
        and source.get("available_at") is None
        and source.get("valid_until") is None
        and source.get("purpose") == "close_snapshot_simulation"
        and set(cast(list[str], source.get("restrictions", [])))
        >= {"vendor_reported_at_quote_time", "close_snapshot_only"}
        and source.get("must_not_use_for_decision") is False
    )


def source_clock_proof_matches_report(
    *,
    source: object,
    as_of_text: str,
    account_id: int,
    policy_version: object,
) -> bool:
    """Bind a source proof to the outer report's account, cutoff and version."""

    if not isinstance(source, dict):
        return False
    proof = source.get("clock_evidence_proof")
    if proof is None:
        return True
    if not isinstance(proof, dict):
        return False
    return (
        proof.get("as_of") == as_of_text
        and proof.get("account_id") == account_id
        and type(policy_version) is str
        and type(proof.get("profile_key")) is str
        and policy_version == f"{proof['profile_key']}@{proof['profile_version']}"
    )


def _parse_date(value: object) -> date | None:
    if type(value) is not str:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _parse_aware_instant(value: object) -> datetime | None:
    if type(value) is not str:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None or parsed.isoformat() != value:
        return None
    return parsed


def _is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_prefixed_sha256(value: object) -> bool:
    return (
        type(value) is str
        and value.startswith("sha256:")
        and _is_sha256(value.removeprefix("sha256:"))
    )


def _is_token(value: object) -> bool:
    """Validate one public canonical token without coercing or cleaning it."""

    return (
        type(value) is str
        and bool(value)
        and value.strip() == value
        and not any(character.isspace() for character in value)
    )


__all__ = ["is_source_clock_evidence_proof", "source_clock_proof_matches_report"]
