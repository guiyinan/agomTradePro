"""Reader integration for the explicit ETF disclosure-clock mode."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from typing import Literal

import pytest

from apps.config_center.application.runtime_value_evidence import ActiveRuntimeValueEvidence
from apps.data_center.application import raw_landing_public
from apps.data_center.domain.raw_landing import RawPayload
from apps.risk_center.application.portfolio_risk_assets import (
    PortfolioRiskAssetIdentity,
    PortfolioRiskAssetsReadRequest,
)
from apps.risk_center.application.portfolio_risk_disclosed_etf_report_clock import (
    PortfolioRiskETFReportPublicationCapture,
)
from apps.risk_center.application.portfolio_risk_policy import (
    SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY,
    PortfolioRiskPolicyBundle,
    parse_portfolio_risk_policy_bundle,
)
from apps.risk_center.application.portfolio_risk_source_admission import (
    PortfolioRiskSourceAdmissionRequest,
    parse_portfolio_risk_source_admission_request,
)
from apps.risk_center.domain.portfolio_risk_clock_evidence import PortfolioRiskCaptureReceipt
from apps.risk_center.domain.portfolio_risk_disclosed_etf_report_clock import (
    PortfolioRiskDisclosedETFReportProof,
)
from apps.risk_center.infrastructure.portfolio_risk_source_admission_codec import (
    RetainedPortfolioRiskAdmissionManifestCodec,
    _schema_fingerprint,
)
from apps.risk_center.infrastructure.retained_portfolio_risk_assets_reader import (
    RetainedPortfolioRiskAssetsReader,
)

_AS_OF = datetime(2026, 11, 3, 8, 0, tzinfo=UTC)
_BUSINESS_DATE = date(2026, 11, 3)
_REPORT_DATE = date(2026, 9, 30)
_PUBLICATION_DATE = date(2026, 10, 27)
_ASSET_CODE = "510050.SH"
_SECURITY_ID = "etf:SH:510050"
_REPORT_RECORD_ID = "etf-report-q3"
_REPORT_URL = "https://source.example.test/reports/510050-q3.pdf"
_PUBLICATION_URL = "https://source.example.test/reports/510050-q3.html"
_REPORT_BODY = b"%PDF-1.7 retained ETF report"
_PUBLICATION_BODY = (
    b'<div class="p">\xe6\x97\xb6\xe9\x97\xb4\xef\xbc\x9a2026-10-27</div>'
    b'<a href="/reports/510050-q3.pdf">Download</a>'
)


def _receipt(
    *,
    capture_id: str,
    source_record_id: str,
    body: bytes,
    completed_at: datetime,
    source_id: str = "official_etf_publisher",
) -> PortfolioRiskCaptureReceipt:
    """Build an exact local capture receipt for an original response body."""

    return PortfolioRiskCaptureReceipt(
        capture_id=capture_id,
        source_id=source_id,
        source_record_id=source_record_id,
        original_body_sha256=hashlib.sha256(body).hexdigest(),
        response_completed_at=completed_at,
        http_status=200,
        body_size_bytes=len(body),
        body_complete=True,
    )


def _admitted_report(
    *,
    coverage_status: Literal["complete", "partial"] = "complete",
    publication_completed_after_pdf: timedelta = -timedelta(seconds=1),
) -> RawPayload:
    """Build one v2 candidate carrying separate, receipt-bound PDF and page captures."""

    pdf_completed_at = datetime(2026, 11, 3, 1, 44, 23, tzinfo=UTC)
    page_capture = PortfolioRiskETFReportPublicationCapture(
        publication_on=_PUBLICATION_DATE,
        original_body=_PUBLICATION_BODY,
        original_url=_PUBLICATION_URL,
        receipt=_receipt(
            capture_id="etf-release-page-q3",
            source_record_id="etf-release-page-record-q3",
            body=_PUBLICATION_BODY,
            completed_at=pdf_completed_at + publication_completed_after_pdf,
            source_id="official_etf_release_page",
        ),
    )
    document: dict[str, object] = {
        "schema_version": "ash07.source_admission_request.v1",
        "kind": "etf_report",
        "asset_code": _ASSET_CODE,
        "security_id": _SECURITY_ID,
        "source_record_id": _REPORT_RECORD_ID,
        "original_url": _REPORT_URL,
        "captured_at": pdf_completed_at.isoformat(),
        "source_evidence": {
            "source_id": "official_etf_publisher",
            "source_record_id": _REPORT_RECORD_ID,
            "original_payload_sha256": hashlib.sha256(_REPORT_BODY).hexdigest(),
            "observation_precision": "date",
            "observed_at": None,
            "observed_on": _PUBLICATION_DATE.isoformat(),
            "available_at": None,
            "known_at": (pdf_completed_at + timedelta(seconds=1)).isoformat(),
            "valid_until": None,
            "source_purpose": "ash07_portfolio_exposure",
            "allowed_purposes": ["ash07_portfolio_exposure"],
            "restrictions": [],
            "must_not_use_for_decision": False,
            "coverage": {
                "status": coverage_status,
                "precision_basis": "portfolio_weight",
                "reported_weight_fraction": "1" if coverage_status == "complete" else "0.75",
                "expected_item_count": None,
                "observed_item_count": None,
            },
            "effective_on": _REPORT_DATE.isoformat(),
            "effective_until": None,
        },
        "facts": {
            "report_date": _REPORT_DATE.isoformat(),
            "constituents": [
                {
                    "asset_code": "cash:cn",
                    "weight_fraction": "1" if coverage_status == "complete" else "0.75",
                    "kind": "cash",
                }
            ],
        },
    }
    request: PortfolioRiskSourceAdmissionRequest = parse_portfolio_risk_source_admission_request(
        document,
        original_body=_REPORT_BODY,
        capture_receipt=_receipt(
            capture_id="etf-report-pdf-q3",
            source_record_id=_REPORT_RECORD_ID,
            body=_REPORT_BODY,
            completed_at=pdf_completed_at,
        ),
        etf_publication_capture=page_capture,
    )
    return RetainedPortfolioRiskAdmissionManifestCodec().build_payload(request)


def _policy_configuration(report: RawPayload) -> dict[str, object]:
    """Pin the exact report manifest under a simulation-only disclosure policy."""

    return {
        "schema_version": "ash07.simulated_portfolio_risk.v1",
        "scope": "simulation_only",
        "ledger_money_unit": "CNY",
        "account_ids": [12],
        "industry": {
            "taxonomy_id": "sw-2021",
            "taxonomy_kind": "industry",
            "provider_id": "provider-a",
            "provider_version": "v2026.10",
            "requested_purpose": "ash07_portfolio_exposure",
            "date_precision_purposes": ["ash07_portfolio_exposure"],
            "allowed_observation_precisions": ["timestamp", "date"],
            "allowed_source_restrictions": [],
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
            "basis": "average_per_session",
            "usage_scope": "account_security_session",
            "date_basis": "execution_session",
            "max_participation": "0.08",
            "increment": "100",
            "window_kind": "rolling_sessions",
            "sessions": 5,
            "allowed_observation_precisions": ["timestamp", "date"],
            "date_precision_purposes": ["ash07_capacity"],
            "allowed_source_restrictions": [],
        },
        "source_max_timestamp_age_seconds": 1800,
        "source_max_date_age_days": 45,
        "etf_report": {
            "age_basis": "report_period_end",
            "max_report_age_days": 45,
        },
        "source_references": [
            {
                "kind": "etf_report",
                "asset_code": _ASSET_CODE,
                "security_id": _SECURITY_ID,
                "raw_payload_hash": report.payload_hash,
                "source_record_id": _REPORT_RECORD_ID,
                "clock_evidence_mode": "policy_bounded_disclosed_report",
            }
        ],
    }


def _runtime_evidence(value: dict[str, object]) -> ActiveRuntimeValueEvidence:
    """Bind one local active value to a stable typed ConfigCenter runtime envelope."""

    return ActiveRuntimeValueEvidence(
        environment="development",
        definition_key=SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY,
        value=value,
        profile_id="runtime-profile-12",
        profile_key="risk-center-development",
        profile_version=12,
        profile_content_hash="e" * 64,
        snapshot_id="runtime-snapshot-12",
        snapshot_hash="f" * 64,
        created_at=_AS_OF - timedelta(minutes=5),
        known_at=_AS_OF - timedelta(minutes=5),
        activated_at=_AS_OF - timedelta(minutes=3),
        snapshot_generated_at=_AS_OF - timedelta(minutes=2),
        effective_at=_AS_OF - timedelta(minutes=3),
        as_of=_AS_OF,
    )


def _policy(report: RawPayload) -> PortfolioRiskPolicyBundle:
    """Build the policy that pins the retained report for the same account and cutoff."""

    return parse_portfolio_risk_policy_bundle(
        _runtime_evidence(_policy_configuration(report)),
        business_date=_BUSINESS_DATE,
        as_of=_AS_OF,
    )


def test_reader_attaches_the_disclosure_proof_from_both_captured_responses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pinned ETF report is admitted only after the page and PDF both qualify."""

    report = _admitted_report()
    policy = _policy(report)
    monkeypatch.setattr(
        raw_landing_public,
        "get_retained_raw_payload",
        lambda *, payload_hash: report if payload_hash == report.payload_hash else None,
    )
    request = PortfolioRiskAssetsReadRequest(
        policy=policy,
        requested_assets=(PortfolioRiskAssetIdentity(_ASSET_CODE, _SECURITY_ID),),
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE,
        execution_session=_BUSINESS_DATE,
        capacity_requested_purpose="ash07_capacity",
        account_id=12,
        business_timezone=UTC,
        business_timezone_name="UTC",
    )

    result = RetainedPortfolioRiskAssetsReader().read_assets(request)

    assert result.status == "partial"
    report_evidence = next(
        item for item in result.all_source_evidence if item.source_record_id == _REPORT_RECORD_ID
    )
    proof = report_evidence.policy_clock_proof
    assert type(proof) is PortfolioRiskDisclosedETFReportProof
    assert proof.report_period_end == _REPORT_DATE
    assert proof.publication_on == _PUBLICATION_DATE
    assert proof.publication_source_id == "official_etf_release_page"
    assert proof.publication_record_id == "etf-release-page-record-q3"
    assert proof.source_available_at is None
    assert proof.source_valid_until is None
    assert report_evidence.available_at is None
    assert report_evidence.valid_until is None
    assert "RISK_INPUT_VALUATION_REFERENCE_MISSING" in result.reason_codes


