"""Contract tests for scoped policy-bounded DATE membership clocks."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Literal, cast
from zoneinfo import ZoneInfo

import pytest

from apps.config_center.application.runtime_value_evidence import ActiveRuntimeValueEvidence
from apps.risk_center.application.portfolio_pressure_report import (
    decode_portfolio_risk_report_json,
)
from apps.risk_center.application.portfolio_risk_date_snapshot_clock import (
    PortfolioRiskCaptureReceipt,
    PortfolioRiskClockEvidenceMode,
    PortfolioRiskDateSnapshotQualification,
    qualify_policy_bounded_industry_date_snapshot,
)
from apps.risk_center.application.portfolio_risk_deadlines import (
    portfolio_risk_execution_deadline_for_evidence,
)
from apps.risk_center.application.portfolio_risk_policy import (
    SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY,
    PortfolioRiskPolicyBundle,
    PortfolioRiskPolicyConfigurationError,
    PortfolioRiskSourceReference,
    parse_portfolio_risk_policy_bundle,
)
from apps.risk_center.application.portfolio_risk_report import _source_payload
from apps.risk_center.application.portfolio_risk_serialization import (
    canonical_portfolio_risk_json,
)
from apps.risk_center.domain.portfolio_exposure_types import (
    EffectiveEndState,
    IndustryMembership,
)
from apps.risk_center.domain.portfolio_risk_sources import (
    CoverageStatus,
    PortfolioRiskCoverage,
    PortfolioRiskSourceEvidence,
    SourceObservationPrecision,
)

_AS_OF = datetime(2026, 11, 3, 14, 0, tzinfo=UTC)
_BUSINESS_DATE = date(2026, 11, 3)
_RECEIVED_AT = datetime(2026, 11, 3, 21, 59, 36, 774295, tzinfo=ZoneInfo("Asia/Shanghai"))
_BUSINESS_ZONE = ZoneInfo("Asia/Shanghai")
_BODY = b'{"code":200,"data":{"total":1,"rows":[{"tradeDate":"2026-11-03"}]}}'
_BODY_HASH = sha256(_BODY).hexdigest()
_MANIFEST_HASH = "sha256:" + "a" * 64
_PURPOSE = "ash07_portfolio_exposure"


def _policy(
    *,
    as_of: datetime = _AS_OF,
    max_date_age_days: int = 0,
    date_purposes: tuple[str, ...] = (_PURPOSE,),
    clock_evidence_mode: str | None = "policy_bounded_date_snapshot",
) -> PortfolioRiskPolicyBundle:
    """Build a complete synthetic profile used only to exercise the clock contract."""

    source_reference: dict[str, object] = {
        "kind": "industry_membership",
        "asset_code": "600036.SH",
        "security_id": "equity:SH:600036",
        "raw_payload_hash": _MANIFEST_HASH,
        "source_record_id": "cnindex-20261103-600036",
    }
    if clock_evidence_mode is not None:
        source_reference["clock_evidence_mode"] = clock_evidence_mode
    configuration: dict[str, object] = {
        "schema_version": "ash07.simulated_portfolio_risk.v1",
        "scope": "simulation_only",
        "ledger_money_unit": "CNY",
        "account_ids": [12],
        "industry": {
            "taxonomy_id": "cnindex-reviewed-taxonomy",
            "taxonomy_kind": "industry",
            "provider_id": "cnindex",
            "provider_version": "reviewed-standard-plus-notice",
            "requested_purpose": _PURPOSE,
            "date_precision_purposes": list(date_purposes),
            "allowed_observation_precisions": ["date"],
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
            "allowed_observation_precisions": ["timestamp"],
            "date_precision_purposes": [],
            "allowed_source_restrictions": [],
        },
        "source_max_timestamp_age_seconds": 1800,
        "source_max_date_age_days": max_date_age_days,
        "source_references": [source_reference],
    }
    created_at = as_of - timedelta(minutes=10)
    effective_at = as_of - timedelta(minutes=5)
    generated_at = as_of - timedelta(minutes=2)
    runtime = ActiveRuntimeValueEvidence(
        environment="development",
        definition_key=SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY,
        value=configuration,
        profile_id="risk-profile-sim-test",
        profile_key="risk-center-simulation-test",
        profile_version=3,
        profile_content_hash="e" * 64,
        snapshot_id="risk-snapshot-sim-test",
        snapshot_hash="f" * 64,
        created_at=created_at,
        known_at=created_at,
        activated_at=effective_at,
        snapshot_generated_at=generated_at,
        effective_at=effective_at,
        as_of=as_of,
    )
    return parse_portfolio_risk_policy_bundle(
        runtime,
        business_date=as_of.astimezone(_BUSINESS_ZONE).date(),
        as_of=as_of,
    )


def _source_evidence(
    *,
    as_of: datetime = _AS_OF,
    available_at: datetime | None = None,
    valid_until: datetime | None = None,
    known_at: datetime | None = _RECEIVED_AT,
    observed_on: date = _BUSINESS_DATE,
    must_not_use: bool = False,
    allowed_purposes: tuple[str, ...] = (_PURPOSE,),
    coverage_status: CoverageStatus = CoverageStatus.COMPLETE,
) -> PortfolioRiskSourceEvidence:
    """Build raw source-origin clocks while keeping unknown values explicit."""

    return PortfolioRiskSourceEvidence(
        source_id="cnindex",
        source_record_id="cnindex-20261103-600036",
        original_payload_sha256=_BODY_HASH,
        observation_precision=SourceObservationPrecision.DATE,
        observed_at=None,
        observed_on=observed_on,
        available_at=available_at,
        known_at=known_at,
        decision_cutoff=as_of,
        decision_date_cutoff=_BUSINESS_DATE,
        valid_until=valid_until,
        source_purpose="official_classification_snapshot",
        allowed_purposes=allowed_purposes,
        restrictions=(),
        must_not_use_for_decision=must_not_use,
        coverage=PortfolioRiskCoverage(
            status=coverage_status,
            precision_basis="portfolio_weight",
            reported_weight_fraction=(
                Decimal("0.50") if coverage_status is CoverageStatus.PARTIAL else None
            ),
            expected_item_count=(
                1
                if coverage_status is CoverageStatus.COMPLETE
                else 2 if coverage_status is CoverageStatus.PARTIAL else None
            ),
            observed_item_count=(
                1 if coverage_status in (CoverageStatus.COMPLETE, CoverageStatus.PARTIAL) else None
            ),
        ),
        effective_on=_BUSINESS_DATE,
        effective_until=_BUSINESS_DATE,
    )


def _membership(
    *,
    evidence: PortfolioRiskSourceEvidence | None = None,
    effective_from: date = _BUSINESS_DATE,
    effective_until: date | None = _BUSINESS_DATE,
    end_state: EffectiveEndState = EffectiveEndState.BOUNDED,
    taxonomy_id: str = "cnindex-reviewed-taxonomy",
) -> IndustryMembership:
    """Build the exact source-bound day membership for one equity."""

    return IndustryMembership(
        taxonomy_id=taxonomy_id,
        taxonomy_kind="industry",
        provider_id="cnindex",
        provider_version="reviewed-standard-plus-notice",
        industry_code="C07010101",
        effective_from=effective_from,
        effective_end_state=end_state,
        source_evidence=evidence or _source_evidence(),
        effective_until=effective_until,
    )


def _receipt(*, body_complete: bool = True, http_status: int = 200) -> PortfolioRiskCaptureReceipt:
    """Return the response-completion receipt bound to the exact test body."""

    return PortfolioRiskCaptureReceipt(
        capture_id="cnindex-capture-20261103-600036-001",
        source_id="cnindex",
        source_record_id="cnindex-20261103-600036",
        original_body_sha256=_BODY_HASH,
        response_completed_at=_RECEIVED_AT,
        http_status=http_status,
        body_size_bytes=len(_BODY),
        body_complete=body_complete,
    )


def _decision(
    *,
    policy: PortfolioRiskPolicyBundle | None = None,
    reference: PortfolioRiskSourceReference | None = None,
    retained_payload_hash: str | None = None,
    account_id: int = 12,
    evidence: PortfolioRiskSourceEvidence | None = None,
    membership: IndustryMembership | None = None,
    receipt: PortfolioRiskCaptureReceipt | None = None,
    original_body: bytes = _BODY,
    as_of: datetime = _AS_OF,
    additional_policy_deadlines: tuple[datetime, ...] = (),
    timezone_name: str = "Asia/Shanghai",
) -> PortfolioRiskDateSnapshotQualification:
    """Invoke the narrowly scoped qualifier with explicit policy inputs."""

    selected_policy = _policy(as_of=as_of) if policy is None else policy
    selected_reference = selected_policy.source_references[0] if reference is None else reference
    selected_evidence = _source_evidence(as_of=as_of) if evidence is None else evidence
    selected_membership = (
        _membership(evidence=selected_evidence) if membership is None else membership
    )
    return qualify_policy_bounded_industry_date_snapshot(
        clock_evidence_mode=PortfolioRiskClockEvidenceMode.POLICY_BOUNDED_DATE_SNAPSHOT,
        policy=selected_policy,
        source_reference=selected_reference,
        retained_payload_hash=(
            selected_reference.raw_payload_hash
            if retained_payload_hash is None
            else retained_payload_hash
        ),
        account_id=account_id,
        asset_code="600036.SH",
        security_id="equity:SH:600036",
        membership=selected_membership,
        receipt=_receipt() if receipt is None else receipt,
        original_body=original_body,
        as_of=as_of,
        business_date=as_of.astimezone(_BUSINESS_ZONE).date(),
        business_timezone=_BUSINESS_ZONE,
        business_timezone_name=timezone_name,
        additional_policy_deadlines=additional_policy_deadlines,
    )


def test_same_day_bounded_date_snapshot_qualifies_without_rewriting_source_clocks() -> None:
    """A complete pinned same-day receipt qualifies only through its explicit policy mode."""

    result = _decision()

    assert result.qualified is True
    assert result.reason_codes == ()
    assert result.proof is not None
    assert result.proof.proven_available_at == _RECEIVED_AT
    assert result.proof.source_available_at is None
    assert result.proof.source_valid_until is None
    assert result.proof.account_id == 12
    assert result.proof.capture_id == "cnindex-capture-20261103-600036-001"
    assert result.proof.known_at == _RECEIVED_AT
    assert result.proof.profile_key == "risk-center-simulation-test"
    assert result.proof.profile_version == 3
    assert result.proof.policy_content_sha256 == _policy().normalized_config_sha256
    assert result.proof.policy_acceptance_deadline == datetime(2026, 11, 3, 16, tzinfo=UTC)
    assert result.proof.http_status == 200
    assert result.proof.body_complete is True


def test_date_proof_domain_rejects_tampered_scope_mode_and_coverage() -> None:
    proof = _decision().proof
    assert proof is not None
    domain_proof = proof.to_domain()

    with pytest.raises(ValueError, match="date snapshot proof must be simulation-only"):
        replace(domain_proof, scope=cast(Literal["simulation_only"], "live"))
    with pytest.raises(ValueError, match="date snapshot proof must be simulation-only"):
        replace(domain_proof, source_kind=cast(Literal["industry_membership"], "valuation"))
    with pytest.raises(ValueError, match="date snapshot proof must be simulation-only"):
        replace(
            domain_proof,
            clock_evidence_mode=cast(
                Literal["policy_bounded_date_snapshot"], "source_clocks_required"
            ),
        )
    with pytest.raises(ValueError, match="coverage_status must be complete or partial"):
        replace(
            domain_proof,
            coverage_status=cast(Literal["complete", "partial"], "unknown"),
        )


def test_date_proof_recomputes_age_and_inclusive_membership_deadlines() -> None:
    application_proof = _decision(policy=_policy(max_date_age_days=2)).proof
    assert application_proof is not None
    proof = application_proof.to_domain()

    with pytest.raises(ValueError, match="date_age_deadline must use the configured"):
        replace(proof, source_max_date_age_days=1)

    changed_membership_deadline = proof.membership_deadline + timedelta(days=1)
    changed_acceptance_deadline = min(
        proof.date_age_deadline,
        changed_membership_deadline,
        *proof.policy_deadlines,
    )
    with pytest.raises(ValueError, match="membership_deadline must follow"):
        replace(
            proof,
            membership_deadline=changed_membership_deadline,
            policy_acceptance_deadline=changed_acceptance_deadline,
        )


def test_earliest_existing_calendar_or_baseline_deadline_wins() -> None:
    """The source's same-day and age cutoffs cannot outlive an earlier policy deadline."""

    earlier = _AS_OF + timedelta(minutes=20)
    result = _decision(additional_policy_deadlines=(earlier,))

    assert result.qualified is True
    assert result.proof is not None
    assert result.proof.policy_acceptance_deadline == earlier
    assert result.proof.date_age_deadline == datetime(2026, 11, 3, 16, tzinfo=UTC)
    assert result.proof.membership_deadline == datetime(2026, 11, 3, 16, tzinfo=UTC)


