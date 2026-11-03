"""Contract tests for strict runtime-backed simulation risk policy reads."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest

from apps.config_center.application.runtime_value_evidence import ActiveRuntimeValueEvidence
from apps.risk_center.application.portfolio_risk_policy import (
    SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY,
    PortfolioRiskPolicyConfigurationError,
    parse_portfolio_risk_policy_bundle,
)
from apps.risk_center.domain.portfolio_exposure import assess_portfolio_industry_exposure
from apps.risk_center.domain.portfolio_exposure_types import (
    ExposureOutcome,
    PortfolioExposureProjection,
)
from apps.risk_center.infrastructure import configured_portfolio_risk_policy_reader

_AS_OF = datetime(2026, 11, 3, 8, 0, tzinfo=UTC)
_BUSINESS_DATE = date(2026, 11, 3)


def _configuration() -> dict[str, object]:
    """Build one explicit simulation policy with all limits and source pins present."""

    return {
        "schema_version": "ash07.simulated_portfolio_risk.v1",
        "scope": "simulation_only",
        "ledger_money_unit": "CNY",
        "account_ids": [12, 8],
        "industry": {
            "taxonomy_id": "sw-2021",
            "taxonomy_kind": "industry",
            "provider_id": "provider-a",
            "provider_version": "v2026.10",
            "requested_purpose": "ash07_portfolio_exposure",
            "date_precision_purposes": ["ash07_portfolio_exposure"],
            "allowed_observation_precisions": ["timestamp", "date"],
            "allowed_source_restrictions": ["session_only"],
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
                "asset_code": "000001.SZ",
                "security_id": "equity:SZ:000001",
                "raw_payload_hash": "sha256:" + "a" * 64,
                "source_record_id": "valuation-record-1",
            },
            {
                "kind": "industry_membership",
                "asset_code": "000001.SZ",
                "security_id": "equity:SZ:000001",
                "raw_payload_hash": "sha256:" + "b" * 64,
                "source_record_id": "industry-record-1",
            },
            {
                "kind": "etf_report",
                "asset_code": "510300.SH",
                "security_id": "etf:SH:510300",
                "raw_payload_hash": "sha256:" + "c" * 64,
                "source_record_id": "etf-record-1",
            },
            {
                "kind": "capacity_window",
                "asset_code": "000001.SZ",
                "security_id": "equity:SZ:000001",
                "raw_payload_hash": "sha256:" + "d" * 64,
                "source_record_id": "capacity-record-1",
            },
            {
                "kind": "execution_session_state",
                "asset_code": "000001.SZ",
                "security_id": "equity:SZ:000001",
                "raw_payload_hash": "sha256:" + "e" * 64,
                "source_record_id": "trading-state-record-1",
            },
        ],
    }


def _runtime_evidence(
    value: object | None = None,
    *,
    effective_at: datetime = _AS_OF - timedelta(minutes=3),
    snapshot_generated_at: datetime = _AS_OF - timedelta(minutes=2),
    created_at: datetime = _AS_OF - timedelta(minutes=5),
    as_of: datetime = _AS_OF,
) -> ActiveRuntimeValueEvidence:
    """Build real profile/snapshot metadata around one typed JSON value."""

    selected_value = _configuration() if value is None else value
    return ActiveRuntimeValueEvidence(
        environment="development",
        definition_key=SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY,
        value=selected_value,
        profile_id="runtime-profile-12",
        profile_key="risk-center-development",
        profile_version=12,
        profile_content_hash="e" * 64,
        snapshot_id="runtime-snapshot-12",
        snapshot_hash="f" * 64,
        created_at=created_at,
        known_at=created_at,
        activated_at=effective_at,
        snapshot_generated_at=snapshot_generated_at,
        effective_at=effective_at,
        as_of=as_of,
    )


def test_valid_configuration_shares_runtime_identity_and_full_config_digest() -> None:
    """Both policy types share actual profile identity and canonical full-content digest."""

    evidence = _runtime_evidence()
    bundle = parse_portfolio_risk_policy_bundle(
        evidence,
        business_date=_BUSINESS_DATE,
        as_of=_AS_OF,
    )

    assert bundle.schema_version == "ash07.simulated_portfolio_risk.v1"
    assert bundle.scope == "simulation_only"
    assert bundle.account_ids == (8, 12)
    assert bundle.profile_id == evidence.profile_id
    assert bundle.profile_key == evidence.profile_key
    assert bundle.environment == evidence.environment
    assert bundle.profile_version == evidence.profile_version
    assert bundle.snapshot_hash == evidence.snapshot_hash
    assert bundle.normalized_config_sha256 == bundle.industry_policy.content_sha256
    assert bundle.normalized_config_sha256 == bundle.capacity_policy.content_hash
    assert bundle.industry_policy.policy_id == bundle.capacity_policy.policy_id
    assert bundle.industry_policy.policy_version == bundle.capacity_policy.version == "12"
    assert bundle.industry_policy.effective_from == evidence.effective_at
    assert bundle.industry_policy.effective_until is None
    assert bundle.capacity_policy.effective_until is None
    assert bundle.known_at == evidence.snapshot_generated_at
    assert bundle.industry_policy.known_at == bundle.capacity_policy.known_at == bundle.known_at
    assert bundle.source_max_timestamp_age_seconds == 1800
    assert bundle.source_max_date_age_days == 5
    assert {item.kind for item in bundle.source_references} == {
        "valuation",
        "industry_membership",
        "etf_report",
        "capacity_window",
        "execution_session_state",
    }


def test_empty_date_precision_purpose_lists_are_explicit_no_date_allowlists() -> None:
    """Empty date-purpose lists are valid and do not grant DATE evidence permission."""

    configuration = _configuration()
    cast(dict[str, object], configuration["industry"])["date_precision_purposes"] = []

    bundle = parse_portfolio_risk_policy_bundle(
        _runtime_evidence(configuration),
        business_date=_BUSINESS_DATE,
        as_of=_AS_OF,
    )

    assert bundle.industry_policy.date_precision_purposes == ()
    assert bundle.capacity_policy.date_precision_purposes == ()


def test_source_references_are_included_in_canonical_content_digest() -> None:
    """Changing a pinned raw source record changes the policy content identity."""

    first_config = _configuration()
    second_config = _configuration()
    second_sources = cast(list[dict[str, object]], second_config["source_references"])
    second_sources[-1]["raw_payload_hash"] = "sha256:" + "9" * 64

    first = parse_portfolio_risk_policy_bundle(
        _runtime_evidence(first_config),
        business_date=_BUSINESS_DATE,
        as_of=_AS_OF,
    )
    second = parse_portfolio_risk_policy_bundle(
        _runtime_evidence(second_config),
        business_date=_BUSINESS_DATE,
        as_of=_AS_OF,
    )

    assert first.normalized_config_sha256 != second.normalized_config_sha256
    first_state_ref = next(
        item for item in first.source_references if item.kind == "execution_session_state"
    )
    second_state_ref = next(
        item for item in second.source_references if item.kind == "execution_session_state"
    )
    assert first_state_ref.raw_payload_hash != second_state_ref.raw_payload_hash


def test_ledger_money_unit_is_required_and_amount_capacity_must_match_it() -> None:
    """The native ledger currency is explicit config, never an implicit default."""

    missing_unit = _configuration()
    missing_unit.pop("ledger_money_unit")
    with pytest.raises(PortfolioRiskPolicyConfigurationError) as missing_error:
        parse_portfolio_risk_policy_bundle(
            _runtime_evidence(missing_unit),
            business_date=_BUSINESS_DATE,
            as_of=_AS_OF,
        )
    assert missing_error.value.reason_code == "SIMULATED_PORTFOLIO_RISK_CONFIGURATION_INVALID"

    mismatched_amount = _configuration()
    capacity = cast(dict[str, object], mismatched_amount["capacity"])
    capacity["measure"] = "amount"
    capacity["unit"] = "USD"
    with pytest.raises(PortfolioRiskPolicyConfigurationError) as mismatch_error:
        parse_portfolio_risk_policy_bundle(
            _runtime_evidence(mismatched_amount),
            business_date=_BUSINESS_DATE,
            as_of=_AS_OF,
        )
    assert mismatch_error.value.reason_code == "SIMULATED_PORTFOLIO_RISK_CAPACITY_UNIT_MISMATCH"


@pytest.mark.parametrize(
    ("mutation", "reason_code"),
    [
        ("missing_date_age", "SIMULATED_PORTFOLIO_RISK_CONFIGURATION_INVALID"),
        ("unknown_top_level", "SIMULATED_PORTFOLIO_RISK_CONFIGURATION_INVALID"),
        ("unknown_schema", "SIMULATED_PORTFOLIO_RISK_SCHEMA_UNSUPPORTED"),
        ("wrong_scope", "SIMULATED_PORTFOLIO_RISK_SCOPE_UNSUPPORTED"),
        ("boolean_age", "SIMULATED_PORTFOLIO_RISK_CONFIGURATION_INVALID"),
        ("negative_age", "SIMULATED_PORTFOLIO_RISK_CONFIGURATION_INVALID"),
    ],
)
def test_reader_parser_rejects_missing_unknown_or_unsafe_top_level_values(
    mutation: str,
    reason_code: str,
) -> None:
    """No omitted age, unknown field, unrecognized schema or broad scope is accepted."""

    configuration = _configuration()
    if mutation == "missing_date_age":
        configuration.pop("source_max_date_age_days")
    elif mutation == "unknown_top_level":
        configuration["unrecognized"] = True
    elif mutation == "unknown_schema":
        configuration["schema_version"] = "ash07.simulated_portfolio_risk.v9"
    elif mutation == "wrong_scope":
        configuration["scope"] = "broker_live"
    elif mutation == "boolean_age":
        configuration["source_max_timestamp_age_seconds"] = True
    else:
        configuration["source_max_date_age_days"] = -1
    with pytest.raises(PortfolioRiskPolicyConfigurationError) as error:
        parse_portfolio_risk_policy_bundle(
            _runtime_evidence(configuration),
            business_date=_BUSINESS_DATE,
            as_of=_AS_OF,
        )

    assert error.value.reason_code == reason_code


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    [
        ("max_industry_weight", 0.35),
        ("minimum_industry_coverage", "NaN"),
        ("max_participation", 0.08),
        ("increment", "0"),
    ],
)
def test_parser_rejects_float_nonfinite_or_invalid_decimal_text(
    field_name: str,
    replacement: object,
) -> None:
    """Financial limits require exact finite Decimal text and valid domain ranges."""

    configuration = _configuration()
    industry = cast(dict[str, object], configuration["industry"])
    if field_name in industry:
        industry[field_name] = replacement
    else:
        cast(dict[str, object], configuration["capacity"])[field_name] = replacement

    with pytest.raises(PortfolioRiskPolicyConfigurationError):
        parse_portfolio_risk_policy_bundle(
            _runtime_evidence(configuration),
            business_date=_BUSINESS_DATE,
            as_of=_AS_OF,
        )


@pytest.mark.parametrize(
    ("mutation", "reason_code"),
    [
        ("unknown_kind", "SIMULATED_PORTFOLIO_RISK_SOURCE_KIND_UNSUPPORTED"),
        ("bad_hash", "SIMULATED_PORTFOLIO_RISK_SOURCE_HASH_INVALID"),
        ("duplicate", "SIMULATED_PORTFOLIO_RISK_SOURCE_REFERENCE_DUPLICATE"),
        ("empty", "SIMULATED_PORTFOLIO_RISK_SOURCE_REFERENCES_INVALID"),
    ],
)
def test_source_reference_kind_hash_duplicates_and_empty_list_fail_closed(
    mutation: str,
    reason_code: str,
) -> None:
    """Source references require a supported kind, exact hash, uniqueness and an explicit row."""

    configuration = _configuration()
    references = cast(list[dict[str, object]], configuration["source_references"])
    if mutation == "unknown_kind":
        references[0]["kind"] = "market_tape"
    elif mutation == "bad_hash":
        references[0]["raw_payload_hash"] = "sha256:ABC"
    elif mutation == "duplicate":
        references.append(dict(references[0]))
    else:
        configuration["source_references"] = []

    with pytest.raises(PortfolioRiskPolicyConfigurationError) as error:
        parse_portfolio_risk_policy_bundle(
            _runtime_evidence(configuration),
            business_date=_BUSINESS_DATE,
            as_of=_AS_OF,
        )

    assert error.value.reason_code == reason_code


@pytest.mark.parametrize(
    ("section", "reason_code"),
    [
        ("industry", "SIMULATED_PORTFOLIO_RISK_INDUSTRY_POLICY_INVALID"),
        ("capacity", "SIMULATED_PORTFOLIO_RISK_CAPACITY_POLICY_INVALID"),
    ],
)
def test_policy_allowlists_cannot_override_permanent_source_prohibitions(
    section: str,
    reason_code: str,
) -> None:
    """Policy JSON cannot make must-not, research-only or observation-only usable."""

    configuration = _configuration()
    cast(dict[str, object], configuration[section])["allowed_source_restrictions"] = [
        "must_not_use_for_decision"
    ]

    with pytest.raises(PortfolioRiskPolicyConfigurationError) as error:
        parse_portfolio_risk_policy_bundle(
            _runtime_evidence(configuration),
            business_date=_BUSINESS_DATE,
            as_of=_AS_OF,
        )

    assert error.value.reason_code == reason_code


def test_policy_can_be_open_ended_but_future_or_not_yet_known_runtime_is_rejected() -> None:
    """No policy end is invented; actual runtime clocks still gate the requested cutoff."""

    open_policy = parse_portfolio_risk_policy_bundle(
        _runtime_evidence(),
        business_date=_BUSINESS_DATE,
        as_of=_AS_OF,
    )
    assert open_policy.industry_policy.effective_until is None

    with pytest.raises(PortfolioRiskPolicyConfigurationError) as future_error:
        parse_portfolio_risk_policy_bundle(
            _runtime_evidence(effective_at=_AS_OF + timedelta(seconds=1)),
            business_date=_BUSINESS_DATE,
            as_of=_AS_OF,
        )
    assert (
        future_error.value.reason_code == "SIMULATED_PORTFOLIO_RISK_RUNTIME_NOT_CURRENT_AT_CUTOFF"
    )

    with pytest.raises(PortfolioRiskPolicyConfigurationError) as cutoff_error:
        parse_portfolio_risk_policy_bundle(
            _runtime_evidence(),
            business_date=_BUSINESS_DATE,
            as_of=_AS_OF - timedelta(seconds=1),
        )
    assert cutoff_error.value.reason_code == "SIMULATED_PORTFOLIO_RISK_CUTOFF_MISMATCH"


def test_actual_runtime_policy_end_blocks_at_and_after_its_end() -> None:
    """A real bounded policy end remains enforceable after open-ended None support."""

    bundle = parse_portfolio_risk_policy_bundle(
        _runtime_evidence(),
        business_date=_BUSINESS_DATE,
        as_of=_AS_OF,
    )
    bounded_policy = replace(
        bundle.industry_policy,
        effective_until=_AS_OF,
    )
    projection = PortfolioExposureProjection(
        portfolio_snapshot_id="portfolio-snapshot-12",
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE,
        portfolio_market_value=Decimal("100"),
        assets=(),
    )

    assessment = assess_portfolio_industry_exposure(
        policy=bounded_policy,
        projection=projection,
    )

    assert assessment.outcome is ExposureOutcome.BLOCKED
    assert "INDUSTRY_RISK_POLICY_NOT_EFFECTIVE" in assessment.reason_codes


def test_runtime_policy_metadata_never_comes_from_client_configuration() -> None:
    """Client-supplied version or effective clocks are rejected as unknown keys."""

    configuration = _configuration()
    configuration["policy_version"] = "business-v99"
    configuration["effective_at"] = "2099-01-01T00:00:00+00:00"

    with pytest.raises(PortfolioRiskPolicyConfigurationError) as error:
        parse_portfolio_risk_policy_bundle(
            _runtime_evidence(configuration),
            business_date=_BUSINESS_DATE,
            as_of=_AS_OF,
        )

    assert error.value.reason_code == "SIMULATED_PORTFOLIO_RISK_CONFIGURATION_INVALID"


def test_optional_etf_report_age_policy_is_explicit_and_legacy_mode_stays_strict() -> None:
    """The optional report-period limit does not add defaults to old profiles."""

    legacy_configuration = _configuration()
    legacy = parse_portfolio_risk_policy_bundle(
        _runtime_evidence(legacy_configuration),
        business_date=_BUSINESS_DATE,
        as_of=_AS_OF,
    )
    assert legacy.etf_report_policy is None
    assert all(
        reference.clock_evidence_mode == "source_clocks_required"
        for reference in legacy.source_references
        if reference.kind == "etf_report"
    )
    explicitly_strict_configuration = _configuration()
    strict_references = cast(
        list[dict[str, object]],
        explicitly_strict_configuration["source_references"],
    )
    for reference in strict_references:
        reference["clock_evidence_mode"] = "source_clocks_required"
    explicitly_strict = parse_portfolio_risk_policy_bundle(
        _runtime_evidence(explicitly_strict_configuration),
        business_date=_BUSINESS_DATE,
        as_of=_AS_OF,
    )
    assert explicitly_strict.normalized_config_sha256 == legacy.normalized_config_sha256

    configuration = _configuration()
    source_references = cast(list[dict[str, object]], configuration["source_references"])
    etf_reference = next(
        reference for reference in source_references if reference["kind"] == "etf_report"
    )
    etf_reference["clock_evidence_mode"] = "policy_bounded_disclosed_report"
    configuration["etf_report"] = {
        "age_basis": "report_period_end",
        "max_report_age_days": 45,
    }
    configured = parse_portfolio_risk_policy_bundle(
        _runtime_evidence(configuration),
        business_date=_BUSINESS_DATE,
        as_of=_AS_OF,
    )

    assert configured.etf_report_policy is not None
    assert configured.etf_report_policy.age_basis == "report_period_end"
    assert configured.etf_report_policy.max_report_age_days == 45
    assert (
        next(
            reference.clock_evidence_mode
            for reference in configured.source_references
            if reference.kind == "etf_report"
        )
        == "policy_bounded_disclosed_report"
    )
    assert (
        legacy.normalized_config_sha256
        == parse_portfolio_risk_policy_bundle(
            _runtime_evidence(legacy_configuration),
            business_date=_BUSINESS_DATE,
            as_of=_AS_OF,
        ).normalized_config_sha256
    )


def test_disclosed_etf_mode_requires_policy_block_and_valid_explicit_age() -> None:
    """No implicit age limit or malformed block can qualify an ETF report source."""

    configuration = _configuration()
    source_references = cast(list[dict[str, object]], configuration["source_references"])
    etf_reference = next(
        reference for reference in source_references if reference["kind"] == "etf_report"
    )
    etf_reference["clock_evidence_mode"] = "policy_bounded_disclosed_report"
    with pytest.raises(PortfolioRiskPolicyConfigurationError) as absent:
        parse_portfolio_risk_policy_bundle(
            _runtime_evidence(configuration),
            business_date=_BUSINESS_DATE,
            as_of=_AS_OF,
        )
    assert absent.value.reason_code == "SIMULATED_PORTFOLIO_RISK_ETF_REPORT_POLICY_REQUIRED"

    for block in (
        {"age_basis": "report_period_end"},
        {"age_basis": "unknown", "max_report_age_days": 45},
        {"age_basis": "report_period_end", "max_report_age_days": -1},
        {"age_basis": "report_period_end", "max_report_age_days": 45, "ttl": 1},
    ):
        candidate = _configuration()
        references = cast(list[dict[str, object]], candidate["source_references"])
        next(reference for reference in references if reference["kind"] == "etf_report")[
            "clock_evidence_mode"
        ] = "policy_bounded_disclosed_report"
        candidate["etf_report"] = block
        with pytest.raises(PortfolioRiskPolicyConfigurationError) as invalid:
            parse_portfolio_risk_policy_bundle(
                _runtime_evidence(candidate),
                business_date=_BUSINESS_DATE,
                as_of=_AS_OF,
            )
        assert invalid.value.reason_code == "SIMULATED_PORTFOLIO_RISK_ETF_REPORT_POLICY_INVALID"


def test_disclosed_etf_mode_keeps_existing_date_allowlist_and_kind_scope() -> None:
    """ETF report dates reuse the policy's existing DATE permission, without a new purpose."""

    configuration = _configuration()
    source_references = cast(list[dict[str, object]], configuration["source_references"])
    etf_reference = next(
        reference for reference in source_references if reference["kind"] == "etf_report"
    )
    etf_reference["clock_evidence_mode"] = "policy_bounded_disclosed_report"
    cast(dict[str, object], configuration["industry"])["date_precision_purposes"] = []
    configuration["etf_report"] = {
        "age_basis": "report_period_end",
        "max_report_age_days": 45,
    }
    with pytest.raises(PortfolioRiskPolicyConfigurationError) as date_not_allowed:
        parse_portfolio_risk_policy_bundle(
            _runtime_evidence(configuration),
            business_date=_BUSINESS_DATE,
            as_of=_AS_OF,
        )
    assert date_not_allowed.value.reason_code == "SIMULATED_PORTFOLIO_RISK_RUNTIME_IDENTITY_INVALID"

    wrong_kind = _configuration()
    valuation_reference = cast(list[dict[str, object]], wrong_kind["source_references"])[0]
    valuation_reference["clock_evidence_mode"] = "policy_bounded_disclosed_report"
    wrong_kind["etf_report"] = {
        "age_basis": "report_period_end",
        "max_report_age_days": 45,
    }
    with pytest.raises(PortfolioRiskPolicyConfigurationError) as invalid_kind:
        parse_portfolio_risk_policy_bundle(
            _runtime_evidence(wrong_kind),
            business_date=_BUSINESS_DATE,
            as_of=_AS_OF,
        )
    assert invalid_kind.value.reason_code == "SIMULATED_PORTFOLIO_RISK_CLOCK_MODE_KIND_UNSUPPORTED"


