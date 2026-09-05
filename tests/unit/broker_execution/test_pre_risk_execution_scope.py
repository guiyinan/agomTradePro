"""Pure Domain coverage for permanently inactive pre-Risk scopes."""

from __future__ import annotations

import ast
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.broker_execution.domain.pre_risk_execution_scope import (
    BROKER_PRE_RISK_SCOPE_BLOCKERS,
    BROKER_PRE_RISK_SCOPE_OWNER,
    BROKER_PRE_RISK_SCOPE_PERMISSION,
    BROKER_PRE_RISK_SCOPE_VERSION,
    BrokerPreRiskExecutionScope,
    validate_pre_risk_scope_successor,
)

NOW = datetime(2026, 8, 13, 4, tzinfo=UTC)
ORDER_ID = "56f9ae53-7606-46de-bf88-a6543f822d4a"


def _scope(**changes: object) -> BrokerPreRiskExecutionScope:
    values: dict[str, object] = {
        "scope_id": "pre-risk-scope-1",
        "broker_account_id": 7,
        "portfolio_account_id": "portfolio-account-7",
        "plan_id": "transition-plan-1",
        "plan_version": 2,
        "plan_content_hash": "a" * 64,
        "plan_valid_until": NOW + timedelta(hours=5),
        "portfolio_receipt_id": "portfolio-receipt-1",
        "portfolio_receipt_version": "portfolio-receipt.v1",
        "portfolio_receipt_content_hash": "b" * 64,
        "portfolio_subject_id": "portfolio-subject-1",
        "portfolio_subject_version": "portfolio-subject.v1",
        "portfolio_subject_content_hash": "c" * 64,
        "portfolio_receipt_valid_until": NOW + timedelta(hours=4),
        "order_artifact_id": ORDER_ID,
        "order_artifact_version": "broker-order-artifact.v1.3",
        "order_artifact_content_hash": "d" * 64,
        "order_artifact_identity_hash": "e" * 64,
        "order_version": 3,
        "order_approval_digest": "f" * 64,
        "order_valid_until": NOW + timedelta(hours=3),
        "order_risk_policy_version": "risk-policy-v4",
        "recorded_at": NOW,
        "valid_until": NOW + timedelta(hours=3),
    }
    values.update(changes)
    return BrokerPreRiskExecutionScope(**values)  # type: ignore[arg-type]


def test_scope_seals_three_exact_sources_but_remains_inactive() -> None:
    scope = _scope()

    assert scope.owner == BROKER_PRE_RISK_SCOPE_OWNER
    assert scope.scope_version == BROKER_PRE_RISK_SCOPE_VERSION
    assert scope.permission == BROKER_PRE_RISK_SCOPE_PERMISSION
    assert scope.blocker_codes == BROKER_PRE_RISK_SCOPE_BLOCKERS
    assert scope.valid_until == scope.order_valid_until
    assert len(scope.content_hash) == 64
    assert scope.activation_available is False
    assert scope.must_not_execute is True
    assert scope.is_knowable_at(NOW)
    assert not scope.is_knowable_at(scope.valid_until)
    assert scope.to_payload()["activation_available"] is False
    assert scope.to_payload()["must_not_execute"] is True


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    [
        ("portfolio_account_id", "portfolio-account-8"),
        ("plan_content_hash", "0" * 64),
        ("portfolio_subject_content_hash", "1" * 64),
        ("order_artifact_identity_hash", "2" * 64),
        ("order_risk_policy_version", "risk-policy-v5"),
        ("supersedes_scope_hash", "3" * 64),
    ],
)
def test_every_material_binding_participates_in_canonical_hash(
    field_name: str, replacement: object
) -> None:
    original = _scope()
    changed = replace(
        original,
        **{field_name: replacement, "content_hash": ""},
    )

    assert changed.content_hash != original.content_hash


@pytest.mark.parametrize(
    "changes",
    [
        {"broker_account_id": True},
        {"broker_account_id": 0},
        {"plan_version": True},
        {"order_version": 0},
        {"order_artifact_id": ORDER_ID.upper()},
        {"plan_content_hash": "A" * 64},
        {"recorded_at": datetime(2026, 8, 13, 4)},
        {"valid_until": NOW + timedelta(hours=4)},
        {"owner": "risk_center"},
        {"scope_version": "broker-pre-risk-execution-scope.v2"},
        {"permission": "active"},
        {"blocker_codes": ("different",)},
        {"scope_id": "noncanonical scope"},
    ],
)
def test_scope_rejects_noncanonical_or_authority_upgrading_values(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        _scope(**changes)


def test_successor_binds_same_account_order_and_exact_previous_hash() -> None:
    previous = _scope()
    successor = _scope(
        scope_id="pre-risk-scope-2",
        recorded_at=NOW + timedelta(minutes=1),
        supersedes_scope_hash=previous.content_hash,
    )

    validate_pre_risk_scope_successor(previous, successor)


@pytest.mark.parametrize(
    "changes",
    [
        {"supersedes_scope_hash": "0" * 64},
        {"broker_account_id": 8},
        {"order_artifact_id": "75df9306-cb1d-47de-8588-3bfce22a7930"},
        {"recorded_at": NOW},
    ],
)
def test_successor_rejects_chain_substitution(changes: dict[str, object]) -> None:
    previous = _scope()
    successor_values: dict[str, object] = {
        "scope_id": "pre-risk-scope-2",
        "recorded_at": NOW + timedelta(minutes=1),
        "supersedes_scope_hash": previous.content_hash,
    }
    successor_values.update(changes)
    successor = _scope(**successor_values)

    with pytest.raises(ValueError):
        validate_pre_risk_scope_successor(previous, successor)


def test_domain_has_no_cross_app_dependency() -> None:
    path = Path("apps/broker_execution/domain/pre_risk_execution_scope.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}

    assert not any(name.startswith("apps.") for name in imported)
