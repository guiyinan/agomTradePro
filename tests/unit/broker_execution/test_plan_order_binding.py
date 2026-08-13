"""Pure Domain coverage for the inactive Broker plan-to-order binding seal."""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.broker_execution.domain.plan_order_binding import (
    BROKER_ORDER_ARTIFACT_SOURCE_OWNER,
    BROKER_ORDER_ARTIFACT_SOURCE_TYPE,
    BROKER_PLAN_ORDER_BINDING_BLOCKERS,
    BROKER_PLAN_ORDER_BINDING_OWNER,
    BROKER_PLAN_ORDER_BINDING_PERMISSION,
    BROKER_PLAN_ORDER_BINDING_SCHEMA,
    BROKER_PLAN_ORDER_BINDING_TYPE,
    PORTFOLIO_PLAN_SOURCE_ARTIFACT_TYPE,
    PORTFOLIO_PLAN_SOURCE_OWNER,
    PORTFOLIO_RECEIPT_SOURCE_CAPABILITY,
    PORTFOLIO_RECEIPT_SOURCE_OWNER,
    BrokerPlanOrderBinding,
    canonical_plan_order_payload_hash_v1,
    validate_plan_order_binding_successor,
)

NOW = datetime(2026, 8, 13, 6, tzinfo=UTC)
ORDER_ID = "56f9ae53-7606-46de-bf88-a6543f822d4a"


def _order_payload(**changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "asset_code": "600000.SH",
        "side": "buy",
        "quantity": 100,
        "reference_price": "10.2500",
        "estimated_fee": "5.00",
        "status": "draft",
        "remaining_quantity": 100,
        "constraints": [
            {
                "rule_code": "max-position",
                "asset_code": "600000.SH",
                "allowed": True,
                "original_quantity": 100,
                "allowed_quantity": 100,
                "reason": "within limit",
            }
        ],
    }
    values.update(changes)
    return values


def _canonical_json(payload: dict[str, object] | None = None) -> str:
    return json.dumps(
        payload or _order_payload(),
        sort_keys=True,
        separators=(",", ":"),
    )


def _binding(**changes: object) -> BrokerPlanOrderBinding:
    payload_json = changes.pop("plan_order_payload_json", _canonical_json())
    assert isinstance(payload_json, str)
    values: dict[str, object] = {
        "binding_id": "plan-order-binding-1",
        "binding_version": BROKER_PLAN_ORDER_BINDING_SCHEMA,
        "portfolio_plan_id": "transition-plan-1",
        "portfolio_plan_version": 2,
        "portfolio_plan_content_hash": "a" * 64,
        "portfolio_account_id": "portfolio-account-7",
        "portfolio_receipt_id": "portfolio-receipt-1",
        "portfolio_receipt_version": "portfolio-receipt.v1",
        "portfolio_receipt_content_hash": "b" * 64,
        "portfolio_subject_id": "portfolio-subject-1",
        "portfolio_subject_version": "portfolio-subject.v1",
        "portfolio_subject_content_hash": "c" * 64,
        "plan_order_ordinal": 0,
        "plan_order_payload_json": payload_json,
        "plan_order_content_hash": canonical_plan_order_payload_hash_v1(payload_json),
        "broker_account_id": 7,
        "order_artifact_id": ORDER_ID,
        "order_artifact_version": "broker-live-order-approval-artifact.v1.3",
        "order_artifact_identity_hash": "d" * 64,
        "order_artifact_content_hash": "e" * 64,
        "order_approval_digest": "f" * 64,
        "order_version": 3,
        "portfolio_plan_valid_until": NOW + timedelta(hours=3),
        "portfolio_receipt_valid_until": NOW + timedelta(hours=2),
        "order_artifact_valid_until": NOW + timedelta(hours=1),
        "recorded_at": NOW,
        "valid_until": NOW + timedelta(hours=1),
    }
    values.update(changes)
    return BrokerPlanOrderBinding(**values)  # type: ignore[arg-type]


