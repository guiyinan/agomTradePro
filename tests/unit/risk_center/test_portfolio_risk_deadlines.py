"""Focused contracts for exact source-age and policy execution deadlines."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from apps.config_center.application.runtime_value_evidence import ActiveRuntimeValueEvidence
from apps.risk_center.application.portfolio_risk_deadlines import (
    portfolio_risk_execution_deadline,
)
from apps.risk_center.application.portfolio_risk_policy import (
    SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY,
    PortfolioRiskPolicyBundle,
    parse_portfolio_risk_policy_bundle,
)
from apps.risk_center.domain.portfolio_risk_sources import (
    CoverageStatus,
    PortfolioRiskCoverage,
    PortfolioRiskSourceEvidence,
    SourceObservationPrecision,
)

_AS_OF = datetime(2026, 11, 3, 8, 0, tzinfo=timezone.utc)
_BUSINESS_DATE = date(2026, 11, 3)


def _policy_bundle() -> PortfolioRiskPolicyBundle:
    """Parse the same typed, profile-bound policy used by the risk application."""

    configuration: dict[str, object] = {
        "schema_version": "ash07.simulated_portfolio_risk.v1",
        "scope": "simulation_only",
        "ledger_money_unit": "CNY",
        "account_ids": [12],
        "industry": {
            "taxonomy_id": "industry-deadline-test-v1",
            "taxonomy_kind": "industry",
            "provider_id": "provider-test",
            "provider_version": "v1",
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
            "allowed_observation_precisions": ["timestamp"],
            "date_precision_purposes": [],
            "allowed_source_restrictions": [],
        },
        "source_max_timestamp_age_seconds": 1800,
        "source_max_date_age_days": 5,
        "source_references": [
            {
                "kind": "valuation",
                "asset_code": "600036",
                "security_id": "SSE:600036",
                "raw_payload_hash": "sha256:" + "a" * 64,
                "source_record_id": "valuation-record-1",
            },
        ],
    }
    created_at = _AS_OF - timedelta(minutes=5)
    effective_at = _AS_OF - timedelta(minutes=3)
    runtime_evidence = ActiveRuntimeValueEvidence(
        environment="development",
        definition_key=SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY,
        value=configuration,
        profile_id="runtime-profile-deadline-test",
        profile_key="risk-center-deadline-test",
        profile_version=12,
        profile_content_hash="e" * 64,
        snapshot_id="risk-deadline-test-snapshot",
        snapshot_hash="f" * 64,
        created_at=created_at,
        known_at=created_at,
        activated_at=effective_at,
        snapshot_generated_at=_AS_OF - timedelta(minutes=2),
        effective_at=effective_at,
        as_of=_AS_OF,
    )
    return parse_portfolio_risk_policy_bundle(
        runtime_evidence,
        business_date=_BUSINESS_DATE,
        as_of=_AS_OF,
    )


def _source(
    *,
    precision: SourceObservationPrecision,
    observed_at: datetime | None,
    observed_on: date | None,
    valid_until: datetime | None,
    decision_date_cutoff: date | None = None,
) -> PortfolioRiskSourceEvidence:
    """Build one retained source evidence row without synthetic clocks."""

    return PortfolioRiskSourceEvidence(
        source_id="source-deadline-test",
        source_record_id="record-deadline-test",
        original_payload_sha256="b" * 64,
        observation_precision=precision,
        observed_at=observed_at,
        observed_on=observed_on,
        available_at=_AS_OF - timedelta(minutes=1),
        known_at=_AS_OF - timedelta(minutes=1),
        decision_cutoff=_AS_OF,
        decision_date_cutoff=decision_date_cutoff,
        valid_until=valid_until,
        source_purpose="ash07_portfolio_exposure",
        allowed_purposes=("ash07_portfolio_exposure",),
        restrictions=(),
        must_not_use_for_decision=False,
        coverage=PortfolioRiskCoverage(
            status=CoverageStatus.COMPLETE,
            precision_basis="source_rows",
            reported_weight_fraction=Decimal("1"),
        ),
    )


def test_timestamp_deadline_uses_utc_observation_age_and_all_real_end_times() -> None:
    """The earliest source-age, source-expiry, and actual policy end wins."""

    policy = _policy_bundle()
    observed_at = datetime(2026, 11, 3, 15, 50, tzinfo=ZoneInfo("Asia/Shanghai"))
    age_deadline = datetime(2026, 11, 3, 8, 20, tzinfo=timezone.utc)
    evidence = _source(
        precision=SourceObservationPrecision.TIMESTAMP,
        observed_at=observed_at,
        observed_on=None,
        valid_until=age_deadline,
    )

    assert (
        portfolio_risk_execution_deadline(
            evidence,
            policy,
            business_timezone=ZoneInfo("Asia/Shanghai"),
            additional_policy_deadlines=(datetime(2026, 11, 3, 8, 25, tzinfo=timezone.utc),),
        )
        == age_deadline
    )
    assert evidence.observed_at == observed_at

    assert portfolio_risk_execution_deadline(
        replace(evidence, valid_until=datetime(2026, 11, 3, 8, 15, tzinfo=timezone.utc)),
        policy,
        business_timezone=ZoneInfo("Asia/Shanghai"),
        additional_policy_deadlines=(),
    ) == datetime(2026, 11, 3, 8, 15, tzinfo=timezone.utc)
    assert portfolio_risk_execution_deadline(
        evidence,
        policy,
        business_timezone=ZoneInfo("Asia/Shanghai"),
        additional_policy_deadlines=(datetime(2026, 11, 3, 8, 10, tzinfo=timezone.utc),),
    ) == datetime(2026, 11, 3, 8, 10, tzinfo=timezone.utc)

    boundary_policy = replace(policy, as_of=age_deadline)
    boundary_evidence = replace(
        evidence,
        decision_cutoff=age_deadline,
        valid_until=age_deadline + timedelta(minutes=10),
    )
    assert (
        portfolio_risk_execution_deadline(
            boundary_evidence,
            boundary_policy,
            business_timezone=ZoneInfo("Asia/Shanghai"),
            additional_policy_deadlines=(),
        )
        is None
    )


def test_date_deadline_is_local_policy_boundary_without_a_synthetic_source_time() -> None:
    """Date-only evidence expires after the final permitted local calendar day."""

    policy = _policy_bundle()
    business_timezone = ZoneInfo("Asia/Shanghai")
    observed_on = _BUSINESS_DATE - timedelta(days=5)
    evidence = _source(
        precision=SourceObservationPrecision.DATE,
        observed_at=None,
        observed_on=observed_on,
        valid_until=datetime(2026, 11, 10, tzinfo=timezone.utc),
        decision_date_cutoff=_BUSINESS_DATE,
    )

    expected_local_expiry = datetime.combine(
        observed_on + timedelta(days=6),
        time.min,
        tzinfo=business_timezone,
    ).astimezone(timezone.utc)
    assert (
        portfolio_risk_execution_deadline(
            evidence,
            policy,
            business_timezone=business_timezone,
            additional_policy_deadlines=(),
        )
        == expected_local_expiry
    )
    assert evidence.observed_at is None
    assert evidence.observed_on == observed_on


def test_missing_expiry_unknown_precision_and_expired_boundary_fail_closed() -> None:
    """No missing source clock or expiry is repaired from the current cutoff."""

    policy = _policy_bundle()
    evidence = _source(
        precision=SourceObservationPrecision.TIMESTAMP,
        observed_at=_AS_OF - timedelta(minutes=1),
        observed_on=None,
        valid_until=_AS_OF + timedelta(minutes=10),
    )
    business_timezone = ZoneInfo("Asia/Shanghai")

    assert (
        portfolio_risk_execution_deadline(
            replace(evidence, valid_until=None),
            policy,
            business_timezone=business_timezone,
            additional_policy_deadlines=(),
        )
        is None
    )
    unknown = replace(
        evidence,
        observation_precision=SourceObservationPrecision.UNKNOWN,
        observed_at=None,
        observed_on=None,
    )
    assert (
        portfolio_risk_execution_deadline(
            unknown,
            policy,
            business_timezone=business_timezone,
            additional_policy_deadlines=(),
        )
        is None
    )
    assert (
        portfolio_risk_execution_deadline(
            replace(evidence, valid_until=_AS_OF),
            policy,
            business_timezone=business_timezone,
            additional_policy_deadlines=(),
        )
        is None
    )
    assert (
        portfolio_risk_execution_deadline(
            evidence,
            policy,
            business_timezone=business_timezone,
            additional_policy_deadlines=(datetime(2026, 11, 3, 8, 30),),
        )
        is None
    )
