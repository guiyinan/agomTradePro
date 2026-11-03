"""Contracts for policy-bounded timestamp source proofs in simulation risk."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import cast
from zoneinfo import ZoneInfo

import pytest

from apps.config_center.application.runtime_value_evidence import ActiveRuntimeValueEvidence
from apps.risk_center.application.portfolio_pressure_report import (
    decode_portfolio_risk_report_json,
)
from apps.risk_center.application.portfolio_risk_contracts import (
    PortfolioRiskTimestampSnapshotClockProofPayload,
)
from apps.risk_center.application.portfolio_risk_deadlines import (
    portfolio_risk_execution_deadline_for_evidence,
)
from apps.risk_center.application.portfolio_risk_policy import (
    SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY,
    PortfolioRiskPolicyBundle,
    PortfolioRiskPolicyConfigurationError,
    parse_portfolio_risk_policy_bundle,
)
from apps.risk_center.application.portfolio_risk_report import _source_payload
from apps.risk_center.application.portfolio_risk_serialization import (
    canonical_portfolio_risk_json,
)
from apps.risk_center.application.portfolio_risk_timestamp_snapshot_clock import (
    PortfolioRiskTimestampSnapshotFacts,
    PortfolioRiskTimestampSnapshotQualification,
    qualify_policy_bounded_timestamp_snapshot,
)
from apps.risk_center.domain.portfolio_risk_clock_evidence import PortfolioRiskCaptureReceipt
from apps.risk_center.domain.portfolio_risk_sources import (
    CoverageStatus,
    PortfolioRiskCoverage,
    PortfolioRiskSourceEvidence,
    SourceObservationPrecision,
)

_AS_OF = datetime(2026, 11, 3, 14, 0, tzinfo=UTC)
_BUSINESS_DATE = date(2026, 11, 3)
_ZONE = ZoneInfo("Asia/Shanghai")
_PURPOSE = "ash07_portfolio_exposure"
_CAPACITY_PURPOSE = "ash07_capacity"
_BODY = b'{"source":"fixture","observed_at":"2026-11-03T21:58:00+08:00"}'
_BODY_HASH = sha256(_BODY).hexdigest()
_MANIFEST_HASH = "sha256:" + "a" * 64
_OBSERVED_AT = datetime(2026, 11, 3, 21, 58, tzinfo=_ZONE)
_CAPTURED_AT = datetime(2026, 11, 3, 21, 59, 30, tzinfo=_ZONE)
_KNOWN_AT = datetime(2026, 11, 3, 21, 59, 40, tzinfo=_ZONE)


def _policy(
    *,
    kind: str = "valuation",
    clock_mode: str | None = "policy_bounded_timestamp_snapshot",
    max_age_seconds: int = 1800,
    capacity_window_kind: str = "session_cumulative",
    capacity_sessions: int = 1,
    capacity_basis: str = "session_total",
) -> PortfolioRiskPolicyBundle:
    """Parse a complete synthetic simulation-only profile with an exact source pin."""

    reference: dict[str, object] = {
        "kind": kind,
        "asset_code": "600036.SH",
        "security_id": "equity:SH:600036",
        "raw_payload_hash": _MANIFEST_HASH,
        "source_record_id": "source-record-1",
    }
    if clock_mode is not None:
        reference["clock_evidence_mode"] = clock_mode
    configuration: dict[str, object] = {
        "schema_version": "ash07.simulated_portfolio_risk.v1",
        "scope": "simulation_only",
        "ledger_money_unit": "CNY",
        "account_ids": [12],
        "industry": {
            "taxonomy_id": "cnindex-taxonomy",
            "taxonomy_kind": "industry",
            "provider_id": "cnindex",
            "provider_version": "approved-v1",
            "requested_purpose": _PURPOSE,
            "date_precision_purposes": [],
            "allowed_observation_precisions": ["timestamp"],
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
            "basis": capacity_basis,
            "usage_scope": "account_security_session",
            "date_basis": "execution_session",
            "max_participation": "0.08",
            "increment": "1",
            "window_kind": capacity_window_kind,
            "sessions": capacity_sessions,
            "allowed_observation_precisions": ["timestamp"],
            "date_precision_purposes": [],
            "allowed_source_restrictions": (
                ["vendor_reported_at_quote_time", "close_snapshot_only"]
                if clock_mode == "policy_bounded_close_snapshot_state"
                else []
            ),
        },
        "source_max_timestamp_age_seconds": max_age_seconds,
        "source_max_date_age_days": 0,
        "source_references": [reference],
    }
    created_at = _AS_OF - timedelta(minutes=10)
    activated_at = _AS_OF - timedelta(minutes=5)
    runtime = ActiveRuntimeValueEvidence(
        environment="development",
        definition_key=SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY,
        value=configuration,
        profile_id="risk-profile-simulation-test",
        profile_key="risk-center-simulation-test",
        profile_version=4,
        profile_content_hash="b" * 64,
        snapshot_id="risk-snapshot-test",
        snapshot_hash="c" * 64,
        created_at=created_at,
        known_at=created_at,
        activated_at=activated_at,
        snapshot_generated_at=_AS_OF - timedelta(minutes=2),
        effective_at=activated_at,
        as_of=_AS_OF,
    )
    return parse_portfolio_risk_policy_bundle(
        runtime,
        business_date=_BUSINESS_DATE,
        as_of=_AS_OF,
    )


def _evidence(
    *,
    observed_at: datetime = _OBSERVED_AT,
    known_at: datetime | None = _KNOWN_AT,
    must_not_use: bool = False,
    available_at: datetime | None = None,
    valid_until: datetime | None = None,
) -> PortfolioRiskSourceEvidence:
    """Build one exact timestamp fact while preserving unknown origin clocks."""

    return PortfolioRiskSourceEvidence(
        source_id="official-source",
        source_record_id="source-record-1",
        original_payload_sha256=_BODY_HASH,
        observation_precision=SourceObservationPrecision.TIMESTAMP,
        observed_at=observed_at,
        observed_on=None,
        available_at=available_at,
        known_at=known_at,
        decision_cutoff=_AS_OF,
        decision_date_cutoff=None,
        valid_until=valid_until,
        source_purpose="official_source_observation",
        allowed_purposes=(_PURPOSE, _CAPACITY_PURPOSE),
        restrictions=(),
        must_not_use_for_decision=must_not_use,
        coverage=PortfolioRiskCoverage(
            status=CoverageStatus.COMPLETE,
            precision_basis="source_record_count",
            expected_item_count=1,
            observed_item_count=1,
        ),
    )


def _receipt() -> PortfolioRiskCaptureReceipt:
    """Bind one complete successful response body to its local receipt clock."""

    return PortfolioRiskCaptureReceipt(
        capture_id="capture-1",
        source_id="official-source",
        source_record_id="source-record-1",
        original_body_sha256=_BODY_HASH,
        response_completed_at=_CAPTURED_AT,
        http_status=200,
        body_size_bytes=len(_BODY),
        body_complete=True,
    )


def _facts(kind: str = "valuation") -> PortfolioRiskTimestampSnapshotFacts:
    if kind == "valuation":
        return PortfolioRiskTimestampSnapshotFacts(
            source_kind="valuation",
            valuation_price=Decimal("100.25"),
            valuation_quantity_unit="share",
            valuation_price_unit="CNY",
        )
    return PortfolioRiskTimestampSnapshotFacts(
        source_kind="capacity_window",
        capacity_window_kind="session_cumulative",
        capacity_window_start=_BUSINESS_DATE,
        capacity_window_end=_BUSINESS_DATE,
        capacity_window_sessions=1,
        capacity_volume_value=Decimal("10000"),
        capacity_volume_unit="share",
        capacity_measure="volume",
        capacity_policy_unit="share",
    )


def _qualify(
    *,
    kind: str = "valuation",
    policy: PortfolioRiskPolicyBundle | None = None,
    evidence: PortfolioRiskSourceEvidence | None = None,
    facts: PortfolioRiskTimestampSnapshotFacts | None = None,
    purpose: str = _PURPOSE,
    receipt: PortfolioRiskCaptureReceipt | None = None,
    account_id: int = 12,
) -> PortfolioRiskTimestampSnapshotQualification:
    selected_policy = _policy(kind=kind) if policy is None else policy
    reference = selected_policy.source_references[0]
    return qualify_policy_bounded_timestamp_snapshot(
        policy=selected_policy,
        source_reference=reference,
        retained_payload_hash=_MANIFEST_HASH,
        account_id=account_id,
        source_evidence=_evidence() if evidence is None else evidence,
        facts=_facts(kind) if facts is None else facts,
        receipt=_receipt() if receipt is None else receipt,
        original_body=_BODY,
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE,
        execution_session=_BUSINESS_DATE,
        requested_purpose=purpose,
        asset_code="600036.SH",
        security_id="equity:SH:600036",
        business_timezone=_ZONE,
        business_timezone_name="Asia/Shanghai",
    )


def test_timestamp_valuation_proof_preserves_origin_clocks_and_binds_all_bounds() -> None:
    result = _qualify()

    assert result.qualified is True
    proof = result.proof
    assert proof is not None
    assert proof.observed_at == _OBSERVED_AT
    assert proof.proven_available_at == _CAPTURED_AT
    assert proof.known_at == _KNOWN_AT
    assert proof.source_available_at is None
    assert proof.source_valid_until is None
    assert proof.market_window_deadline == datetime(2026, 11, 3, 16, 0, tzinfo=UTC)
    assert proof.policy_acceptance_deadline == min(
        proof.timestamp_age_deadline,
        proof.market_window_deadline,
        *proof.policy_deadlines,
    )


def test_timestamp_proof_rejects_known_at_after_decision_cutoff() -> None:
    proof = _qualify().proof
    assert proof is not None

    with pytest.raises(ValueError, match="capture, known-at and decision cutoffs"):
        replace(proof, known_at=proof.as_of + timedelta(seconds=1))


def test_timestamp_capacity_requires_one_current_session_and_matching_unit() -> None:
    result = _qualify(kind="capacity_window", purpose=_CAPACITY_PURPOSE)

    assert result.qualified is True
    assert result.proof is not None
    assert result.proof.capacity_window_start == _BUSINESS_DATE
    assert result.proof.capacity_window_end == _BUSINESS_DATE
    assert result.proof.capacity_window_sessions == 1

    mismatch = _qualify(
        kind="capacity_window",
        purpose=_CAPACITY_PURPOSE,
        facts=PortfolioRiskTimestampSnapshotFacts(
            source_kind="capacity_window",
            capacity_window_kind="session_cumulative",
            capacity_window_start=_BUSINESS_DATE - timedelta(days=1),
            capacity_window_end=_BUSINESS_DATE,
            capacity_window_sessions=2,
            capacity_volume_value=Decimal("10000"),
            capacity_volume_unit="share",
            capacity_measure="volume",
            capacity_policy_unit="share",
        ),
    )
    assert mismatch.qualified is False
    assert "PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_CAPACITY_WINDOW_NOT_CURRENT_SESSION" in (
        mismatch.reason_codes
    )


@pytest.mark.parametrize(
    ("evidence", "reason"),
    [
        (
            _evidence(observed_at=_OBSERVED_AT - timedelta(minutes=31)),
            "PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_AGE_EXCEEDED",
        ),
        (
            _evidence(must_not_use=True),
            "PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_PROHIBITED",
        ),
        (
            _evidence(available_at=_CAPTURED_AT),
            "PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_SOURCE_CLOCK_MODE_CONFLICT",
        ),
        (
            _evidence(known_at=_CAPTURED_AT - timedelta(seconds=1)),
            "PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_KNOWN_BEFORE_RECEIPT",
        ),
        (
            _evidence(observed_at=_CAPTURED_AT + timedelta(seconds=1)),
            "PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_OBSERVATION_AFTER_CAPTURE",
        ),
    ],
)
def test_timestamp_snapshot_fails_closed_on_stale_prohibited_or_conflicting_source(
    evidence: PortfolioRiskSourceEvidence, reason: str
) -> None:
    result = _qualify(evidence=evidence)

    assert result.qualified is False
    assert reason in result.reason_codes


def test_timestamp_capacity_policy_refuses_rolling_window_substitution() -> None:
    with pytest.raises(PortfolioRiskPolicyConfigurationError) as error:
        _policy(
            kind="capacity_window",
            capacity_window_kind="rolling_sessions",
            capacity_sessions=5,
            capacity_basis="average_per_session",
        )

    assert error.value.reason_code == "SIMULATED_PORTFOLIO_RISK_RUNTIME_IDENTITY_INVALID"
    assert isinstance(error.value.__cause__, ValueError)
    assert "timestamp capacity mode requires one explicit cumulative session" in str(
        error.value.__cause__
    )


def test_timestamp_clock_mode_cannot_be_assigned_to_other_source_kinds() -> None:
    with pytest.raises(ValueError, match="only available for valuation or capacity"):
        _policy(kind="etf_report")


def test_timestamp_proof_requires_receipt_and_policy_account_scope() -> None:
    missing_receipt = qualify_policy_bounded_timestamp_snapshot(
        policy=_policy(),
        source_reference=_policy().source_references[0],
        retained_payload_hash=_MANIFEST_HASH,
        account_id=12,
        source_evidence=_evidence(),
        facts=_facts(),
        receipt=None,
        original_body=_BODY,
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE,
        execution_session=_BUSINESS_DATE,
        requested_purpose=_PURPOSE,
        asset_code="600036.SH",
        security_id="equity:SH:600036",
        business_timezone=_ZONE,
        business_timezone_name="Asia/Shanghai",
    )
    assert missing_receipt.qualified is False
    assert "PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_CAPTURE_UNKNOWN" in missing_receipt.reason_codes

    out_of_scope = _qualify(account_id=13)
    assert out_of_scope.qualified is False
    assert "PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_ACCOUNT_SCOPE_MISMATCH" in (out_of_scope.reason_codes)


def test_timestamp_valuation_requires_configured_ledger_price_unit() -> None:
    mismatch = _qualify(
        facts=PortfolioRiskTimestampSnapshotFacts(
            source_kind="valuation",
            valuation_price=Decimal("100"),
            valuation_quantity_unit="share",
            valuation_price_unit="USD",
        )
    )
    assert mismatch.qualified is False
    assert "PORTFOLIO_RISK_TIMESTAMP_SNAPSHOT_PRICE_UNIT_MISMATCH" in mismatch.reason_codes


def test_timestamp_report_codec_roundtrips_source_offset_and_separate_deadlines() -> None:
    policy = _policy()
    result = _qualify(policy=policy)
    assert result.proof is not None
    evidence = replace(_evidence(), policy_clock_proof=result.proof)
    report: dict[str, object] = {
        "account_id": 12,
        "as_of": _AS_OF.isoformat(),
        "outcome": "allowed",
        "policy_version": f"{policy.profile_key}@{policy.profile_version}",
        "resource_snapshot_hash": "d" * 64,
        "checks": [],
        "sources": [_source_payload(evidence)],
        "freshness": "qualified_snapshot",
        "reliability": "source_bound",
        "must_not_use_for_decision": False,
        "scope": "simulation_only",
        "must_not_execute": True,
    }

    decoded = decode_portfolio_risk_report_json(canonical_portfolio_risk_json(report))

    assert decoded is not None
    source = decoded["sources"][0]
    proof = cast(
        PortfolioRiskTimestampSnapshotClockProofPayload,
        source["clock_evidence_proof"],
    )
    assert source["observed_at"] == _OBSERVED_AT.isoformat()
    assert source["available_at"] is None
    assert source["valid_until"] is None
    assert proof["observed_at"] == _OBSERVED_AT.isoformat()
    assert proof["proven_available_at"] == _CAPTURED_AT.isoformat()
    assert proof["source_available_at"] is None
    assert proof["source_valid_until"] is None


def test_execution_deadline_rebinds_timestamp_proof_and_keeps_external_limits() -> None:
    policy = _policy()
    result = _qualify(policy=policy)
    assert result.proof is not None
    evidence = replace(_evidence(), policy_clock_proof=result.proof)
    deadline = portfolio_risk_execution_deadline_for_evidence(
        evidence,
        policy,
        account_id=12,
        business_timezone=_ZONE,
        additional_policy_deadlines=(_AS_OF + timedelta(minutes=10),),
        requested_purpose=_PURPOSE,
    )

    assert deadline == _AS_OF + timedelta(minutes=10)
    assert (
        portfolio_risk_execution_deadline_for_evidence(
            evidence,
            policy,
            account_id=13,
            business_timezone=_ZONE,
            additional_policy_deadlines=(),
            requested_purpose=_PURPOSE,
        )
        is None
    )
