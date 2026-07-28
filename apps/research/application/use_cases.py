"""Research registry use cases."""

from __future__ import annotations

import json
import math
import re
import uuid
from collections.abc import Mapping, Sequence
from copy import deepcopy

from apps.research.domain.contracts import (
    DatasetSplitPayload,
    ExperimentTrialView,
    MetricObservationPayload,
    PromotionDecisionView,
    ResearchExperimentView,
    ResearchRegistryGateway,
    TrialRegistrationPayload,
)

_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_TRIAL_STATUSES = frozenset({"draft", "running", "completed", "failed", "aborted"})
_TRUST_STATUSES = frozenset({"legacy_unverified", "exploratory", "pit_verified"})
_TRIAL_FIELDS = frozenset(TrialRegistrationPayload.__required_keys__)
_SPLIT_FIELDS = frozenset(DatasetSplitPayload.__required_keys__)
_METRIC_REQUIRED_FIELDS = frozenset({"metric_name", "value", "sample_count"})
_METRIC_OPTIONAL_FIELDS = frozenset(
    {
        "confidence_interval_low",
        "confidence_interval_high",
        "p_value",
        "metadata",
    }
)
_MAX_JSON_OBJECT_BYTES = 65_536
_MAX_TRIAL_EVIDENCE_BYTES = 262_144


class RegisterExperiment:
    def __init__(self, repository: ResearchRegistryGateway):
        self._repository = repository

    def execute(
        self,
        *,
        question: str,
        hypothesis: str,
        owner_id: int | None,
    ) -> ResearchExperimentView:
        """Register a bounded question and falsifiable hypothesis."""

        normalized_owner_id = _optional_positive_id(owner_id, label="owner_id")
        return self._repository.create_experiment(
            experiment_id=uuid.uuid4().hex,
            question=_bounded_text(question, label="question", maximum=4_000),
            hypothesis=_bounded_text(hypothesis, label="hypothesis", maximum=8_000),
            owner_id=normalized_owner_id,
        )


class RunTrial:
    def __init__(self, repository: ResearchRegistryGateway):
        self._repository = repository

    def execute(
        self,
        payload: Mapping[str, object],
        *,
        actor_user_id: int,
        actor_is_staff: bool = False,
    ) -> ExperimentTrialView:
        """Validate, freeze and register one owner-scoped trial payload."""

        actor_id = _positive_id(actor_user_id, label="actor_user_id")
        if not isinstance(actor_is_staff, bool):
            raise ValueError("actor_is_staff must be boolean")
        normalized = _normalize_trial_payload(payload)
        return self._repository.create_trial(
            normalized,
            trial_id=uuid.uuid4().hex,
            actor_user_id=actor_id,
            actor_is_staff=actor_is_staff,
        )


class EvaluatePromotion:
    def __init__(self, repository: ResearchRegistryGateway):
        self._repository = repository

    def execute(
        self,
        trial_id: str,
        *,
        actor_user_id: int,
        actor_is_staff: bool = False,
    ) -> PromotionDecisionView:
        """Evaluate an owner-scoped completed trial against the promotion gate."""

        actor_id = _positive_id(actor_user_id, label="actor_user_id")
        if not isinstance(actor_is_staff, bool):
            raise ValueError("actor_is_staff must be boolean")
        return self._repository.evaluate_promotion(
            _identifier(trial_id, label="trial_id"),
            actor_user_id=actor_id,
            actor_is_staff=actor_is_staff,
        )


def _normalize_trial_payload(payload: Mapping[str, object]) -> TrialRegistrationPayload:
    """Return a detached exact trial contract for repository persistence."""

    if any(not isinstance(key, str) for key in payload):
        raise ValueError("trial payload keys must be strings")
    fields = set(payload)
    missing = _TRIAL_FIELDS - fields
    unknown = fields - _TRIAL_FIELDS
    if missing:
        raise ValueError(f"trial payload missing fields: {', '.join(sorted(missing))}")
    if unknown:
        raise ValueError(f"trial payload contains unknown fields: {', '.join(sorted(unknown))}")

    status = _bounded_text(payload["status"], label="status", maximum=32)
    if status not in _TRIAL_STATUSES:
        raise ValueError("status is not supported")
    trust_status = _bounded_text(
        payload["backtest_trust_status"],
        label="backtest_trust_status",
        maximum=24,
    )
    if trust_status not in _TRUST_STATUSES:
        raise ValueError("backtest_trust_status is not supported")

    normalized = TrialRegistrationPayload(
        experiment_id=_identifier(payload["experiment_id"], label="experiment_id"),
        family_id=_identifier(payload["family_id"], label="family_id"),
        planned_trial_count=_bounded_int(
            payload["planned_trial_count"],
            label="planned_trial_count",
            minimum=1,
            maximum=10_000,
        ),
        status=status,
        pit_manifest_id=_identifier(payload["pit_manifest_id"], label="pit_manifest_id"),
        backtest_id=_optional_positive_id(payload["backtest_id"], label="backtest_id"),
        backtest_trust_status=trust_status,
        code_commit=_bounded_text(payload["code_commit"], label="code_commit", maximum=64),
        dependency_lock_hash=_bounded_text(
            payload["dependency_lock_hash"],
            label="dependency_lock_hash",
            maximum=64,
        ),
        engine_version=_bounded_text(
            payload["engine_version"],
            label="engine_version",
            maximum=64,
        ),
        parameters=_json_object(payload["parameters"], label="parameters"),
        random_seed=_bounded_int(
            payload["random_seed"],
            label="random_seed",
            minimum=-(2**63),
            maximum=2**63 - 1,
        ),
        benchmark_spec=_json_object(payload["benchmark_spec"], label="benchmark_spec"),
        cost_spec=_json_object(payload["cost_spec"], label="cost_spec"),
        slippage_spec=_json_object(payload["slippage_spec"], label="slippage_spec"),
        universe_spec=_json_object(payload["universe_spec"], label="universe_spec"),
        split_spec=_normalize_split(payload["split_spec"]),
        metrics=_normalize_metrics(payload["metrics"]),
    )
    _ensure_json_size(
        normalized,
        label="trial evidence",
        maximum=_MAX_TRIAL_EVIDENCE_BYTES,
    )
    return normalized


