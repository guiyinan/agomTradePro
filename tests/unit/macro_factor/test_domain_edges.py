"""Boundary coverage for fail-closed R3 domain contracts."""

from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from apps.macro_factor.domain.entities import (
    FactorLifecycleStatus,
    FactorOutputRole,
    FactorWeight,
    FactorWeightVersion,
    MacroFactorAssessmentStatus,
    MacroFactorBlockerCode,
    MacroFactorResearchAssessment,
    ProxyAssetDefinition,
    ProxyAssetKind,
    RetirementEvidence,
    SampleWindow,
    WalkForwardFold,
    calculate_factor_weight_hash,
    validate_external_macro_factor_result,
)
from tests.unit.macro_factor.factories import (
    ASSESSED_AT,
    complete_manifest,
    complete_result,
)


def _weight_version(
    *,
    factor_version: str,
    calculated_at: datetime,
    weights: tuple[FactorWeight, ...],
) -> FactorWeightVersion:
    return FactorWeightVersion(
        factor_version=factor_version,
        calculated_at=calculated_at,
        weights=weights,
        weight_hash=calculate_factor_weight_hash(
            factor_version=factor_version,
            calculated_at=calculated_at,
            weights=weights,
        ),
    )


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ({"target_code": ""}, "blank"),
        ({"target_code": "has space"}, "whitespace"),
        ({"target_code": "x" * 161}, "exceeds"),
        ({"family": "growth"}, "family"),
        ({"output_role": "forward_expectation"}, "output_role"),
        ({"horizon_periods": 0}, "positive"),
    ],
)
def test_target_definition_rejects_invalid_identity_and_horizon(
    mutation: dict[str, object],
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        replace(complete_result().target, **mutation)


def test_proxy_and_manifest_structural_edges_fail_closed() -> None:
    candidate = complete_result().candidates[0]
    with pytest.raises(ValueError, match="kind"):
        replace(candidate, kind="etf")
    with pytest.raises(ValueError, match="roll policy"):
        replace(
            candidate,
            kind=ProxyAssetKind.CONTINUOUS_FUTURE,
            continuous_roll_policy_version="",
        )
    with pytest.raises(ValueError, match="only valid"):
        replace(candidate, continuous_roll_policy_version="roll-v1")

    manifest_slice = complete_manifest().slices[0]
    with pytest.raises(ValueError, match="cannot be empty"):
        replace(manifest_slice, version_ids=())
    with pytest.raises(ValueError, match="unique"):
        replace(manifest_slice, version_ids=(1, 1))
    with pytest.raises(ValueError, match="positive"):
        replace(manifest_slice, version_ids=(0,))

    manifest = complete_manifest()
    with pytest.raises(ValueError, match="between zero and one"):
        replace(manifest, coverage_ratio=Decimal("1.1"))
    with pytest.raises(ValueError, match="cannot be negative"):
        replace(manifest, missing_count=-1)
    with pytest.raises(ValueError, match="boolean"):
        replace(manifest, is_verified=1)
    with pytest.raises(ValueError, match="unique"):
        replace(manifest, slices=(manifest.slices[0], manifest.slices[0]))
    with pytest.raises(ValueError, match="sha256"):
        replace(manifest, manifest_hash="bad")
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(manifest, as_of_time=datetime(2026, 1, 1))


def test_temporal_split_and_nested_cv_edges_are_rejected() -> None:
    result = complete_result()
    split = result.split
    with pytest.raises(ValueError, match="start cannot follow"):
        SampleWindow(date(2020, 2, 1), date(2020, 1, 1))
    with pytest.raises(ValueError, match="training must precede"):
        WalkForwardFold(
            "bad-train",
            SampleWindow(date(2020, 1, 1), date(2020, 2, 1)),
            SampleWindow(date(2020, 2, 1), date(2020, 3, 1)),
            SampleWindow(date(2020, 4, 1), date(2020, 5, 1)),
        )
    with pytest.raises(ValueError, match="validation must precede"):
        WalkForwardFold(
            "bad-validation",
            SampleWindow(date(2020, 1, 1), date(2020, 1, 15)),
            SampleWindow(date(2020, 2, 1), date(2020, 3, 1)),
            SampleWindow(date(2020, 3, 1), date(2020, 4, 1)),
        )
    with pytest.raises(ValueError, match="out-of-sample embargo"):
        replace(
            split,
            out_of_sample=SampleWindow(
                split.validation.end + timedelta(days=2),
                split.out_of_sample.end,
            ),
        )
    with pytest.raises(ValueError, match="cannot be empty"):
        replace(split, walk_forward_folds=())
    with pytest.raises(ValueError, match="identities must be unique"):
        replace(split, walk_forward_folds=(split.walk_forward_folds[0],) * 2)

    fold = split.walk_forward_folds[0]
    short_train_gap = WalkForwardFold(
        "short-train-gap",
        fold.training,
        SampleWindow(fold.training.end + timedelta(days=2), fold.validation.end),
        fold.out_of_sample,
    )
    with pytest.raises(ValueError, match="lacks train embargo"):
        replace(split, walk_forward_folds=(short_train_gap,))
    short_oos_gap = WalkForwardFold(
        "short-oos-gap",
        fold.training,
        fold.validation,
        SampleWindow(fold.validation.end + timedelta(days=2), fold.out_of_sample.end),
    )
    with pytest.raises(ValueError, match="lacks OOS embargo"):
        replace(split, walk_forward_folds=(short_oos_gap,))

    selection = result.selection
    for mutation, match in (
        ({"inner_fold_count": 1}, "at least two"),
        ({"alpha_grid": ()}, "cannot be empty"),
        ({"alpha_grid": (Decimal("-1"),)}, "positive"),
        ({"alpha_grid": (Decimal("0.1"), Decimal("0.1"))}, "unique"),
        ({"selected_alpha": Decimal("99")}, "present"),
        ({"selected_asset_codes": ()}, "at least one"),
        ({"selected_asset_codes": ("ETF_CREDIT", "ETF_CREDIT")}, "unique"),
        ({"produced_at": datetime(2026, 1, 1)}, "timezone-aware"),
    ):
        with pytest.raises(ValueError, match=match):
            replace(selection, **mutation)


def test_evaluation_weight_and_retirement_edges_are_rejected() -> None:
    result = complete_result()
    metric = result.evaluation.in_sample
    for mutation, match in (
        ({"segment": "in_sample"}, "segment"),
        ({"sample_count": 0}, "positive"),
        ({"r_squared": Decimal("NaN")}, "finite"),
        ({"r_squared": Decimal("1.1")}, "cannot exceed"),
        ({"information_coefficient": Decimal("1.1")}, "between -1 and 1"),
        ({"stability_score": Decimal("-0.1")}, "between zero and one"),
        ({"turnover": Decimal("-1")}, "cannot be negative"),
    ):
        with pytest.raises(ValueError, match=match):
            replace(metric, **mutation)
    with pytest.raises(ValueError, match="wrong sample"):
        replace(result.evaluation, validation=metric)
    with pytest.raises(ValueError, match="finite"):
        replace(result.evaluation, bic=Decimal("NaN"))
    for field_name in (
        "statistical_significance_summary",
        "statistical_significance_evidence_ref",
        "economic_interpretation",
    ):
        with pytest.raises(ValueError, match="blank"):
            replace(result.evaluation, **{field_name: ""})

    weight = result.weights.weights[0]
    with pytest.raises(ValueError, match="cannot be zero"):
        replace(weight, lasso_coefficient=Decimal("0"))
    with pytest.raises(ValueError, match="cannot be empty"):
        replace(result.weights, weights=())
    with pytest.raises(ValueError, match="unique"):
        replace(result.weights, weights=(weight, weight))
    with pytest.raises(ValueError, match="does not match"):
        replace(result.weights, weight_hash="0" * 64)

    rule = result.retirement_policy.rules[0]
    with pytest.raises(ValueError, match="operator"):
        replace(rule, operator="lt")
    with pytest.raises(ValueError, match="boolean"):
        replace(result.retirement_policy, retire_on_any=1)
    with pytest.raises(ValueError, match="cannot be empty"):
        replace(result.retirement_policy, rules=())
    with pytest.raises(ValueError, match="identities must be unique"):
        replace(result.retirement_policy, rules=(rule, rule))

    retirement = RetirementEvidence(
        event_id="retire-growth-v1",
        retired_at=ASSESSED_AT,
        policy_version=result.retirement_policy.policy_version,
        reason_codes=(rule.rule_id,),
        evidence_hash="9" * 64,
    )
    with pytest.raises(ValueError, match="cannot be empty"):
        replace(retirement, reason_codes=())
    with pytest.raises(ValueError, match="unique"):
        replace(retirement, reason_codes=(rule.rule_id, rule.rule_id))


def test_cross_contract_and_lifecycle_edges_are_rejected() -> None:
    result = complete_result()
    first_candidate, second_candidate = result.candidates
    with pytest.raises(ValueError, match="universe cannot be empty"):
        replace(result, candidates=())
    with pytest.raises(ValueError, match="asset codes must be unique"):
        replace(
            result, candidates=(first_candidate, replace(second_candidate, asset_code="ETF_CREDIT"))
        )
    duplicate_scope = ProxyAssetDefinition(
        asset_code="SECOND_CODE",
        dataset_key=first_candidate.dataset_key,
        business_key=first_candidate.business_key,
        kind=ProxyAssetKind.ETF,
        frequency="daily",
        transformation_version="return-v1",
    )
    with pytest.raises(ValueError, match="dataset scopes must be unique"):
        replace(result, candidates=(first_candidate, duplicate_scope))

    unknown = FactorWeight("UNKNOWN", Decimal("1"), Decimal("1"))
    unknown_weights = _weight_version(
        factor_version=result.factor_version,
        calculated_at=result.weights.calculated_at,
        weights=(unknown,),
    )
    unknown_selection = replace(result.selection, selected_asset_codes=("UNKNOWN",))
    with pytest.raises(ValueError, match="candidate universe"):
        replace(result, weights=unknown_weights, selection=unknown_selection)

    other_version_weights = _weight_version(
        factor_version="other-factor-v1",
        calculated_at=result.weights.calculated_at,
        weights=result.weights.weights,
    )
    with pytest.raises(ValueError, match="must match factor_version"):
        replace(result, weights=other_version_weights)
    with pytest.raises(ValueError, match="outer folds"):
        replace(result, selection=replace(result.selection, outer_fold_count=3))
    early_weights = _weight_version(
        factor_version=result.factor_version,
        calculated_at=result.selection.produced_at - timedelta(days=1),
        weights=result.weights.weights,
    )
    with pytest.raises(ValueError, match="cannot predate"):
        replace(result, weights=early_weights)
    with pytest.raises(ValueError, match="lifecycle_status"):
        replace(result, lifecycle_status="research_only")
    with pytest.raises(ValueError, match="decision-blocked"):
        replace(result, must_not_use_for_decision=False)

    rule_id = result.retirement_policy.rules[0].rule_id
    retirement = RetirementEvidence(
        event_id="retire-growth-v1",
        retired_at=ASSESSED_AT,
        policy_version="wrong-policy",
        reason_codes=(rule_id,),
        evidence_hash="9" * 64,
    )
    with pytest.raises(ValueError, match="retirement policy"):
        replace(
            result,
            lifecycle_status=FactorLifecycleStatus.RETIRED,
            retirement_evidence=retirement,
        )
    retirement = replace(
        retirement,
        policy_version=result.retirement_policy.policy_version,
        reason_codes=("unknown-rule",),
    )
    with pytest.raises(ValueError, match="unknown invalidation"):
        replace(
            result,
            lifecycle_status=FactorLifecycleStatus.RETIRED,
            retirement_evidence=retirement,
        )
    valid_retirement = replace(retirement, reason_codes=(rule_id,))
    with pytest.raises(ValueError, match="non-retired"):
        replace(result, retirement_evidence=valid_retirement)


def test_record_assessment_and_retired_timeline_edges_are_rejected() -> None:
    result = complete_result()
    record = result.to_record()
    with pytest.raises(ValueError, match="does not match payload"):
        replace(record, content_hash="0" * 64)
    with pytest.raises(ValueError, match="lifecycle_status"):
        replace(record, lifecycle_status="research_only")
    with pytest.raises(ValueError, match="decision-blocked"):
        replace(record, research_only=False)

    with pytest.raises(ValueError, match="status"):
        MacroFactorResearchAssessment(
            status="accepted",
            external_evidence_id=result.selection.evidence_id,
            factor_version=result.factor_version,
            assessed_at=ASSESSED_AT,
            blocked_reasons=(),
            record=record,
        )
    with pytest.raises(ValueError, match="requires a record"):
        MacroFactorResearchAssessment(
            status=MacroFactorAssessmentStatus.ACCEPTED,
            external_evidence_id=result.selection.evidence_id,
            factor_version=result.factor_version,
            assessed_at=ASSESSED_AT,
            blocked_reasons=(),
            record=None,
        )
    with pytest.raises(ValueError, match="requires blockers"):
        MacroFactorResearchAssessment(
            status=MacroFactorAssessmentStatus.BLOCKED,
            external_evidence_id=result.selection.evidence_id,
            factor_version=result.factor_version,
            assessed_at=ASSESSED_AT,
            blocked_reasons=(),
            record=None,
        )

    retirement = RetirementEvidence(
        event_id="retire-growth-v1",
        retired_at=ASSESSED_AT + timedelta(days=1),
        policy_version=result.retirement_policy.policy_version,
        reason_codes=(result.retirement_policy.rules[0].rule_id,),
        evidence_hash="9" * 64,
    )
    retired = replace(
        result,
        lifecycle_status=FactorLifecycleStatus.RETIRED,
        retirement_evidence=retirement,
    )
    payload = retired.canonical_payload()
    blockers = validate_external_macro_factor_result(
        retired,
        complete_manifest(),
        assessed_at=ASSESSED_AT,
    )
    assert payload["retirement_evidence"] is not None
    assert MacroFactorBlockerCode.EXTERNAL_EVIDENCE_FROM_FUTURE in blockers


def test_output_role_and_evaluation_report_are_sealed_by_content_hash() -> None:
    result = complete_result()
    current_state = replace(
        result,
        target=replace(result.target, output_role=FactorOutputRole.CURRENT_STATE),
    )
    changed_bic = replace(
        result,
        evaluation=replace(result.evaluation, bic=result.evaluation.bic + Decimal("1")),
    )

    assert current_state.content_hash != result.content_hash
    assert changed_bic.content_hash != result.content_hash
    assert current_state.canonical_payload()["target"] != result.canonical_payload()["target"]

    with pytest.raises(ValueError, match="does not match payload"):
        replace(
            result.to_record(),
            payload_json=changed_bic.canonical_json,
        )
