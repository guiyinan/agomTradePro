"""Historical DTO contract checks for the retained ETF report helper.

This opt-in test consumes retained report bytes and the real 2026-11-03 bank
membership admission requests. It checks DTO construction only; it deliberately
does not run current-source qualification or read any profile/database state.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

from apps.risk_center.application.portfolio_risk_source_admission import (
    PortfolioRiskSourceAdmissionError,
    PortfolioRiskSourceAdmissionRequest,
    parse_portfolio_risk_source_admission_request,
)
from apps.risk_center.domain.portfolio_risk_sources import (
    CoverageStatus,
    SourceObservationPrecision,
)
from tests.support import ash07_public_risk_sources as retained_source_builder
from tests.support.ash07_owner_etf_partial_case import (
    RetainedQ3ReportFacts,
    build_q3_report_admission_request,
    load_q3_report_facts,
)

_REPOSITORY_ROOT = retained_source_builder.REPOSITORY_ROOT
_DEFAULT_NOVEMBER_03_CANDIDATE = (
    _REPOSITORY_ROOT
    / ".tmp"
    / "ash07-risk-20261103"
    / "a-real-source-e2e"
    / "real-source-owner-risk-candidate.json"
)
_BUSINESS_DATE = date(2026, 11, 3)
_SOURCE_PURPOSE = "official_etf_report"
_CONSUMER_PURPOSE = "simulation_portfolio_risk_industry_exposure"
_FACTS_PATH_ENV = "ASH07_OWNER_ETF_PARTIAL_FACTS_PATH"
_FACTS_SHA256_ENV = "ASH07_OWNER_ETF_PARTIAL_FACTS_SHA256"


def _historical_bank_candidate_path() -> Path:
    """Keep the historical DTO source separate from the current financial input."""

    configured = os.environ.get("ASH07_OWNER_ETF_PARTIAL_HISTORICAL_CANDIDATE_PATH", "").strip()
    path = Path(configured) if configured else _DEFAULT_NOVEMBER_03_CANDIDATE
    return path if path.is_absolute() else _REPOSITORY_ROOT / path


@pytest.fixture(scope="module")
def retained_report_request() -> tuple[
    RetainedQ3ReportFacts,
    PortfolioRiskSourceAdmissionRequest,
    dict[str, str],
]:
    """Load available ignored report facts and exact November 3 bank requests."""

    configured_facts = os.environ.get(_FACTS_PATH_ENV, "").strip()
    if not configured_facts:
        pytest.skip("retained Q3 facts are not configured for this ignored contract test")
    expected_facts_sha256 = os.environ.get(_FACTS_SHA256_ENV, "").strip()
    if not expected_facts_sha256:
        pytest.skip("the external Q3 facts SHA-256 is not configured")
    facts_path = Path(configured_facts)
    if not facts_path.is_absolute():
        facts_path = _REPOSITORY_ROOT / facts_path
    if not facts_path.is_file():
        pytest.skip("configured retained Q3 facts file is unavailable")

    candidate_path = _historical_bank_candidate_path()
    if not candidate_path.is_file():
        pytest.skip("retained November 3 bank source candidate is unavailable")

    facts = load_q3_report_facts(
        facts_path=facts_path,
        expected_facts_sha256=expected_facts_sha256,
        repository_root=_REPOSITORY_ROOT,
    )
    candidate = json.loads(candidate_path.read_text(encoding="utf-8-sig"))
    if type(candidate) is not dict:
        raise AssertionError("retained bank candidate must be a JSON object")
    if candidate.get("business_date") != _BUSINESS_DATE.isoformat():
        raise AssertionError("typed bank requests must come from the retained November 3 candidate")

    requests = retained_source_builder.build_real_source_admission_requests(candidate_path)
    bank_requests = tuple(request for request in requests if request.kind == "industry_membership")
    if len(bank_requests) != 2:
        raise AssertionError("the retained November 3 input must contain exactly two bank requests")

    identity_resolution = candidate.get("identity_resolution")
    if type(identity_resolution) is not dict:
        raise AssertionError("bank candidate identity resolution is missing")
    raw_records = identity_resolution.get("records")
    if type(raw_records) is not list:
        raise AssertionError("bank candidate identity records are missing")
    identity_by_code: dict[str, str] = {}
    for raw_record in raw_records:
        if type(raw_record) is not dict:
            raise AssertionError("bank identity record is malformed")
        source_code = raw_record.get("sse_company_code")
        asset_code = raw_record.get("asset_code")
        if type(source_code) is str and type(asset_code) is str:
            identity_by_code[source_code] = asset_code

    source_code_to_asset_code = {
        source_code: identity_by_code[source_code]
        for source_code in ("600036", "601398")
        if source_code in identity_by_code
    }
    if set(source_code_to_asset_code) != {"600036", "601398"}:
        raise AssertionError("the exact two bank normalization identities are unavailable")

    report_request = build_q3_report_admission_request(
        facts=facts,
        repository_root=_REPOSITORY_ROOT,
        asset_code="510050.SH",
        security_id="SSE:510050",
        source_id="chinaamc_510050_disclosed_report",
        source_purpose=_SOURCE_PURPOSE,
        allowed_purposes=(_CONSUMER_PURPOSE,),
        restrictions=(),
        coverage_precision_basis="reported_top_ten_weight_fraction",
        business_date=_BUSINESS_DATE,
        same_day_bank_industry_requests=bank_requests,
        source_code_to_asset_code=source_code_to_asset_code,
    )
    return facts, report_request, source_code_to_asset_code


def test_historical_etf_request_preserves_distinct_source_and_consumer_purposes(
    retained_report_request: tuple[
        RetainedQ3ReportFacts,
        PortfolioRiskSourceAdmissionRequest,
        dict[str, str],
    ],
) -> None:
    """Keep historical disclosure clocks and both original-body hashes distinct."""

    facts, request, source_code_to_asset_code = retained_report_request
    evidence = request.source_evidence
    publication = request.etf_publication_capture
    pdf_receipt = request.capture_receipt
    if publication is None or pdf_receipt is None:
        raise AssertionError("ETF request must carry both typed source receipts")

    assert facts.report_date == date(2026, 9, 30)
    assert facts.publication_on == date(2026, 10, 27)
    assert evidence.source_purpose == _SOURCE_PURPOSE
    assert evidence.allowed_purposes == (_CONSUMER_PURPOSE,)
    assert evidence.source_purpose not in evidence.allowed_purposes
    assert evidence.observation_precision is SourceObservationPrecision.DATE
    assert evidence.observed_on == facts.publication_on
    assert evidence.observed_at is None
    assert evidence.effective_on == facts.report_date
    assert evidence.effective_until is None
    assert evidence.available_at is None
    assert evidence.valid_until is None
    assert evidence.coverage.status is CoverageStatus.PARTIAL
    assert evidence.coverage.reported_weight_fraction == facts.reported_weight_fraction
    assert evidence.coverage.expected_item_count is None
    assert evidence.coverage.observed_item_count is None

    admission_facts = cast(Mapping[str, object], request.facts)
    raw_constituents = admission_facts.get("constituents")
    if type(raw_constituents) is not list or len(raw_constituents) != 10:
        raise AssertionError("the report DTO must preserve exactly ten disclosed holdings")
    for source_fact, raw_row in zip(facts.constituents, raw_constituents, strict=True):
        if type(raw_row) is not dict:
            raise AssertionError("the report DTO contains a malformed constituent row")
        expected_code = source_code_to_asset_code.get(
            source_fact.source_stock_code,
            source_fact.source_stock_code,
        )
        if raw_row.get("asset_code") != expected_code:
            raise AssertionError("the report DTO changed a mapped bank or unmapped source code")

    pdf_hash = hashlib.sha256(request.original_body).hexdigest()
    page_hash = hashlib.sha256(publication.original_body).hexdigest()
    assert evidence.original_payload_sha256 == pdf_hash
    assert pdf_receipt.original_body_sha256 == pdf_hash
    assert publication.receipt.original_body_sha256 == page_hash
    assert pdf_hash != page_hash
    assert pdf_receipt.capture_id != publication.receipt.capture_id
    assert pdf_receipt.source_record_id != publication.receipt.source_record_id
    assert request.captured_at == pdf_receipt.response_completed_at
    assert evidence.known_at == max(
        pdf_receipt.response_completed_at,
        publication.receipt.response_completed_at,
    )


def test_declared_mapping_rejects_source_and_policy_unit_mislabeling(
    retained_report_request: tuple[
        RetainedQ3ReportFacts,
        PortfolioRiskSourceAdmissionRequest,
        dict[str, str],
    ],
) -> None:
    """Keep currency, quantity and capacity labels tied to reviewed provenance."""

    del retained_report_request
    path = _historical_bank_candidate_path()
    candidate = json.loads(path.read_text(encoding="utf-8-sig"))
    mapping = retained_source_builder.verify_source_unit_mapping(candidate)
    requests = retained_source_builder.build_real_source_admission_requests(path)
    policy = {
        "ledger_money_unit": mapping["canonical_money_unit"],
        "capacity": {"measure": "volume", "unit": mapping["canonical_quantity_unit"]},
    }
    retained_source_builder.verify_source_request_units(
        requests, unit_mapping=mapping, policy=policy
    )
    valuation = next(item for item in requests if item.kind == "valuation")
    capacity = next(item for item in requests if item.kind == "capacity_window")
    for field in ("quantity_unit", "price_unit"):
        facts = copy.deepcopy(valuation.facts)
        facts[field] = "different-declared-unit"
        changed = replace(valuation, facts=facts)
        with pytest.raises(ValueError, match="declared unit mapping"):
            retained_source_builder.verify_source_request_units((changed,), unit_mapping=mapping)
    for field in ("volume", "amount"):
        facts = copy.deepcopy(capacity.facts)
        facts[field]["unit"] = "different-declared-unit"
        changed = replace(capacity, facts=facts)
        with pytest.raises(ValueError, match="declared unit mapping"):
            retained_source_builder.verify_source_request_units((changed,), unit_mapping=mapping)
    for changed_policy in (
        {**policy, "ledger_money_unit": "different-declared-unit"},
        {**policy, "capacity": {"measure": "volume", "unit": "different-declared-unit"}},
    ):
        with pytest.raises(ValueError, match="declared unit mapping"):
            retained_source_builder.verify_source_request_units(
                requests, unit_mapping=mapping, policy=changed_policy
            )
    missing = copy.deepcopy(valuation.facts)
    missing["price_unit"] = None
    retained_source_builder.verify_source_request_units(
        (replace(valuation, facts=missing),), unit_mapping=mapping
    )
    assert missing["price_unit"] is None


def test_q3_facts_reject_self_consistent_weight_rewrite(
    tmp_path: Path,
) -> None:
    """Reject changed percentages even when rows and the declared sum still agree."""

    configured_facts = os.environ.get(_FACTS_PATH_ENV, "").strip()
    expected_facts_sha256 = os.environ.get(_FACTS_SHA256_ENV, "").strip()
    if not configured_facts or not expected_facts_sha256:
        pytest.skip("the externally anchored Q3 facts input is not configured")
    facts_path = Path(configured_facts)
    if not facts_path.is_absolute():
        facts_path = _REPOSITORY_ROOT / facts_path
    document = json.loads(facts_path.read_text(encoding="utf-8-sig"))
    if type(document) is not dict:
        raise AssertionError("retained Q3 facts must be an object")
    rows = document.get("constituents")
    if type(rows) is not list or not rows or type(rows[0]) is not dict:
        raise AssertionError("retained Q3 facts must contain typed constituent rows")
    first_row = cast(dict[str, object], rows[0])
    first_percentage = first_row.get("weight_percent_text")
    declared_fraction = document.get("reported_weight_fraction")
    if type(first_percentage) is not str or type(declared_fraction) is not str:
        raise AssertionError("retained Q3 percentage facts must remain decimal text")
    first_row["weight_percent_text"] = str(Decimal(first_percentage) + Decimal("0.01"))
    document["reported_weight_fraction"] = str(Decimal(declared_fraction) + Decimal("0.0001"))
    tampered_facts_path = tmp_path / "self-consistent-but-unpinned-q3-facts.json"
    tampered_facts_path.write_text(
        json.dumps(document, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="externally bound digest"):
        load_q3_report_facts(
            facts_path=tampered_facts_path,
            expected_facts_sha256=expected_facts_sha256,
            repository_root=_REPOSITORY_ROOT,
        )


def test_historical_etf_admission_rejects_tampered_partial_coverage(
    retained_report_request: tuple[
        RetainedQ3ReportFacts,
        PortfolioRiskSourceAdmissionRequest,
        dict[str, str],
    ],
) -> None:
    """Reject changing the source's explicitly partial coverage to complete."""

    _facts, request, _source_code_to_asset_code = retained_report_request
    document = _admission_document(request)
    source_evidence = cast(dict[str, object], document["source_evidence"])
    coverage = cast(dict[str, object], source_evidence["coverage"])
    coverage["status"] = "complete"

    with pytest.raises(PortfolioRiskSourceAdmissionError) as raised:
        _parse_document(request, document)

    assert raised.value.code == "RISK_INPUT_ADMISSION_SOURCE_INVALID"