def test_date_age_window_is_inclusive_and_does_not_extend_same_day_membership() -> None:
    """A configured age bound cannot outlive an inclusive point-day membership."""

    result = _decision(policy=_policy(max_date_age_days=1))

    assert result.qualified is True
    assert result.proof is not None
    assert result.proof.date_age_deadline == datetime(2026, 11, 4, 16, tzinfo=UTC)
    assert result.proof.policy_acceptance_deadline == datetime(2026, 11, 3, 16, tzinfo=UTC)


def test_partial_coverage_is_preserved_instead_of_promoted() -> None:
    """A clock receipt does not change the provider's partial-coverage statement."""

    result = _decision(evidence=_source_evidence(coverage_status=CoverageStatus.PARTIAL))

    assert result.qualified is True
    assert result.proof is not None
    assert result.proof.coverage_status is CoverageStatus.PARTIAL


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("capture_before_cutoff", "PORTFOLIO_RISK_DATE_SNAPSHOT_CAPTURE_AFTER_CUTOFF"),
        ("known_before_receipt", "PORTFOLIO_RISK_DATE_SNAPSHOT_KNOWN_BEFORE_RECEIPT"),
        ("wrong_body", "PORTFOLIO_RISK_DATE_SNAPSHOT_RECEIPT_BODY_MISMATCH"),
        ("incomplete_capture", "PORTFOLIO_RISK_DATE_SNAPSHOT_CAPTURE_INCOMPLETE"),
        ("future_observation", "PORTFOLIO_RISK_DATE_SNAPSHOT_OBSERVATION_DATE_MISMATCH"),
        ("open_membership", "PORTFOLIO_RISK_DATE_SNAPSHOT_MEMBERSHIP_NOT_BOUNDED"),
        ("wide_membership", "PORTFOLIO_RISK_DATE_SNAPSHOT_MEMBERSHIP_NOT_SAME_DAY"),
        ("wrong_taxonomy", "PORTFOLIO_RISK_DATE_SNAPSHOT_TAXONOMY_BINDING_MISMATCH"),
        ("unknown_coverage", "PORTFOLIO_RISK_DATE_SNAPSHOT_COVERAGE_UNKNOWN"),
    ],
)
def test_incomplete_or_misaligned_evidence_fails_closed(mutation: str, reason: str) -> None:
    """A date receipt never replaces missing identity, observation, or effective facts."""

    if mutation == "capture_before_cutoff":
        result = _decision(as_of=_RECEIVED_AT - timedelta(seconds=1))
    elif mutation == "known_before_receipt":
        result = _decision(evidence=_source_evidence(known_at=_RECEIVED_AT - timedelta(seconds=1)))
    elif mutation == "wrong_body":
        result = _decision(original_body=b'{"code":200,"data":{}}')
    elif mutation == "incomplete_capture":
        result = _decision(receipt=_receipt(body_complete=False))
    elif mutation == "future_observation":
        result = _decision(evidence=_source_evidence(observed_on=date(2026, 11, 4)))
    elif mutation == "open_membership":
        open_evidence = replace(_source_evidence(), effective_until=None)
        result = _decision(
            evidence=open_evidence,
            membership=_membership(
                evidence=open_evidence,
                effective_until=None,
                end_state=EffectiveEndState.OPEN,
            ),
        )
    elif mutation == "wide_membership":
        wide_evidence = replace(_source_evidence(), effective_until=None)
        result = _decision(
            evidence=wide_evidence,
            membership=_membership(
                effective_until=date(2026, 11, 4),
                evidence=wide_evidence,
            ),
        )
    elif mutation == "wrong_taxonomy":
        result = _decision(membership=_membership(taxonomy_id="unapproved-taxonomy"))
    else:
        result = _decision(evidence=_source_evidence(coverage_status=CoverageStatus.UNKNOWN))

    assert result.qualified is False
    assert reason in result.reason_codes
    assert result.proof is None


