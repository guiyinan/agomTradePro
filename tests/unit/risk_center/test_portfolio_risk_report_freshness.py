"""Report-level freshness and decision-use contracts for ASH07 source evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from apps.config_center.application.runtime_value_evidence import ActiveRuntimeValueEvidence
from apps.risk_center.application.portfolio_risk_assets import (
    PortfolioRiskAssetInputs,
    PortfolioRiskAssetReadStatus,
    PortfolioRiskAssetsReadResult,
)
from apps.risk_center.application.portfolio_risk_contracts import PortfolioRiskReportPayload
from apps.risk_center.application.portfolio_risk_policy import (
    SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY,
    PortfolioRiskPolicyBundle,
    PortfolioRiskSourceReference,
    parse_portfolio_risk_policy_bundle,
)
from apps.risk_center.application.portfolio_risk_report import (
    _ReportSourceUseRule,
    _source_use_qualification_reasons,
    build_portfolio_risk_report,
)
from apps.risk_center.domain.portfolio_exposure_types import (
    ExposureOutcome,
    PortfolioAssetKind,
    PortfolioIndustryExposureAssessment,
)
from apps.risk_center.domain.portfolio_risk_snapshot import AccountSnapshot
from apps.risk_center.domain.portfolio_risk_sources import (
    CoverageStatus,
    PortfolioRiskCoverage,
    PortfolioRiskSourceEvidence,
    SourceObservationPrecision,
)

_AS_OF = datetime(2026, 11, 3, 8, 0, tzinfo=UTC)
_BUSINESS_DATE = date(2026, 11, 3)
_ASSET_CODE = "600000.SH"
_SECURITY_ID = "equity:SH:600000"
_PURPOSE = "lagged_portfolio_exposure"
_SOURCE_HASH = "a" * 64
_MANIFEST_HASH = "b" * 64


def _policy() -> PortfolioRiskPolicyBundle:
    """Parse one explicit runtime policy whose date source use is purpose-bound."""

    configuration: dict[str, object] = {
        "schema_version": "ash07.simulated_portfolio_risk.v1",
        "scope": "simulation_only",
        "ledger_money_unit": "CNY",
        "account_ids": [42],
        "industry": {
            "taxonomy_id": "sw-2021",
            "taxonomy_kind": "industry",
            "provider_id": "sector-provider",
            "provider_version": "2026-q3",
            "requested_purpose": _PURPOSE,
            "date_precision_purposes": [_PURPOSE],
            "allowed_observation_precisions": ["date", "timestamp"],
            "allowed_source_restrictions": [],
            "coverage_precision_basis": "official_nav_weight",
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
        "source_max_date_age_days": 5,
        "source_references": [
            {
                "kind": "valuation",
                "asset_code": _ASSET_CODE,
                "security_id": _SECURITY_ID,
                "raw_payload_hash": f"sha256:{_MANIFEST_HASH}",
                "source_record_id": "valuation-record-1",
            }
        ],
    }
    created_at = _AS_OF - timedelta(minutes=10)
    effective_at = _AS_OF - timedelta(minutes=30)
    snapshot_generated_at = _AS_OF - timedelta(minutes=5)
    runtime_evidence = ActiveRuntimeValueEvidence(
        environment="development",
        definition_key=SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY,
        value=configuration,
        profile_id="risk-profile-42",
        profile_key="risk-development",
        profile_version=42,
        profile_content_hash="b" * 64,
        snapshot_id="risk-snapshot-42",
        snapshot_hash="c" * 64,
        created_at=created_at,
        known_at=created_at,
        activated_at=effective_at,
        snapshot_generated_at=snapshot_generated_at,
        effective_at=effective_at,
        as_of=_AS_OF,
    )
    return parse_portfolio_risk_policy_bundle(
        runtime_evidence,
        business_date=_BUSINESS_DATE,
        as_of=_AS_OF,
    )


def _evidence(
    *,
    valid_until: datetime | None = None,
    precision: SourceObservationPrecision = SourceObservationPrecision.DATE,
    observed_on: date = date(2026, 10, 31),
    prohibited: bool = False,
    source_purpose: str = "published_valuation_record",
    coverage_status: CoverageStatus = CoverageStatus.COMPLETE,
) -> PortfolioRiskSourceEvidence:
    """Create source clocks with an old but policy-allowed date observation."""

    observed_at = (
        _AS_OF - timedelta(minutes=10)
        if precision is SourceObservationPrecision.TIMESTAMP
        else None
    )
    source_date = observed_on if precision is SourceObservationPrecision.DATE else None
    return PortfolioRiskSourceEvidence(
        source_id="valuation-provider",
        source_record_id="valuation-record-1",
        original_payload_sha256=_SOURCE_HASH,
        observation_precision=precision,
        observed_at=observed_at,
        observed_on=source_date,
        available_at=_AS_OF - timedelta(days=2),
        known_at=_AS_OF - timedelta(days=2),
        decision_cutoff=_AS_OF,
        decision_date_cutoff=(
            _BUSINESS_DATE if precision is SourceObservationPrecision.DATE else None
        ),
        valid_until=valid_until or (_AS_OF + timedelta(days=1)),
        source_purpose=source_purpose,
        allowed_purposes=(_PURPOSE,),
        restrictions=(),
        must_not_use_for_decision=prohibited,
        coverage=PortfolioRiskCoverage(
            status=coverage_status,
            precision_basis="point_valuation_record",
            reported_weight_fraction=(
                Decimal("0.75")
                if coverage_status is CoverageStatus.PARTIAL
                else Decimal("1") if coverage_status is CoverageStatus.COMPLETE else None
            ),
            expected_item_count=(4 if coverage_status is CoverageStatus.PARTIAL else 1),
            observed_item_count=(3 if coverage_status is CoverageStatus.PARTIAL else 1),
        ),
    )


def _report(
    policy: PortfolioRiskPolicyBundle,
    evidence: PortfolioRiskSourceEvidence,
    *,
    reader_status: PortfolioRiskAssetReadStatus = "complete",
) -> PortfolioRiskReportPayload:
    """Build the full public report path with only the selected evidence row."""

    reasons = () if reader_status == "complete" else ("RISK_INPUTS_PARTIAL",)
    asset_inputs = PortfolioRiskAssetsReadResult(
        status=reader_status,
        assets=(
            PortfolioRiskAssetInputs(
                asset_code=_ASSET_CODE,
                security_id=_SECURITY_ID,
                kind=PortfolioAssetKind.EQUITY,
                price=Decimal("10"),
                quantity_unit="share",
                price_unit="CNY",
                valuation_evidence=evidence,
                industry_membership=None,
                etf_report=None,
                capacity_observation=None,
            ),
        ),
        all_source_evidence=(evidence,),
        reason_codes=reasons,
        policy_snapshot_id=policy.snapshot_id,
        policy_snapshot_hash=policy.snapshot_hash,
        source_reference_bindings=policy.source_references,
    )
    snapshot = AccountSnapshot(
        account_id=42,
        owner_user_id=77,
        snapshot_id="portfolio-snapshot-1",
        read_at=_AS_OF - timedelta(seconds=5),
        cash=Decimal("1000"),
        money_unit="CNY",
        holdings=(),
        active_orders=(),
        executed_usage=(),
        active_orders_complete=True,
        execution_session=_BUSINESS_DATE,
        executed_usage_complete=True,
    )
    industry = PortfolioIndustryExposureAssessment(
        portfolio_snapshot_id=snapshot.snapshot_id,
        policy_id=policy.profile_id,
        policy_version=str(policy.profile_version),
        policy_content_sha256=policy.normalized_config_sha256,
        as_of=_AS_OF,
        outcome=ExposureOutcome.LIMIT_BREACHED,
        industry_bounds=(),
        security_bounds=(),
        etf_bounds=(),
        repeated_underlyings=(),
        unknown_industry_market_value=None,
        unknown_security_market_value=None,
        industry_coverage_fraction=Decimal("1"),
        etf_lookthrough_coverage_fraction=Decimal("1"),
        reason_codes=("INDUSTRY_RISK_LIMIT_BREACHED",),
        source_ids=(evidence.source_id,),
        source_evidence=(evidence,),
    )
    return build_portfolio_risk_report(
        snapshot=snapshot,
        proposals=(),
        policy=policy,
        asset_inputs=asset_inputs,
        all_source_evidence=(evidence,),
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE,
        capacity_requested_purpose="ash07_capacity_session",
        scope_reasons=(),
        calculation_reasons=(),
        pre_trade_nav=Decimal("1000"),
        actual_holdings_value=Decimal("0"),
        industry=industry,
        capacity_decisions=(),
        capacity_reasons=(),
        identity_basis={},
    ).payload


def test_explicitly_allowed_lagged_date_source_is_a_qualified_snapshot_veto() -> None:
    """A lagged report stays source-bound at its disclosed date and can veto a limit."""

    report = _report(_policy(), _evidence())

    assert report["freshness"] == "qualified_snapshot"
    assert report["reliability"] == "source_bound"
    assert report["must_not_use_for_decision"] is False
    assert report["must_not_execute"] is True
    source = report["sources"][0]
    assert source["observed_on"] == "2026-10-31"
    assert source["observed_at"] is None
    assert source["must_not_use_for_decision"] is False
    assert report["outcome"] == "blocked"
    assert _policy().source_references[0].raw_payload_hash != f"sha256:{_SOURCE_HASH}"


def test_shared_record_id_uses_each_exact_asset_binding_not_the_body_hash() -> None:
    """Manifest pins remain distinct from body hashes and same record IDs stay scoped."""

    policy = _policy()
    first_reference = replace(
        policy.source_references[0],
        source_record_id="shared-response-record",
    )
    second_reference = PortfolioRiskSourceReference(
        kind="valuation",
        asset_code="600001.SH",
        security_id="equity:SH:600001",
        raw_payload_hash=f"sha256:{'c' * 64}",
        source_record_id="shared-response-record",
    )
    policy = replace(policy, source_references=(first_reference, second_reference))
    evidence = replace(_evidence(), source_record_id="shared-response-record")

    def reasons_for(
        *, asset_code: str, security_id: str, bindings: tuple[PortfolioRiskSourceReference, ...]
    ) -> tuple[str, ...]:
        rule = _ReportSourceUseRule(
            evidence=evidence,
            purpose=policy.industry_policy.requested_purpose,
            allowed_precisions=policy.industry_policy.allowed_observation_precisions,
            date_precision_purposes=policy.industry_policy.date_precision_purposes,
            allowed_restrictions=policy.industry_policy.allowed_source_restrictions,
            coverage_precision_basis=None,
            source_role="valuation",
            asset_code=asset_code,
            security_id=security_id,
        )
        return _source_use_qualification_reasons(
            rule=rule,
            policy=policy,
            as_of=_AS_OF,
            business_date=_BUSINESS_DATE,
            execution_session=_BUSINESS_DATE,
            account_id=42,
            source_reference_bindings=bindings,
        )

    both = (first_reference, second_reference)
    assert "PORTFOLIO_REPORT_SOURCE_REFERENCE_BINDING_MISMATCH" not in reasons_for(
        asset_code=_ASSET_CODE,
        security_id=_SECURITY_ID,
        bindings=both,
    )
    assert "PORTFOLIO_REPORT_SOURCE_REFERENCE_BINDING_MISMATCH" not in reasons_for(
        asset_code="600001.SH",
        security_id="equity:SH:600001",
        bindings=both,
    )
    assert "PORTFOLIO_REPORT_SOURCE_REFERENCE_BINDING_MISMATCH" in reasons_for(
        asset_code="600001.SH",
        security_id="equity:SH:600001",
        bindings=(first_reference,),
    )
    wrong_manifest_pin = replace(
        second_reference,
        raw_payload_hash=f"sha256:{'d' * 64}",
    )
    assert "PORTFOLIO_REPORT_SOURCE_REFERENCE_BINDING_MISMATCH" in reasons_for(
        asset_code="600001.SH",
        security_id="equity:SH:600001",
        bindings=(wrong_manifest_pin,),
    )


def test_expired_source_is_expired_unknown_and_prohibited_for_decision() -> None:
    """An expired source cannot be rescued by a complete reader status or veto result."""

    report = _report(_policy(), _evidence(valid_until=_AS_OF))

    assert report["freshness"] == "expired"
    assert report["reliability"] == "unknown"
    assert report["must_not_use_for_decision"] is True
    assert report["must_not_execute"] is True
    assert report["sources"][0]["valid_until"] == _AS_OF.isoformat()


def test_partial_or_globally_prohibited_source_stays_prohibited() -> None:
    """Unknown coverage and source-level prohibitions remain visible and fail closed."""

    partial = _report(
        _policy(),
        _evidence(coverage_status=CoverageStatus.PARTIAL),
        reader_status="partial",
    )
    prohibited = _report(
        _policy(),
        _evidence(prohibited=True, source_purpose="research_only"),
        reader_status="partial",
    )
    unknown_clock = _report(
        _policy(),
        _evidence(precision=SourceObservationPrecision.UNKNOWN),
        reader_status="partial",
    )

    assert partial["freshness"] == "unknown"
    assert partial["reliability"] == "partial"
    assert partial["must_not_use_for_decision"] is True
    assert prohibited["freshness"] == "unknown"
    assert prohibited["must_not_use_for_decision"] is True
    assert prohibited["sources"][0]["must_not_use_for_decision"] is True
    assert unknown_clock["freshness"] == "unknown"
    assert unknown_clock["must_not_use_for_decision"] is True
    assert unknown_clock["sources"][0]["observed_at"] is None
    assert unknown_clock["sources"][0]["observed_on"] is None
