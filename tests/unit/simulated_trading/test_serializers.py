from decimal import Decimal

import pytest

from apps.simulated_trading.interface.performance_serializers import (
    BenchmarkPutSerializer,
    PerformanceReportQuerySerializer,
)
from apps.simulated_trading.interface.serializers import (
    AccountBatchDeleteRequestSerializer,
    AccountCreationKeySerializer,
    CreateAccountRequestSerializer,
)


def test_create_account_request_preserves_decimal_contract() -> None:
    serializer = CreateAccountRequestSerializer(
        data={
            "account_name": "typed-simulated-account",
            "initial_capital": "100000.00",
        }
    )

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["initial_capital"] == Decimal("100000.00")
    assert serializer.validated_data["account_type"] == "simulated"


def test_account_batch_delete_requires_nonempty_positive_ids() -> None:
    serializer = AccountBatchDeleteRequestSerializer(data={"account_ids": [1, 0]})

    assert not serializer.is_valid()
    assert "account_ids" in serializer.errors


@pytest.mark.parametrize(
    ("amount", "valid"),
    [("9999999999999.99", True), ("10000000000000.00", False)],
)
def test_creation_amount_matches_database_precision(amount: str, valid: bool) -> None:
    serializer = CreateAccountRequestSerializer(
        data={"account_name": "storage-boundary", "initial_capital": amount}
    )
    assert serializer.is_valid() is valid
    if not valid:
        assert "initial_capital" in serializer.errors


@pytest.mark.parametrize("fee_config_id", [0, 1, -1])
def test_creation_rejects_unimplemented_fee_configuration(fee_config_id: int) -> None:
    serializer = CreateAccountRequestSerializer(
        data={
            "account_name": "explicit-fee-input",
            "initial_capital": "100000.00",
            "fee_config_id": fee_config_id,
        }
    )
    assert not serializer.is_valid()
    assert "fee_config_id" in serializer.errors


def test_creation_accepts_explicit_null_fee_configuration() -> None:
    serializer = CreateAccountRequestSerializer(
        data={
            "account_name": "no-fee-configuration",
            "initial_capital": "100000.00",
            "fee_config_id": None,
        }
    )
    assert serializer.is_valid(), serializer.errors


@pytest.mark.parametrize("field", ["actor_id", "user_id", "mode", "auto_trading_enabled"])
def test_creation_rejects_client_identity_and_unknown_fields(field: str) -> None:
    serializer = CreateAccountRequestSerializer(
        data={"account_name": "owned", "initial_capital": "100000.00", field: "forged"}
    )
    assert not serializer.is_valid()


@pytest.mark.parametrize("key", ["", " ", "key value", "key\n", "a" * 193])
def test_creation_key_rejects_missing_whitespace_or_unbounded_values(key: str) -> None:
    serializer = AccountCreationKeySerializer(data={"request_key": key})
    assert not serializer.is_valid()


def test_creation_adapter_uses_resolved_serializer_defaults() -> None:
    serializer = CreateAccountRequestSerializer(
        data={"account_name": "  owned  ", "initial_capital": "100000.00"}
    )
    assert serializer.is_valid(), serializer.errors
    parameters = serializer.to_creation_input(request_key="key-1")
    assert parameters.account_name == "owned"
    assert parameters.request_key == "key-1"
    assert parameters.max_position_pct == 20.0
    assert parameters.stop_loss_pct is None
    assert parameters.commission_rate == 0.0003
    assert parameters.slippage_rate == 0.001


def test_performance_report_query_rejects_inverted_date_range() -> None:
    serializer = PerformanceReportQuerySerializer(
        data={"start_date": "2026-07-23", "end_date": "2026-07-01"}
    )

    assert not serializer.is_valid()
    assert "end_date 必须晚于 start_date" in str(serializer.errors)


def test_benchmark_put_requires_at_least_one_component() -> None:
    serializer = BenchmarkPutSerializer(data={"components": []})

    assert not serializer.is_valid()
    assert "至少需要配置 1 个基准成分" in str(serializer.errors)
