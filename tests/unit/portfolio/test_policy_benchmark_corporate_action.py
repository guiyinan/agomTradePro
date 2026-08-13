"""Pure tests for the Portfolio benchmark corporate-action methodology."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

import pytest

from apps.portfolio.domain.policy_benchmark_corporate_action import (
    POLICY_BENCHMARK_CORPORATE_ACTION_TYPE,
    PolicyBenchmarkCorporateActionRule,
    PolicyBenchmarkCorporateActionSourceRef,
    PortfolioPolicyBenchmarkCorporateAction,
)

RECORDED_AT = datetime(2026, 3, 1, tzinfo=UTC)
VALID_UNTIL = datetime(2027, 3, 1, tzinfo=UTC)


def _source(ordinal: int, artifact_id: str) -> PolicyBenchmarkCorporateActionSourceRef:
    return PolicyBenchmarkCorporateActionSourceRef(
        owner="portfolio",
        artifact_type="benchmark_corporate_action_source_definition",
        artifact_id=artifact_id,
        artifact_version="v1",
        content_hash=("a" if ordinal == 0 else "b") * 64,
        ordinal=ordinal,
        recorded_at=RECORDED_AT - timedelta(days=1),
        valid_until=VALID_UNTIL,
    )


def _rules() -> tuple[PolicyBenchmarkCorporateActionRule, ...]:
    return (
        PolicyBenchmarkCorporateActionRule(
            ordinal=0,
            event_type="cash_dividend",
            required_date_fields=("effective_date", "ex_date", "pay_date"),
            effective_date_semantics="action_terms_effective",
            ex_date_semantics="recognize_receivable_and_internal_return_once",
            pay_date_semantics="settle_receivable_without_second_return",
            valuation_treatment="cash_receivable_then_cash",
            performance_treatment="internal_return",
        ),
        PolicyBenchmarkCorporateActionRule(
            ordinal=1,
            event_type="stock_dividend",
            required_date_fields=("effective_date", "ex_date", "pay_date"),
            effective_date_semantics="action_terms_effective",
            ex_date_semantics="recognize_share_receivable_and_price_adjustment_once",
            pay_date_semantics="settle_share_receivable_without_second_adjustment",
            valuation_treatment="share_receivable_then_quantity",
            performance_treatment="no_return",
        ),
        PolicyBenchmarkCorporateActionRule(
            ordinal=2,
            event_type="split",
            required_date_fields=("effective_date",),
            effective_date_semantics="adjust_quantity_and_reference_price_once",
            ex_date_semantics="not_applicable",
            pay_date_semantics="not_applicable",
            valuation_treatment="quantity_and_reference_price_adjustment",
            performance_treatment="no_return",
        ),
        PolicyBenchmarkCorporateActionRule(
            ordinal=3,
            event_type="reverse_split",
            required_date_fields=("effective_date",),
            effective_date_semantics="adjust_quantity_and_reference_price_once",
            ex_date_semantics="not_applicable",
            pay_date_semantics="not_applicable",
            valuation_treatment="quantity_and_reference_price_adjustment",
            performance_treatment="no_return",
        ),
        PolicyBenchmarkCorporateActionRule(
            ordinal=4,
            event_type="rights_issue",
            required_date_fields=("effective_date", "ex_date"),
            effective_date_semantics="action_terms_effective",
            ex_date_semantics=("establish_entitlement_then_block_without_exact_terms_and_election"),
            pay_date_semantics="not_applicable",
            valuation_treatment="block",
            performance_treatment="block",
        ),
    )


def _methodology(**changes: object) -> PortfolioPolicyBenchmarkCorporateAction:
    values: dict[str, object] = {
        "methodology_id": "listed-equity-corporate-actions",
        "methodology_version": "v1",
        "security_identifier_namespace": "MIC_TICKER",
        "timezone": "Asia/Shanghai",
        "business_date_cutoff_local": time(18),
        "source_priority": (
            _source(0, "official-actions"),
            _source(1, "licensed-actions"),
        ),
        "event_rules": _rules(),
        "missing_action_policy": "fail_closed",
        "unknown_event_type_policy": "fail_closed",
        "recorded_at": RECORDED_AT,
        "valid_until": VALID_UNTIL,
    }
    values.update(changes)
    return PortfolioPolicyBenchmarkCorporateAction(**values)  # type: ignore[arg-type]


def test_definition_seals_owner_schema_sources_and_inactive_authority() -> None:
    value = _methodology()
    payload = value.to_payload()

    assert value.owner == "portfolio"
    assert value.artifact_type == "corporate_action_methodology"
    assert value.schema == "portfolio-policy-benchmark-corporate-action.v1"
    assert value.permission == "methodology_definition_only"
    assert value.activation_available is False
    assert value.automatic_fallback_allowed is False
    assert value.mutable_fact_projection_allowed is False
    assert value.must_not_execute is True
    assert payload["business_date_cutoff_local"] == "18:00:00"
    assert payload["source_priority"][0]["ordinal"] == 0  # type: ignore[index]
    assert len(value.identity_hash) == len(value.content_hash) == 64


def test_event_matrix_covers_dividends_splits_and_rights_explicitly() -> None:
    rules = {rule.event_type: rule for rule in _methodology().event_rules}

    assert set(rules) == {
        "cash_dividend",
        "stock_dividend",
        "split",
        "reverse_split",
        "rights_issue",
    }
    assert rules["cash_dividend"].performance_treatment == "internal_return"
    assert rules["cash_dividend"].pay_date_semantics == ("settle_receivable_without_second_return")
    assert rules["stock_dividend"].performance_treatment == "no_return"
    assert rules["stock_dividend"].pay_date_semantics == (
        "settle_share_receivable_without_second_adjustment"
    )
    assert rules["split"].performance_treatment == "no_return"
    assert rules["reverse_split"].performance_treatment == "no_return"
    assert rules["rights_issue"].valuation_treatment == "block"


def test_event_date_semantics_and_complete_closed_matrix_cannot_drift() -> None:
    rules = _rules()
    assert rules[0].required_date_fields == (
        "effective_date",
        "ex_date",
        "pay_date",
    )
    assert rules[2].required_date_fields == ("effective_date",)
    with pytest.raises(ValueError, match="closed v1 matrix"):
        _methodology(event_rules=rules[:-1])
    with pytest.raises(ValueError, match="closed v1 matrix"):
        replace(rules[0], event_type="special_dividend")
    with pytest.raises(ValueError, match="closed v1 matrix"):
        replace(rules[2], performance_treatment="internal_return")
    with pytest.raises(ValueError, match="required_date_fields"):
        replace(rules[2], required_date_fields=("announcement_date",))


def test_missing_unknown_source_failure_and_nonbusiness_dates_fail_closed() -> None:
    with pytest.raises(ValueError, match="missing_action_policy"):
        _methodology(missing_action_policy="assume_none")
    with pytest.raises(ValueError, match="unknown_event_type_policy"):
        _methodology(unknown_event_type_policy="ignore")
    with pytest.raises(ValueError, match="source_failure_policy"):
        _methodology(source_failure_policy="try_next")
    with pytest.raises(ValueError, match="non_business_date_policy"):
        _methodology(non_business_date_policy="roll_forward")
    assert _methodology().business_date_policy == "issuer_market_local_date"


def test_unadjusted_input_exact_once_and_duplicate_blocks_prevent_double_counting() -> None:
    value = _methodology()
    assert value.price_input_adjustment_basis == "unadjusted"
    assert value.adjustment_application_policy == "exact_event_once"
    assert value.duplicate_event_policy == "block"
    assert value.pre_adjusted_input_policy == "block"
    with pytest.raises(ValueError, match="price_input_adjustment_basis"):
        _methodology(price_input_adjustment_basis="forward_adjusted")
    with pytest.raises(ValueError, match="adjustment_application_policy"):
        _methodology(adjustment_application_policy="best_effort")
    with pytest.raises(ValueError, match="duplicate_event_policy"):
        _methodology(duplicate_event_policy="deduplicate_silently")


def test_source_refs_are_exact_ordered_unique_knowable_and_min_validity_bound() -> None:
    value = _methodology()
    with pytest.raises(ValueError, match="ordinal"):
        _methodology(source_priority=(value.source_priority[1], value.source_priority[0]))
    with pytest.raises(ValueError, match="unique"):
        _methodology(source_priority=(_source(0, "same"), _source(1, "same")))
    with pytest.raises(ValueError, match="not knowable"):
        _methodology(
            source_priority=(
                replace(
                    _source(0, "future"),
                    recorded_at=RECORDED_AT + timedelta(seconds=1),
                ),
            )
        )
    with pytest.raises(ValueError, match="validity minimum"):
        _methodology(
            source_priority=(
                replace(
                    _source(0, "short"),
                    valid_until=VALID_UNTIL - timedelta(seconds=1),
                ),
            )
        )
    with pytest.raises(ValueError, match="artifact_type"):
        replace(_source(0, "mutable"), artifact_type="corporate_action_fact")


def test_iana_business_date_cutoff_rejects_gap_ambiguity_and_naive_clocks() -> None:
    with pytest.raises(ValueError, match="IANA timezone"):
        _methodology(timezone="Not/AZone")
    spring_source = replace(
        _source(0, "spring"),
        recorded_at=datetime(2026, 3, 7, tzinfo=UTC),
        valid_until=datetime(2026, 3, 9, 5, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="does not exist"):
        _methodology(
            timezone="America/New_York",
            business_date_cutoff_local=time(2, 30),
            source_priority=(spring_source,),
            recorded_at=datetime(2026, 3, 8, tzinfo=UTC),
            valid_until=spring_source.valid_until,
        )
    fall_source = replace(
        _source(0, "fall"),
        recorded_at=datetime(2026, 10, 31, tzinfo=UTC),
        valid_until=datetime(2026, 11, 2, 5, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="ambiguous"):
        _methodology(
            timezone="America/New_York",
            business_date_cutoff_local=time(1, 30),
            source_priority=(fall_source,),
            recorded_at=datetime(2026, 11, 1, tzinfo=UTC),
            valid_until=fall_source.valid_until,
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        _methodology(recorded_at=datetime(2026, 3, 1))


def test_canonical_hash_binds_rules_sources_business_date_and_safety_policies() -> None:
    value = _methodology()
    changed_source = _methodology(
        source_priority=(replace(_source(0, "official-actions"), content_hash="c" * 64),),
    )
    assert changed_source.identity_hash == value.identity_hash
    assert changed_source.content_hash != value.content_hash
    with pytest.raises(ValueError, match="content_hash"):
        replace(value, business_date_cutoff_local=time(17))
    with pytest.raises(ValueError, match="content_hash"):
        replace(value, security_identifier_namespace="ISIN")


def test_fixed_owner_type_and_zero_cross_app_or_framework_dependencies() -> None:
    assert POLICY_BENCHMARK_CORPORATE_ACTION_TYPE == "corporate_action_methodology"
    with pytest.raises(ValueError, match="authority"):
        _methodology(owner="data_center")
    source = Path("apps/portfolio/domain/policy_benchmark_corporate_action.py").read_text(
        encoding="utf-8"
    )
    assert "django" not in source
    assert "from apps." not in source
    assert "import apps." not in source
