"""Qualify a captured ETF report period against its separately published notice."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apps.risk_center.application.portfolio_risk_policy import (
    PortfolioRiskPolicyBundle,
    PortfolioRiskSourceReference,
)
from apps.risk_center.domain.portfolio_exposure_types import ETFConstituentReport
from apps.risk_center.domain.portfolio_risk_clock_evidence import PortfolioRiskCaptureReceipt
from apps.risk_center.domain.portfolio_risk_disclosed_etf_report_clock import (
    PortfolioRiskDisclosedETFReportProof,
)
from apps.risk_center.domain.portfolio_risk_sources import (
    CoverageStatus,
    PortfolioRiskSourceEvidence,
    SourceObservationPrecision,
    qualify_portfolio_risk_source,
)


@dataclass(frozen=True, slots=True)
class PortfolioRiskETFReportPublicationCapture:
    """Trusted capture of the official page publishing one ETF report date.

    A trusted publication decoder must populate ``publication_on`` from the
    captured page body. This DTO verifies the bytes and receipt, not the HTML
    page's semantic date extraction.
    """

    publication_on: date
    original_body: bytes
    original_url: str
    receipt: PortfolioRiskCaptureReceipt

    def __post_init__(self) -> None:
        """Require an exact date, absolute URL, and matching successful body receipt."""

        if type(self.publication_on) is not date:
            raise TypeError("publication_on must be an exact date")
        if type(self.original_body) is not bytes or not self.original_body:
            raise TypeError("publication original_body must be nonempty bytes")
        _require_https_url(self.original_url, "publication original_url")
        if type(self.receipt) is not PortfolioRiskCaptureReceipt:
            raise TypeError("publication receipt must be PortfolioRiskCaptureReceipt")
        self.receipt.__post_init__()
        body_hash = hashlib.sha256(self.original_body).hexdigest()
        if self.receipt.original_body_sha256 != body_hash:
            raise ValueError("publication receipt hash differs from its original body")
        if self.receipt.body_size_bytes != len(self.original_body):
            raise ValueError("publication receipt size differs from its original body")
        if not 200 <= self.receipt.http_status < 300 or not self.receipt.body_complete:
            raise ValueError("publication capture requires a complete successful response")


@dataclass(frozen=True, slots=True)
class PortfolioRiskDisclosedETFReportClockQualification:
    """Return a disclosure-clock proof or stable clock-qualification reasons."""

    proof: PortfolioRiskDisclosedETFReportProof | None
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        """Keep proof presence consistent with qualification reasons."""

        if type(self.reason_codes) is not tuple or any(
            type(reason) is not str or not reason.strip() for reason in self.reason_codes
        ):
            raise ValueError("reason_codes must contain stable nonempty tokens")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("reason_codes cannot contain duplicates")
        if self.proof is not None and type(self.proof) is not PortfolioRiskDisclosedETFReportProof:
            raise TypeError("proof must be PortfolioRiskDisclosedETFReportProof or None")
        if (self.proof is None) == (not self.reason_codes):
            raise ValueError("qualification must contain exactly a proof or failure reasons")


def qualify_policy_bounded_disclosed_etf_report(
    *,
    policy: PortfolioRiskPolicyBundle,
    source_reference: PortfolioRiskSourceReference,
    retained_payload_hash: str,
    account_id: int,
    asset_code: str,
    security_id: str,
    source_evidence: PortfolioRiskSourceEvidence,
    report: ETFConstituentReport,
    report_original_body: bytes,
    report_original_url: str,
    report_receipt: PortfolioRiskCaptureReceipt,
    publication_capture: PortfolioRiskETFReportPublicationCapture,
    as_of: datetime,
    business_date: date,
    business_timezone_name: str,
    policy_deadlines: tuple[datetime, ...],
) -> PortfolioRiskDisclosedETFReportClockQualification:
    """Prove the bounded disclosure dates without manufacturing source expiry.

    The report period end and publication date receive independent inclusive
    age limits. Both originals and receipts are hash-bound, while source-origin
    ``available_at`` and ``valid_until`` remain ``None``.
    """

    reasons: list[str] = []
    if type(policy) is not PortfolioRiskPolicyBundle:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_POLICY_INVALID")
    if type(source_reference) is not PortfolioRiskSourceReference:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_SOURCE_REFERENCE_INVALID")
    if type(source_evidence) is not PortfolioRiskSourceEvidence:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_SOURCE_EVIDENCE_INVALID")
    if type(report) is not ETFConstituentReport:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_FACTS_INVALID")
    if type(report_receipt) is not PortfolioRiskCaptureReceipt:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_RECEIPT_INVALID")
    if type(publication_capture) is not PortfolioRiskETFReportPublicationCapture:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_PUBLICATION_CAPTURE_INVALID")
    if type(account_id) is not int or account_id < 1:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_ACCOUNT_SCOPE_INVALID")
    if any(
        type(identity_value) is not str or not identity_value.strip()
        for identity_value in (asset_code, security_id)
    ):
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_ASSET_IDENTITY_INVALID")
    if type(as_of) is not datetime or not _is_aware(as_of):
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_CUTOFF_INVALID")
    if type(business_date) is not date:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_BUSINESS_DATE_INVALID")
    if not isinstance(business_timezone_name, str) or not business_timezone_name:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_TIMEZONE_INVALID")
    if type(policy_deadlines) is not tuple or any(
        type(policy_deadline) is not datetime or not _is_aware(policy_deadline)
        for policy_deadline in policy_deadlines
    ):
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_POLICY_DEADLINES_INVALID")
    if reasons:
        return _failure(reasons)

    try:
        policy.__post_init__()
        policy.industry_policy.__post_init__()
        policy.capacity_policy.__post_init__()
        if policy.etf_report_policy is not None:
            policy.etf_report_policy.__post_init__()
        source_reference.__post_init__()
        source_evidence.__post_init__()
        report.__post_init__()
        report_receipt.__post_init__()
        publication_capture.__post_init__()
    except (AttributeError, ArithmeticError, TypeError, ValueError):
        return _failure(("PORTFOLIO_RISK_ETF_REPORT_INPUT_CONTRACT_INVALID",))

    etf_policy = policy.etf_report_policy
    if etf_policy is None:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_POLICY_UNCONFIGURED")
    if (
        source_reference.kind != "etf_report"
        or source_reference.clock_evidence_mode != "policy_bounded_disclosed_report"
        or source_reference not in policy.source_references
        or source_reference.raw_payload_hash != retained_payload_hash
        or source_reference.asset_code != asset_code
        or source_reference.security_id != security_id
    ):
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_REFERENCE_MISMATCH")
    if account_id not in policy.account_ids:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_ACCOUNT_SCOPE_MISMATCH")
    if policy.as_of != as_of:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_POLICY_CUTOFF_MISMATCH")
    if policy.business_date != business_date:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_POLICY_BUSINESS_DATE_MISMATCH")
    source_qualification = qualify_portfolio_risk_source(
        evidence=source_evidence,
        requested_purpose=policy.industry_policy.requested_purpose,
        allowed_observation_precisions=policy.industry_policy.allowed_observation_precisions,
        as_of=as_of,
        allowed_restrictions=policy.industry_policy.allowed_source_restrictions,
        expected_source_kind="etf_report",
    )
    special_missing_clocks = {
        "RISK_SOURCE_AVAILABLE_AT_UNKNOWN",
        "RISK_SOURCE_VALID_UNTIL_UNKNOWN",
    }
    reasons.extend(
        reason
        for reason in source_qualification.reason_codes
        if reason not in special_missing_clocks
    )
    if SourceObservationPrecision.DATE not in policy.industry_policy.allowed_observation_precisions:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_DATE_PRECISION_NOT_ALLOWED")
    if (
        policy.industry_policy.requested_purpose
        not in policy.industry_policy.date_precision_purposes
    ):
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_DATE_PURPOSE_NOT_ALLOWED")
    if type(report_original_body) is not bytes or not report_original_body:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_BODY_INVALID")
    try:
        _require_https_url(report_original_url, "report original_url")
    except ValueError:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_URL_INVALID")
    if report_receipt.source_id != source_evidence.source_id or (
        report_receipt.source_record_id != source_reference.source_record_id
    ):
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_RECEIPT_IDENTITY_MISMATCH")
    if source_evidence.source_record_id != source_reference.source_record_id:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_RECORD_ID_MISMATCH")
    source_body_hash = source_evidence.original_payload_sha256
    if source_body_hash is None or (
        type(report_original_body) is bytes
        and hashlib.sha256(report_original_body).hexdigest() != source_body_hash
    ):
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_BODY_HASH_MISMATCH")
    if (
        type(report_original_body) is bytes
        and report_receipt.original_body_sha256 != hashlib.sha256(report_original_body).hexdigest()
    ):
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_RECEIPT_HASH_MISMATCH")
    if type(report_original_body) is bytes and report_receipt.body_size_bytes != len(
        report_original_body
    ):
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_RECEIPT_SIZE_MISMATCH")
    if not 200 <= report_receipt.http_status < 300 or not report_receipt.body_complete:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_CAPTURE_INCOMPLETE")
    if report.source_evidence != source_evidence:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_EVIDENCE_MISMATCH")
    if source_evidence.observation_precision is not SourceObservationPrecision.DATE:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_OBSERVATION_PRECISION_MISMATCH")
    if source_evidence.observed_on != publication_capture.publication_on:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_PUBLICATION_DATE_MISMATCH")
    if source_evidence.observed_at is not None:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_SYNTHETIC_OBSERVATION_TIME")
    if source_evidence.decision_date_cutoff != business_date:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_DATE_CUTOFF_MISMATCH")
    if source_evidence.decision_cutoff != as_of:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_INSTANT_CUTOFF_MISMATCH")
    if source_evidence.available_at is not None or source_evidence.valid_until is not None:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_SOURCE_CLOCKS_MUST_REMAIN_UNKNOWN")
    known_at = source_evidence.known_at
    if known_at is None:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_KNOWN_AT_UNKNOWN")
    if source_evidence.effective_on != report.report_date:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_PERIOD_END_MISMATCH")
    if etf_policy is not None and report.report_date > publication_capture.publication_on:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_PERIOD_AFTER_PUBLICATION")

    try:
        timezone = ZoneInfo(business_timezone_name)
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_TIMEZONE_INVALID")
        return _failure(reasons)
    if as_of.astimezone(timezone).date() != business_date:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_BUSINESS_DATE_CUTOFF_MISMATCH")
    if policy.known_at > as_of or policy.effective_at > as_of:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_POLICY_NOT_CURRENT_AT_CUTOFF")
    if known_at is not None and (
        known_at
        < max(
            report_receipt.response_completed_at,
            publication_capture.receipt.response_completed_at,
        )
    ):
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_KNOWN_BEFORE_CAPTURE")
    if report_receipt.response_completed_at > as_of or (
        publication_capture.receipt.response_completed_at > as_of
    ):
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_CAPTURE_AFTER_CUTOFF")
    if (
        publication_capture.receipt.http_status < 200
        or (publication_capture.receipt.http_status >= 300)
        or not publication_capture.receipt.body_complete
    ):
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_PUBLICATION_CAPTURE_INCOMPLETE")
    if publication_capture.receipt.response_completed_at.astimezone(timezone).date() < (
        publication_capture.publication_on
    ):
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_PUBLICATION_AFTER_CAPTURE")
    if report.report_date > business_date or publication_capture.publication_on > business_date:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_DATE_AFTER_BUSINESS_DATE")
    if source_evidence.coverage.status is CoverageStatus.UNKNOWN:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_COVERAGE_UNKNOWN")
    if reasons:
        return _failure(reasons)
    if etf_policy is None:
        return _failure(("PORTFOLIO_RISK_ETF_REPORT_POLICY_UNCONFIGURED",))
    if known_at is None:
        return _failure(("PORTFOLIO_RISK_ETF_REPORT_KNOWN_AT_UNKNOWN",))
    if source_body_hash is None:
        return _failure(("PORTFOLIO_RISK_ETF_REPORT_BODY_HASH_MISMATCH",))

    report_age = (business_date - report.report_date).days
    publication_age = (business_date - publication_capture.publication_on).days
    if report_age > etf_policy.max_report_age_days:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_PERIOD_AGE_EXCEEDED")
    if publication_age > policy.source_max_date_age_days:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_PUBLICATION_AGE_EXCEEDED")
    try:
        report_period_deadline = _inclusive_date_deadline(
            report.report_date,
            etf_policy.max_report_age_days,
            timezone,
        )
        publication_deadline = _inclusive_date_deadline(
            publication_capture.publication_on,
            policy.source_max_date_age_days,
            timezone,
        )
        business_date_deadline = _inclusive_date_deadline(business_date, 0, timezone)
    except (OverflowError, ValueError):
        return _failure((*reasons, "PORTFOLIO_RISK_ETF_REPORT_DEADLINE_INVALID"))
    external_deadlines = list(policy_deadlines)
    for policy_end in (
        policy.industry_policy.effective_until,
        policy.capacity_policy.effective_until,
    ):
        if policy_end is not None and policy_end not in external_deadlines:
            external_deadlines.append(policy_end)
    deadline_candidates = (
        report_period_deadline,
        publication_deadline,
        business_date_deadline,
        *external_deadlines,
    )
    acceptance_deadline = min(deadline_candidates)
    if acceptance_deadline <= as_of:
        reasons.append("PORTFOLIO_RISK_ETF_REPORT_EXPIRED_AT_CUTOFF")
    if reasons:
        return _failure(reasons)

    publication_receipt = publication_capture.receipt
    proof = PortfolioRiskDisclosedETFReportProof(
        scope="simulation_only",
        source_kind="etf_report",
        clock_evidence_mode="policy_bounded_disclosed_report",
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
        source_id=source_evidence.source_id,
        source_record_id=source_evidence.source_record_id,
        capture_id=report_receipt.capture_id,
        original_body_sha256=source_body_hash,
        source_original_url=report_original_url,
        receipt_completed_at=report_receipt.response_completed_at,
        http_status=report_receipt.http_status,
        body_size_bytes=report_receipt.body_size_bytes,
        body_complete=report_receipt.body_complete,
        report_period_end=report.report_date,
        publication_source_id=publication_receipt.source_id,
        publication_record_id=publication_receipt.source_record_id,
        publication_capture_id=publication_receipt.capture_id,
        publication_original_body_sha256=publication_receipt.original_body_sha256,
        publication_original_url=publication_capture.original_url,
        publication_on=publication_capture.publication_on,
        publication_receipt_completed_at=publication_receipt.response_completed_at,
        publication_http_status=publication_receipt.http_status,
        publication_body_size_bytes=publication_receipt.body_size_bytes,
        publication_body_complete=publication_receipt.body_complete,
        as_of=as_of,
        business_date=business_date,
        business_timezone_name=business_timezone_name,
        known_at=known_at,
        proven_available_at=max(
            report_receipt.response_completed_at,
            publication_receipt.response_completed_at,
        ),
        age_basis="report_period_end",
        max_report_age_days=etf_policy.max_report_age_days,
        source_max_date_age_days=policy.source_max_date_age_days,
        report_period_age_deadline=report_period_deadline,
        publication_age_deadline=publication_deadline,
        business_date_deadline=business_date_deadline,
        policy_deadlines=tuple(external_deadlines),
        policy_acceptance_deadline=acceptance_deadline,
        coverage_status=(
            "complete" if source_evidence.coverage.status is CoverageStatus.COMPLETE else "partial"
        ),
        coverage_precision_basis=source_evidence.coverage.precision_basis,
        source_available_at=None,
        source_valid_until=None,
    )
    return PortfolioRiskDisclosedETFReportClockQualification(proof=proof, reason_codes=())


def _inclusive_date_deadline(start: date, age_days: int, timezone: ZoneInfo) -> datetime:
    return datetime.combine(
        start + timedelta(days=age_days + 1), time.min, tzinfo=timezone
    ).astimezone(UTC)


def _is_aware(value: datetime) -> bool:
    """Return whether an exact datetime carries a usable timezone offset."""

    return type(value) is datetime and value.tzinfo is not None and value.utcoffset() is not None


def _failure(
    reasons: tuple[str, ...] | list[str],
) -> PortfolioRiskDisclosedETFReportClockQualification:
    return PortfolioRiskDisclosedETFReportClockQualification(
        proof=None,
        reason_codes=tuple(dict.fromkeys(reasons)),
    )


def _require_https_url(value: str, field_name: str) -> None:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(f"{field_name} must be an absolute HTTPS URL")
    if any(character.isspace() for character in value):
        raise ValueError(f"{field_name} cannot contain whitespace")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.hostname is None
        or "@" in parsed.netloc
        or "#" in value
    ):
        raise ValueError(f"{field_name} must be a credential-free HTTPS URL without fragment")


__all__ = (
    "PortfolioRiskDisclosedETFReportClockQualification",
    "PortfolioRiskETFReportPublicationCapture",
    "qualify_policy_bounded_disclosed_etf_report",
)
