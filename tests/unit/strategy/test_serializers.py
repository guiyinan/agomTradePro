from types import SimpleNamespace

from django.utils import timezone

from apps.strategy.interface.serializers import (
    PositionManagementEvaluateInputSerializer,
    StrategyDetailSerializer,
    StrategyExecuteRequestSerializer,
)


def test_position_management_evaluate_context_remains_a_writable_json_field() -> None:
    serializer = PositionManagementEvaluateInputSerializer(
        data={"context": {"current_price": 10.5}}
    )

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data == {"context": {"current_price": 10.5}}


def test_strategy_execute_request_rejects_unknown_fields() -> None:
    serializer = StrategyExecuteRequestSerializer(data={"unexpected": True})

    assert not serializer.is_valid()
    assert "Unknown parameters: unexpected" in str(serializer.errors)


def test_strategy_execute_request_accepts_current_date() -> None:
    serializer = StrategyExecuteRequestSerializer(
        data={"as_of_date": timezone.localdate().isoformat()}
    )

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["as_of_date"] == timezone.localdate()


def test_strategy_detail_rules_count_is_an_integer() -> None:
    relation = SimpleNamespace(count=lambda: 3)
    strategy = SimpleNamespace(rules=relation)

    assert StrategyDetailSerializer().get_rules_count(strategy) == 3