def test_binding_seals_exact_sources_and_never_activates_execution() -> None:
    binding = _binding()

    assert binding.owner == BROKER_PLAN_ORDER_BINDING_OWNER
    assert binding.artifact_type == BROKER_PLAN_ORDER_BINDING_TYPE
    assert binding.schema == BROKER_PLAN_ORDER_BINDING_SCHEMA
    assert binding.permission == BROKER_PLAN_ORDER_BINDING_PERMISSION
    assert binding.blocker_codes == BROKER_PLAN_ORDER_BINDING_BLOCKERS
    assert binding.portfolio_plan_owner == PORTFOLIO_PLAN_SOURCE_OWNER
    assert binding.portfolio_plan_artifact_type == PORTFOLIO_PLAN_SOURCE_ARTIFACT_TYPE
    assert binding.portfolio_receipt_owner == PORTFOLIO_RECEIPT_SOURCE_OWNER
    assert binding.portfolio_receipt_capability == PORTFOLIO_RECEIPT_SOURCE_CAPABILITY
    assert binding.order_artifact_owner == BROKER_ORDER_ARTIFACT_SOURCE_OWNER
    assert binding.order_artifact_type == BROKER_ORDER_ARTIFACT_SOURCE_TYPE
    assert len(binding.identity_hash) == 64
    assert len(binding.content_hash) == 64
    assert binding.activation_available is False
    assert binding.must_not_execute is True
    assert binding.is_knowable_at(NOW)
    assert not binding.is_knowable_at(binding.valid_until)
    assert binding.to_payload()["must_not_execute"] is True


def test_order_payload_hash_is_byte_compatible_with_canonical_v1_row() -> None:
    payload = _order_payload(
        constraints=[
            {
                "rule_code": "lot-size",
                "asset_code": "600000.SH",
                "allowed": True,
                "original_quantity": 100,
                "allowed_quantity": 100,
                "reason": "手数正常",
            }
        ]
    )
    payload_json = _canonical_json(payload)

    assert "手数正常" not in payload_json
    assert "\\u624b\\u6570\\u6b63\\u5e38" in payload_json
    assert (
        canonical_plan_order_payload_hash_v1(payload_json)
        == hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    )
    assert _binding(plan_order_payload_json=payload_json).plan_order_payload == payload


@pytest.mark.parametrize(
    "payload_json",
    [
        json.dumps(_order_payload(), sort_keys=False),
        '{"asset_code":"600000.SH","asset_code":"000001.SZ"}',
        _canonical_json(_order_payload(extra="forbidden")),
        _canonical_json(_order_payload(side="BUY")),
        _canonical_json(_order_payload(quantity=True)),
        _canonical_json(_order_payload(reference_price="NaN")),
        _canonical_json(_order_payload(estimated_fee="-1")),
        _canonical_json(_order_payload(constraints="not-a-list")),
    ],
)
def test_order_payload_rejects_noncanonical_or_non_v1_rows(payload_json: str) -> None:
    with pytest.raises((TypeError, ValueError)):
        canonical_plan_order_payload_hash_v1(payload_json)


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    [
        ("portfolio_plan_content_hash", "0" * 64),
        ("portfolio_account_id", "portfolio-account-8"),
        ("portfolio_receipt_content_hash", "1" * 64),
        ("portfolio_subject_content_hash", "2" * 64),
        ("plan_order_ordinal", 1),
        ("broker_account_id", 8),
        ("order_artifact_identity_hash", "3" * 64),
        ("order_artifact_content_hash", "4" * 64),
        ("order_approval_digest", "5" * 64),
        ("portfolio_plan_valid_until", NOW + timedelta(hours=4)),
        ("portfolio_receipt_valid_until", NOW + timedelta(hours=4)),
        ("supersedes_binding_hash", "6" * 64),
    ],
)
def test_every_material_source_seal_participates_in_content_hash(
    field_name: str, replacement: object
) -> None:
    original = _binding()
    changed = replace(original, **{field_name: replacement, "content_hash": ""})

    assert changed.content_hash != original.content_hash