@pytest.mark.parametrize(
    ("evidence", "reason"),
    [
        (
            _source_evidence(allowed_purposes=("some_other_purpose",)),
            "RISK_SOURCE_PURPOSE_NOT_ALLOWED",
        ),
        (_source_evidence(must_not_use=True), "RISK_SOURCE_PROHIBITED_FOR_DECISION"),
    ],
)
def test_source_permissions_and_prohibitions_remain_mandatory(
    evidence: PortfolioRiskSourceEvidence,
    reason: str,
) -> None:
    """Only the two absent source clock fields receive the special treatment."""

    result = _decision(evidence=evidence)

    assert result.qualified is False
    assert reason in result.reason_codes


def test_source_pin_and_profile_policy_date_allowlist_remain_mandatory() -> None:
    """Wrong raw record identity and disallowed DATE purpose are not waived by receipt."""

    policy = _policy()
    mismatched_reference = replace(
        policy.source_references[0],
        raw_payload_hash="sha256:" + "b" * 64,
    )
    pinned = _decision(
        reference=mismatched_reference,
        retained_payload_hash=_MANIFEST_HASH,
    )
    assert pinned.qualified is False
    assert "PORTFOLIO_RISK_DATE_SNAPSHOT_MANIFEST_PIN_MISMATCH" in pinned.reason_codes

    with pytest.raises(PortfolioRiskPolicyConfigurationError) as error:
        _policy(date_purposes=())

    assert error.value.reason_code == "SIMULATED_PORTFOLIO_RISK_RUNTIME_IDENTITY_INVALID"
    assert isinstance(error.value.__cause__, ValueError)
    assert "date snapshot mode requires an explicitly allowed DATE purpose" in str(
        error.value.__cause__
    )