def test_disclosure_proof_does_not_lift_the_partial_coverage_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disclosure timing can qualify a partial report without making it complete."""

    report = _admitted_report(coverage_status="partial")
    policy = _policy(report)
    monkeypatch.setattr(
        raw_landing_public,
        "get_retained_raw_payload",
        lambda *, payload_hash: report if payload_hash == report.payload_hash else None,
    )
    request = PortfolioRiskAssetsReadRequest(
        policy=policy,
        requested_assets=(PortfolioRiskAssetIdentity(_ASSET_CODE, _SECURITY_ID),),
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE,
        execution_session=_BUSINESS_DATE,
        capacity_requested_purpose="ash07_capacity",
        account_id=12,
        business_timezone=UTC,
        business_timezone_name="UTC",
    )

    result = RetainedPortfolioRiskAssetsReader().read_assets(request)

    report_evidence = next(
        item for item in result.all_source_evidence if item.source_record_id == _REPORT_RECORD_ID
    )
    assert result.status == "partial"
    assert "RISK_INPUT_SOURCE_COVERAGE_PARTIAL" in result.reason_codes
    assert type(report_evidence.policy_clock_proof) is PortfolioRiskDisclosedETFReportProof
    assert report_evidence.policy_clock_proof.coverage_status == "partial"


def test_reader_blocks_if_known_at_precedes_the_publication_page_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The source knowledge clock cannot be earlier than either local capture."""

    report = _admitted_report(publication_completed_after_pdf=timedelta(seconds=5))
    policy = _policy(report)
    monkeypatch.setattr(
        raw_landing_public,
        "get_retained_raw_payload",
        lambda *, payload_hash: report if payload_hash == report.payload_hash else None,
    )
    request = PortfolioRiskAssetsReadRequest(
        policy=policy,
        requested_assets=(PortfolioRiskAssetIdentity(_ASSET_CODE, _SECURITY_ID),),
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE,
        execution_session=_BUSINESS_DATE,
        capacity_requested_purpose="ash07_capacity",
        account_id=12,
        business_timezone=UTC,
        business_timezone_name="UTC",
    )

    result = RetainedPortfolioRiskAssetsReader().read_assets(request)

    report_evidence = next(
        item for item in result.all_source_evidence if item.source_record_id == _REPORT_RECORD_ID
    )
    assert result.status == "blocked"
    assert "PORTFOLIO_RISK_ETF_REPORT_KNOWN_BEFORE_CAPTURE" in result.reason_codes
    assert report_evidence.policy_clock_proof is None


