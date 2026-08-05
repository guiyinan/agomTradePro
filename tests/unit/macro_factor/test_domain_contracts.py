"""Domain validation for externally calculated macro-factor evidence."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from apps.macro_factor.domain.entities import (
    FactorLifecycleStatus,
    FactorOutputRole,
    FactorWeight,
    FactorWeightVersion,
    RetirementEvidence,
    SampleWindow,
    TemporalSplitSpec,
    calculate_factor_weight_hash,
    validate_external_macro_factor_result,
)
from tests.unit.macro_factor.factories import (
    ASSESSED_AT,
    complete_manifest,
    complete_result,
)


def test_complete_external_result_covers_r3_contract_and_remains_research_only() -> None:
    result = complete_result()

    blockers = validate_external_macro_factor_result(
        result,
        complete_manifest(),
        assessed_at=ASSESSED_AT,
    )

    assert blockers == ()
    assert result.research_only is True
    assert result.must_not_use_for_decision is True
    assert result.selection.estimator == "lasso"
    assert result.selection.validation_method == "nested_cv"
    assert result.target.output_role is FactorOutputRole.FORWARD_EXPECTATION
    assert result.evaluation.in_sample.r_squared is not None
    assert result.evaluation.out_of_sample.information_coefficient is not None
    assert result.evaluation.bic == Decimal("412.75")
    assert result.evaluation.statistical_significance_evidence_ref
    assert result.evaluation.economic_interpretation
    assert result.weights.factor_version == result.factor_version
    assert len(result.content_hash) == 64


def test_selected_assets_must_be_candidates_and_match_factor_weights() -> None:
    result = complete_result()
    unknown_weight = FactorWeight(
        asset_code="UNKNOWN_PROXY",
        lasso_coefficient=Decimal("1"),
        factor_weight=Decimal("1"),
    )
    calculated_at = result.weights.calculated_at
    weights = FactorWeightVersion(
        factor_version=result.factor_version,
        calculated_at=calculated_at,
        weights=(unknown_weight,),
        weight_hash=calculate_factor_weight_hash(
            factor_version=result.factor_version,
            calculated_at=calculated_at,
            weights=(unknown_weight,),
        ),
    )

    with pytest.raises(ValueError, match="selected proxy assets"):
        replace(result, weights=weights)


def test_temporal_split_rejects_missing_embargo_between_samples() -> None:
    split = complete_result().split

    with pytest.raises(ValueError, match="embargo"):
        TemporalSplitSpec(
            policy_version=split.policy_version,
            training=SampleWindow(date(2015, 1, 1), date(2019, 12, 31)),
            validation=SampleWindow(date(2020, 1, 2), date(2021, 12, 31)),
            out_of_sample=split.out_of_sample,
            walk_forward_folds=split.walk_forward_folds,
            embargo_days=5,
        )


def test_only_external_precomputed_nested_cv_lasso_evidence_is_accepted() -> None:
    result = complete_result()

    with pytest.raises(ValueError, match="external_precomputed"):
        replace(
            result.selection,
            computation_origin="internal_training",
        )
    with pytest.raises(ValueError, match="nested_cv"):
        replace(result.selection, validation_method="single_holdout")
    with pytest.raises(ValueError, match="lasso"):
        replace(result.selection, estimator="ols")


def test_retired_factor_requires_append_only_retirement_evidence() -> None:
    result = complete_result()

    with pytest.raises(ValueError, match="retirement evidence"):
        replace(result, lifecycle_status=FactorLifecycleStatus.RETIRED)

    retired = replace(
        result,
        lifecycle_status=FactorLifecycleStatus.RETIRED,
        retirement_evidence=RetirementEvidence(
            event_id="retire-growth-v1",
            retired_at=ASSESSED_AT,
            policy_version=result.retirement_policy.policy_version,
            reason_codes=("oos-r2-floor",),
            evidence_hash="9" * 64,
        ),
    )
    assert retired.lifecycle_status is FactorLifecycleStatus.RETIRED
