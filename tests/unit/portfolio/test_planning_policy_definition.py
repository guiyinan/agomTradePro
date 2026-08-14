"""Pure Domain tests for immutable Portfolio planning-policy definitions."""

from __future__ import annotations

import ast
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from apps.portfolio.domain.planning_policy_definition import (
    PLANNING_POLICY_DEFINITION_OWNER,
    PLANNING_POLICY_DEFINITION_PERMISSION,
    PLANNING_POLICY_DEFINITION_SCHEMA,
    PLANNING_POLICY_DEFINITION_TYPE,
    PlanningPolicyDefinition,
)

NOW = datetime(2026, 8, 13, 10, tzinfo=UTC)


def _definition(**changes: object) -> PlanningPolicyDefinition:
    values: dict[str, object] = {
        "policy_id": "planning-policy-1",
        "policy_version": "policy-v1",
        "buy_lot_size": 100,
        "fee_rate": Decimal("0.00030000"),
        "slippage_rate": Decimal("0.0010"),
        "min_rebalance_value": Decimal("1000.0000"),
        "max_asset_weight": Decimal("0.20000000"),
        "max_volume_participation": Decimal("0.10000000"),
        "recorded_at": NOW,
        "valid_until": NOW + timedelta(days=365),
    }
    values.update(changes)
    return PlanningPolicyDefinition(**values)  # type: ignore[arg-type]


def test_definition_is_content_addressed_definition_only_and_non_executable() -> None:
    value = _definition()

    assert value.owner == PLANNING_POLICY_DEFINITION_OWNER == "portfolio"
    assert value.artifact_type == PLANNING_POLICY_DEFINITION_TYPE
    assert value.schema == PLANNING_POLICY_DEFINITION_SCHEMA
    assert value.permission == PLANNING_POLICY_DEFINITION_PERMISSION == "definition_only"
    assert value.must_not_execute is True
    assert value.is_knowable_at(NOW)
    assert not value.is_knowable_at(value.valid_until)
    assert len(value.identity_hash) == 64
    assert len(value.content_hash) == 64

    assert value.to_payload() == {
        "owner": "portfolio",
        "artifact_type": "planning_policy_definition",
        "schema": "portfolio-planning-policy-definition.v1",
        "policy_id": "planning-policy-1",
        "policy_version": "policy-v1",
        "buy_lot_size": 100,
        "fee_rate": "0.0003",
        "slippage_rate": "0.001",
        "min_rebalance_value": "1000",
        "max_asset_weight": "0.2",
        "max_volume_participation": "0.1",
        "recorded_at": "2026-08-13T10:00:00Z",
        "valid_until": "2027-08-13T10:00:00Z",
        "permission": "definition_only",
        "identity_hash": value.identity_hash,
        "content_hash": value.content_hash,
        "must_not_execute": True,
    }


@pytest.mark.parametrize(
    "field_name",
    [
        "fee_rate",
        "slippage_rate",
        "min_rebalance_value",
        "max_asset_weight",
        "max_volume_participation",
    ],
)
@pytest.mark.parametrize(
    "bad_value",
    [0, 0.0, True, Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity"), Decimal("-0")],
)
def test_decimal_fields_require_exact_finite_non_negative_non_negative_zero(
    field_name: str, bad_value: object
) -> None:
    with pytest.raises((TypeError, ValueError), match=field_name):
        _definition(**{field_name: bad_value})


@pytest.mark.parametrize("field_name", ["fee_rate", "slippage_rate", "min_rebalance_value"])
def test_fee_slippage_and_minimum_accept_exact_zero(field_name: str) -> None:
    value = _definition(**{field_name: Decimal("0")})
    assert getattr(value, field_name) == Decimal("0")


@pytest.mark.parametrize("field_name", ["max_asset_weight", "max_volume_participation"])
@pytest.mark.parametrize("bad_value", [Decimal("0"), Decimal("1.0001"), Decimal("2")])
def test_weight_and_participation_require_open_zero_closed_one(
    field_name: str, bad_value: Decimal
) -> None:
    with pytest.raises(ValueError, match=field_name):
        _definition(**{field_name: bad_value})


@pytest.mark.parametrize("field_name", ["max_asset_weight", "max_volume_participation"])
def test_weight_and_participation_accept_exact_one(field_name: str) -> None:
    assert getattr(_definition(**{field_name: Decimal("1")}), field_name) == Decimal("1")


@pytest.mark.parametrize("bad_value", [0, -1, True, 100.0, Decimal("100")])
def test_buy_lot_size_requires_exact_positive_int(bad_value: object) -> None:
    with pytest.raises((TypeError, ValueError), match="buy_lot_size"):
        _definition(buy_lot_size=bad_value)


@pytest.mark.parametrize(
    "changes",
    [
        {"policy_id": ""},
        {"policy_id": " planning-policy-1"},
        {"policy_version": "policy v1"},
        {"recorded_at": datetime(2026, 8, 13, 10)},
        {"valid_until": datetime(2026, 8, 14, 10)},
        {"valid_until": NOW},
        {"owner": "account"},
        {"artifact_type": "planning_policy_activation"},
        {"schema": "v2"},
        {"permission": "active"},
    ],
)
def test_definition_rejects_noncanonical_identity_clock_or_authority(
    changes: dict[str, object]
) -> None:
    with pytest.raises(ValueError):
        _definition(**changes)


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    [
        ("buy_lot_size", 200),
        ("fee_rate", Decimal("0.0004")),
        ("slippage_rate", Decimal("0.002")),
        ("min_rebalance_value", Decimal("2000")),
        ("max_asset_weight", Decimal("0.3")),
        ("max_volume_participation", Decimal("0.2")),
        ("recorded_at", NOW + timedelta(seconds=1)),
        ("valid_until", NOW + timedelta(days=366)),
    ],
)
def test_every_definition_value_participates_in_content_hash(
    field_name: str, replacement: object
) -> None:
    original = _definition()
    changed = replace(original, **{field_name: replacement, "content_hash": ""})

    assert changed.identity_hash == original.identity_hash
    assert changed.content_hash != original.content_hash


def test_policy_identity_changes_identity_and_content_hash() -> None:
    original = _definition()
    changed = _definition(policy_version="policy-v2")

    assert changed.identity_hash != original.identity_hash
    assert changed.content_hash != original.content_hash


def test_equivalent_decimal_representations_have_one_plain_canonical_hash() -> None:
    first = _definition(fee_rate=Decimal("0.1000"))
    second = _definition(fee_rate=Decimal("1E-1"))

    assert first.content_hash == second.content_hash
    assert first.to_payload()["fee_rate"] == "0.1"


def test_identity_and_content_hash_tampering_is_rejected() -> None:
    value = _definition()
    with pytest.raises(ValueError, match="identity_hash"):
        replace(value, identity_hash="0" * 64)
    with pytest.raises(ValueError, match="content_hash"):
        replace(value, content_hash="0" * 64)


def test_contract_contains_no_status_current_or_activation_state() -> None:
    names = {item.name for item in fields(PlanningPolicyDefinition)}
    assert "status" not in names
    assert "current" not in names
    assert "activation" not in names
    assert "activation_state" not in names
    assert not hasattr(_definition(), "activation_available")


def test_domain_module_has_only_stdlib_imports_and_no_framework_clock() -> None:
    path = Path("apps/portfolio/domain/planning_policy_definition.py")
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    roots = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }

    assert roots <= {"__future__", "dataclasses", "datetime", "decimal", "hashlib", "json"}
    assert "datetime.now" not in source
    assert "django" not in source
    assert "from apps." not in source