def test_account_outside_runtime_policy_scope_cannot_use_date_receipt() -> None:
    """A valid source receipt cannot widen the runtime policy's account scope."""

    result = _decision(account_id=13)

    assert result.qualified is False
    assert "PORTFOLIO_RISK_DATE_SNAPSHOT_ACCOUNT_SCOPE_MISMATCH" in result.reason_codes


def test_business_timezone_name_must_match_the_deadline_timezone() -> None:
    """A caller cannot derive a valid-day boundary with a different named timezone."""

    result = _decision(timezone_name="UTC")

    assert result.qualified is False
    assert "PORTFOLIO_RISK_DATE_SNAPSHOT_TIMEZONE_BINDING_MISMATCH" in result.reason_codes


def test_generic_mode_does_not_use_capture_clock_substitution() -> None:
    """The date-only path is opt-in; strict source clocks still reject these nulls."""

    result = qualify_policy_bounded_industry_date_snapshot(
        clock_evidence_mode=PortfolioRiskClockEvidenceMode.SOURCE_CLOCKS_REQUIRED,
        policy=_policy(),
        source_reference=_policy().source_references[0],
        retained_payload_hash=_MANIFEST_HASH,
        account_id=12,
        asset_code="600036.SH",
        security_id="equity:SH:600036",
        membership=_membership(),
        receipt=_receipt(),
        original_body=_BODY,
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE,
        business_timezone=_BUSINESS_ZONE,
        business_timezone_name="Asia/Shanghai",
    )

    assert result.qualified is False
    assert "PORTFOLIO_RISK_DATE_SNAPSHOT_CLOCK_MODE_NOT_ENABLED" in result.reason_codes


