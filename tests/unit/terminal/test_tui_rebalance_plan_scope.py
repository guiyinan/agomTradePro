"""Strict task scope contracts for plan pins, target intent and authority fields."""

from __future__ import annotations

import pytest

from apps.terminal.application.tui_task_scope_contracts import (
    TuiTaskScopeError,
    validate_task_action_scope,
)

_HASH = "a" * 64


def test_plan_read_scope_keeps_only_owner_account_and_exact_revision_pins() -> None:
    scope = validate_task_action_scope(
        "rebalance-plan.read",
        {
            "account_id": "9",
            "plan_id": "plan-17",
            "plan_version": "2",
            "revision_hash": _HASH,
        },
    )

    assert scope is not None
    assert scope.to_params() == {
        "account_id": 9,
        "plan_id": "plan-17",
        "plan_version": 2,
        "revision_hash": _HASH,
    }


@pytest.mark.parametrize(
    ("action", "params"),
    [
        (
            "rebalance-plan.read",
            {"account_id": 9, "plan_id": "plan-17", "plan_version": 2},
        ),
        (
            "rebalance-plan.read",
            {
                "account_id": 9,
                "plan_id": "plan-17",
                "plan_version": 2,
                "revision_hash": _HASH,
                "user_id": 1,
            },
        ),
        (
            "rebalance-plan.read",
            {
                "account_id": 9,
                "plan_id": "plan-17",
                "plan_version": True,
                "revision_hash": _HASH,
            },
        ),
        (
            "rebalance-plan.read",
            {
                "account_id": 9,
                "plan_id": "plan-17",
                "plan_version": 2,
                "revision_hash": "A" * 64,
            },
        ),
        (
            "rebalance-plan.review",
            {
                "account_id": 9,
                "plan_id": "plan-17",
                "plan_version": 2,
                "revision_hash": _HASH,
                "confirmed": False,
            },
        ),
    ],
)
def test_plan_scope_rejects_missing_or_unauthorized_values(
    action: str, params: dict[str, object]
) -> None:
    with pytest.raises(TuiTaskScopeError):
        validate_task_action_scope(action, params)


def test_create_scope_allows_only_targets_and_explicit_reference_basis() -> None:
    scope = validate_task_action_scope(
        "rebalance-plan.create",
        {
            "account_id": "9",
            "target_weights": "600000.SH,60\n000001.SZ,30",
            "reference_price_basis": "published_close",
        },
    )

    assert scope is not None
    assert scope.to_params() == {
        "account_id": 9,
        "target_weights": "600000.SH,60\n000001.SZ,30",
        "reference_price_basis": "published_close",
    }


def test_order_grid_scope_requires_exact_revision_without_order_or_actor_override() -> None:
    scope = validate_task_action_scope(
        "rebalance-plan.orders",
        {
            "account_id": "9",
            "plan_id": "plan-17",
            "plan_version": "2",
            "revision_hash": _HASH,
        },
    )

    assert scope is not None
    assert scope.to_params() == {
        "account_id": 9,
        "plan_id": "plan-17",
        "plan_version": 2,
        "revision_hash": _HASH,
    }


def test_order_preview_scope_preserves_exact_decimal_text_and_only_user_intent() -> None:
    scope = validate_task_action_scope(
        "rebalance-plan.preview-order",
        {
            "account_id": "9",
            "plan_id": "plan-17",
            "plan_version": "2",
            "revision_hash": _HASH,
            "order_ordinal": "0",
            "order_content_hash": "b" * 64,
            "plan_order_binding_id": "c" * 64,
            "quantity": "100",
            "limit_price": "13.400000",
            "reason": "用户选择分笔模拟",
        },
    )

    assert scope is not None
    assert scope.to_params() == {
        "account_id": 9,
        "plan_id": "plan-17",
        "plan_version": 2,
        "revision_hash": _HASH,
        "order_ordinal": 0,
        "order_content_hash": "b" * 64,
        "plan_order_binding_id": "c" * 64,
        "quantity": "100",
        "limit_price": "13.400000",
        "reason": "用户选择分笔模拟",
    }


@pytest.mark.parametrize(
    "extra",
    [
        "asset_code",
        "security_id",
        "side",
        "fee_budget",
        "cash",
        "positions",
        "user_id",
        "request_key",
    ],
)
def test_plan_order_preview_scope_rejects_facts_and_identity_overrides(extra: str) -> None:
    params: dict[str, object] = {
        "account_id": 9,
        "plan_id": "plan-17",
        "plan_version": 2,
        "revision_hash": _HASH,
        "order_ordinal": 0,
        "order_content_hash": "b" * 64,
        "plan_order_binding_id": "c" * 64,
        "quantity": "100",
        "limit_price": "13.40",
        extra: "forbidden",
    }
    with pytest.raises(TuiTaskScopeError):
        validate_task_action_scope("rebalance-plan.preview-order", params)


@pytest.mark.parametrize(
    ("quantity", "limit_price"),
    [(100.0, "13.4"), ("100.5", "13.4"), ("0", "13.4"), ("100", "0"), ("100", "nan")],
)
def test_plan_order_preview_scope_rejects_inexact_or_nonpositive_number_text(
    quantity: object, limit_price: object
) -> None:
    with pytest.raises(TuiTaskScopeError):
        validate_task_action_scope(
            "rebalance-plan.preview-order",
            {
                "account_id": 9,
                "plan_id": "plan-17",
                "plan_version": 2,
                "revision_hash": _HASH,
                "order_ordinal": 0,
                "order_content_hash": "b" * 64,
                "plan_order_binding_id": "c" * 64,
                "quantity": quantity,
                "limit_price": limit_price,
            },
        )


@pytest.mark.parametrize("extra", ["cash", "positions", "fees", "risk", "user_id", "request_key"])
def test_create_scope_rejects_client_facts_and_idempotency_override(extra: str) -> None:
    values: dict[str, object] = {
        "account_id": 9,
        "target_weights": "600000.SH,50",
        "reference_price_basis": "market",
        extra: "forbidden",
    }
    with pytest.raises(TuiTaskScopeError):
        validate_task_action_scope("rebalance-plan.create", values)
