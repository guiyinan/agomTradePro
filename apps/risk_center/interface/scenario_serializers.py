"""Strict DRF serializers for governed stress-scenario workflows."""

from __future__ import annotations

from typing import Any, ClassVar, cast

from rest_framework import serializers


class RejectUnknownFieldsSerializer(serializers.Serializer[dict[str, Any]]):
    """Reject input keys that are not declared by the concrete serializer."""

    allowed_input_aliases: ClassVar[frozenset[str]] = frozenset()

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        """Reject unknown keys before normal DRF validation."""

        if not isinstance(data, dict):
            raise serializers.ValidationError("request payload must be an object")
        allowed = set(self.fields).union(self.allowed_input_aliases)
        unknown = sorted(set(data).difference(allowed))
        if unknown:
            raise serializers.ValidationError({key: ["unknown field"] for key in unknown})
        return cast(dict[str, Any], super().to_internal_value(data))


class ScenarioEvidenceSerializer(RejectUnknownFieldsSerializer):
    """One point-in-time source reference."""

    source: Any = serializers.CharField(max_length=160)
    publication_id = serializers.CharField(max_length=160)
    observed_at = serializers.DateTimeField()
    freshness_state = serializers.ChoiceField(
        choices=("fresh", "stale", "missing", "unpublished", "blocked")
    )


class HistoricalWindowParametersSerializer(RejectUnknownFieldsSerializer):
    """Typed parameters for historical-window replay."""

    start_date = serializers.DateField()
    end_date = serializers.DateField()
    source: Any = serializers.CharField(max_length=160)
    event_description = serializers.CharField(max_length=500)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Require an increasing historical window."""

        if attrs["end_date"] < attrs["start_date"]:
            raise serializers.ValidationError("end_date must not precede start_date")
        return attrs


class RollingExtremeParametersSerializer(RejectUnknownFieldsSerializer):
    """Typed parameters for rolling extreme-window generation."""

    lookback_days = serializers.IntegerField(min_value=20, max_value=10000)
    window_days = serializers.IntegerField(min_value=2, max_value=500)
    selection_indicator = serializers.CharField(max_length=120)
    selection_metric = serializers.ChoiceField(choices=("cumulative_return", "realized_volatility"))
    direction = serializers.ChoiceField(choices=("minimum", "maximum"))
    recalculation_frequency = serializers.ChoiceField(choices=("daily", "weekly", "monthly"))

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Keep the rolling window strictly inside its lookback period."""

        if attrs["window_days"] >= attrs["lookback_days"]:
            raise serializers.ValidationError("window_days must be smaller than lookback_days")
        return attrs


class ParametricShockItemSerializer(RejectUnknownFieldsSerializer):
    """One finite, explicitly unit-tagged shock."""

    target_kind = serializers.ChoiceField(choices=("asset", "asset_class", "factor"))
    target = serializers.CharField(max_length=120)
    shock_kind = serializers.CharField(max_length=80)
    magnitude = serializers.FloatField(min_value=-10000, max_value=10000)
    unit = serializers.ChoiceField(choices=("percent", "basis_points", "absolute", "correlation"))
    horizon_days = serializers.IntegerField(min_value=1, max_value=3650)


class ParametricShockParametersSerializer(RejectUnknownFieldsSerializer):
    """Typed list of finite parametric shocks."""

    shocks = serializers.ListField(
        child=ParametricShockItemSerializer(),
        allow_empty=False,
        max_length=100,
    )
    correlation_assumption = serializers.CharField(max_length=500)


class MacroPathNodeSerializer(RejectUnknownFieldsSerializer):
    """One finite path node; arbitrary code is never accepted."""

    path_date = serializers.DateField()
    value = serializers.FloatField()


class MacroDriverSerializer(RejectUnknownFieldsSerializer):
    """Observable macro driver used by one path scenario."""

    driver_key = serializers.CharField(max_length=120)
    state = serializers.CharField(max_length=120)
    proxy_indicator = serializers.CharField(max_length=160)
    unit = serializers.CharField(max_length=40)
    nodes = serializers.ListField(
        child=MacroPathNodeSerializer(),
        min_length=1,
        max_length=120,
    )


class MacroAssetImpactSerializer(RejectUnknownFieldsSerializer):
    """Explicit, explainable asset impact for one macro path."""

    target_kind = serializers.ChoiceField(choices=("asset", "asset_class", "factor"))
    target = serializers.CharField(max_length=120)
    cumulative_return = serializers.FloatField(min_value=-1)
    rationale = serializers.CharField(max_length=1000)


class MacroPathParametersSerializer(RejectUnknownFieldsSerializer):
    """Typed parameters for two-dimensional or list-form macro paths."""

    drivers = serializers.ListField(
        child=MacroDriverSerializer(),
        min_length=1,
        max_length=8,
    )
    probability = serializers.FloatField(min_value=0, max_value=1)
    probability_source = serializers.ChoiceField(choices=("subjective", "model_inferred"))
    asset_impacts = serializers.ListField(
        child=MacroAssetImpactSerializer(),
        min_length=1,
        max_length=100,
    )
    invalidation_conditions = serializers.ListField(
        child=serializers.CharField(max_length=1000),
        min_length=1,
        max_length=50,
    )
    review_date = serializers.DateField()


_PARAMETER_SERIALIZERS: dict[str, type[RejectUnknownFieldsSerializer]] = {
    "historical_window": HistoricalWindowParametersSerializer,
    "rolling_extreme": RollingExtremeParametersSerializer,
    "parametric_shock": ParametricShockParametersSerializer,
    "macro_path": MacroPathParametersSerializer,
}


class ScenarioRevisionSerializer(RejectUnknownFieldsSerializer):
    """Strict revision payload shared by validate, preview, and proposal APIs."""

    scenario_key = serializers.RegexField(r"^[a-z0-9][a-z0-9_.-]{1,95}$")
    name = serializers.CharField(max_length=160)
    category = serializers.CharField(max_length=80)
    owner = serializers.CharField(max_length=160)
    scenario_type = serializers.ChoiceField(choices=tuple(_PARAMETER_SERIALIZERS))
    based_on_version = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    parameters = serializers.JSONField()
    assumptions = serializers.ListField(
        child=serializers.CharField(max_length=1000),
        allow_empty=False,
        max_length=100,
    )
    evidence = serializers.ListField(
        child=ScenarioEvidenceSerializer(),
        allow_empty=False,
        max_length=100,
    )
    invalidation_logic = serializers.CharField(max_length=2000)
    review_date = serializers.DateField()
    change_reason = serializers.CharField(max_length=1000)
    source_type = serializers.ChoiceField(
        choices=("human", "ai_mcp", "seed", "detector"),
        default="human",
    )
    preview_id = serializers.CharField(required=False, max_length=160)
    proposal_id = serializers.CharField(required=False, max_length=160)
    idempotency_key = serializers.CharField(required=False, max_length=255)
    expected_active_version = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
    )
    expected_active_hash = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=64,
    )
    correlation_id = serializers.CharField(required=False, max_length=160)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Validate the scenario-type-specific parameter schema."""

        scenario_type = str(attrs["scenario_type"])
        serializer_type = _PARAMETER_SERIALIZERS[scenario_type]
        parameter_serializer = serializer_type(data=attrs["parameters"])
        parameter_serializer.is_valid(raise_exception=True)
        attrs["parameters"] = parameter_serializer.validated_data
        return attrs


class ScenarioActivationSerializer(RejectUnknownFieldsSerializer):
    """Strict persisted confirmation payload for activation."""

    scenario_set_revision_id = serializers.CharField(max_length=160)
    proposal_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    preview_id = serializers.CharField(max_length=160)
    environment = serializers.ChoiceField(choices=("production", "shadow"))
    purpose = serializers.CharField(max_length=120)
    expected_active_version = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    expected_active_hash = serializers.CharField(required=False, allow_null=True, max_length=64)
    idempotency_key = serializers.CharField(max_length=255)
    change_reason = serializers.CharField(max_length=1000)
    correlation_id = serializers.CharField(max_length=160)


class ScenarioRollbackSerializer(ScenarioActivationSerializer):
    """Strict rollback payload; rollback creates a new immutable revision."""

    scenario_key = serializers.CharField(max_length=120)
    target_version = serializers.IntegerField(min_value=1)


class ScenarioRetireSerializer(RejectUnknownFieldsSerializer):
    """Strict retirement proposal or execution payload."""

    preview_id = serializers.CharField(max_length=160)
    proposal_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    expected_active_version = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    expected_active_hash = serializers.CharField(required=False, allow_null=True, max_length=64)
    idempotency_key = serializers.CharField(max_length=255)
    change_reason = serializers.CharField(max_length=1000)
    correlation_id = serializers.CharField(max_length=160)


class ScenarioGovernancePreviewSerializer(RejectUnknownFieldsSerializer):
    """Exact operation payload for a durable, actor-bound preview."""

    operation = serializers.ChoiceField(choices=("propose", "activate", "rollback", "retire"))
    payload = serializers.JSONField()
    scenario_key = serializers.CharField(required=False, allow_null=True, max_length=120)
    scenario_set_revision_id = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=160,
    )
    environment = serializers.ChoiceField(
        choices=("production", "shadow"),
        required=False,
        allow_null=True,
    )
    purpose = serializers.CharField(required=False, allow_null=True, max_length=120)
    target_version = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    expected_active_version = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
    )
    expected_active_hash = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=64,
    )
    change_reason = serializers.CharField(max_length=1000)
    correlation_id = serializers.CharField(max_length=160)


class ScenarioProposalReviewSerializer(RejectUnknownFieldsSerializer):
    """Explicit human review payload for one persisted proposal."""

    reason = serializers.CharField(max_length=1000)
    correlation_id = serializers.CharField(max_length=160)


class ScenarioImpactPreviewSerializer(RejectUnknownFieldsSerializer):
    """References required for a side-effect-free portfolio impact preview."""

    scenario_set_revision_id = serializers.CharField(max_length=160)
    portfolio_snapshot_id = serializers.CharField(max_length=160)
    allocation_policy_version = serializers.CharField(max_length=160)
    as_of_time = serializers.DateTimeField(required=False)


class ActiveScenarioSetQuerySerializer(RejectUnknownFieldsSerializer):
    """Scope for resolving a sole active scenario-set revision."""

    environment = serializers.ChoiceField(
        choices=("production", "shadow"),
        default="production",
    )
    purpose = serializers.CharField(max_length=120, default="portfolio_stress")


class ScenarioListQuerySerializer(RejectUnknownFieldsSerializer):
    """Strict filters for the scenario catalog."""

    include_inactive = serializers.BooleanField(default=False)
    scenario_type = serializers.ChoiceField(
        choices=tuple(_PARAMETER_SERIALIZERS),
        required=False,
    )