def test_configured_reader_returns_only_the_scoped_active_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reader requires active runtime evidence, exact environment, and account scope."""

    evidence = _runtime_evidence()
    monkeypatch.setattr(
        configured_portfolio_risk_policy_reader,
        "get_active_runtime_value_evidence",
        lambda **kwargs: evidence,
    )
    reader = configured_portfolio_risk_policy_reader.ConfiguredPortfolioRiskPolicyReader(
        environment="development",
    )
    accepted = reader.read_policy(
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE,
        account_id=8,
    )
    outside_scope = reader.read_policy(
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE,
        account_id=13,
    )

    assert accepted.policy is not None
    assert accepted.reason_codes == ()
    assert outside_scope.policy is None
    assert outside_scope.reason_codes == ("SIMULATED_PORTFOLIO_RISK_ACCOUNT_OUT_OF_SCOPE",)

    monkeypatch.setattr(
        configured_portfolio_risk_policy_reader,
        "get_active_runtime_value_evidence",
        lambda **kwargs: replace(evidence, environment="production"),
    )
    wrong_environment = reader.read_policy(
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE,
        account_id=8,
    )
    assert wrong_environment.policy is None
    assert wrong_environment.reason_codes == (
        "SIMULATED_PORTFOLIO_RISK_RUNTIME_ENVIRONMENT_MISMATCH",
    )


def test_configured_reader_fails_closed_without_active_or_current_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An inactive/expired profile cannot silently fall back to a previous revision."""

    monkeypatch.setattr(
        configured_portfolio_risk_policy_reader,
        "get_active_runtime_value_evidence",
        lambda **kwargs: None,
    )
    reader = configured_portfolio_risk_policy_reader.ConfiguredPortfolioRiskPolicyReader(
        environment="development",
    )

    result = reader.read_policy(
        as_of=_AS_OF,
        business_date=_BUSINESS_DATE,
        account_id=8,
    )

    assert result.policy is None
    assert result.reason_codes == ("SIMULATED_PORTFOLIO_RISK_RUNTIME_VALUE_UNAVAILABLE",)
