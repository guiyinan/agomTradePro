from decimal import Decimal

from apps.simulated_trading.interface.performance_serializers import (
    BenchmarkPutSerializer,
    PerformanceReportQuerySerializer,
)
from apps.simulated_trading.interface.serializers import (
    AccountBatchDeleteRequestSerializer,
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
