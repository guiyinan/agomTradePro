"""Boundary contracts for investment-signal serializers."""

from __future__ import annotations

from math import inf, nan

import pytest

from apps.signal.interface.serializers import (
    InvestmentSignalCreateSerializer,
    InvestmentSignalSerializer,
    InvestmentSignalUpdateSerializer,
    InvestmentSignalValidateRequestSerializer,
    SignalListQuerySerializer,
)


def _valid_create_payload() -> dict[str, object]:
    return {
        "asset_code": " 510300.sh ",
        "asset_class": "a_share_growth",
        "direction": "LONG",
        "logic_desc": "PMI 回升，看好宽基指数",
        "invalidation_logic": "PMI < 50",
        "target_regime": "Recovery",
    }


def test_create_serializer_preserves_comparison_operator_and_normalizes_code() -> None:
    serializer = InvestmentSignalCreateSerializer(data=_valid_create_payload())

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["asset_code"] == "510300.SH"
    assert serializer.validated_data["invalidation_logic"] == "PMI < 50"


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("asset_code", "../unsafe"),
        ("asset_class", "unregistered_asset_class"),
        ("direction", "BUY"),
        ("target_regime", "Unknown"),
        ("logic_desc", "tiny"),
        ("invalidation_logic", "没有量化条件"),
    ],
)
def test_create_serializer_rejects_invalid_signal_contract(
    field_name: str,
    value: object,
) -> None:
    payload = _valid_create_payload()
    payload[field_name] = value
    serializer = InvestmentSignalCreateSerializer(data=payload)

    assert not serializer.is_valid()
    assert field_name in serializer.errors


def test_write_serializers_reject_unknown_fields() -> None:
    create_payload = _valid_create_payload() | {"status": "approved"}
    create_serializer = InvestmentSignalCreateSerializer(data=create_payload)
    update_serializer = InvestmentSignalUpdateSerializer(
        data={"logic_desc": "有效的更新逻辑", "user_id": 99}
    )

    assert not create_serializer.is_valid()
    assert "non_field_errors" in create_serializer.errors
    assert not update_serializer.is_valid()
    assert "non_field_errors" in update_serializer.errors


def test_update_serializer_applies_the_same_bounded_normalization() -> None:
    serializer = InvestmentSignalUpdateSerializer(
        data={
            "asset_code": " 000001.sz ",
            "invalidation_logic": "CPI >= 3",
        }
    )

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data == {
        "asset_code": "000001.SZ",
        "invalidation_logic": "CPI >= 3",
    }


@pytest.mark.parametrize("threshold", [nan, inf, -inf])
def test_eligibility_request_rejects_non_finite_threshold(
    threshold: float,
) -> None:
    serializer = InvestmentSignalValidateRequestSerializer(
        data={"asset_code": "510300.SH", "invalidation_threshold": threshold}
    )

    assert not serializer.is_valid()
    assert "invalidation_threshold" in serializer.errors


def test_eligibility_request_requires_asset_code() -> None:
    serializer = InvestmentSignalValidateRequestSerializer(data={"signal_id": 1})

    assert not serializer.is_valid()
    assert "asset_code" in serializer.errors


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "not-a-status"},
        {"direction": "BUY"},
        {"limit": 501},
        {"search": "x" * 201},
        {"unexpected": "value"},
    ],
)
def test_list_query_rejects_invalid_or_unknown_filters(
    payload: dict[str, object],
) -> None:
    serializer = SignalListQuerySerializer(data=payload)

    assert not serializer.is_valid()


def test_read_serializer_ignores_non_string_human_description() -> None:
    serializer = InvestmentSignalSerializer()

    assert (
        serializer.get_human_readable_invalidation(
            {"human_readable_invalidation": {"unexpected": True}}
        )
        == ""
    )