def _normalize_split(value: object) -> DatasetSplitPayload:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError("split_spec must be an object")
    fields = set(value)
    if fields != _SPLIT_FIELDS:
        raise ValueError("split_spec must contain exactly the governed fields")
    windows = value["walk_forward_windows"]
    if not isinstance(windows, Sequence) or isinstance(windows, (str, bytes)):
        raise ValueError("walk_forward_windows must be an array")
    if len(windows) > 1_000:
        raise ValueError("walk_forward_windows exceeds 1000 items")
    normalized_windows = [_json_object(item, label="walk_forward_window") for item in windows]
    return DatasetSplitPayload(
        training_window=_json_object(value["training_window"], label="training_window"),
        validation_window=_json_object(
            value["validation_window"],
            label="validation_window",
        ),
        out_of_sample_window=_json_object(
            value["out_of_sample_window"],
            label="out_of_sample_window",
        ),
        walk_forward_windows=normalized_windows,
        embargo_days=_bounded_int(
            value["embargo_days"],
            label="embargo_days",
            minimum=0,
            maximum=3_650,
        ),
    )


def _normalize_metrics(value: object) -> list[MetricObservationPayload]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("metrics must be an array")
    if len(value) > 100:
        raise ValueError("metrics exceeds 100 items")
    metrics: list[MetricObservationPayload] = []
    names: set[str] = set()
    for raw_metric in value:
        if not isinstance(raw_metric, Mapping) or any(
            not isinstance(key, str) for key in raw_metric
        ):
            raise ValueError("metric must be an object")
        fields = set(raw_metric)
        if not _METRIC_REQUIRED_FIELDS <= fields or fields - (
            _METRIC_REQUIRED_FIELDS | _METRIC_OPTIONAL_FIELDS
        ):
            raise ValueError("metric fields do not match the governed contract")
        metric_name = _identifier(raw_metric["metric_name"], label="metric_name")
        if metric_name in names:
            raise ValueError("metric_name must be unique within one trial")
        names.add(metric_name)
        metric = MetricObservationPayload(
            metric_name=metric_name,
            value=_finite_float(raw_metric["value"], label="metric.value"),
            sample_count=_bounded_int(
                raw_metric["sample_count"],
                label="metric.sample_count",
                minimum=1,
                maximum=2**31 - 1,
            ),
        )
        low = _optional_finite_float(
            raw_metric.get("confidence_interval_low"),
            label="confidence_interval_low",
        )
        high = _optional_finite_float(
            raw_metric.get("confidence_interval_high"),
            label="confidence_interval_high",
        )
        if (low is None) != (high is None) or (low is not None and high is not None and low > high):
            raise ValueError("metric confidence interval must be paired and ordered")
        p_value = _optional_finite_float(raw_metric.get("p_value"), label="p_value")
        if p_value is not None and not 0 <= p_value <= 1:
            raise ValueError("p_value must be between 0 and 1")
        if "confidence_interval_low" in raw_metric:
            metric["confidence_interval_low"] = low
        if "confidence_interval_high" in raw_metric:
            metric["confidence_interval_high"] = high
        if "p_value" in raw_metric:
            metric["p_value"] = p_value
        if "metadata" in raw_metric:
            metric["metadata"] = _json_object(raw_metric["metadata"], label="metric.metadata")
        metrics.append(metric)
    return metrics


def _json_object(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be an object with string keys")
    detached = deepcopy(dict(value))
    try:
        encoded = json.dumps(detached, allow_nan=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must contain finite JSON values") from exc
    if len(encoded.encode("utf-8")) > _MAX_JSON_OBJECT_BYTES:
        raise ValueError(f"{label} exceeds {_MAX_JSON_OBJECT_BYTES} bytes")
    return detached


def _ensure_json_size(value: object, *, label: str, maximum: int) -> None:
    """Reject JSON evidence that exceeds the bounded persistence envelope."""

    try:
        encoded = json.dumps(value, allow_nan=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must contain finite JSON values") from exc
    if len(encoded.encode("utf-8")) > maximum:
        raise ValueError(f"{label} exceeds {maximum} bytes")


def _identifier(value: object, *, label: str) -> str:
    normalized = _bounded_text(value, label=label, maximum=64)
    if _IDENTIFIER_PATTERN.fullmatch(normalized) is None:
        raise ValueError(f"{label} has an invalid format")
    return normalized


def _bounded_text(value: object, *, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or "\x00" in normalized:
        raise ValueError(f"{label} must contain 1-{maximum} characters")
    return normalized


def _bounded_int(value: object, *, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{label} is outside the supported range")
    return value


def _positive_id(value: object, *, label: str) -> int:
    return _bounded_int(value, label=label, minimum=1, maximum=2**63 - 1)


def _optional_positive_id(value: object, *, label: str) -> int | None:
    if value is None:
        return None
    return _positive_id(value, label=label)


def _finite_float(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{label} must be finite")
    return normalized


def _optional_finite_float(value: object, *, label: str) -> float | None:
    if value is None:
        return None
    return _finite_float(value, label=label)
