"""Type-sensitive API field contracts for Equity serializers."""

from datetime import date

import pytest

from apps.equity.interface.serializers import (
    FinancialDataSerializer,
    IntradayChartResponseSerializer,
    SyncFinancialDataRequestSerializer,
    SyncFinancialDataResponseSerializer,
    SyncValuationDataResponseSerializer,
)


@pytest.mark.parametrize(
    ("serializer_class", "payload", "field_name", "expected"),
    [
        (FinancialDataSerializer, {"source": "akshare"}, "source", "akshare"),
        (
            IntradayChartResponseSerializer,
            {
                "success": True,
                "stock_code": "000001.SZ",
                "stock_name": "平安银行",
                "source": "cache",
            },
            "source",
            "cache",
        ),
        (
            SyncValuationDataResponseSerializer,
            {
                "requested_count": 2,
                "synced_count": 1,
                "fallback_used_count": 0,
                "skipped_count": 0,
                "error_count": 1,
                "start_date": date(2026, 7, 1),
                "end_date": date(2026, 7, 2),
                "errors": ["timeout"],
            },
            "errors",
            ["timeout"],
        ),
        (
            SyncFinancialDataResponseSerializer,
            {"success": False, "errors": ["denied"]},
            "errors",
            ["denied"],
        ),
    ],
)
def test_reserved_serializer_field_names_remain_in_response_contract(
    serializer_class: type,
    payload: dict[str, object],
    field_name: str,
    expected: object,
) -> None:
    """Fields colliding with DRF properties must keep their public JSON names."""

    assert serializer_class(payload).data[field_name] == expected


def test_sync_financial_source_field_accepts_value_and_default() -> None:
    """The dynamically registered source field preserves validation semantics."""

    explicit = SyncFinancialDataRequestSerializer(data={"source": "tushare"})
    defaulted = SyncFinancialDataRequestSerializer(data={})

    assert explicit.is_valid(), explicit.errors
    assert defaulted.is_valid(), defaulted.errors
    assert explicit.validated_data["source"] == "tushare"
    assert defaulted.validated_data["source"] == "akshare"
