"""Lossless JSON boundary for finite ETF disclosure clock proofs."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Literal, TypedDict, cast

from apps.risk_center.domain.portfolio_risk_disclosed_etf_report_clock import (
    PortfolioRiskDisclosedETFReportProof,
)


class PortfolioRiskDisclosedETFReportClockProofPayload(TypedDict):
    """Separate report/publication ages and receipts; vendor clocks stay unknown."""

    scope: Literal["simulation_only"]
    source_kind: Literal["etf_report"]
    clock_evidence_mode: Literal["policy_bounded_disclosed_report"]
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
    source_original_url: str
    receipt_completed_at: str
    http_status: int
    body_size_bytes: int
    body_complete: bool
    report_period_end: str
    publication_source_id: str
    publication_record_id: str
    publication_capture_id: str
    publication_original_body_sha256: str
    publication_original_url: str
    publication_on: str
    publication_receipt_completed_at: str
    publication_http_status: int
    publication_body_size_bytes: int
    publication_body_complete: bool
    as_of: str
    business_date: str
    business_timezone_name: str
    known_at: str
    proven_available_at: str
    age_basis: Literal["report_period_end"]
    max_report_age_days: int
    source_max_date_age_days: int
    report_period_age_deadline: str
    publication_age_deadline: str
    business_date_deadline: str
    policy_deadlines: list[str]
    policy_acceptance_deadline: str
    coverage_status: Literal["complete", "partial"]
    coverage_precision_basis: str
    source_available_at: None
    source_valid_until: None


_PROOF_KEYS: frozenset[str] = frozenset(
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
        "source_original_url",
        "receipt_completed_at",
        "http_status",
        "body_size_bytes",
        "body_complete",
        "report_period_end",
        "publication_source_id",
        "publication_record_id",
        "publication_capture_id",
        "publication_original_body_sha256",
        "publication_original_url",
        "publication_on",
        "publication_receipt_completed_at",
        "publication_http_status",
        "publication_body_size_bytes",
        "publication_body_complete",
        "as_of",
        "business_date",
        "business_timezone_name",
        "known_at",
        "proven_available_at",
        "age_basis",
        "max_report_age_days",
        "source_max_date_age_days",
        "report_period_age_deadline",
        "publication_age_deadline",
        "business_date_deadline",
        "policy_deadlines",
        "policy_acceptance_deadline",
        "coverage_status",
        "coverage_precision_basis",
        "source_available_at",
        "source_valid_until",
    }
)


def disclosed_etf_report_clock_payload(
    proof: PortfolioRiskDisclosedETFReportProof,
) -> PortfolioRiskDisclosedETFReportClockProofPayload:
    """Serialize exact offsets and independent dates without rewriting origin clocks."""

    proof.__post_init__()
    return {
        "scope": proof.scope,
        "source_kind": proof.source_kind,
        "clock_evidence_mode": proof.clock_evidence_mode,
        "profile_key": proof.profile_key,
        "profile_version": proof.profile_version,
        "profile_content_hash": proof.profile_content_hash,
        "policy_snapshot_id": proof.policy_snapshot_id,
        "policy_snapshot_hash": proof.policy_snapshot_hash,
        "policy_content_sha256": proof.policy_content_sha256,
        "policy_known_at": proof.policy_known_at.isoformat(),
        "policy_effective_at": proof.policy_effective_at.isoformat(),
        "source_reference_hash": proof.source_reference_hash,
        "account_id": proof.account_id,
        "asset_code": proof.asset_code,
        "security_id": proof.security_id,
        "source_id": proof.source_id,
        "source_record_id": proof.source_record_id,
        "capture_id": proof.capture_id,
        "original_body_sha256": proof.original_body_sha256,
        "source_original_url": proof.source_original_url,
        "receipt_completed_at": proof.receipt_completed_at.isoformat(),
        "http_status": proof.http_status,
        "body_size_bytes": proof.body_size_bytes,
        "body_complete": proof.body_complete,
        "report_period_end": proof.report_period_end.isoformat(),
        "publication_source_id": proof.publication_source_id,
        "publication_record_id": proof.publication_record_id,
        "publication_capture_id": proof.publication_capture_id,
        "publication_original_body_sha256": proof.publication_original_body_sha256,
        "publication_original_url": proof.publication_original_url,
        "publication_on": proof.publication_on.isoformat(),
        "publication_receipt_completed_at": proof.publication_receipt_completed_at.isoformat(),
        "publication_http_status": proof.publication_http_status,
        "publication_body_size_bytes": proof.publication_body_size_bytes,
        "publication_body_complete": proof.publication_body_complete,
        "as_of": proof.as_of.isoformat(),
        "business_date": proof.business_date.isoformat(),
        "business_timezone_name": proof.business_timezone_name,
        "known_at": proof.known_at.isoformat(),
        "proven_available_at": proof.proven_available_at.isoformat(),
        "age_basis": proof.age_basis,
        "max_report_age_days": proof.max_report_age_days,
        "source_max_date_age_days": proof.source_max_date_age_days,
        "report_period_age_deadline": proof.report_period_age_deadline.isoformat(),
        "publication_age_deadline": proof.publication_age_deadline.isoformat(),
        "business_date_deadline": proof.business_date_deadline.isoformat(),
        "policy_deadlines": [item.isoformat() for item in proof.policy_deadlines],
        "policy_acceptance_deadline": proof.policy_acceptance_deadline.isoformat(),
        "coverage_status": proof.coverage_status,
        "coverage_precision_basis": proof.coverage_precision_basis,
        "source_available_at": proof.source_available_at,
        "source_valid_until": proof.source_valid_until,
    }


def decode_disclosed_etf_report_clock_payload(
    value: object,
) -> PortfolioRiskDisclosedETFReportProof:
    """Reconstruct and revalidate the exact clock proof at a JSON trust boundary."""

    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise TypeError("ETF clock proof must be a string-keyed mapping")
    mapping = cast(Mapping[str, object], value)
    if set(mapping) != _PROOF_KEYS:
        raise ValueError("ETF clock proof fields do not match the exact schema")
    if mapping["scope"] != "simulation_only":
        raise ValueError("ETF clock proof scope is unsupported")
    if mapping["source_kind"] != "etf_report":
        raise ValueError("ETF clock proof source_kind is unsupported")
    if mapping["clock_evidence_mode"] != "policy_bounded_disclosed_report":
        raise ValueError("ETF clock proof clock_evidence_mode is unsupported")
    if mapping["age_basis"] != "report_period_end":
        raise ValueError("ETF clock proof age_basis is unsupported")
    if mapping["source_available_at"] is not None:
        raise ValueError("ETF proof must retain unknown supplier source_available_at")
    if mapping["source_valid_until"] is not None:
        raise ValueError("ETF proof must retain unknown supplier source_valid_until")
    return PortfolioRiskDisclosedETFReportProof(
        scope="simulation_only",
        source_kind="etf_report",
        clock_evidence_mode="policy_bounded_disclosed_report",
        profile_key=_text(mapping["profile_key"]),
        profile_version=_integer(mapping["profile_version"]),
        profile_content_hash=_text(mapping["profile_content_hash"]),
        policy_snapshot_id=_text(mapping["policy_snapshot_id"]),
        policy_snapshot_hash=_text(mapping["policy_snapshot_hash"]),
        policy_content_sha256=_text(mapping["policy_content_sha256"]),
        policy_known_at=_instant(mapping["policy_known_at"]),
        policy_effective_at=_instant(mapping["policy_effective_at"]),
        source_reference_hash=_text(mapping["source_reference_hash"]),
        account_id=_integer(mapping["account_id"]),
        asset_code=_text(mapping["asset_code"]),
        security_id=_text(mapping["security_id"]),
        source_id=_text(mapping["source_id"]),
        source_record_id=_text(mapping["source_record_id"]),
        capture_id=_text(mapping["capture_id"]),
        original_body_sha256=_text(mapping["original_body_sha256"]),
        source_original_url=_text(mapping["source_original_url"]),
        receipt_completed_at=_instant(mapping["receipt_completed_at"]),
        http_status=_integer(mapping["http_status"]),
        body_size_bytes=_integer(mapping["body_size_bytes"]),
        body_complete=_boolean(mapping["body_complete"]),
        report_period_end=_date(mapping["report_period_end"]),
        publication_source_id=_text(mapping["publication_source_id"]),
        publication_record_id=_text(mapping["publication_record_id"]),
        publication_capture_id=_text(mapping["publication_capture_id"]),
        publication_original_body_sha256=_text(mapping["publication_original_body_sha256"]),
        publication_original_url=_text(mapping["publication_original_url"]),
        publication_on=_date(mapping["publication_on"]),
        publication_receipt_completed_at=_instant(mapping["publication_receipt_completed_at"]),
        publication_http_status=_integer(mapping["publication_http_status"]),
        publication_body_size_bytes=_integer(mapping["publication_body_size_bytes"]),
        publication_body_complete=_boolean(mapping["publication_body_complete"]),
        as_of=_instant(mapping["as_of"]),
        business_date=_date(mapping["business_date"]),
        business_timezone_name=_text(mapping["business_timezone_name"]),
        known_at=_instant(mapping["known_at"]),
        proven_available_at=_instant(mapping["proven_available_at"]),
        age_basis="report_period_end",
        max_report_age_days=_integer(mapping["max_report_age_days"]),
        source_max_date_age_days=_integer(mapping["source_max_date_age_days"]),
        report_period_age_deadline=_instant(mapping["report_period_age_deadline"]),
        publication_age_deadline=_instant(mapping["publication_age_deadline"]),
        business_date_deadline=_instant(mapping["business_date_deadline"]),
        policy_deadlines=_instants(mapping["policy_deadlines"]),
        policy_acceptance_deadline=_instant(mapping["policy_acceptance_deadline"]),
        coverage_status=_coverage(mapping["coverage_status"]),
        coverage_precision_basis=_text(mapping["coverage_precision_basis"]),
        source_available_at=None,
        source_valid_until=None,
    )


def is_disclosed_etf_report_clock_payload(value: object, source: Mapping[str, object]) -> bool:
    """Bind a decoded report proof to its exact original source clocks and bytes."""

    try:
        proof = decode_disclosed_etf_report_clock_payload(value)
        return (
            source.get("source_id") == proof.source_id
            and source.get("source_record_id") == proof.source_record_id
            and source.get("raw_payload_sha256") == proof.original_body_sha256
            and _date(source.get("observed_on")) == proof.publication_on
            and source.get("observed_at") is None
            and source.get("observation_precision") == "date"
            and _instant(source.get("known_at")) == proof.known_at
            and _date(source.get("cutoff")) == proof.business_date
            and source.get("available_at") is None
            and source.get("valid_until") is None
            and source.get("must_not_use_for_decision") is False
            and source.get("coverage_basis") == proof.coverage_precision_basis
        )
    except (ArithmeticError, TypeError, ValueError):
        return False


def _text(value: object) -> str:
    if type(value) is not str:
        raise TypeError("ETF proof text must remain text")
    return value


def _integer(value: object) -> int:
    if type(value) is not int:
        raise TypeError("ETF proof count must be an exact integer")
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise TypeError("ETF proof flag must be an exact boolean")
    return value


def _date(value: object) -> date:
    text = _text(value)
    parsed = date.fromisoformat(text)
    if parsed.isoformat() != text:
        raise ValueError("ETF proof date must be canonical ISO date")
    return parsed


def _instant(value: object) -> datetime:
    parsed = datetime.fromisoformat(_text(value))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("ETF proof instant must retain its timezone")
    return parsed


def _instants(value: object) -> tuple[datetime, ...]:
    if type(value) is not list:
        raise TypeError("ETF policy deadlines must remain a JSON array")
    return tuple(_instant(item) for item in value)


def _coverage(value: object) -> Literal["complete", "partial"]:
    if type(value) is not str or value not in ("complete", "partial"):
        raise ValueError("ETF proof requires known complete or partial coverage")
    return cast(Literal["complete", "partial"], value)


__all__ = (
    "PortfolioRiskDisclosedETFReportClockProofPayload",
    "disclosed_etf_report_clock_payload",
    "decode_disclosed_etf_report_clock_payload",
    "is_disclosed_etf_report_clock_payload",
)