def test_historical_etf_admission_rejects_tampered_pdf_body_hash(
    retained_report_request: tuple[
        RetainedQ3ReportFacts,
        PortfolioRiskSourceAdmissionRequest,
        dict[str, str],
    ],
) -> None:
    """Reject an evidence hash that no longer matches the captured PDF receipt."""

    _facts, request, _source_code_to_asset_code = retained_report_request
    document = _admission_document(request)
    source_evidence = cast(dict[str, object], document["source_evidence"])
    original_hash = cast(str, source_evidence["original_payload_sha256"])
    source_evidence["original_payload_sha256"] = "0" * 64 if original_hash != "0" * 64 else "1" * 64

    with pytest.raises(PortfolioRiskSourceAdmissionError) as raised:
        _parse_document(request, document)

    assert raised.value.code == "RISK_INPUT_ADMISSION_DOCUMENT_INVALID"


def _admission_document(request: PortfolioRiskSourceAdmissionRequest) -> dict[str, object]:
    """Rebuild the public admission document from one typed DTO for tamper cases."""

    source = request.source_evidence
    coverage = source.coverage
    source_evidence: dict[str, object] = {
        "source_id": source.source_id,
        "source_record_id": source.source_record_id,
        "original_payload_sha256": source.original_payload_sha256,
        "observation_precision": source.observation_precision.value,
        "observed_at": _iso_or_none(source.observed_at),
        "observed_on": source.observed_on.isoformat() if source.observed_on else None,
        "available_at": _iso_or_none(source.available_at),
        "known_at": _iso_or_none(source.known_at),
        "valid_until": _iso_or_none(source.valid_until),
        "source_purpose": source.source_purpose,
        "allowed_purposes": list(source.allowed_purposes),
        "restrictions": list(source.restrictions),
        "must_not_use_for_decision": source.must_not_use_for_decision,
        "coverage": {
            "status": coverage.status.value,
            "precision_basis": coverage.precision_basis,
            "reported_weight_fraction": (
                str(coverage.reported_weight_fraction)
                if coverage.reported_weight_fraction is not None
                else None
            ),
            "expected_item_count": coverage.expected_item_count,
            "observed_item_count": coverage.observed_item_count,
        },
        "effective_on": source.effective_on.isoformat() if source.effective_on else None,
        "effective_until": source.effective_until.isoformat() if source.effective_until else None,
    }
    return {
        "schema_version": "ash07.source_admission_request.v1",
        "kind": request.kind,
        "asset_code": request.asset_code,
        "security_id": request.security_id,
        "source_record_id": request.source_record_id,
        "original_url": request.original_url,
        "captured_at": request.captured_at.isoformat(),
        "source_evidence": source_evidence,
        "facts": cast(Mapping[str, object], request.facts),
    }


def _parse_document(
    request: PortfolioRiskSourceAdmissionRequest,
    document: Mapping[str, object],
) -> PortfolioRiskSourceAdmissionRequest:
    """Run only the public DTO parser against the same captured source bytes."""

    return parse_portfolio_risk_source_admission_request(
        document,
        original_body=request.original_body,
        capture_receipt=request.capture_receipt,
        etf_publication_capture=request.etf_publication_capture,
    )


def _iso_or_none(value: datetime | None) -> str | None:
    """Serialize an existing aware source timestamp without substitution."""

    return value.isoformat() if value is not None else None