def test_disclosure_mode_does_not_fall_back_when_page_capture_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Removing the optional v2 page capture leaves the disclosed-report mode blocked."""

    report = _admitted_report()
    payload = dict(report.payload)
    payload.pop("etf_publication_capture")
    raw_payload = dict(payload)
    manifest_hash = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                raw_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
    )
    missing_page = RawPayload(
        payload_id="missing-page-report",
        dataset_key=report.dataset_key,
        provider_name=report.provider_name,
        payload_hash=manifest_hash,
        schema_fingerprint=_schema_fingerprint(
            "ash07.retained_risk_input.v2",
            frozenset(raw_payload),
        ),
        payload=raw_payload,
        fetched_at=report.fetched_at,
        request_params={},
        content_type="application/json",
        parser_version=report.parser_version,
        redacted=True,
        payload_size_bytes=report.payload_size_bytes,
    )
    config = _policy_configuration(missing_page)
    monkeypatch.setattr(
        raw_landing_public,
        "get_retained_raw_payload",
        lambda *, payload_hash: missing_page if payload_hash == missing_page.payload_hash else None,
    )
    request = PortfolioRiskAssetsReadRequest(
        policy=parse_portfolio_risk_policy_bundle(
            _runtime_evidence(config),
            business_date=_BUSINESS_DATE,
            as_of=_AS_OF,
        ),
        requested_assets=(PortfolioRiskAssetIdentity(_ASSET_CODE, _SECURITY_ID),),
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE,
        execution_session=_BUSINESS_DATE,
        capacity_requested_purpose="ash07_capacity",
        account_id=12,
        business_timezone=UTC,
        business_timezone_name="UTC",
    )

    result = RetainedPortfolioRiskAssetsReader().read_assets(request)

    assert result.status == "blocked"
    assert "RISK_INPUT_ETF_PUBLICATION_CAPTURE_REQUIRED" in result.reason_codes
    assert all(item.policy_clock_proof is None for item in result.all_source_evidence)
