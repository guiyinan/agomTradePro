from types import SimpleNamespace

from django.utils import timezone

from apps.strategy.interface.serializers import (
    ExecutionEvaluateInputSerializer,
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


def test_execution_evaluate_rejects_nonfinite_and_nonpositive_financial_inputs() -> None:
    nonfinite_serializer = ExecutionEvaluateInputSerializer(
        data={
            "symbol": "000001.SZ",
            "side": "buy",
            "current_price": float("nan"),
        }
    )
    nonpositive_serializer = ExecutionEvaluateInputSerializer(
        data={
            "symbol": "000001.SZ",
            "side": "buy",
            "account_equity": 0,
            "current_position_value": -1,
        }
    )

    assert not nonfinite_serializer.is_valid()
    assert "current_price" in nonfinite_serializer.errors
    assert not nonpositive_serializer.is_valid()
    assert {"account_equity", "current_position_value"} <= set(nonpositive_serializer.errors)


def test_execution_evaluate_requires_all_current_fact_provenance() -> None:
    serializer = ExecutionEvaluateInputSerializer(data={"symbol": "000001.SZ", "side": "buy"})

    assert not serializer.is_valid()
    assert {
        "current_price",
        "signal_strength",
        "signal_direction",
        "signal_confidence",
        "current_regime",
        "regime_confidence",
        "market_observed_at",
        "signal_observed_at",
        "regime_observed_at",
        "account_observed_at",
        "account_equity",
        "current_position_value",
        "daily_pnl_pct",
        "daily_trade_count",
    } <= set(serializer.errors)


def test_strategy_detail_rules_count_is_an_integer() -> None:
    relation = SimpleNamespace(count=lambda: 3)
    strategy = SimpleNamespace(rules=relation)

    assert StrategyDetailSerializer().get_rules_count(strategy) == 3