def test_capture_receipt_rejects_non_success_transport_status() -> None:
    """HTTP error responses cannot create a qualified date snapshot proof."""

    result = _decision(receipt=_receipt(http_status=404))

    assert result.qualified is False
    assert "PORTFOLIO_RISK_DATE_SNAPSHOT_CAPTURE_NOT_SUCCESSFUL" in result.reason_codes


def test_missing_or_explicit_strict_mode_keeps_legacy_source_reference_hash() -> None:
    """Old policy JSON remains strict and normalizes identically to explicit strict mode."""

    omitted = _policy(clock_evidence_mode=None)
    explicit = _policy(clock_evidence_mode="source_clocks_required")

    assert omitted.source_references[0].clock_evidence_mode == "source_clocks_required"
    assert omitted.normalized_config_sha256 == explicit.normalized_config_sha256


def test_date_snapshot_mode_is_rejected_for_other_source_kinds() -> None:
    """A per-reference clock exception cannot be assigned to valuation or capacity."""

    with pytest.raises(ValueError):
        replace(
            _policy().source_references[0],
            kind="valuation",
        )


def test_verified_industry_proof_supplies_only_its_policy_deadline_to_execution() -> None:
    policy = _policy()
    qualification = _decision(policy=policy)
    assert qualification.proof is not None
    evidence = replace(
        _source_evidence(),
        policy_clock_proof=qualification.proof.to_domain(),
    )
    later_baseline_deadline = _AS_OF + timedelta(hours=2)

    deadline = portfolio_risk_execution_deadline_for_evidence(
        evidence,
        policy,
        account_id=12,
        business_timezone=_BUSINESS_ZONE,
        additional_policy_deadlines=(later_baseline_deadline,),
    )

    assert deadline == qualification.proof.policy_acceptance_deadline
    earlier_baseline_deadline = _AS_OF + timedelta(minutes=30)
    assert (
        portfolio_risk_execution_deadline_for_evidence(
            evidence,
            policy,
            account_id=12,
            business_timezone=_BUSINESS_ZONE,
            additional_policy_deadlines=(earlier_baseline_deadline,),
        )
        == earlier_baseline_deadline
    )
    assert (
        portfolio_risk_execution_deadline_for_evidence(
            _source_evidence(),
            policy,
            account_id=12,
            business_timezone=_BUSINESS_ZONE,
            additional_policy_deadlines=(),
        )
        is None
    )
    assert (
        portfolio_risk_execution_deadline_for_evidence(
            evidence,
            policy,
            account_id=13,
            business_timezone=_BUSINESS_ZONE,
            additional_policy_deadlines=(),
        )
        is None
    )


