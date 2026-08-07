"""Canonical JSON codecs for Portfolio-owned R4 rolling research records."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, cast

from apps.portfolio.domain.macro_factor_risk import (
    AssetAllocation,
    AssetMacroExposure,
    FactorCovarianceVersion,
    MacroExposureVersion,
    MacroFactorBeta,
    MacroRiskCandidateInput,
    MacroRiskCandidateKind,
    MacroRiskValidationPolicy,
)
from apps.portfolio.domain.macro_risk_rolling_contracts import (
    R4CostTreatment,
    R4RollingResearchArtifact,
    R4RollingStudyInput,
    R4RollingValidationPolicy,
    R4RollingWindowInput,
)
from apps.portfolio.domain.macro_risk_rolling_service import evaluate_r4_rolling_study
from apps.portfolio.domain.r4_rolling_evidence import (
    ExactR3PromotionAttestation,
    R4AssetCovarianceEvidence,
    R4AssetReturn,
    R4MacroExposureProjectionEvidence,
    R4OOSReturnPathEvidence,
    R4RegimeAssignmentEvidence,
    R4ReturnObservation,
)
from apps.portfolio.domain.r4_temporal_split import SampleWindow, TemporalSplitSpec, WalkForwardFold

_STUDY_SCHEMA = "portfolio-r4-rolling-study-payload.v1"
_ATTESTATION_SCHEMA = "portfolio-r4-r3-attestation-payload.v1"
_ARTIFACT_SCHEMA = "portfolio-r4-rolling-artifact-payload.v1"


def study_to_payload(study: R4RollingStudyInput) -> dict[str, object]:
    """Encode one canonical typed R4 study."""

    return _wrap(_STUDY_SCHEMA, study)


def study_from_payload(value: object) -> R4RollingStudyInput:
    """Decode and factory-verify one canonical typed R4 study."""

    data = _payload_data(value, _STUDY_SCHEMA, "R4 study")
    study = _study(data)
    _assert_canonical(study, data, "R4 study")
    return study


def promotion_to_payload(
    attestation: ExactR3PromotionAttestation,
) -> dict[str, object]:
    """Encode the exact authoritative R3 attestation consumed by R4."""

    return _wrap(_ATTESTATION_SCHEMA, attestation)


def promotion_from_payload(value: object) -> ExactR3PromotionAttestation:
    """Decode and factory-verify an exact authoritative R3 attestation."""

    data = _payload_data(value, _ATTESTATION_SCHEMA, "R3 promotion attestation")
    attestation = ExactR3PromotionAttestation.create(
        artifact_id=_text(data, "artifact_id"),
        artifact_version=_text(data, "artifact_version"),
        artifact_content_hash=_text(data, "artifact_content_hash"),
        decision_id=_text(data, "decision_id"),
        decision_version=_text(data, "decision_version"),
        decision_content_hash=_text(data, "decision_content_hash"),
        approved_at=_datetime(data, "approved_at"),
        valid_until=_datetime(data, "valid_until"),
        retired_at=_optional_datetime(data, "retired_at"),
    )
    _assert_canonical(attestation, data, "R3 promotion attestation")
    return attestation


def artifact_to_payload(artifact: R4RollingResearchArtifact) -> dict[str, object]:
    """Encode one complete canonical R4 rolling result artifact."""

    return _wrap(_ARTIFACT_SCHEMA, artifact)


def artifact_from_payload(
    value: object,
    *,
    study: R4RollingStudyInput,
    promotion_attestation: ExactR3PromotionAttestation,
) -> R4RollingResearchArtifact:
    """Recompute and exact-match a persisted artifact payload."""

    data = _payload_data(value, _ARTIFACT_SCHEMA, "R4 artifact")
    artifact = evaluate_r4_rolling_study(
        study,
        promotion_attestation=promotion_attestation,
        evaluated_at=_datetime(data, "evaluated_at"),
    )
    _assert_canonical(artifact, data, "R4 artifact")
    return artifact


def _study(data: dict[str, Any]) -> R4RollingStudyInput:
    temporal_split = _temporal_split(_mapping(data.get("temporal_split"), "temporal split"))
    candidate_policy = _candidate_policy(_mapping(data.get("candidate_policy"), "candidate policy"))
    rolling_policy = _rolling_policy(_mapping(data.get("rolling_policy"), "rolling policy"))
    windows = tuple(
        _window(_mapping(item, "rolling window"))
        for item in _array(data.get("windows"), "rolling windows")
    )
    return R4RollingStudyInput.create(
        study_id=_text(data, "study_id"),
        study_version=_text(data, "study_version"),
        temporal_split=temporal_split,
        candidate_policy=candidate_policy,
        rolling_policy=rolling_policy,
        windows=windows,
    )


def _temporal_split(data: dict[str, Any]) -> TemporalSplitSpec:
    return TemporalSplitSpec(
        policy_version=_text(data, "policy_version"),
        training=_sample_window(_mapping(data.get("training"), "training window")),
        validation=_sample_window(_mapping(data.get("validation"), "validation window")),
        out_of_sample=_sample_window(_mapping(data.get("out_of_sample"), "out-of-sample window")),
        walk_forward_folds=tuple(
            _fold(_mapping(item, "walk-forward fold"))
            for item in _array(data.get("walk_forward_folds"), "walk-forward folds")
        ),
        embargo_days=_integer(data, "embargo_days"),
    )


def _fold(data: dict[str, Any]) -> WalkForwardFold:
    return WalkForwardFold(
        fold_id=_text(data, "fold_id"),
        training=_sample_window(_mapping(data.get("training"), "fold training window")),
        validation=_sample_window(_mapping(data.get("validation"), "fold validation window")),
        out_of_sample=_sample_window(
            _mapping(data.get("out_of_sample"), "fold out-of-sample window")
        ),
    )


def _sample_window(data: dict[str, Any]) -> SampleWindow:
    return SampleWindow(
        start=_date(data, "start"),
        end=_date(data, "end"),
    )


def _candidate_policy(data: dict[str, Any]) -> MacroRiskValidationPolicy:
    return MacroRiskValidationPolicy(
        version=_text(data, "version"),
        weight_sum_tolerance=_decimal(data, "weight_sum_tolerance"),
        covariance_symmetry_tolerance=_decimal(data, "covariance_symmetry_tolerance"),
        covariance_psd_tolerance=_decimal(data, "covariance_psd_tolerance"),
        contribution_identity_tolerance=_decimal(data, "contribution_identity_tolerance"),
        minimum_r_squared=_decimal(data, "minimum_r_squared"),
        minimum_stability_score=_decimal(data, "minimum_stability_score"),
        maximum_turnover=_decimal(data, "maximum_turnover"),
        maximum_expected_cost=_decimal(data, "maximum_expected_cost"),
        macro_risk_parity_tolerance=_decimal(data, "macro_risk_parity_tolerance"),
    )


def _rolling_policy(data: dict[str, Any]) -> R4RollingValidationPolicy:
    return R4RollingValidationPolicy(
        version=_text(data, "version"),
        cost_semantics_version=_text(data, "cost_semantics_version"),
        cost_treatment=R4CostTreatment(_text(data, "cost_treatment")),
        weight_tolerance=_decimal(data, "weight_tolerance"),
        covariance_symmetry_tolerance=_decimal(data, "covariance_symmetry_tolerance"),
        covariance_psd_tolerance=_decimal(data, "covariance_psd_tolerance"),
        maximum_condition_number=_decimal(data, "maximum_condition_number"),
        minimum_covariance_coverage_ratio=_decimal(data, "minimum_covariance_coverage_ratio"),
        asset_risk_parity_tolerance=_decimal(data, "asset_risk_parity_tolerance"),
        minimum_regime_windows=_integer(data, "minimum_regime_windows"),
    )


def _window(data: dict[str, Any]) -> R4RollingWindowInput:
    window = R4RollingWindowInput.create(
        fold=_fold(_mapping(data.get("fold"), "rolling fold")),
        selection_as_of=_datetime(data, "selection_as_of"),
        evaluation_as_of=_datetime(data, "evaluation_as_of"),
        macro_projection=_macro_projection(
            _mapping(data.get("macro_projection"), "macro projection")
        ),
        candidates=tuple(
            _candidate(_mapping(item, "macro-risk candidate"))
            for item in _array(data.get("candidates"), "macro-risk candidates")
        ),
        asset_covariance=_asset_covariance(
            _mapping(data.get("asset_covariance"), "asset covariance")
        ),
        return_path=_return_path(_mapping(data.get("return_path"), "OOS return path")),
        regime_assignment=_regime_assignment(
            _mapping(data.get("regime_assignment"), "regime assignment")
        ),
    )
    _assert_canonical(window, data, "rolling window")
    return window


def _macro_projection(data: dict[str, Any]) -> R4MacroExposureProjectionEvidence:
    projection = R4MacroExposureProjectionEvidence.create(
        exposure_version=_macro_exposure(
            _mapping(data.get("exposure_version"), "macro exposure version")
        ),
        factor_artifact_id=_text(data, "factor_artifact_id"),
        factor_artifact_version=_text(data, "factor_artifact_version"),
        factor_artifact_content_hash=_text(data, "factor_artifact_content_hash"),
        promotion_decision_id=_text(data, "promotion_decision_id"),
        promotion_decision_version=_text(data, "promotion_decision_version"),
        promotion_decision_content_hash=_text(data, "promotion_decision_content_hash"),
        available_at=_datetime(data, "available_at"),
        knowledge_as_of=_datetime(data, "knowledge_as_of"),
    )
    _assert_canonical(projection, data, "macro projection")
    return projection


def _macro_exposure(data: dict[str, Any]) -> MacroExposureVersion:
    exposure = MacroExposureVersion(
        version_id=_text(data, "version_id"),
        promoted_factor_version=_text(data, "promoted_factor_version"),
        promotion_decision_id=_text(data, "promotion_decision_id"),
        pit_manifest_id=_text(data, "pit_manifest_id"),
        code_version=_text(data, "code_version"),
        parameter_version=_text(data, "parameter_version"),
        observed_at=_datetime(data, "observed_at"),
        valid_until=_datetime(data, "valid_until"),
        exposures=tuple(
            _asset_exposure(_mapping(item, "asset macro exposure"))
            for item in _array(data.get("exposures"), "asset macro exposures")
        ),
    )
    _assert_canonical(exposure, data, "macro exposure version")
    return exposure


def _asset_exposure(data: dict[str, Any]) -> AssetMacroExposure:
    return AssetMacroExposure(
        asset_code=_text(data, "asset_code"),
        betas=tuple(
            _factor_beta(_mapping(item, "macro factor beta"))
            for item in _array(data.get("betas"), "macro factor betas")
        ),
        residual_variance=_decimal(data, "residual_variance"),
        r_squared=_decimal(data, "r_squared"),
        stability_score=_decimal(data, "stability_score"),
    )


def _factor_beta(data: dict[str, Any]) -> MacroFactorBeta:
    return MacroFactorBeta(
        factor_code=_text(data, "factor_code"),
        beta=_decimal(data, "beta"),
        confidence_low=_decimal(data, "confidence_low"),
        confidence_high=_decimal(data, "confidence_high"),
    )


def _candidate(data: dict[str, Any]) -> MacroRiskCandidateInput:
    candidate = MacroRiskCandidateInput(
        candidate_id=_text(data, "candidate_id"),
        kind=MacroRiskCandidateKind(_text(data, "kind")),
        canonical_portfolio_snapshot_id=_text(data, "canonical_portfolio_snapshot_id"),
        exposure_version=_macro_exposure(
            _mapping(data.get("exposure_version"), "candidate exposure version")
        ),
        covariance_version=_factor_covariance(
            _mapping(data.get("covariance_version"), "factor covariance version")
        ),
        cost_model_version=_text(data, "cost_model_version"),
        constraint_version=_text(data, "constraint_version"),
        allocations=tuple(
            _allocation(_mapping(item, "asset allocation"))
            for item in _array(data.get("allocations"), "asset allocations")
        ),
        expected_cost=_decimal(data, "expected_cost"),
        created_at=_datetime(data, "created_at"),
        input_hash=_text(data, "input_hash"),
    )
    _assert_canonical(candidate, data, "macro-risk candidate")
    return candidate


def _factor_covariance(data: dict[str, Any]) -> FactorCovarianceVersion:
    return FactorCovarianceVersion(
        version_id=_text(data, "version_id"),
        factor_codes=tuple(
            _array_text(item, "factor code")
            for item in _array(data.get("factor_codes"), "factor codes")
        ),
        values=_decimal_matrix(data.get("values"), "factor covariance values"),
        pit_manifest_id=_text(data, "pit_manifest_id"),
        estimator_version=_text(data, "estimator_version"),
        observed_at=_datetime(data, "observed_at"),
        valid_until=_datetime(data, "valid_until"),
    )


def _allocation(data: dict[str, Any]) -> AssetAllocation:
    return AssetAllocation(
        asset_code=_text(data, "asset_code"),
        current_weight=_decimal(data, "current_weight"),
        candidate_weight=_decimal(data, "candidate_weight"),
        minimum_weight=_decimal(data, "minimum_weight"),
        maximum_weight=_decimal(data, "maximum_weight"),
        maximum_trade_weight=_decimal(data, "maximum_trade_weight"),
    )


def _asset_covariance(data: dict[str, Any]) -> R4AssetCovarianceEvidence:
    evidence = R4AssetCovarianceEvidence.create(
        covariance_id=_text(data, "covariance_id"),
        covariance_version=_text(data, "covariance_version"),
        universe_id=_text(data, "universe_id"),
        universe_hash=_text(data, "universe_hash"),
        asset_codes=tuple(
            _array_text(item, "asset code")
            for item in _array(data.get("asset_codes"), "asset codes")
        ),
        values=_decimal_matrix(data.get("values"), "asset covariance values"),
        estimator_version=_text(data, "estimator_version"),
        condition_number=_decimal(data, "condition_number"),
        matrix_rank=_integer(data, "matrix_rank"),
        expected_observation_count=_integer(data, "expected_observation_count"),
        missing_observation_count=_integer(data, "missing_observation_count"),
        missing_value_policy_version=_text(data, "missing_value_policy_version"),
        estimation_window=_sample_window(
            _mapping(data.get("estimation_window"), "estimation window")
        ),
        observed_at=_datetime(data, "observed_at"),
        available_at=_datetime(data, "available_at"),
        knowledge_as_of=_datetime(data, "knowledge_as_of"),
        valid_until=_datetime(data, "valid_until"),
        pit_manifest_id=_text(data, "pit_manifest_id"),
        pit_manifest_hash=_text(data, "pit_manifest_hash"),
        source_content_hashes=tuple(
            _array_text(item, "source content hash")
            for item in _array(data.get("source_content_hashes"), "source content hashes")
        ),
    )
    _assert_canonical(evidence, data, "asset covariance")
    return evidence


def _return_path(data: dict[str, Any]) -> R4OOSReturnPathEvidence:
    evidence = R4OOSReturnPathEvidence.create(
        path_id=_text(data, "path_id"),
        path_version=_text(data, "path_version"),
        universe_id=_text(data, "universe_id"),
        universe_hash=_text(data, "universe_hash"),
        out_of_sample=_sample_window(_mapping(data.get("out_of_sample"), "return path OOS window")),
        observations=tuple(
            _return_observation(_mapping(item, "return observation"))
            for item in _array(data.get("observations"), "return observations")
        ),
        observed_at=_datetime(data, "observed_at"),
        available_at=_datetime(data, "available_at"),
        knowledge_as_of=_datetime(data, "knowledge_as_of"),
        valid_until=_datetime(data, "valid_until"),
        pit_manifest_id=_text(data, "pit_manifest_id"),
        pit_manifest_hash=_text(data, "pit_manifest_hash"),
        source_content_hashes=tuple(
            _array_text(item, "source content hash")
            for item in _array(data.get("source_content_hashes"), "source content hashes")
        ),
    )
    _assert_canonical(evidence, data, "OOS return path")
    return evidence


def _return_observation(data: dict[str, Any]) -> R4ReturnObservation:
    return R4ReturnObservation(
        period_end=_datetime(data, "period_end"),
        asset_returns=tuple(
            _asset_return(_mapping(item, "asset return"))
            for item in _array(data.get("asset_returns"), "asset returns")
        ),
    )


def _asset_return(data: dict[str, Any]) -> R4AssetReturn:
    return R4AssetReturn(
        asset_code=_text(data, "asset_code"),
        value=_decimal(data, "value"),
    )


def _regime_assignment(data: dict[str, Any]) -> R4RegimeAssignmentEvidence:
    evidence = R4RegimeAssignmentEvidence.create(
        assignment_id=_text(data, "assignment_id"),
        assignment_version=_text(data, "assignment_version"),
        taxonomy_version=_text(data, "taxonomy_version"),
        regime_code=_text(data, "regime_code"),
        effective_at=_datetime(data, "effective_at"),
        available_at=_datetime(data, "available_at"),
        knowledge_as_of=_datetime(data, "knowledge_as_of"),
        valid_until=_datetime(data, "valid_until"),
        pit_manifest_id=_text(data, "pit_manifest_id"),
        pit_manifest_hash=_text(data, "pit_manifest_hash"),
        source_content_hash=_text(data, "source_content_hash"),
    )
    _assert_canonical(evidence, data, "regime assignment")
    return evidence


def _wrap(schema: str, value: object) -> dict[str, object]:
    return {"schema_version": schema, "data": _encode_dataclass(value)}


def _encode_dataclass(value: object) -> dict[str, object]:
    if not is_dataclass(value) or isinstance(value, type):
        raise TypeError("canonical payload root must be a dataclass instance")
    instance = cast(Any, value)
    return {field.name: _encode(getattr(instance, field.name)) for field in fields(instance)}


def _encode(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        normalized = value.normalize()
        return "0" if normalized == 0 else format(normalized, "f")
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("canonical payload datetime must be timezone-aware")
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return _encode_dataclass(value)
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    if isinstance(value, list):
        return [_encode(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"unsupported canonical payload value: {type(value).__name__}")


def _payload_data(value: object, schema: str, label: str) -> dict[str, Any]:
    payload = _mapping(value, label)
    if set(payload) != {"schema_version", "data"}:
        raise ValueError(f"persisted {label} envelope is non-canonical")
    if payload.get("schema_version") != schema:
        raise ValueError(f"persisted {label} schema version is unsupported")
    return _mapping(payload.get("data"), f"{label} data")


def _assert_canonical(value: object, data: dict[str, Any], label: str) -> None:
    if _encode_dataclass(value) != data:
        raise ValueError(f"persisted {label} canonical payload mismatch")


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"persisted {label} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise ValueError(f"persisted {label} keys must be strings")
    return cast(dict[str, Any], value)


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"persisted {label} must be an array")
    return cast(list[object], value)


def _text(data: dict[str, Any], field_name: str) -> str:
    value = data.get(field_name)
    if not isinstance(value, str):
        raise ValueError(f"persisted {field_name} must be text")
    return value


def _array_text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"persisted {label} must be text")
    return value


def _integer(data: dict[str, Any], field_name: str) -> int:
    value = data.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"persisted {field_name} must be an integer")
    return value


def _decimal(data: dict[str, Any], field_name: str) -> Decimal:
    value = data.get(field_name)
    if not isinstance(value, str):
        raise ValueError(f"persisted {field_name} must be decimal text")
    return Decimal(value)


def _decimal_matrix(value: object, label: str) -> tuple[tuple[Decimal, ...], ...]:
    return tuple(
        tuple(_decimal_item(item, label) for item in _array(row, label))
        for row in _array(value, label)
    )


def _decimal_item(value: object, label: str) -> Decimal:
    if not isinstance(value, str):
        raise ValueError(f"persisted {label} values must be decimal text")
    return Decimal(value)


def _datetime(data: dict[str, Any], field_name: str) -> datetime:
    return _canonical_datetime(_text(data, field_name), field_name)


def _optional_datetime(data: dict[str, Any], field_name: str) -> datetime | None:
    value = data.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"persisted {field_name} must be datetime text or null")
    return _canonical_datetime(value, field_name)


def _canonical_datetime(value: str, field_name: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"persisted {field_name} must be timezone-aware")
    canonical = parsed.astimezone(UTC)
    if value != canonical.isoformat():
        raise ValueError(f"persisted {field_name} must use canonical UTC text")
    return canonical


def _date(data: dict[str, Any], field_name: str) -> date:
    return date.fromisoformat(_text(data, field_name))


__all__ = [
    "artifact_from_payload",
    "artifact_to_payload",
    "promotion_from_payload",
    "promotion_to_payload",
    "study_from_payload",
    "study_to_payload",
]
