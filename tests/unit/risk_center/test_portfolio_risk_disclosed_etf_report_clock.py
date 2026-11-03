"""Disclosure-clock contracts for ETF report and publication captures."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from zoneinfo import ZoneInfo

import pytest

from apps.config_center.application.runtime_value_evidence import ActiveRuntimeValueEvidence
from apps.risk_center.application.portfolio_risk_disclosed_etf_report_clock import (
    PortfolioRiskDisclosedETFReportClockQualification,
    PortfolioRiskETFReportPublicationCapture,
    qualify_policy_bounded_disclosed_etf_report,
)
from apps.risk_center.application.portfolio_risk_policy import (
    SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY,
    PortfolioRiskPolicyBundle,
    parse_portfolio_risk_policy_bundle,
)
from apps.risk_center.domain.portfolio_exposure_types import (
    ETFConstituent,
    ETFConstituentKind,
    ETFConstituentReport,
)
from apps.risk_center.domain.portfolio_risk_clock_evidence import PortfolioRiskCaptureReceipt
from apps.risk_center.domain.portfolio_risk_disclosed_etf_report_clock import (
    PortfolioRiskDisclosedETFReportProof,
)
from apps.risk_center.domain.portfolio_risk_sources import (
    CoverageStatus,
    PortfolioRiskCoverage,
    PortfolioRiskSourceEvidence,
    PortfolioRiskSourceQualification,
    SourceObservationPrecision,
    qualify_portfolio_risk_source,
)

_AS_OF = datetime(2026, 11, 4, 3, 0, tzinfo=UTC)
_BUSINESS_DATE = date(2026, 11, 4)
_BUSINESS_ZONE = ZoneInfo("Asia/Shanghai")
_REPORT_DATE = date(2026, 9, 30)
_PUBLICATION_DATE = date(2026, 10, 27)
_PDF_BODY = b"synthetic ETF report bytes for a clock contract test"
_PUBLICATION_BODY = b"synthetic official report notice bytes"
_PDF_HASH = sha256(_PDF_BODY).hexdigest()
_PUBLICATION_HASH = sha256(_PUBLICATION_BODY).hexdigest()
_MANIFEST_HASH = "sha256:" + "a" * 64
_SOURCE_ID = "china-amc"
_REPORT_RECORD_ID = "china-amc-510050-2026q3"
_PUBLICATION_SOURCE_ID = "china-amc-notice"
_PUBLICATION_RECORD_ID = "notice-1013352"
_ASSET_CODE = "510050.SH"
_SECURITY_ID = "etf:SH:510050"
_PURPOSE = "ash07_portfolio_exposure"


def _configuration(*, clock_mode: str = "policy_bounded_disclosed_report") -> dict[str, object]:
    """Build an explicit profile with a pinned ETF report and DATE allowlist."""

    return {
        "schema_version": "ash07.simulated_portfolio_risk.v1",
        "scope": "simulation_only",
        "ledger_money_unit": "CNY",
        "account_ids": [12],
        "industry": {
            "taxonomy_id": "cnindex-2019-standard",
            "taxonomy_kind": "industry",
            "provider_id": "cnindex",
            "provider_version": "2019-standard",
            "requested_purpose": _PURPOSE,
            "date_precision_purposes": [_PURPOSE],
            "allowed_observation_precisions": ["date", "timestamp"],
            "allowed_source_restrictions": ["close_snapshot_only"],
            "coverage_precision_basis": "portfolio_weight",
            "max_industry_weight": "0.35",
            "max_security_weight": "0.15",
            "minimum_industry_coverage": "0.90",
            "minimum_etf_lookthrough_coverage": "0.80",
            "coverage_weight_tolerance": "0.01",
        },
        "capacity": {
            "measure": "volume",
            "unit": "share",
            "basis": "session_total",
            "usage_scope": "account_security_session",
            "date_basis": "execution_session",
            "max_participation": "0.08",
            "increment": "100",
            "window_kind": "session_cumulative",
            "sessions": 1,
            "allowed_observation_precisions": ["timestamp"],
            "date_precision_purposes": [],
            "allowed_source_restrictions": [],
        },
        "source_max_timestamp_age_seconds": 1800,
        "source_max_date_age_days": 14,
        "source_references": [
            {
                "kind": "etf_report",
                "asset_code": _ASSET_CODE,
                "security_id": _SECURITY_ID,
                "raw_payload_hash": _MANIFEST_HASH,
                "source_record_id": _REPORT_RECORD_ID,
                "clock_evidence_mode": clock_mode,
            }
        ],
        "etf_report": {"age_basis": "report_period_end", "max_report_age_days": 60},
    }


def _policy(
    *,
    as_of: datetime = _AS_OF,
    max_report_age_days: int = 60,
    clock_mode: str = "policy_bounded_disclosed_report",
) -> PortfolioRiskPolicyBundle:
    """Parse one runtime-backed policy with the requested ETF report settings."""

    configuration = _configuration(clock_mode=clock_mode)
    etf_policy = configuration["etf_report"]
    assert isinstance(etf_policy, dict)
    etf_policy["max_report_age_days"] = max_report_age_days
    created_at = as_of - timedelta(minutes=10)
    effective_at = as_of - timedelta(minutes=5)
    runtime = ActiveRuntimeValueEvidence(
        environment="development",
        definition_key=SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY,
        value=configuration,
        profile_id="risk-profile-etf-test",
        profile_key="risk-center-etf-test",
        profile_version=4,
        profile_content_hash="e" * 64,
        snapshot_id="risk-snapshot-etf-test",
        snapshot_hash="f" * 64,
        created_at=created_at,
        known_at=created_at,
        activated_at=effective_at,
        snapshot_generated_at=as_of - timedelta(minutes=2),
        effective_at=effective_at,
        as_of=as_of,
    )
    return parse_portfolio_risk_policy_bundle(
        runtime,
        business_date=as_of.astimezone(_BUSINESS_ZONE).date(),
        as_of=as_of,
    )


def _receipt(
    *,
    source_id: str,
    source_record_id: str,
    capture_id: str,
    body: bytes,
    completed_at: datetime,
    http_status: int = 200,
    body_complete: bool = True,
) -> PortfolioRiskCaptureReceipt:
    """Bind one synthetic complete or invalid test response to its exact bytes."""

    return PortfolioRiskCaptureReceipt(
        capture_id=capture_id,
        source_id=source_id,
        source_record_id=source_record_id,
        original_body_sha256=sha256(body).hexdigest(),
        response_completed_at=completed_at,
        http_status=http_status,
        body_size_bytes=len(body),
        body_complete=body_complete,
    )


def _evidence(
    *,
    coverage_status: CoverageStatus = CoverageStatus.PARTIAL,
    observed_on: date = _PUBLICATION_DATE,
    known_at: datetime | None = datetime(2026, 10, 27, 12, 5, tzinfo=UTC),
    available_at: datetime | None = None,
    valid_until: datetime | None = None,
    decision_cutoff: datetime = _AS_OF,
    original_payload_sha256: str | None = _PDF_HASH,
) -> PortfolioRiskSourceEvidence:
    """Build source facts while keeping vendor availability and expiry unknown."""

    coverage = PortfolioRiskCoverage(
        status=coverage_status,
        precision_basis="portfolio_weight",
        reported_weight_fraction=(
            Decimal("0.4456")
            if coverage_status is CoverageStatus.PARTIAL
            else Decimal("1") if coverage_status is CoverageStatus.COMPLETE else None
        ),
        expected_item_count=(None if coverage_status is CoverageStatus.UNKNOWN else 100),
        observed_item_count=(
            44
            if coverage_status is CoverageStatus.PARTIAL
            else 100 if coverage_status is CoverageStatus.COMPLETE else None
        ),
    )
    return PortfolioRiskSourceEvidence(
        source_id=_SOURCE_ID,
        source_record_id=_REPORT_RECORD_ID,
        original_payload_sha256=original_payload_sha256,
        observation_precision=SourceObservationPrecision.DATE,
        observed_at=None,
        observed_on=observed_on,
        available_at=available_at,
        known_at=known_at,
        decision_cutoff=decision_cutoff,
        decision_date_cutoff=_BUSINESS_DATE,
        valid_until=valid_until,
        source_purpose="official_etf_report",
        allowed_purposes=(_PURPOSE,),
        restrictions=("close_snapshot_only",),
        must_not_use_for_decision=False,
        coverage=coverage,
        effective_on=_REPORT_DATE,
        effective_until=_REPORT_DATE,
    )


def _report(
    evidence: PortfolioRiskSourceEvidence,
    *,
    report_date: date = _REPORT_DATE,
) -> ETFConstituentReport:
    """Build a partial disclosed-weight report, never implying full NAV coverage."""

    row_count = 100 if evidence.coverage.status is CoverageStatus.COMPLETE else 44
    weights = [Decimal("0.01")] * row_count
    if evidence.coverage.status is CoverageStatus.PARTIAL:
        weights[-1] = Decimal("0.0156")
    return ETFConstituentReport(
        report_date=report_date,
        source_evidence=evidence,
        constituents=tuple(
            ETFConstituent(
                asset_code=f"600{index:03}.SH",
                weight_fraction=weight,
                kind=ETFConstituentKind.EQUITY,
                industry_membership=None,
            )
            for index, weight in enumerate(weights)
        ),
    )


def _publication_capture(
    *,
    publication_on: date = _PUBLICATION_DATE,
    receipt: PortfolioRiskCaptureReceipt | None = None,
    body: bytes = _PUBLICATION_BODY,
    original_url: str = "https://www.chinaamc.com.cn/c/2026-10-27/1013352.shtml",
) -> PortfolioRiskETFReportPublicationCapture:
    """Build the separately captured official publication-page evidence."""

    return PortfolioRiskETFReportPublicationCapture(
        publication_on=publication_on,
        original_body=body,
        original_url=original_url,
        receipt=(
            _receipt(
                source_id=_PUBLICATION_SOURCE_ID,
                source_record_id=_PUBLICATION_RECORD_ID,
                capture_id="publication-capture-1",
                body=body,
                completed_at=datetime(2026, 10, 27, 12, 5, tzinfo=UTC),
            )
            if receipt is None
            else receipt
        ),
    )


def _qualification(
    *,
    policy: PortfolioRiskPolicyBundle | None = None,
    evidence: PortfolioRiskSourceEvidence | None = None,
    report: ETFConstituentReport | None = None,
    report_body: bytes = _PDF_BODY,
    report_url: str = "https://www.chinaamc.com.cn/q3-report.pdf",
    report_receipt: PortfolioRiskCaptureReceipt | None = None,
    publication_capture: PortfolioRiskETFReportPublicationCapture | None = None,
    as_of: datetime = _AS_OF,
    business_date: date = _BUSINESS_DATE,
    policy_deadlines: tuple[datetime, ...] = (datetime(2026, 11, 4, 4, 0, tzinfo=UTC),),
) -> PortfolioRiskDisclosedETFReportClockQualification:
    """Run the disclosure clock qualifier using independent PDF and page captures."""

    selected_policy = _policy(as_of=as_of) if policy is None else policy
    selected_evidence = _evidence(decision_cutoff=as_of) if evidence is None else evidence
    selected_report = _report(selected_evidence) if report is None else report
    selected_receipt = (
        _receipt(
            source_id=_SOURCE_ID,
            source_record_id=_REPORT_RECORD_ID,
            capture_id="pdf-capture-1",
            body=report_body,
            completed_at=datetime(2026, 10, 27, 12, 0, tzinfo=UTC),
        )
        if report_receipt is None
        else report_receipt
    )
    selected_publication = (
        _publication_capture() if publication_capture is None else publication_capture
    )
    return qualify_policy_bounded_disclosed_etf_report(
        policy=selected_policy,
        source_reference=selected_policy.source_references[0],
        retained_payload_hash=_MANIFEST_HASH,
        account_id=12,
        asset_code=_ASSET_CODE,
        security_id=_SECURITY_ID,
        source_evidence=selected_evidence,
        report=selected_report,
        report_original_body=report_body,
        report_original_url=report_url,
        report_receipt=selected_receipt,
        publication_capture=selected_publication,
        as_of=as_of,
        business_date=business_date,
        business_timezone_name="Asia/Shanghai",
        policy_deadlines=policy_deadlines,
    )


def _qualify_source_evidence(
    evidence: PortfolioRiskSourceEvidence,
    *,
    expected_source_kind: str | None = "etf_report",
) -> PortfolioRiskSourceQualification:
    """Apply the ordinary source gate to one explicitly bounded report purpose."""

    return qualify_portfolio_risk_source(
        evidence=evidence,
        requested_purpose=_PURPOSE,
        allowed_observation_precisions=(SourceObservationPrecision.DATE,),
        as_of=_AS_OF,
        allowed_restrictions=("close_snapshot_only",),
        expected_source_kind=expected_source_kind,
    )


def test_partial_report_can_carry_clock_proof_without_filling_source_clocks() -> None:
    """A correctly dated partial disclosure has a proof but remains explicitly partial."""

    result = _qualification()

    assert result.proof is not None
    assert result.reason_codes == ()
    proof = result.proof
    assert proof.coverage_status == "partial"
    assert proof.report_period_end == _REPORT_DATE
    assert proof.publication_on == _PUBLICATION_DATE
    assert proof.proven_available_at == datetime(2026, 10, 27, 12, 5, tzinfo=UTC)
    assert proof.known_at == proof.proven_available_at
    assert proof.source_available_at is None
    assert proof.source_valid_until is None
    assert proof.source_reference_hash == _MANIFEST_HASH
    assert proof.original_body_sha256 == _PDF_HASH
    assert proof.publication_original_body_sha256 == _PUBLICATION_HASH
    assert proof.source_original_url.endswith("q3-report.pdf")
    assert proof.publication_original_url.endswith("1013352.shtml")
    assert proof.publication_record_id != proof.source_record_id
    assert proof.policy_acceptance_deadline == datetime(2026, 11, 4, 4, 0, tzinfo=UTC)


def test_report_period_publication_and_policy_deadlines_each_bound_the_proof() -> None:
    """The earliest report-age, publication-age, local-day, and policy end wins."""

    report_age_limited = _qualification(
        policy=_policy(max_report_age_days=35),
        policy_deadlines=(datetime(2026, 11, 4, 8, 0, tzinfo=UTC),),
    )
    assert report_age_limited.proof is not None
    assert report_age_limited.proof.report_period_age_deadline == datetime(
        2026, 11, 4, 16, 0, tzinfo=UTC
    )
    assert report_age_limited.proof.policy_acceptance_deadline == datetime(
        2026, 11, 4, 8, 0, tzinfo=UTC
    )

    policy_limited = _qualification(
        policy_deadlines=(datetime(2026, 11, 4, 3, 30, tzinfo=UTC),),
    )
    assert policy_limited.proof is not None
    assert policy_limited.proof.policy_acceptance_deadline == datetime(
        2026, 11, 4, 3, 30, tzinfo=UTC
    )

    exactly_expired = _qualification(
        policy_deadlines=(_AS_OF,),
    )
    assert exactly_expired.proof is None
    assert "PORTFOLIO_RISK_ETF_REPORT_EXPIRED_AT_CUTOFF" in exactly_expired.reason_codes


@pytest.mark.parametrize(
    ("coverage", "reason"),
    (
        (CoverageStatus.UNKNOWN, "PORTFOLIO_RISK_ETF_REPORT_COVERAGE_UNKNOWN"),
        (CoverageStatus.COMPLETE, None),
        (CoverageStatus.PARTIAL, None),
    ),
)
def test_only_known_complete_or_partial_coverage_can_have_clock_proof(
    coverage: CoverageStatus,
    reason: str | None,
) -> None:
    evidence = _evidence(coverage_status=coverage)
    result = _qualification(evidence=evidence)

    if reason is None:
        assert result.proof is not None
        assert result.proof.coverage_status == coverage.value
    else:
        assert result.proof is None
        assert reason in result.reason_codes


def test_untrusted_body_or_receipt_mismatch_never_yields_a_proof() -> None:
    """Manifest-bound source bytes and both full-response receipts are mandatory."""

    tampered_body = _PDF_BODY + b" altered"
    body_mismatch = _qualification(report_body=tampered_body)
    assert body_mismatch.proof is None
    assert "PORTFOLIO_RISK_ETF_REPORT_BODY_HASH_MISMATCH" in body_mismatch.reason_codes

    failed_receipt = _receipt(
        source_id=_SOURCE_ID,
        source_record_id=_REPORT_RECORD_ID,
        capture_id="pdf-capture-failed",
        body=_PDF_BODY,
        completed_at=datetime(2026, 10, 27, 12, 0, tzinfo=UTC),
        body_complete=False,
    )
    failed_pdf = _qualification(report_receipt=failed_receipt)
    assert failed_pdf.proof is None
    assert "PORTFOLIO_RISK_ETF_REPORT_CAPTURE_INCOMPLETE" in failed_pdf.reason_codes

    with pytest.raises(ValueError, match="publication receipt hash"):
        _publication_capture(
            receipt=_receipt(
                source_id=_PUBLICATION_SOURCE_ID,
                source_record_id=_PUBLICATION_RECORD_ID,
                capture_id="tampered-page",
                body=b"different bytes",
                completed_at=datetime(2026, 10, 27, 12, 5, tzinfo=UTC),
            )
        )


def test_future_or_mismatched_dates_and_unknown_origin_clocks_fail_closed() -> None:
    """Publication date, report period, known_at, and source clocks retain their own meanings."""

    publication_mismatch = _qualification(
        publication_capture=_publication_capture(publication_on=date(2026, 10, 28)),
    )
    assert publication_mismatch.proof is None
    assert "PORTFOLIO_RISK_ETF_REPORT_PUBLICATION_DATE_MISMATCH" in (
        publication_mismatch.reason_codes
    )

    future_period = date(2026, 10, 28)
    report_after_notice_evidence = replace(
        _evidence(),
        effective_on=future_period,
        effective_until=future_period,
    )
    report_after_notice = _report(
        report_after_notice_evidence,
        report_date=future_period,
    )
    later_report = _qualification(
        evidence=report_after_notice_evidence,
        report=report_after_notice,
    )
    assert later_report.proof is None
    assert "PORTFOLIO_RISK_ETF_REPORT_PERIOD_AFTER_PUBLICATION" in later_report.reason_codes

    no_effective_report_date = _qualification(
        evidence=replace(_evidence(), effective_on=None),
    )
    assert no_effective_report_date.proof is None
    assert "PORTFOLIO_RISK_ETF_REPORT_PERIOD_END_MISMATCH" in (
        no_effective_report_date.reason_codes
    )

    no_known_clock = _qualification(evidence=_evidence(known_at=None))
    assert no_known_clock.proof is None
    assert "PORTFOLIO_RISK_ETF_REPORT_KNOWN_AT_UNKNOWN" in no_known_clock.reason_codes

    invented_expiry = _qualification(
        evidence=_evidence(valid_until=_AS_OF + timedelta(hours=2)),
    )
    assert invented_expiry.proof is None
    assert "PORTFOLIO_RISK_ETF_REPORT_SOURCE_CLOCKS_MUST_REMAIN_UNKNOWN" in (
        invented_expiry.reason_codes
    )

    known_before_both_captures = _qualification(
        evidence=_evidence(known_at=datetime(2026, 10, 27, 12, 4, tzinfo=UTC)),
    )
    assert known_before_both_captures.proof is None
    assert "PORTFOLIO_RISK_ETF_REPORT_KNOWN_BEFORE_CAPTURE" in (
        known_before_both_captures.reason_codes
    )


def test_clock_proof_does_not_override_source_prohibition_or_purpose() -> None:
    """A bounded disclosure mode cannot white-list a source prohibited by its own record."""

    prohibited = _qualification(
        evidence=replace(_evidence(), must_not_use_for_decision=True),
    )
    assert prohibited.proof is None
    assert "RISK_SOURCE_PROHIBITED_FOR_DECISION" in prohibited.reason_codes

    purpose_not_allowed = _qualification(
        evidence=replace(_evidence(), allowed_purposes=("research_only",)),
    )
    assert purpose_not_allowed.proof is None
    assert "RISK_SOURCE_PURPOSE_NOT_ALLOWED" in purpose_not_allowed.reason_codes


def test_domain_proof_recomputes_offsets_hashes_dates_and_deadline() -> None:
    """Proof cannot be mutated to a different source hash, date, timezone, or bound."""

    proof = _qualification().proof
    assert proof is not None
    assert isinstance(proof, PortfolioRiskDisclosedETFReportProof)
    assert proof.receipt_completed_at.utcoffset() == timedelta(0)

    with pytest.raises(ValueError, match="lowercase SHA-256"):
        replace(proof, original_body_sha256="A" * 64)
    with pytest.raises(ValueError, match="source-origin availability and expiry"):
        replace(proof, source_valid_until=proof.policy_acceptance_deadline)
    with pytest.raises(ValueError, match="exact earliest bound"):
        replace(proof, policy_acceptance_deadline=proof.report_period_age_deadline)
    with pytest.raises(ValueError, match="business_date does not match"):
        replace(proof, business_date=date(2026, 11, 5))
    with pytest.raises(ValueError, match="credential-free HTTPS"):
        replace(proof, source_original_url="https://user@example.com/report.pdf")


def test_domain_proof_rejects_mutations_across_identity_clock_and_capture_groups() -> None:
    """A changed identity, source clock, publication receipt, or bound invalidates proof."""

    proof = _qualification().proof
    assert proof is not None
    invalid_cases: tuple[tuple[dict[str, object], str], ...] = (
        ({"scope": "live"}, "unsupported scope or mode"),
        ({"source_kind": "valuation"}, "unsupported scope or mode"),
        ({"clock_evidence_mode": "source_clocks_required"}, "unsupported scope or mode"),
        ({"age_basis": "publication_on"}, "age basis must be report_period_end"),
        ({"coverage_status": "unknown"}, "known complete or partial coverage"),
        ({"source_reference_hash": "not-a-manifest-hash"}, "prefixed SHA-256"),
        ({"capture_id": "capture id with spaces"}, "canonical token"),
        ({"account_id": True}, "positive exact integer"),
        ({"profile_version": 0}, "positive exact integer"),
        ({"report_period_end": datetime(2026, 9, 30, tzinfo=UTC)}, "exact dates"),
        (
            {"business_date": datetime(2026, 11, 4, tzinfo=UTC)},
            "business_date must be an exact date",
        ),
        (
            {"report_period_end": _PUBLICATION_DATE + timedelta(days=1)},
            "cannot end after its publication",
        ),
        (
            {"publication_on": _BUSINESS_DATE + timedelta(days=1)},
            "cannot be after the business date",
        ),
        ({"max_report_age_days": True}, "nonnegative exact integer"),
        ({"source_max_date_age_days": -1}, "nonnegative exact integer"),
        (
            {"policy_known_at": datetime(2026, 10, 27, 12, 0)},
            "must be timezone-aware",
        ),
        (
            {"policy_deadlines": (datetime(2026, 11, 4, 3, 0),)},
            "policy_deadlines must contain aware instants",
        ),
        ({"body_complete": False}, "complete nonempty body"),
        ({"body_size_bytes": 0}, "complete nonempty body"),
        ({"publication_http_status": 302}, "exact successful HTTP status"),
        ({"publication_body_size_bytes": 0}, "complete nonempty body"),
        (
            {"known_at": _AS_OF + timedelta(seconds=1)},
            "receipts, known_at and decision cutoff are inconsistent",
        ),
        (
            {"policy_effective_at": _AS_OF + timedelta(seconds=1)},
            "policy must be known and effective",
        ),
        (
            {"business_timezone_name": "Not/A_Timezone"},
            "dates or timezone cannot form valid deadlines",
        ),
        (
            {"report_period_age_deadline": proof.report_period_age_deadline + timedelta(seconds=1)},
            "report period deadline does not match",
        ),
        (
            {"publication_age_deadline": proof.publication_age_deadline + timedelta(seconds=1)},
            "publication deadline does not match",
        ),
        (
            {"business_date_deadline": proof.business_date_deadline + timedelta(seconds=1)},
            "business date deadline must be the next local midnight",
        ),
        (
            {"policy_deadlines": (_AS_OF,), "policy_acceptance_deadline": _AS_OF},
            "already expired",
        ),
        (
            {"source_original_url": "https://reports.example/report with space.pdf"},
            "canonical token",
        ),
        (
            {"publication_original_url": "file:///report.html"},
            "credential-free HTTPS without fragment",
        ),
        (
            {"source_available_at": _AS_OF},
            "source-origin availability and expiry must remain unknown",
        ),
    )

    failures: list[str] = []
    for changes, message in invalid_cases:
        try:
            replace(proof, **changes)
        except (TypeError, ValueError) as exc:
            if message not in str(exc):
                failures.append(f"{changes!r}: expected {message!r}, received {str(exc)!r}")
        else:
            failures.append(f"{changes!r}: expected rejection containing {message!r}")
    assert failures == [], "\n".join(failures)


def test_report_clock_proof_is_rebound_to_the_exact_retained_source_record() -> None:
    """The proof only substitutes for unknown origin clocks on the exact retained ETF source."""

    proof = _qualification().proof
    assert proof is not None
    source = replace(_evidence(), policy_clock_proof=proof)
    assert _qualify_source_evidence(source).eligible
    source_known_at = source.known_at
    assert source_known_at is not None

    changed_period = replace(
        source,
        effective_on=_PUBLICATION_DATE,
        effective_until=_PUBLICATION_DATE,
    )
    changed_coverage = replace(
        source,
        coverage=PortfolioRiskCoverage(
            status=CoverageStatus.PARTIAL,
            precision_basis="source_row_count",
            reported_weight_fraction=Decimal("0.4456"),
        ),
    )
    mismatched_records = (
        replace(source, source_id="another-provider"),
        replace(source, source_record_id="another-record"),
        replace(source, original_payload_sha256=sha256(b"other ETF bytes").hexdigest()),
        replace(source, observed_on=date(2026, 10, 28)),
        replace(source, decision_date_cutoff=date(2026, 11, 5)),
        changed_period,
        replace(source, known_at=source_known_at + timedelta(seconds=1)),
        changed_coverage,
        replace(
            source,
            coverage=PortfolioRiskCoverage(
                status=CoverageStatus.UNKNOWN,
                precision_basis="portfolio_weight",
            ),
        ),
        replace(source, available_at=source_known_at),
        replace(source, valid_until=_AS_OF + timedelta(hours=1)),
    )
    for mismatched_source in mismatched_records:
        assert not _qualify_source_evidence(mismatched_source).eligible

    wrong_kind = _qualify_source_evidence(
        source,
        expected_source_kind="industry_membership",
    )
    assert not wrong_kind.eligible


@pytest.mark.parametrize(
    "url",
    (
        "http://example.com/report.pdf",
        "https://user@example.com/report.pdf",
        "https://example.com/report.pdf#part",
        "https://example.com/report with-space.pdf",
    ),
)
def test_report_url_must_be_https_without_credentials_fragment_or_whitespace(url: str) -> None:
    result = _qualification(report_url=url)

    assert result.proof is None
    assert "PORTFOLIO_RISK_ETF_REPORT_URL_INVALID" in result.reason_codes


def test_wrong_kind_mode_identity_and_invalid_urls_are_rejected() -> None:
    """A policy mode remains limited to the exact ETF pin and captured report URL."""

    wrong_mode_policy = _policy(clock_mode="source_clocks_required")
    result = _qualification(policy=wrong_mode_policy)
    assert result.proof is None
    assert "PORTFOLIO_RISK_ETF_REPORT_REFERENCE_MISMATCH" in result.reason_codes

    wrong_identity = qualify_policy_bounded_disclosed_etf_report(
        policy=_policy(),
        source_reference=_policy().source_references[0],
        retained_payload_hash=_MANIFEST_HASH,
        account_id=12,
        asset_code="510300.SH",
        security_id=_SECURITY_ID,
        source_evidence=_evidence(),
        report=_report(_evidence()),
        report_original_body=_PDF_BODY,
        report_original_url="not-a-url",
        report_receipt=_receipt(
            source_id=_SOURCE_ID,
            source_record_id=_REPORT_RECORD_ID,
            capture_id="pdf-capture-1",
            body=_PDF_BODY,
            completed_at=datetime(2026, 10, 27, 12, 0, tzinfo=UTC),
        ),
        publication_capture=_publication_capture(),
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE,
        business_timezone_name="Asia/Shanghai",
        policy_deadlines=(),
    )
    assert wrong_identity.proof is None
    assert "PORTFOLIO_RISK_ETF_REPORT_REFERENCE_MISMATCH" in wrong_identity.reason_codes
    assert "PORTFOLIO_RISK_ETF_REPORT_URL_INVALID" in wrong_identity.reason_codes


@pytest.mark.parametrize(
    "url",
    (
        "http://example.com/report.html",
        "https://user@example.com/report.html",
        "https://example.com/report.html#section",
        "https://example.com/report with-space.html",
    ),
)
def test_publication_url_must_be_https_without_credentials_fragment_or_whitespace(url: str) -> None:
    """Captured public URLs reject cleartext, userinfo, fragments, and whitespace."""

    with pytest.raises(ValueError):
        _publication_capture(original_url=url)


def test_qualifier_requires_exact_policy_cutoffs_and_revalidates_typed_inputs() -> None:
    """Typed values re-run their own invariants before the report clock is qualified."""

    earlier_policy = _policy(as_of=_AS_OF - timedelta(seconds=1))
    policy_cutoff_mismatch = _qualification(policy=earlier_policy)
    assert policy_cutoff_mismatch.proof is None
    assert "PORTFOLIO_RISK_ETF_REPORT_POLICY_CUTOFF_MISMATCH" in (
        policy_cutoff_mismatch.reason_codes
    )

    policy_business_date_mismatch = _qualification(business_date=date(2026, 11, 5))
    assert policy_business_date_mismatch.proof is None
    assert "PORTFOLIO_RISK_ETF_REPORT_POLICY_BUSINESS_DATE_MISMATCH" in (
        policy_business_date_mismatch.reason_codes
    )

    tampered_evidence = _evidence()
    object.__setattr__(tampered_evidence, "source_id", "")
    invalid_evidence = _qualification(evidence=tampered_evidence)
    assert invalid_evidence.proof is None
    assert invalid_evidence.reason_codes == ("PORTFOLIO_RISK_ETF_REPORT_INPUT_CONTRACT_INVALID",)

    tampered_publication = _publication_capture()
    object.__setattr__(tampered_publication.receipt, "original_body_sha256", "x" * 64)
    invalid_publication = _qualification(publication_capture=tampered_publication)
    assert invalid_publication.proof is None
    assert invalid_publication.reason_codes == ("PORTFOLIO_RISK_ETF_REPORT_INPUT_CONTRACT_INVALID",)

    tampered_pdf_receipt = _receipt(
        source_id=_SOURCE_ID,
        source_record_id=_REPORT_RECORD_ID,
        capture_id="pdf-capture-tampered",
        body=_PDF_BODY,
        completed_at=datetime(2026, 10, 27, 12, 0, tzinfo=UTC),
    )
    object.__setattr__(tampered_pdf_receipt, "http_status", 700)
    invalid_pdf_receipt = _qualification(report_receipt=tampered_pdf_receipt)
    assert invalid_pdf_receipt.proof is None
    assert invalid_pdf_receipt.reason_codes == ("PORTFOLIO_RISK_ETF_REPORT_INPUT_CONTRACT_INVALID",)