def test_payload_drift_requires_exact_new_row_hash() -> None:
    original = _binding()
    changed_json = _canonical_json(_order_payload(quantity=200, remaining_quantity=200))

    with pytest.raises(ValueError, match="plan_order_content_hash"):
        replace(original, plan_order_payload_json=changed_json, content_hash="")

    changed = replace(
        original,
        plan_order_payload_json=changed_json,
        plan_order_content_hash=canonical_plan_order_payload_hash_v1(changed_json),
        content_hash="",
    )
    assert changed.plan_order_content_hash != original.plan_order_content_hash
    assert changed.content_hash != original.content_hash


@pytest.mark.parametrize(
    "changes",
    [
        {"portfolio_plan_version": True},
        {"portfolio_plan_version": 0},
        {"plan_order_ordinal": True},
        {"plan_order_ordinal": -1},
        {"broker_account_id": True},
        {"broker_account_id": 0},
        {"order_version": True},
        {"order_artifact_id": ORDER_ID.upper()},
        {"order_artifact_version": "broker-live-order-approval-artifact.v1.2"},
        {"portfolio_plan_content_hash": "A" * 64},
        {"recorded_at": datetime(2026, 8, 13, 6)},
        {"valid_until": NOW},
        {"portfolio_plan_valid_until": datetime(2026, 8, 13, 9)},
        {"portfolio_receipt_valid_until": NOW + timedelta(minutes=30)},
        {"order_artifact_valid_until": NOW + timedelta(minutes=30)},
        {"valid_until": NOW + timedelta(hours=2)},
        {"binding_version": "v2"},
        {"owner": "portfolio"},
        {"permission": "execution_eligible"},
        {"blocker_codes": ("different",)},
        {"portfolio_plan_owner": "broker_execution"},
        {"portfolio_plan_artifact_type": "approximate_plan"},
        {"portfolio_receipt_owner": "broker_execution"},
        {"portfolio_receipt_capability": "caller_claim"},
        {"order_artifact_owner": "portfolio"},
        {"order_artifact_type": "order_guess"},
    ],
)
def test_binding_rejects_noncanonical_or_permission_upgrading_values(
    changes: dict[str, object]
) -> None:
    with pytest.raises(ValueError):
        _binding(**changes)


def test_separate_account_namespaces_are_preserved_without_coercion() -> None:
    binding = _binding(portfolio_account_id="007", broker_account_id=7)

    assert binding.portfolio_account_id == "007"
    assert binding.broker_account_id == 7
    assert binding.to_payload()["portfolio_account_id"] == "007"
    assert binding.to_payload()["broker_account_id"] == 7


def test_successor_binds_exact_previous_and_same_logical_plan_order() -> None:
    previous = _binding()
    successor = _binding(
        binding_id="plan-order-binding-2",
        recorded_at=NOW + timedelta(minutes=1),
        supersedes_binding_hash=previous.content_hash,
    )

    validate_plan_order_binding_successor(previous, successor)


@pytest.mark.parametrize(
    "changes",
    [
        {"supersedes_binding_hash": "0" * 64},
        {"portfolio_plan_id": "transition-plan-2"},
        {"portfolio_plan_version": 3},
        {"plan_order_ordinal": 1},
        {"broker_account_id": 8},
        {"order_artifact_id": "75df9306-cb1d-47de-8588-3bfce22a7930"},
        {"recorded_at": NOW},
    ],
)
def test_successor_rejects_chain_substitution(changes: dict[str, object]) -> None:
    previous = _binding()
    values: dict[str, object] = {
        "binding_id": "plan-order-binding-2",
        "recorded_at": NOW + timedelta(minutes=1),
        "supersedes_binding_hash": previous.content_hash,
    }
    values.update(changes)
    successor = _binding(**values)

    with pytest.raises(ValueError):
        validate_plan_order_binding_successor(previous, successor)


def test_domain_contract_has_no_cross_app_imports() -> None:
    path = Path("apps/broker_execution/domain/plan_order_binding.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}

    assert not any(name.startswith("apps.") for name in imported)
