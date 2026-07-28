"""Strict DRF input contracts for the Research registry."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from copy import deepcopy
from typing import cast

from rest_framework import serializers

_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_MAX_JSON_OBJECT_BYTES = 65_536
_MAX_TRIAL_EVIDENCE_BYTES = 262_144


class StrictFieldsSerializer(serializers.Serializer[dict[str, object]]):
    """Reject undeclared input fields instead of silently discarding them."""

    def to_internal_value(self, data: object) -> dict[str, object]:
        """Validate the mapping shape and reject unknown field names."""

        if isinstance(data, Mapping):
            if any(not isinstance(key, str) for key in data):
                raise serializers.ValidationError(
                    {"non_field_errors": ["Object keys must be strings."]}
                )
            unknown = set(data) - set(self.fields)
            if unknown:
                raise serializers.ValidationError(
                    {"non_field_errors": [f"Unknown fields: {', '.join(sorted(unknown))}."]}
                )
        return cast(dict[str, object], super().to_internal_value(data))


class ExperimentSerializer(StrictFieldsSerializer):
    """Validate one bounded research experiment registration."""

    question = serializers.CharField(min_length=1, max_length=4_000)
    hypothesis = serializers.CharField(min_length=1, max_length=8_000)


class DatasetSplitSerializer(StrictFieldsSerializer):
    """Validate governed train/validation/out-of-sample split evidence."""

    training_window = serializers.DictField(child=serializers.JSONField())
    validation_window = serializers.DictField(child=serializers.JSONField())
    out_of_sample_window = serializers.DictField(child=serializers.JSONField())
    walk_forward_windows = serializers.ListField(
        child=serializers.DictField(child=serializers.JSONField()),
        max_length=1_000,
    )
    embargo_days = serializers.IntegerField(min_value=0, max_value=3_650)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        """Enforce JSON validity and per-object size limits."""

        for field_name in (
            "training_window",
            "validation_window",
            "out_of_sample_window",
        ):
            attrs[field_name] = _bounded_json_object(attrs[field_name], label=field_name)
        windows = attrs["walk_forward_windows"]
        if not isinstance(windows, list):
            raise serializers.ValidationError({"walk_forward_windows": ["Expected an array."]})
        attrs["walk_forward_windows"] = [
            _bounded_json_object(window, label="walk_forward_window") for window in windows
        ]
        return attrs


class MetricObservationSerializer(StrictFieldsSerializer):
    """Validate one finite, immutable research metric observation."""

    metric_name = serializers.RegexField(
        regex=_IDENTIFIER_PATTERN,
        max_length=64,
    )
    value = serializers.FloatField()
    sample_count = serializers.IntegerField(min_value=1, max_value=2**31 - 1)
    confidence_interval_low = serializers.FloatField(required=False, allow_null=True)
    confidence_interval_high = serializers.FloatField(required=False, allow_null=True)
    p_value = serializers.FloatField(
        required=False,
        allow_null=True,
        min_value=0.0,
        max_value=1.0,
    )
    metadata = serializers.DictField(
        child=serializers.JSONField(),
        required=False,
        default=dict,
    )

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        """Require finite values and paired, ordered confidence bounds."""

        for field_name in (
            "value",
            "confidence_interval_low",
            "confidence_interval_high",
            "p_value",
        ):
            value = attrs.get(field_name)
            if value is not None and not _is_finite_number(value):
                raise serializers.ValidationError({field_name: ["A finite number is required."]})

        low = attrs.get("confidence_interval_low")
        high = attrs.get("confidence_interval_high")
        if (low is None) != (high is None):
            raise serializers.ValidationError(
                {
                    "confidence_interval_low": [
                        "Both confidence interval bounds are required together."
                    ]
                }
            )
        if (
            isinstance(low, (int, float))
            and not isinstance(low, bool)
            and isinstance(high, (int, float))
            and not isinstance(high, bool)
            and float(low) > float(high)
        ):
            raise serializers.ValidationError(
                {"confidence_interval_low": ["Lower bound must not exceed upper bound."]}
            )
        attrs["metadata"] = _bounded_json_object(attrs["metadata"], label="metadata")
        return attrs


class TrialSerializer(StrictFieldsSerializer):
    """Validate one complete Research trial registration payload."""

    experiment_id = serializers.RegexField(regex=_IDENTIFIER_PATTERN, max_length=64)
    family_id = serializers.RegexField(regex=_IDENTIFIER_PATTERN, max_length=64)
    planned_trial_count = serializers.IntegerField(min_value=1, max_value=10_000)
    status = serializers.ChoiceField(
        choices=("draft", "running", "completed", "failed", "aborted"),
        default="draft",
    )
    pit_manifest_id = serializers.RegexField(regex=_IDENTIFIER_PATTERN, max_length=64)
    backtest_id = serializers.IntegerField(
        min_value=1,
        max_value=2**63 - 1,
        required=False,
        allow_null=True,
        default=None,
    )
    backtest_trust_status = serializers.ChoiceField(
        choices=("legacy_unverified", "exploratory", "pit_verified")
    )
    code_commit = serializers.CharField(min_length=1, max_length=64)
    dependency_lock_hash = serializers.CharField(min_length=1, max_length=64)
    engine_version = serializers.CharField(min_length=1, max_length=64)
    parameters = serializers.DictField(child=serializers.JSONField())
    random_seed = serializers.IntegerField(min_value=-(2**63), max_value=2**63 - 1)
    benchmark_spec = serializers.DictField(child=serializers.JSONField())
    cost_spec = serializers.DictField(child=serializers.JSONField())
    slippage_spec = serializers.DictField(child=serializers.JSONField())
    universe_spec = serializers.DictField(child=serializers.JSONField())
    split_spec = DatasetSplitSerializer()
    metrics = MetricObservationSerializer(many=True, required=False, default=list)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        """Bound all JSON objects, metric identities and total evidence size."""

        for field_name in (
            "parameters",
            "benchmark_spec",
            "cost_spec",
            "slippage_spec",
            "universe_spec",
        ):
            attrs[field_name] = _bounded_json_object(attrs[field_name], label=field_name)

        metrics = attrs["metrics"]
        if not isinstance(metrics, list):
            raise serializers.ValidationError({"metrics": ["Expected an array."]})
        if len(metrics) > 100:
            raise serializers.ValidationError({"metrics": ["At most 100 items are allowed."]})
        metric_names = [
            metric.get("metric_name") for metric in metrics if isinstance(metric, Mapping)
        ]
        if len(metric_names) != len(set(metric_names)):
            raise serializers.ValidationError(
                {"metrics": ["metric_name must be unique within one trial."]}
            )
        _ensure_json_size(
            attrs,
            label="trial evidence",
            maximum=_MAX_TRIAL_EVIDENCE_BYTES,
        )
        return attrs


def _bounded_json_object(value: object, *, label: str) -> dict[str, object]:
    """Return a detached, finite JSON object within the configured size bound."""

    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise serializers.ValidationError({label: ["Expected an object with string keys."]})
    detached = {key: deepcopy(item) for key, item in value.items()}
    _ensure_json_size(detached, label=label, maximum=_MAX_JSON_OBJECT_BYTES)
    return detached


def _ensure_json_size(value: object, *, label: str, maximum: int) -> None:
    """Reject non-finite/non-JSON evidence and oversized encoded payloads."""

    try:
        encoded = json.dumps(value, allow_nan=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise serializers.ValidationError(
            {label: ["Finite JSON-compatible values are required."]}
        ) from exc
    if len(encoded.encode("utf-8")) > maximum:
        raise serializers.ValidationError({label: [f"Maximum size is {maximum} bytes."]})


def _is_finite_number(value: object) -> bool:
    """Return whether a serializer value is a finite real number."""

    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )
