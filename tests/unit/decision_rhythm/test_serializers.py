from apps.decision_rhythm.domain.entities import (
    DecisionPriority,
    ExecutionTarget,
    QuotaPeriod,
)
from apps.decision_rhythm.interface.serializers import (
    DecisionPrioritySerializer,
    ExecuteDecisionRequestSerializer,
    SubmitDecisionRequestRequestSerializer,
)


def test_decision_priority_field_round_trips_domain_enum() -> None:
    field = DecisionPrioritySerializer()

    assert field.to_representation(DecisionPriority.HIGH) == "high"
    assert field.to_internal_value("high") is DecisionPriority.HIGH


def test_submit_decision_normalizes_priority_and_quota_period() -> None:
    serializer = SubmitDecisionRequestRequestSerializer(
        data={
            "asset_code": "600519.SH",
            "asset_class": "a_share",
            "direction": "BUY",
            "priority": " HIGH ",
            "quota_period": " WEEKLY ",
        }
    )

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["priority"] == DecisionPriority.HIGH.value
    assert serializer.validated_data["quota_period"] == QuotaPeriod.WEEKLY.value


def test_execute_decision_normalizes_execution_target() -> None:
    serializer = ExecuteDecisionRequestSerializer(data={"target": " simulated "})

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["target"] == ExecutionTarget.SIMULATED.value
