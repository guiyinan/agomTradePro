"""Clock proof for a retained ETF report tied to its official publication notice."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True, slots=True)
class PortfolioRiskDisclosedETFReportProof:
    """Bind an ETF reporting-period date to a captured, dated publication notice.

    This clock proof does not certify holdings coverage. A partial report can carry
    this proof for display while the separate coverage and exposure gates block use.
    Source-origin availability and expiry remain unknown.
    """

    scope: Literal["simulation_only"]
    source_kind: Literal["etf_report"]
    clock_evidence_mode: Literal["policy_bounded_disclosed_report"]
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
    source_original_url: str
    receipt_completed_at: datetime
    http_status: int
    body_size_bytes: int
    body_complete: bool
    report_period_end: date
    publication_source_id: str
    publication_record_id: str
    publication_capture_id: str
    publication_original_body_sha256: str
    publication_original_url: str
    publication_on: date
    publication_receipt_completed_at: datetime
    publication_http_status: int
    publication_body_size_bytes: int
    publication_body_complete: bool
    as_of: datetime
    business_date: date
    business_timezone_name: str
    known_at: datetime
    proven_available_at: datetime
    age_basis: Literal["report_period_end"]
    max_report_age_days: int
    source_max_date_age_days: int
    report_period_age_deadline: datetime
    publication_age_deadline: datetime
    business_date_deadline: datetime
    policy_deadlines: tuple[datetime, ...]
    policy_acceptance_deadline: datetime
    coverage_status: Literal["complete", "partial"]
    coverage_precision_basis: str
    source_available_at: None
    source_valid_until: None

    def __post_init__(self) -> None:
        """Validate identities, both captures, dates, and the exact earliest deadline."""

        if (
            self.scope != "simulation_only"
            or self.source_kind != "etf_report"
            or self.clock_evidence_mode != "policy_bounded_disclosed_report"
        ):
            raise ValueError("disclosed ETF report proof has an unsupported scope or mode")
        if self.age_basis != "report_period_end":
            raise ValueError("ETF report age basis must be report_period_end")
        if self.coverage_status not in ("complete", "partial"):
            raise ValueError("clock proof requires known complete or partial coverage")
        for token_name, token_value in (
            ("profile_key", self.profile_key),
            ("policy_snapshot_id", self.policy_snapshot_id),
            ("asset_code", self.asset_code),
            ("security_id", self.security_id),
            ("source_id", self.source_id),
            ("source_record_id", self.source_record_id),
            ("capture_id", self.capture_id),
            ("source_original_url", self.source_original_url),
            ("publication_source_id", self.publication_source_id),
            ("publication_record_id", self.publication_record_id),
            ("publication_capture_id", self.publication_capture_id),
            ("publication_original_url", self.publication_original_url),
            ("business_timezone_name", self.business_timezone_name),
            ("coverage_precision_basis", self.coverage_precision_basis),
        ):
            _require_token(token_value, token_name)
        _require_https_url(self.source_original_url, "source_original_url")
        _require_https_url(self.publication_original_url, "publication_original_url")
        for hash_name, hash_value in (
            ("profile_content_hash", self.profile_content_hash),
            ("policy_snapshot_hash", self.policy_snapshot_hash),
            ("policy_content_sha256", self.policy_content_sha256),
            ("original_body_sha256", self.original_body_sha256),
            ("publication_original_body_sha256", self.publication_original_body_sha256),
        ):
            _require_sha256(hash_value, hash_name)
        if (
            type(self.source_reference_hash) is not str
            or re.fullmatch(r"sha256:[0-9a-f]{64}", self.source_reference_hash) is None
        ):
            raise ValueError("source_reference_hash must be a prefixed SHA-256 manifest hash")
        if type(self.account_id) is not int or self.account_id < 1:
            raise ValueError("account_id must be a positive exact integer")
        if type(self.profile_version) is not int or self.profile_version < 1:
            raise ValueError("profile_version must be a positive exact integer")
        if type(self.report_period_end) is not date or type(self.publication_on) is not date:
            raise TypeError("report period end and publication date must be exact dates")
        if type(self.business_date) is not date:
            raise TypeError("business_date must be an exact date")
        if self.report_period_end > self.publication_on:
            raise ValueError("report period cannot end after its publication date")
        if self.publication_on > self.business_date:
            raise ValueError("publication date cannot be after the business date")
        for age_name, age_days in (
            ("max_report_age_days", self.max_report_age_days),
            ("source_max_date_age_days", self.source_max_date_age_days),
        ):
            if type(age_days) is not int or age_days < 0:
                raise ValueError(f"{age_name} must be a nonnegative exact integer")
        for capture_name, status, size, complete in (
            ("ETF report", self.http_status, self.body_size_bytes, self.body_complete),
            (
                "publication notice",
                self.publication_http_status,
                self.publication_body_size_bytes,
                self.publication_body_complete,
            ),
        ):
            if type(status) is not int or not 200 <= status < 300:
                raise ValueError(f"{capture_name} capture requires an exact successful HTTP status")
            if type(size) is not int or size < 1 or type(complete) is not bool or not complete:
                raise ValueError(f"{capture_name} capture requires a complete nonempty body")
        if self.source_available_at is not None or self.source_valid_until is not None:
            raise ValueError("source-origin availability and expiry must remain unknown")
        instant_fields = (
            ("policy_known_at", self.policy_known_at),
            ("policy_effective_at", self.policy_effective_at),
            ("receipt_completed_at", self.receipt_completed_at),
            ("publication_receipt_completed_at", self.publication_receipt_completed_at),
            ("as_of", self.as_of),
            ("known_at", self.known_at),
            ("proven_available_at", self.proven_available_at),
            ("report_period_age_deadline", self.report_period_age_deadline),
            ("publication_age_deadline", self.publication_age_deadline),
            ("business_date_deadline", self.business_date_deadline),
            ("policy_acceptance_deadline", self.policy_acceptance_deadline),
        )
        for clock_name, clock_value in instant_fields:
            _require_aware(clock_value, clock_name)
        if type(self.policy_deadlines) is not tuple or any(
            type(policy_deadline) is not datetime or not _is_aware(policy_deadline)
            for policy_deadline in self.policy_deadlines
        ):
            raise ValueError("policy_deadlines must contain aware instants")
        if self.proven_available_at != max(
            self.receipt_completed_at, self.publication_receipt_completed_at
        ):
            raise ValueError("proven_available_at must be the later of both complete captures")
        if (
            self.receipt_completed_at > self.known_at
            or self.publication_receipt_completed_at > self.known_at
            or self.known_at > self.as_of
            or self.proven_available_at > self.as_of
        ):
            raise ValueError("both source receipts, known_at and decision cutoff are inconsistent")
        if self.policy_known_at > self.as_of or self.policy_effective_at > self.as_of:
            raise ValueError("policy must be known and effective at the decision cutoff")
        try:
            timezone = ZoneInfo(self.business_timezone_name)
            report_age_deadline = _inclusive_date_deadline(
                self.report_period_end,
                self.max_report_age_days,
                timezone,
            )
            publication_age_deadline = _inclusive_date_deadline(
                self.publication_on,
                self.source_max_date_age_days,
                timezone,
            )
            business_date_deadline = _inclusive_date_deadline(
                self.business_date,
                0,
                timezone,
            )
        except (OverflowError, TypeError, ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("ETF report dates or timezone cannot form valid deadlines") from exc
        if self.as_of.astimezone(timezone).date() != self.business_date:
            raise ValueError("business_date does not match the configured timezone")
        if (
            self.receipt_completed_at > self.as_of
            or self.publication_receipt_completed_at > self.as_of
        ):
            raise ValueError("capture receipts cannot be after the decision cutoff")
        if self.report_period_age_deadline != report_age_deadline:
            raise ValueError("report period deadline does not match the configured inclusive age")
        if self.publication_age_deadline != publication_age_deadline:
            raise ValueError("publication deadline does not match the configured inclusive age")
        if self.business_date_deadline != business_date_deadline:
            raise ValueError("business date deadline must be the next local midnight")
        expected_deadline = min(
            (
                report_age_deadline,
                publication_age_deadline,
                business_date_deadline,
                *self.policy_deadlines,
            )
        )
        if self.policy_acceptance_deadline != expected_deadline:
            raise ValueError("policy acceptance deadline must be the exact earliest bound")
        if self.policy_acceptance_deadline <= self.as_of:
            raise ValueError("disclosed ETF report proof is already expired")
        if (self.business_date - self.report_period_end).days > self.max_report_age_days:
            raise ValueError("ETF report period is outside the configured age")
        if (self.business_date - self.publication_on).days > self.source_max_date_age_days:
            raise ValueError("ETF publication date is outside the configured source age")


def _inclusive_date_deadline(start: date, age_days: int, timezone: ZoneInfo) -> datetime:
    return datetime.combine(
        start + timedelta(days=age_days + 1), time.min, tzinfo=timezone
    ).astimezone(UTC)


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
        raise ValueError(f"{field_name} must be credential-free HTTPS without fragment")


def _require_aware(value: datetime, field_name: str) -> None:
    if not _is_aware(value):
        raise ValueError(f"{field_name} must be timezone-aware")


def _is_aware(value: datetime) -> bool:
    return type(value) is datetime and value.tzinfo is not None and value.utcoffset() is not None


__all__ = ("PortfolioRiskDisclosedETFReportProof",)
