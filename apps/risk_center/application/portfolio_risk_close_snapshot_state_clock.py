"""Qualify close-only quote-time status without claiming a full-session state."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from apps.data_center.domain.sina_quote_capture import (
    SINA_QUOTE_SOURCE_ID,
    SINA_VENDOR_STATUS_MAPPING_SHA256,
    SinaQuoteCapture,
    SinaQuoteClockStatus,
    SinaReportedTradingState,
)
from apps.risk_center.application.portfolio_risk_assets import CloseSnapshotSessionEvidence
from apps.risk_center.application.portfolio_risk_policy import (
    PortfolioRiskPolicyBundle,
    PortfolioRiskSourceReference,
)
from apps.risk_center.domain.close_snapshot_simulation import (
    CloseSnapshotSimulationStatus,
)
from apps.risk_center.domain.portfolio_risk_clock_evidence import (
    PortfolioRiskCaptureReceipt,
)
from apps.risk_center.domain.portfolio_risk_clock_evidence import (
    PortfolioRiskCloseSnapshotStateProof as DomainPortfolioRiskCloseSnapshotStateProof,
)
from apps.risk_center.domain.portfolio_risk_sources import (
    CoverageStatus,
    PortfolioRiskSourceEvidence,
    SourceObservationPrecision,
)

_CLOSE_PURPOSE = "close_snapshot_simulation"
_CLOSE_RESTRICTIONS: tuple[
    Literal["vendor_reported_at_quote_time"], Literal["close_snapshot_only"]
] = ("vendor_reported_at_quote_time", "close_snapshot_only")
_SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class PortfolioRiskCloseSnapshotStateQualification:
    """Typed qualified session proof or precise blocking reasons."""

    proof: DomainPortfolioRiskCloseSnapshotStateProof | None
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        """Require proof and reasons to describe one unambiguous outcome."""

        if (
            self.proof is not None
            and type(self.proof) is not DomainPortfolioRiskCloseSnapshotStateProof
        ):
            raise TypeError("proof must be a close snapshot session proof or None")
        if type(self.reason_codes) is not tuple or any(
            type(reason) is not str or not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must be a tuple of nonempty strings")
        if (self.proof is None) == (not self.reason_codes):
            raise ValueError("exactly one of proof or blocking reasons is required")


def qualify_policy_bounded_close_snapshot_state(
    *,
    policy: PortfolioRiskPolicyBundle,
    source_reference: PortfolioRiskSourceReference,
    retained_payload_hash: str,
    account_id: int,
    source_evidence: PortfolioRiskSourceEvidence,
    receipt: PortfolioRiskCaptureReceipt,
    original_body: bytes,
    source_capture: SinaQuoteCapture,
    session_evidence: CloseSnapshotSessionEvidence,
    as_of: datetime,
    business_date: date,
    execution_session: date,
    requested_purpose: str,
) -> PortfolioRiskCloseSnapshotStateQualification:
    """Bind one real ASH-03 qualified evaluation to risk source and clocks.

    This adapter consumes the existing close use case result. It never accepts
    operator strings as proof that a source is qualified, and it keeps the
    source-origin availability and expiry clocks null.
    """

    reasons: list[str] = []
    if type(policy) is not PortfolioRiskPolicyBundle:
        reasons.append("PORTFOLIO_RISK_CLOSE_STATE_POLICY_INVALID")
    if type(source_reference) is not PortfolioRiskSourceReference:
        reasons.append("PORTFOLIO_RISK_CLOSE_STATE_REFERENCE_INVALID")
    if type(source_evidence) is not PortfolioRiskSourceEvidence:
        reasons.append("PORTFOLIO_RISK_CLOSE_STATE_SOURCE_EVIDENCE_INVALID")
    if type(receipt) is not PortfolioRiskCaptureReceipt:
        reasons.append("PORTFOLIO_RISK_CLOSE_STATE_RECEIPT_INVALID")
    if type(source_capture) is not SinaQuoteCapture:
        reasons.append("PORTFOLIO_RISK_CLOSE_STATE_CAPTURE_INVALID")
    if type(session_evidence) is not CloseSnapshotSessionEvidence:
        reasons.append("PORTFOLIO_RISK_CLOSE_STATE_EVALUATION_MISSING")
    if type(original_body) is not bytes or not original_body:
        reasons.append("PORTFOLIO_RISK_CLOSE_STATE_BODY_INVALID")
    if type(account_id) is not int or account_id < 1:
        reasons.append("PORTFOLIO_RISK_CLOSE_STATE_ACCOUNT_INVALID")
    if type(as_of) is not datetime or not _aware(as_of):
        reasons.append("PORTFOLIO_RISK_CLOSE_STATE_CUTOFF_INVALID")
    if type(business_date) is not date or type(execution_session) is not date:
        reasons.append("PORTFOLIO_RISK_CLOSE_STATE_DATE_INVALID")
    if requested_purpose != _CLOSE_PURPOSE:
        reasons.append("PORTFOLIO_RISK_CLOSE_STATE_PURPOSE_NOT_ALLOWED")
    if reasons:
        return _blocked(reasons)

    try:
        policy.__post_init__()
        source_reference.__post_init__()
        source_evidence.__post_init__()
        receipt.__post_init__()
        source_capture.__post_init__()
    except (ArithmeticError, TypeError, ValueError):
        return _blocked(("PORTFOLIO_RISK_CLOSE_STATE_INPUT_CONTRACT_INVALID",))
    evaluation = session_evidence.evaluation
    decision = evaluation.decision
    bundle = evaluation.bundle
    if decision.status is not CloseSnapshotSimulationStatus.QUALIFIED or bundle is None:
        return _blocked(("PORTFOLIO_RISK_CLOSE_STATE_ASH03_NOT_QUALIFIED",))
    try:
        bundle.__post_init__()
        decision.__post_init__()
    except (ArithmeticError, TypeError, ValueError):
        return _blocked(("PORTFOLIO_RISK_CLOSE_STATE_ASH03_EVIDENCE_INVALID",))

    close_policy = bundle.policy
    calendar = bundle.calendar
    capture = bundle.capture
    quote = capture.quote
    market = bundle.market
    market_evidence = market.market_evidence_v1
    policy_references = tuple(item for item in policy.source_references if item == source_reference)
    if len(policy_references) != 1:
        reasons.append("PORTFOLIO_RISK_CLOSE_STATE_REFERENCE_NOT_PINNED")
    if (
        source_reference.kind != "execution_session_state"
        or source_reference.clock_evidence_mode != "policy_bounded_close_snapshot_state"
    ):
        reasons.append("PORTFOLIO_RISK_CLOSE_STATE_REFERENCE_MODE_MISMATCH")
    if (
        policy.as_of != as_of
        or policy.business_date != business_date
        or policy.known_at > as_of
        or policy.effective_at > as_of
    ):
        reasons.append("PORTFOLIO_RISK_CLOSE_STATE_POLICY_CUTOFF_MISMATCH")
    if source_reference.raw_payload_hash != retained_payload_hash:
        reasons.append("PORTFOLIO_RISK_CLOSE_STATE_RETAINED_HASH_MISMATCH")
    expected_body_hash = hashlib.sha256(original_body).hexdigest()
    if (
        source_reference.source_record_id != receipt.source_record_id
        or receipt.source_id != SINA_QUOTE_SOURCE_ID
        or receipt.original_body_sha256 != expected_body_hash
        or receipt.response_completed_at != capture.response_completed_at
        or receipt.http_status != capture.http_status
        or receipt.body_size_bytes != capture.body_size_bytes
        or not receipt.body_complete
        or capture.body != original_body
        or capture.body_sha256 != expected_body_hash
        or source_capture.asset_code != source_reference.asset_code
        or source_capture.body != original_body
        or source_capture.body_sha256 != expected_body_hash
        or source_capture.response_completed_at != receipt.response_completed_at
        or source_capture.http_status != receipt.http_status
        or source_capture.body_size_bytes != receipt.body_size_bytes
        or capture != source_capture
    ):
        reasons.append("PORTFOLIO_RISK_CLOSE_STATE_CAPTURE_BINDING_MISMATCH")
    if (
        source_evidence.source_id != receipt.source_id
        or source_evidence.source_record_id != receipt.source_record_id
        or source_evidence.original_payload_sha256 != expected_body_hash
        or source_evidence.observation_precision is not SourceObservationPrecision.TIMESTAMP
        or source_evidence.observed_on is not None
        or source_evidence.observed_at is None
        or source_evidence.available_at is not None
        or source_evidence.valid_until is not None
        or source_evidence.known_at is None
        or source_evidence.known_at < receipt.response_completed_at
        or source_evidence.known_at > as_of
        or source_evidence.decision_cutoff != as_of
        or source_evidence.effective_on != business_date
        or source_evidence.coverage.status is not CoverageStatus.COMPLETE
        or source_evidence.must_not_use_for_decision
        or source_evidence.source_purpose != _CLOSE_PURPOSE
        or _CLOSE_PURPOSE not in source_evidence.allowed_purposes
        or not set(_CLOSE_RESTRICTIONS) <= set(source_evidence.restrictions)
        or not set(_CLOSE_RESTRICTIONS) <= set(policy.capacity_policy.allowed_source_restrictions)
    ):
        reasons.append("PORTFOLIO_RISK_CLOSE_STATE_SOURCE_EVIDENCE_INVALID")
    if SourceObservationPrecision.TIMESTAMP not in (
        policy.capacity_policy.allowed_observation_precisions
    ):
        reasons.append("PORTFOLIO_RISK_CLOSE_STATE_POLICY_PURPOSE_OR_PRECISION_MISMATCH")
    if account_id not in policy.account_ids or account_id != close_policy.account_id:
        reasons.append("PORTFOLIO_RISK_CLOSE_STATE_ACCOUNT_MISMATCH")
    if (
        close_policy.asset_code != source_reference.asset_code
        or close_policy.security_id != source_reference.security_id
        or close_policy.trading_date != business_date
        or execution_session != business_date
    ):
        reasons.append("PORTFOLIO_RISK_CLOSE_STATE_ASSET_OR_SESSION_MISMATCH")
    if (
        decision.account_id != account_id
        or decision.asset_code != close_policy.asset_code
        or decision.security_id != close_policy.security_id
        or decision.trading_date != business_date
        or decision.evaluated_at != as_of
        or decision.reason_codes
        or decision.capture_body_sha256 != capture.body_sha256
        or decision.policy_content_hash != close_policy.content_hash
        or decision.calendar_content_hash != calendar.content_hash
        or decision.execution_rule_content_hash != bundle.execution_rule_content_hash
        or decision.market_content_hash != market.content_hash
        or decision.requested_price is None
        or quote is None
        or decision.requested_price != quote.last_price
    ):
        reasons.append("PORTFOLIO_RISK_CLOSE_STATE_DECISION_BINDING_MISMATCH")
    if (
        quote is None
        or quote.source_clock_status is not SinaQuoteClockStatus.VALID
        or quote.source_observed_at is None
        or quote.reported_trading_state is not SinaReportedTradingState.TRADING
        or quote.vendor_status_code is None
        or quote.vendor_status_code not in close_policy.trusted_vendor_status_codes
        or quote.source_observed_at < calendar.session_close_at
        or close_policy.status_mapping_sha256 != SINA_VENDOR_STATUS_MAPPING_SHA256
        or market.security_state_basis
        != "vendor_reported_sina_status_mapping_not_exchange_confirmation"
        or market_evidence.security_state.value != "TRADING"
        or market_evidence.session_state.value != "CLOSED"
        or market_evidence.market_observed_at != quote.source_observed_at
        or market_evidence.market_available_at != capture.response_completed_at
        or market_evidence.security_id != close_policy.security_id
        or market_evidence.trading_date != business_date
        or market_evidence.calendar_source_hash != calendar.calendar_source_hash
        or market_evidence.market_valid_until is None
        or source_evidence.observed_at != quote.source_observed_at
    ):
        reasons.append("PORTFOLIO_RISK_CLOSE_STATE_VENDOR_QUOTE_BINDING_MISMATCH")
    if (
        calendar.session_state.value != "CLOSED"
        or calendar.trading_date != business_date
        or calendar.session_timezone != "Asia/Shanghai"
        or calendar.calendar_available_at > capture.response_completed_at
        or calendar.calendar_valid_until <= as_of
        or close_policy.available_from < calendar.session_close_at
        or as_of < close_policy.available_from
        or as_of >= close_policy.available_until
        or capture.request_started_at < calendar.session_close_at
        or capture.response_completed_at > as_of
    ):
        reasons.append("PORTFOLIO_RISK_CLOSE_STATE_CALENDAR_OR_POLICY_WINDOW_INVALID")
    if reasons:
        return _blocked(reasons)

    assert quote is not None
    assert quote.source_observed_at is not None
    assert quote.vendor_status_code is not None
    assert source_evidence.known_at is not None
    close_usage_deadline = capture.response_completed_at + timedelta(
        seconds=close_policy.usage_ttl_seconds
    )
    market_valid_until = market_evidence.market_valid_until
    assert market_valid_until is not None
    business_date_deadline = datetime.combine(
        business_date + timedelta(days=1), time.min, tzinfo=_SHANGHAI
    ).astimezone(UTC)
    source_age_deadline = quote.source_observed_at + timedelta(
        seconds=policy.source_max_timestamp_age_seconds
    )
    policy_deadlines = tuple(
        sorted(
            deadline
            for deadline in (
                policy.industry_policy.effective_until,
                policy.capacity_policy.effective_until,
            )
            if deadline is not None
        )
    )
    all_deadlines = (
        close_policy.available_until,
        close_usage_deadline,
        calendar.calendar_valid_until,
        market_valid_until,
        business_date_deadline,
        source_age_deadline,
        *policy_deadlines,
    )
    acceptance_deadline = min(all_deadlines)
    if acceptance_deadline <= as_of:
        return _blocked(("PORTFOLIO_RISK_CLOSE_STATE_EVIDENCE_EXPIRED",))

    proof = DomainPortfolioRiskCloseSnapshotStateProof(
        scope="simulation_only",
        source_kind="execution_session_state",
        clock_evidence_mode="policy_bounded_close_snapshot_state",
        state_basis="vendor_reported_at_quote_time",
        reported_trading_state="TRADING",
        full_session_state="unknown",
        purpose="close_snapshot_simulation",
        required_restrictions=_CLOSE_RESTRICTIONS,
        profile_key=policy.profile_key,
        profile_version=policy.profile_version,
        profile_content_hash=policy.profile_content_hash,
        policy_snapshot_id=policy.snapshot_id,
        policy_snapshot_hash=policy.snapshot_hash,
        policy_content_sha256=policy.normalized_config_sha256,
        policy_known_at=policy.known_at,
        policy_effective_at=policy.effective_at,
        source_reference_hash=source_reference.raw_payload_hash,
        account_id=account_id,
        asset_code=source_reference.asset_code,
        security_id=source_reference.security_id,
        source_id=receipt.source_id,
        source_record_id=receipt.source_record_id,
        capture_id=receipt.capture_id,
        original_body_sha256=receipt.original_body_sha256,
        as_of=as_of,
        business_date=business_date,
        execution_session=execution_session,
        known_at=source_evidence.known_at,
        proven_available_at=receipt.response_completed_at,
        observed_at=quote.source_observed_at,
        http_status=receipt.http_status,
        body_size_bytes=receipt.body_size_bytes,
        body_complete=receipt.body_complete,
        status_mapping_sha256=close_policy.status_mapping_sha256,
        trusted_vendor_status_codes=close_policy.trusted_vendor_status_codes,
        reported_status_code=quote.vendor_status_code,
        close_policy_content_hash=close_policy.content_hash,
        close_calendar_content_hash=calendar.content_hash,
        close_calendar_source_hash=calendar.calendar_source_hash,
        close_calendar_session_state="CLOSED",
        close_calendar_available_at=calendar.calendar_available_at,
        close_execution_rule_content_hash=bundle.execution_rule_content_hash,
        close_market_content_hash=market.content_hash,
        close_market_source_hash=market_evidence.market_source_hash,
        close_market_session_state="CLOSED",
        close_market_security_state_basis=(
            "vendor_reported_sina_status_mapping_not_exchange_confirmation"
        ),
        close_bundle_content_hash=bundle.content_hash,
        close_decision_content_hash=decision.content_hash,
        close_policy_available_from=close_policy.available_from,
        close_policy_available_until=close_policy.available_until,
        close_usage_ttl_seconds=close_policy.usage_ttl_seconds,
        close_usage_deadline=close_usage_deadline,
        close_calendar_valid_until=calendar.calendar_valid_until,
        close_market_valid_until=market_valid_until,
        business_timezone_name="Asia/Shanghai",
        business_date_deadline=business_date_deadline,
        source_max_timestamp_age_seconds=policy.source_max_timestamp_age_seconds,
        source_age_deadline=source_age_deadline,
        policy_deadlines=policy_deadlines,
        policy_acceptance_deadline=acceptance_deadline,
        source_available_at=None,
        source_valid_until=None,
    )
    return PortfolioRiskCloseSnapshotStateQualification(proof=proof, reason_codes=())


def _blocked(
    reasons: tuple[str, ...] | list[str],
) -> PortfolioRiskCloseSnapshotStateQualification:
    """Return unique stable blockers for a failed close-state qualification."""

    return PortfolioRiskCloseSnapshotStateQualification(
        proof=None,
        reason_codes=tuple(dict.fromkeys(reasons)),
    )


def _aware(value: datetime) -> bool:
    """Return whether a datetime carries a real UTC offset."""

    return value.tzinfo is not None and value.utcoffset() is not None


__all__ = (
    "PortfolioRiskCloseSnapshotStateQualification",
    "qualify_policy_bounded_close_snapshot_state",
)
