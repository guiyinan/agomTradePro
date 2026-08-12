"""Strict canonical JSON codec for the Research-owned R3 runner-spec ledger."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from apps.macro_factor.domain.baselines import FixedFMPDefinition, FixedFMPWeight
from apps.macro_factor.domain.entities import (
    FactorOutputRole,
    MacroTargetDefinition,
    MacroTargetFamily,
    ProxyAssetDefinition,
    ProxyAssetKind,
    ReproducibilityEvidence,
    SampleWindow,
    TemporalSplitSpec,
    WalkForwardFold,
)
from apps.macro_factor.domain.runner_inputs import (
    InferenceTargetCalendarPeriod,
    InputKnowledgeFreshnessPolicy,
    ResearchOutputValidityPolicy,
    VersionedResearchContract,
)
from apps.macro_factor.domain.temporal_cv_contracts import (
    InnerTemporalFoldPlan,
    NestedTemporalCVPlan,
    OptimizationDirection,
    OuterTemporalFoldPlan,
    TargetAvailabilityPolicy,
)
from apps.macro_factor.domain.temporal_runner_spec import MacroFactorRunnerSpec
from apps.research.domain.r3_macro_factor_runner_spec import (
    PersistedMacroFactorRunnerSpecRecord,
)

_SCHEMA = "research.r3.macro-factor-runner-spec-record.v1"


class R3MacroFactorRunnerSpecCodecError(ValueError):
    """Persisted runner-spec JSON is malformed or non-canonical."""


def encode_persisted_macro_factor_runner_spec(
    record: PersistedMacroFactorRunnerSpecRecord,
) -> dict[str, object]:
    """Encode every spec field plus the server ledger seal."""

    validated = record.validated_copy()
    timing = validated.spec.plan.timing
    return {
        "schema": _SCHEMA,
        "body": {
            "spec": validated.spec.canonical_payload,
            "timing_policy": _encode_timing_policy(timing),
            "spec_content_hash": validated.spec.content_hash.lower(),
            "ledger_recorded_at": _utc_text(validated.ledger_recorded_at),
            "research_only": validated.research_only,
            "must_not_publish_current": validated.must_not_publish_current,
            "must_not_use_for_decision": validated.must_not_use_for_decision,
            "must_not_execute": validated.must_not_execute,
            "record_hash": validated.record_hash.lower(),
        },
    }


def decode_persisted_macro_factor_runner_spec(
    payload: object,
) -> PersistedMacroFactorRunnerSpecRecord:
    """Decode, reconstruct, live-validate, and canonicality-check one record."""

    envelope = _object(payload, "runner-spec envelope")
    _keys(envelope, {"schema", "body"}, "runner-spec envelope")
    if _string(envelope["schema"], "schema") != _SCHEMA:
        raise R3MacroFactorRunnerSpecCodecError("runner-spec schema is unsupported")
    body = _object(envelope["body"], "runner-spec body")
    _keys(
        body,
        {
            "spec",
            "timing_policy",
            "spec_content_hash",
            "ledger_recorded_at",
            "research_only",
            "must_not_publish_current",
            "must_not_use_for_decision",
            "must_not_execute",
            "record_hash",
        },
        "runner-spec body",
    )
    try:
        timing = _decode_timing_policy(_object(body["timing_policy"], "timing_policy"))
        spec = _decode_spec(_object(body["spec"], "spec"), timing=timing)
        stored_spec_hash = _sha256(body["spec_content_hash"], "spec_content_hash")
        if stored_spec_hash.lower() != spec.content_hash.lower():
            raise R3MacroFactorRunnerSpecCodecError("spec_content_hash mismatch")
        record = PersistedMacroFactorRunnerSpecRecord(
            spec=spec,
            ledger_recorded_at=_datetime(
                body["ledger_recorded_at"],
                "ledger_recorded_at",
            ),
            research_only=_boolean(body["research_only"], "research_only"),
            must_not_publish_current=_boolean(
                body["must_not_publish_current"],
                "must_not_publish_current",
            ),
            must_not_use_for_decision=_boolean(
                body["must_not_use_for_decision"],
                "must_not_use_for_decision",
            ),
            must_not_execute=_boolean(body["must_not_execute"], "must_not_execute"),
        )
        stored_record_hash = _sha256(body["record_hash"], "record_hash")
        if stored_record_hash.lower() != record.record_hash.lower():
            raise R3MacroFactorRunnerSpecCodecError("record_hash mismatch")
    except R3MacroFactorRunnerSpecCodecError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise R3MacroFactorRunnerSpecCodecError(str(error)) from error
    canonical = encode_persisted_macro_factor_runner_spec(record)
    if envelope != canonical:
        raise R3MacroFactorRunnerSpecCodecError("runner-spec payload is not canonical")
    return record


def _decode_spec(
    body: dict[str, object],
    *,
    timing: TargetAvailabilityPolicy,
) -> MacroFactorRunnerSpec:
    _keys(
        body,
        {
            "schema",
            "run_key",
            "run_version",
            "factor_version",
            "expected_manifest_content_hash",
            "target",
            "inference_target_period",
            "input_knowledge_freshness_policy",
            "candidates",
            "plan",
            "temporal_split",
            "historical_mean_benchmark",
            "fixed_fmp",
            "cost_model",
            "split_contract",
            "selection_protocol",
            "metrics_protocol",
            "output_validity_policy",
            "reproducibility",
            "random_seed",
            "registered_at",
            "calculated_at",
        },
        "spec",
    )
    if _string(body["schema"], "spec.schema") != "macro-factor-runner-spec.v1":
        raise R3MacroFactorRunnerSpecCodecError("macro-factor spec schema is unsupported")
    return MacroFactorRunnerSpec(
        run_key=_string(body["run_key"], "run_key"),
        run_version=_integer(body["run_version"], "run_version"),
        factor_version=_string(body["factor_version"], "factor_version"),
        expected_manifest_content_hash=_sha256(
            body["expected_manifest_content_hash"],
            "expected_manifest_content_hash",
        ),
        target=_decode_target(_object(body["target"], "target")),
        inference_target_period=_decode_inference_period(
            _object(body["inference_target_period"], "inference_target_period")
        ),
        input_knowledge_freshness_policy=_decode_freshness_policy(
            _object(
                body["input_knowledge_freshness_policy"],
                "input_knowledge_freshness_policy",
            )
        ),
        candidates=tuple(
            _decode_candidate(_object(item, "candidate"))
            for item in _array(body["candidates"], "candidates")
        ),
        plan=_decode_plan(_object(body["plan"], "plan"), timing=timing),
        temporal_split=_decode_temporal_split(_object(body["temporal_split"], "temporal_split")),
        historical_mean_benchmark=_decode_contract(
            _object(body["historical_mean_benchmark"], "historical_mean_benchmark"),
            "historical_mean_benchmark",
        ),
        fixed_fmp=_decode_fixed_fmp(_object(body["fixed_fmp"], "fixed_fmp")),
        cost_model=_decode_contract(
            _object(body["cost_model"], "cost_model"),
            "cost_model",
        ),
        split_contract=_decode_contract(
            _object(body["split_contract"], "split_contract"),
            "split_contract",
        ),
        selection_protocol=_decode_contract(
            _object(body["selection_protocol"], "selection_protocol"),
            "selection_protocol",
        ),
        metrics_protocol=_decode_contract(
            _object(body["metrics_protocol"], "metrics_protocol"),
            "metrics_protocol",
        ),
        output_validity_policy=_decode_output_validity_policy(
            _object(body["output_validity_policy"], "output_validity_policy")
        ),
        reproducibility=_decode_reproducibility(
            _object(body["reproducibility"], "reproducibility")
        ),
        random_seed=_integer(body["random_seed"], "random_seed"),
        registered_at=_datetime(body["registered_at"], "registered_at"),
        calculated_at=_datetime(body["calculated_at"], "calculated_at"),
    )


def _decode_target(body: dict[str, object]) -> MacroTargetDefinition:
    _keys(
        body,
        {
            "target_code",
            "family",
            "output_role",
            "dataset_key",
            "business_key",
            "unit",
            "frequency",
            "transformation_version",
            "horizon_periods",
            "horizon_unit",
        },
        "target",
    )
    return MacroTargetDefinition(
        target_code=_string(body["target_code"], "target_code"),
        family=MacroTargetFamily(_string(body["family"], "target.family")),
        output_role=FactorOutputRole(_string(body["output_role"], "target.output_role")),
        dataset_key=_string(body["dataset_key"], "target.dataset_key"),
        business_key=_string(body["business_key"], "target.business_key"),
        unit=_string(body["unit"], "target.unit"),
        frequency=_string(body["frequency"], "target.frequency"),
        transformation_version=_string(
            body["transformation_version"],
            "target.transformation_version",
        ),
        horizon_periods=_integer(body["horizon_periods"], "target.horizon_periods"),
        horizon_unit=_string(body["horizon_unit"], "target.horizon_unit"),
    )


def _decode_candidate(body: dict[str, object]) -> ProxyAssetDefinition:
    _keys(
        body,
        {
            "asset_code",
            "dataset_key",
            "business_key",
            "kind",
            "frequency",
            "transformation_version",
            "continuous_roll_policy_version",
        },
        "candidate",
    )
    return ProxyAssetDefinition(
        asset_code=_string(body["asset_code"], "candidate.asset_code"),
        dataset_key=_string(body["dataset_key"], "candidate.dataset_key"),
        business_key=_string(body["business_key"], "candidate.business_key"),
        kind=ProxyAssetKind(_string(body["kind"], "candidate.kind")),
        frequency=_string(body["frequency"], "candidate.frequency"),
        transformation_version=_string(
            body["transformation_version"],
            "candidate.transformation_version",
        ),
        continuous_roll_policy_version=_string_allow_blank(
            body["continuous_roll_policy_version"],
            "candidate.continuous_roll_policy_version",
        ),
    )


def _decode_inference_period(
    body: dict[str, object],
) -> InferenceTargetCalendarPeriod:
    _keys(
        body,
        {
            "calendar_id",
            "period_id",
            "calendar_version",
            "calendar_hash",
            "period_start",
            "period_end",
            "content_hash",
        },
        "inference_target_period",
    )
    return InferenceTargetCalendarPeriod(
        calendar_id=_string(body["calendar_id"], "calendar_id"),
        period_id=_string(body["period_id"], "period_id"),
        calendar_version=_string(body["calendar_version"], "calendar_version"),
        calendar_hash=_sha256(body["calendar_hash"], "calendar_hash"),
        period_start=_date(body["period_start"], "period_start"),
        period_end=_date(body["period_end"], "period_end"),
        content_hash=_sha256(body["content_hash"], "inference content_hash"),
    )


def _decode_freshness_policy(
    body: dict[str, object],
) -> InputKnowledgeFreshnessPolicy:
    _keys(
        body,
        {
            "policy_version",
            "max_manifest_age_seconds",
            "max_inference_age_seconds",
            "maximum_allowed_age_seconds",
            "content_hash",
        },
        "input_knowledge_freshness_policy",
    )
    return InputKnowledgeFreshnessPolicy(
        policy_version=_string(body["policy_version"], "freshness.policy_version"),
        max_manifest_age_seconds=_integer(
            body["max_manifest_age_seconds"],
            "max_manifest_age_seconds",
        ),
        max_inference_age_seconds=_integer(
            body["max_inference_age_seconds"],
            "max_inference_age_seconds",
        ),
        maximum_allowed_age_seconds=_integer(
            body["maximum_allowed_age_seconds"],
            "maximum_allowed_age_seconds",
        ),
        content_hash=_sha256(body["content_hash"], "freshness content_hash"),
    )


def _encode_timing_policy(value: TargetAvailabilityPolicy) -> dict[str, object]:
    return {
        "policy_version": value.policy_version,
        "target_code": value.target_code,
        "output_role": value.output_role.value,
        "horizon_periods": value.horizon_periods,
        "horizon_unit": value.horizon_unit,
        "normalized_horizon_days": value.normalized_horizon_days,
        "label_availability_lag_days": value.label_availability_lag_days,
        "purge_days": value.purge_days,
        "embargo_days": value.embargo_days,
        "content_hash": value.content_hash.lower(),
    }


def _decode_timing_policy(body: dict[str, object]) -> TargetAvailabilityPolicy:
    _keys(
        body,
        {
            "policy_version",
            "target_code",
            "output_role",
            "horizon_periods",
            "horizon_unit",
            "normalized_horizon_days",
            "label_availability_lag_days",
            "purge_days",
            "embargo_days",
            "content_hash",
        },
        "timing_policy",
    )
    return TargetAvailabilityPolicy(
        policy_version=_string(body["policy_version"], "timing.policy_version"),
        target_code=_string(body["target_code"], "timing.target_code"),
        output_role=FactorOutputRole(_string(body["output_role"], "timing.output_role")),
        horizon_periods=_integer(body["horizon_periods"], "timing.horizon_periods"),
        horizon_unit=_string(body["horizon_unit"], "timing.horizon_unit"),
        normalized_horizon_days=_integer(
            body["normalized_horizon_days"],
            "normalized_horizon_days",
        ),
        label_availability_lag_days=_integer(
            body["label_availability_lag_days"],
            "label_availability_lag_days",
        ),
        purge_days=_integer(body["purge_days"], "purge_days"),
        embargo_days=_integer(body["embargo_days"], "embargo_days"),
        content_hash=_sha256(body["content_hash"], "timing content_hash"),
    )


def _decode_plan(
    body: dict[str, object],
    *,
    timing: TargetAvailabilityPolicy,
) -> NestedTemporalCVPlan:
    _keys(
        body,
        {
            "policy_version",
            "timing_policy_version",
            "timing_policy_hash",
            "alpha_grid",
            "optimization_metric",
            "optimization_direction",
            "final_fold_id",
            "outer_folds",
            "content_hash",
        },
        "plan",
    )
    if (
        _string(body["timing_policy_version"], "timing_policy_version") != timing.policy_version
        or _sha256(body["timing_policy_hash"], "timing_policy_hash").lower()
        != timing.content_hash.lower()
    ):
        raise R3MacroFactorRunnerSpecCodecError("plan timing-policy identity mismatch")
    plan = NestedTemporalCVPlan(
        policy_version=_string(body["policy_version"], "plan.policy_version"),
        timing=timing,
        alpha_grid=tuple(
            _decimal(item, "alpha") for item in _array(body["alpha_grid"], "alpha_grid")
        ),
        optimization_metric=_string(
            body["optimization_metric"],
            "optimization_metric",
        ),
        optimization_direction=OptimizationDirection(
            _string(body["optimization_direction"], "optimization_direction")
        ),
        outer_folds=tuple(
            _decode_outer_fold(_object(item, "outer_fold"))
            for item in _array(body["outer_folds"], "outer_folds")
        ),
        final_fold_id=_string(body["final_fold_id"], "final_fold_id"),
    )
    if _sha256(body["content_hash"], "plan content_hash").lower() != plan.content_hash:
        raise R3MacroFactorRunnerSpecCodecError("plan content_hash mismatch")
    return plan


def _decode_outer_fold(body: dict[str, object]) -> OuterTemporalFoldPlan:
    _keys(
        body,
        {
            "fold_id",
            "training_row_ids",
            "validation_row_ids",
            "out_of_sample_row_ids",
            "selection_as_of",
            "evaluation_as_of",
            "inner_folds",
        },
        "outer_fold",
    )
    return OuterTemporalFoldPlan(
        fold_id=_string(body["fold_id"], "outer.fold_id"),
        training_row_ids=_strings(body["training_row_ids"], "training_row_ids"),
        validation_row_ids=_strings(
            body["validation_row_ids"],
            "validation_row_ids",
        ),
        out_of_sample_row_ids=_strings(
            body["out_of_sample_row_ids"],
            "out_of_sample_row_ids",
        ),
        selection_as_of=_datetime(body["selection_as_of"], "selection_as_of"),
        evaluation_as_of=_datetime(body["evaluation_as_of"], "evaluation_as_of"),
        inner_folds=tuple(
            _decode_inner_fold(_object(item, "inner_fold"))
            for item in _array(body["inner_folds"], "inner_folds")
        ),
    )


def _decode_inner_fold(body: dict[str, object]) -> InnerTemporalFoldPlan:
    _keys(
        body,
        {"fold_id", "training_row_ids", "validation_row_ids"},
        "inner_fold",
    )
    return InnerTemporalFoldPlan(
        fold_id=_string(body["fold_id"], "inner.fold_id"),
        training_row_ids=_strings(body["training_row_ids"], "training_row_ids"),
        validation_row_ids=_strings(
            body["validation_row_ids"],
            "validation_row_ids",
        ),
    )


def _decode_temporal_split(body: dict[str, object]) -> TemporalSplitSpec:
    _keys(
        body,
        {
            "policy_version",
            "training",
            "validation",
            "out_of_sample",
            "walk_forward_folds",
            "embargo_days",
            "content_hash",
        },
        "temporal_split",
    )
    split = TemporalSplitSpec(
        policy_version=_string(body["policy_version"], "split.policy_version"),
        training=_decode_window(_object(body["training"], "training")),
        validation=_decode_window(_object(body["validation"], "validation")),
        out_of_sample=_decode_window(_object(body["out_of_sample"], "out_of_sample")),
        walk_forward_folds=tuple(
            _decode_walk_forward_fold(_object(item, "walk_forward_fold"))
            for item in _array(body["walk_forward_folds"], "walk_forward_folds")
        ),
        embargo_days=_integer(body["embargo_days"], "embargo_days"),
    )
    from apps.macro_factor.domain.temporal_runner_spec import (  # local cycle-free helper
        calculate_temporal_split_hash,
    )

    if _sha256(
        body["content_hash"], "temporal_split content_hash"
    ).lower() != calculate_temporal_split_hash(split):
        raise R3MacroFactorRunnerSpecCodecError("temporal_split content_hash mismatch")
    return split


def _decode_window(body: dict[str, object]) -> SampleWindow:
    _keys(body, {"start", "end"}, "sample window")
    return SampleWindow(
        start=_date(body["start"], "window.start"),
        end=_date(body["end"], "window.end"),
    )


def _decode_walk_forward_fold(body: dict[str, object]) -> WalkForwardFold:
    _keys(
        body,
        {"fold_id", "training", "validation", "out_of_sample"},
        "walk_forward_fold",
    )
    return WalkForwardFold(
        fold_id=_string(body["fold_id"], "walk_forward.fold_id"),
        training=_decode_window(_object(body["training"], "training")),
        validation=_decode_window(_object(body["validation"], "validation")),
        out_of_sample=_decode_window(_object(body["out_of_sample"], "out_of_sample")),
    )


def _decode_contract(
    body: dict[str, object],
    label: str,
) -> VersionedResearchContract:
    _keys(body, {"version", "content_hash"}, label)
    return VersionedResearchContract(
        version=_string(body["version"], f"{label}.version"),
        content_hash=_sha256(body["content_hash"], f"{label}.content_hash"),
    )


def _decode_fixed_fmp(body: dict[str, object]) -> FixedFMPDefinition:
    _keys(
        body,
        {"benchmark_version", "intercept", "weights", "content_hash"},
        "fixed_fmp",
    )
    weights: list[FixedFMPWeight] = []
    for item in _array(body["weights"], "fixed_fmp.weights"):
        weight = _object(item, "fixed_fmp.weight")
        _keys(weight, {"asset_code", "weight"}, "fixed_fmp.weight")
        weights.append(
            FixedFMPWeight(
                asset_code=_string(weight["asset_code"], "weight.asset_code"),
                weight=_decimal(weight["weight"], "weight.value"),
            )
        )
    return FixedFMPDefinition(
        benchmark_version=_string(
            body["benchmark_version"],
            "fixed_fmp.benchmark_version",
        ),
        intercept=_decimal(body["intercept"], "fixed_fmp.intercept"),
        weights=tuple(weights),
        content_hash=_sha256(body["content_hash"], "fixed_fmp.content_hash"),
    )


def _decode_output_validity_policy(
    body: dict[str, object],
) -> ResearchOutputValidityPolicy:
    _keys(
        body,
        {
            "policy_version",
            "valid_for_seconds",
            "maximum_valid_for_seconds",
            "content_hash",
        },
        "output_validity_policy",
    )
    return ResearchOutputValidityPolicy(
        policy_version=_string(body["policy_version"], "validity.policy_version"),
        valid_for_seconds=_integer(body["valid_for_seconds"], "valid_for_seconds"),
        maximum_valid_for_seconds=_integer(
            body["maximum_valid_for_seconds"],
            "maximum_valid_for_seconds",
        ),
        content_hash=_sha256(body["content_hash"], "validity.content_hash"),
    )


def _decode_reproducibility(body: dict[str, object]) -> ReproducibilityEvidence:
    _keys(
        body,
        {
            "code_version",
            "dependency_lock_hash",
            "parameter_version",
            "parameter_hash",
        },
        "reproducibility",
    )
    return ReproducibilityEvidence(
        code_version=_string(body["code_version"], "code_version"),
        dependency_lock_hash=_sha256(
            body["dependency_lock_hash"],
            "dependency_lock_hash",
        ),
        parameter_version=_string(body["parameter_version"], "parameter_version"),
        parameter_hash=_sha256(body["parameter_hash"], "parameter_hash"),
    )


def _object(value: object, label: str) -> dict[str, object]:
    if type(value) is not dict:
        raise R3MacroFactorRunnerSpecCodecError(f"{label} must be an object")
    return value


def _array(value: object, label: str) -> list[object]:
    if type(value) is not list:
        raise R3MacroFactorRunnerSpecCodecError(f"{label} must be an array")
    return value


def _keys(body: dict[str, object], expected: set[str], label: str) -> None:
    if set(body) != expected:
        raise R3MacroFactorRunnerSpecCodecError(f"{label} must contain exact keys")


def _string(value: object, label: str) -> str:
    if type(value) is not str or not value:
        raise R3MacroFactorRunnerSpecCodecError(f"{label} must be a non-empty string")
    return value


def _string_allow_blank(value: object, label: str) -> str:
    if type(value) is not str:
        raise R3MacroFactorRunnerSpecCodecError(f"{label} must be a string")
    return value


def _integer(value: object, label: str) -> int:
    if type(value) is not int:
        raise R3MacroFactorRunnerSpecCodecError(f"{label} must be an integer")
    return value


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise R3MacroFactorRunnerSpecCodecError(f"{label} must be a boolean")
    return value


def _sha256(value: object, label: str) -> str:
    text = _string(value, label)
    if len(text) != 64 or any(character not in "0123456789abcdefABCDEF" for character in text):
        raise R3MacroFactorRunnerSpecCodecError(f"{label} must be a sha256 digest")
    return text


def _decimal(value: object, label: str) -> Decimal:
    text = _string(value, label)
    try:
        parsed = Decimal(text)
    except InvalidOperation as error:
        raise R3MacroFactorRunnerSpecCodecError(f"{label} must be a decimal string") from error
    if not parsed.is_finite():
        raise R3MacroFactorRunnerSpecCodecError(f"{label} must be finite")
    return parsed


def _date(value: object, label: str) -> date:
    text = _string(value, label)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as error:
        raise R3MacroFactorRunnerSpecCodecError(f"{label} must be an ISO date") from error
    return parsed


def _datetime(value: object, label: str) -> datetime:
    text = _string(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise R3MacroFactorRunnerSpecCodecError(f"{label} must be an ISO datetime") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise R3MacroFactorRunnerSpecCodecError(f"{label} must be timezone-aware")
    return parsed


def _strings(value: object, label: str) -> tuple[str, ...]:
    return tuple(_string(item, f"{label} item") for item in _array(value, label))


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "R3MacroFactorRunnerSpecCodecError",
    "decode_persisted_macro_factor_runner_spec",
    "encode_persisted_macro_factor_runner_spec",
]