def test_report_codec_preserves_and_revalidates_the_industry_clock_proof() -> None:
    policy = _policy()
    qualification = _decision(policy=policy)
    assert qualification.proof is not None
    evidence = replace(
        _source_evidence(),
        policy_clock_proof=qualification.proof.to_domain(),
    )
    report: dict[str, object] = {
        "account_id": 12,
        "as_of": _AS_OF.isoformat(),
        "outcome": "allowed",
        "policy_version": f"{policy.profile_key}@{policy.profile_version}",
        "resource_snapshot_hash": "a" * 64,
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
    assert source["available_at"] is None
    assert source["valid_until"] is None
    assert source["clock_evidence_proof"]["proven_available_at"] == _RECEIVED_AT.isoformat()
    assert source["clock_evidence_proof"]["proven_available_at"].endswith("+08:00")
    tampered = dict(report)
    tampered_source = dict(cast(dict[str, object], report["sources"][0]))
    tampered_proof = dict(cast(dict[str, object], tampered_source["clock_evidence_proof"]))
    tampered_proof["proven_available_at"] = (_AS_OF + timedelta(seconds=1)).isoformat()
    tampered_source["clock_evidence_proof"] = tampered_proof
    tampered["sources"] = [tampered_source]
    assert decode_portfolio_risk_report_json(canonical_portfolio_risk_json(tampered)) is None
