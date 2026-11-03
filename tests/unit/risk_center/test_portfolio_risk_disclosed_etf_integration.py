"""ETF disclosure proofs survive reports/replay and remain bound at execution."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from typing import cast

import pytest

from apps.risk_center.application.portfolio_pressure_report import (
    decode_portfolio_risk_report_json,
    report_payload_from_object,
)
from apps.risk_center.application.portfolio_risk_clock_report_codec import (
    is_source_clock_evidence_proof,
)
from apps.risk_center.application.portfolio_risk_deadlines import (
    portfolio_risk_execution_deadline_for_evidence,
)
from apps.risk_center.application.portfolio_risk_disclosed_etf_deadline import (
    disclosed_etf_report_proof_matches_policy,
)
from apps.risk_center.application.portfolio_risk_disclosed_etf_report_codec import (
    decode_disclosed_etf_report_clock_payload,
    disclosed_etf_report_clock_payload,
)
from apps.risk_center.application.portfolio_risk_report import (
    _clock_proof_matches_current_report,
    _ReportSourceUseRule,
    _source_payload,
    _source_use_qualification_reasons,
)
from apps.risk_center.application.portfolio_risk_serialization import (
    canonical_portfolio_risk_json,
)
from apps.risk_center.domain.portfolio_risk_disclosed_etf_report_clock import (
    PortfolioRiskDisclosedETFReportProof,
)
from apps.risk_center.domain.portfolio_risk_sources import qualify_portfolio_risk_source
from tests.unit.risk_center.test_portfolio_risk_disclosed_etf_report_clock import (
    _AS_OF,
    _BUSINESS_DATE,
    _BUSINESS_ZONE,
    _PURPOSE,
    _evidence,
    _policy,
    _qualification,
)


def _proof() -> PortfolioRiskDisclosedETFReportProof:
    result = _qualification()
    assert result.proof is not None, result.reason_codes
    return result.proof


def test_etf_clock_source_codec_keeps_two_dates_and_unknown_supplier_clocks() -> None:
    proof = _proof()
    evidence = replace(_evidence(), policy_clock_proof=proof)
    source = _source_payload(evidence)
    encoded = disclosed_etf_report_clock_payload(proof)
    assert decode_disclosed_etf_report_clock_payload(json.loads(json.dumps(encoded))) == proof
    assert is_source_clock_evidence_proof(encoded, cast(dict[str, object], source))
    assert source["cutoff"] == _BUSINESS_DATE.isoformat()
    assert encoded["as_of"] == _AS_OF.isoformat()
    timestamp_cutoff = {**source, "cutoff": _AS_OF.isoformat()}
    assert not is_source_clock_evidence_proof(encoded, timestamp_cutoff)
    assert source["available_at"] is None and source["valid_until"] is None
    assert encoded["report_period_end"] == "2026-09-30"
    assert encoded["publication_on"] == "2026-10-27"
    assert encoded["original_body_sha256"] != encoded["publication_original_body_sha256"]
    assert encoded["source_reference_hash"] != "sha256:" + encoded["original_body_sha256"]
    assert encoded["publication_record_id"] != encoded["source_record_id"]
    assert encoded["receipt_completed_at"] == proof.receipt_completed_at.isoformat()
    assert (
        encoded["publication_receipt_completed_at"]
        == proof.publication_receipt_completed_at.isoformat()
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("scope", "live"),
        ("clock_evidence_mode", "policy_bounded_date_snapshot"),
        ("source_kind", "industry_membership"),
        ("report_period_end", "2027-01-01"),
        ("publication_on", "2026-09-30"),
        ("publication_original_body_sha256", None),
        ("publication_body_complete", False),
        ("publication_http_status", 503),
        ("max_report_age_days", True),
        ("source_available_at", "2026-10-27T00:00:00+00:00"),
        ("publication_receipt_completed_at", "2026-11-05T00:00:00+00:00"),
        ("policy_acceptance_deadline", "2099-01-01T00:00:00+00:00"),
    ],
)
def test_stored_clock_proof_rejects_field_and_deadline_tampering(field: str, value: object) -> None:
    proof = _proof()
    source = _source_payload(replace(_evidence(), policy_clock_proof=proof))
    damaged = dict(disclosed_etf_report_clock_payload(proof))
    damaged[field] = value
    assert not is_source_clock_evidence_proof(damaged, cast(dict[str, object], source))


def test_execution_deadline_rebinds_etf_policy_owner_and_external_resource_expiry() -> None:
    proof = _proof()
    evidence = replace(_evidence(), policy_clock_proof=proof)
    policy = _policy()
    assert disclosed_etf_report_proof_matches_policy(
        proof=proof,
        evidence=evidence,
        policy=policy,
        account_id=12,
        business_timezone=_BUSINESS_ZONE,
        requested_purpose=_PURPOSE,
    )
    earlier_resource_expiry = _AS_OF + timedelta(seconds=30)
    assert (
        portfolio_risk_execution_deadline_for_evidence(
            evidence,
            policy,
            account_id=12,
            business_timezone=_BUSINESS_ZONE,
            additional_policy_deadlines=(earlier_resource_expiry,),
            requested_purpose=_PURPOSE,
        )
        == earlier_resource_expiry
    )
    for changed in (
        replace(proof, account_id=13),
        replace(proof, policy_snapshot_hash="b" * 64),
        replace(proof, source_reference_hash="sha256:" + "c" * 64),
    ):
        assert (
            portfolio_risk_execution_deadline_for_evidence(
                replace(evidence, policy_clock_proof=changed),
                policy,
                account_id=12,
                business_timezone=_BUSINESS_ZONE,
                additional_policy_deadlines=(),
                requested_purpose=_PURPOSE,
            )
            is None
        )
    assert not _clock_proof_matches_current_report(
        proof=proof,
        reference=policy.source_references[0],
        policy=policy,
        evidence=evidence,
        account_id=13,
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE,
        execution_session=_BUSINESS_DATE,
    )


def test_etf_proof_does_not_remove_an_explicit_source_prohibition() -> None:
    proof = _proof()
    policy = _policy()
    prohibited = replace(_evidence(), policy_clock_proof=proof, must_not_use_for_decision=True)
    assert not qualify_portfolio_risk_source(
        evidence=prohibited,
        requested_purpose=_PURPOSE,
        allowed_observation_precisions=policy.industry_policy.allowed_observation_precisions,
        allowed_restrictions=policy.industry_policy.allowed_source_restrictions,
        as_of=_AS_OF,
        expected_source_kind="etf_report",
    ).eligible
    assert (
        portfolio_risk_execution_deadline_for_evidence(
            prohibited,
            policy,
            account_id=12,
            business_timezone=_BUSINESS_ZONE,
            additional_policy_deadlines=(),
            requested_purpose=_PURPOSE,
        )
        is None
    )


def test_partial_disclosure_still_blocks_report_decision_after_clock_qualification() -> None:
    proof = _proof()
    policy = _policy()
    evidence = replace(_evidence(), policy_clock_proof=proof)
    assert _source_use_qualification_reasons(
        rule=_ReportSourceUseRule(
            evidence=evidence,
            purpose=_PURPOSE,
            allowed_precisions=policy.industry_policy.allowed_observation_precisions,
            date_precision_purposes=policy.industry_policy.date_precision_purposes,
            allowed_restrictions=policy.industry_policy.allowed_source_restrictions,
            coverage_precision_basis=policy.industry_policy.coverage_precision_basis,
            source_role="etf_report",
            asset_code=proof.asset_code,
            security_id=proof.security_id,
        ),
        policy=policy,
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE,
        execution_session=_BUSINESS_DATE,
        account_id=12,
        source_reference_bindings=policy.source_references,
    ) == ("PORTFOLIO_REPORT_SOURCE_COVERAGE_PARTIAL",)


def test_scenario_report_roundtrip_keeps_original_etf_period_and_permission() -> None:
    proof = _proof()
    policy = _policy()
    source = _source_payload(replace(_evidence(), policy_clock_proof=proof))
    report: dict[str, object] = {
        "account_id": 12,
        "as_of": proof.as_of.isoformat(),
        "outcome": "partial",
        "policy_version": f"{policy.profile_key}@{policy.profile_version}",
        "resource_snapshot_hash": "d" * 64,
        "checks": [
            {
                "dimension": "source_inputs",
                "status": "partial",
                "reason_codes": ["ETF_PARTIAL_DISCLOSURE"],
                "summary": "Only disclosed report rows are known.",
                "details": {},
            }
        ],
        "sources": [source],
        "freshness": "unknown",
        "reliability": "partial",
        "must_not_use_for_decision": True,
        "scope": "simulation_only",
        "must_not_execute": True,
    }
    assert report_payload_from_object(report) is not None
    serialized = canonical_portfolio_risk_json(report)
    assert decode_portfolio_risk_report_json(serialized) == report
    changed_owner = {**report, "account_id": 13}
    assert report_payload_from_object(changed_owner) is None
    changed_cutoff = {**report, "as_of": (_AS_OF + timedelta(days=1)).isoformat()}
    assert report_payload_from_object(changed_cutoff) is None
