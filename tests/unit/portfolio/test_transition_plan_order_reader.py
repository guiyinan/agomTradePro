"""Pure tests for the Portfolio-owned exact transition-plan order reader."""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from apps.portfolio.application.transition_plan_inactive_approval import (
    TransitionPlanDefinition,
)
from apps.portfolio.application.transition_plan_order_reader import (
    ExactActiveTransitionPlanOrderDefinition,
    GetExactActiveTransitionPlanOrder,
    GetExactActiveTransitionPlanOrderQuery,
    TransitionPlanOrderReaderCorruption,
    TransitionPlanOrderReaderUnavailable,
)
from apps.portfolio.domain.entities import ConstraintDecision, OrderDraft, TransitionPlan
from apps.portfolio.domain.transition_plan_integrity import (
    canonical_transition_plan_payload_v1,
    transition_plan_content_hash_v1,
)

PLAN_AT = datetime(2026, 8, 13, 8, tzinfo=UTC)
RECORDED_AT = PLAN_AT + timedelta(minutes=1)
EXPIRES_AT = PLAN_AT + timedelta(hours=1)


def _plan(*, status: str = "APPROVED", version: int = 1) -> TransitionPlan:
    constraint = ConstraintDecision("cash", "中证·测试", True, 100, 80, "金额上限")
    return TransitionPlan(
        plan_id="plan-1",
        idempotency_key="idem-1",
        account_id="account:7",
        decision_snapshot_id="decision-1",
        portfolio_snapshot_id="portfolio-1",
        target_portfolio_id="target-1",
        as_of_time=PLAN_AT,
        expires_at=EXPIRES_AT,
        orders=(
            OrderDraft(
                asset_code="中证·测试",
                side="buy",
                quantity=80,
                reference_price=Decimal("10.00"),
                estimated_fee=Decimal("2.50"),
                status="partial",
                remaining_quantity=20,
                constraints=(constraint,),
            ),
        ),
        constraints=(constraint,),
        cash_before=Decimal("1000.00"),
        cash_after=Decimal("197.50"),
        status=status,
        version=version,
        metadata={"planning_policy_version": "policy-v1"},
    )


def _definition(plan: TransitionPlan | None = None) -> TransitionPlanDefinition:
    value = plan or _plan()
    return TransitionPlanDefinition(
        plan=value,
        content_hash=transition_plan_content_hash_v1(value),
        recorded_at=RECORDED_AT,
    )


class PlanProvider:
    def __init__(self, value: object) -> None:
        self.value = value
        self.calls: list[tuple[str, int, datetime]] = []

    def get_exact(
        self, *, plan_id: str, plan_version: int, as_of: datetime
    ) -> TransitionPlanDefinition | None:
        self.calls.append((plan_id, plan_version, as_of))
        return self.value  # type: ignore[return-value]


def _query(
    *, ordinal: int = 0, as_of: datetime = RECORDED_AT
) -> GetExactActiveTransitionPlanOrderQuery:
    return GetExactActiveTransitionPlanOrderQuery(
        plan_id="plan-1", plan_version=1, order_ordinal=ordinal, as_of=as_of
    )


def test_reader_projects_owner_canonical_unicode_and_decimal_row_at_same_cutoff() -> None:
    definition = _definition()
    provider = PlanProvider(definition)

    result = GetExactActiveTransitionPlanOrder(provider).execute(_query())

    expected_row = canonical_transition_plan_payload_v1(definition.plan)["orders"][0]
    expected_json = json.dumps(expected_row, sort_keys=True, separators=(",", ":"))
    assert result == ExactActiveTransitionPlanOrderDefinition(
        plan_id="plan-1",
        plan_version=1,
        content_hash=definition.content_hash,
        account_id="account:7",
        order_ordinal=0,
        order_payload_json=expected_json,
        order_content_hash=hashlib.sha256(expected_json.encode("utf-8")).hexdigest(),
        recorded_at=RECORDED_AT,
        valid_until=EXPIRES_AT,
    )
    assert "\\u4e2d\\u8bc1" in result.order_payload_json
    assert '"reference_price":"10.00"' in result.order_payload_json
    assert provider.calls == [("plan-1", 1, RECORDED_AT)]


@pytest.mark.parametrize("ordinal", [-1, True])
def test_query_rejects_invalid_order_ordinal(ordinal: object) -> None:
    with pytest.raises(ValueError, match="order_ordinal"):
        GetExactActiveTransitionPlanOrderQuery(
            plan_id="plan-1",
            plan_version=1,
            order_ordinal=ordinal,  # type: ignore[arg-type]
            as_of=RECORDED_AT,
        )


def test_reader_reports_missing_or_out_of_bounds_exact_order_as_unavailable() -> None:
    with pytest.raises(TransitionPlanOrderReaderUnavailable, match="unavailable"):
        GetExactActiveTransitionPlanOrder(PlanProvider(None)).execute(_query())

    with pytest.raises(TransitionPlanOrderReaderUnavailable, match="ordinal"):
        GetExactActiveTransitionPlanOrder(PlanProvider(_definition())).execute(_query(ordinal=1))


@pytest.mark.parametrize("as_of", [RECORDED_AT - timedelta(microseconds=1), EXPIRES_AT])
def test_reader_rejects_plan_outside_exact_active_window(as_of: datetime) -> None:
    with pytest.raises(TransitionPlanOrderReaderUnavailable, match="active"):
        GetExactActiveTransitionPlanOrder(PlanProvider(_definition())).execute(_query(as_of=as_of))


def test_reader_rejects_identity_version_and_type_substitution() -> None:
    other_id = replace(_plan(), plan_id="plan-2")
    with pytest.raises(TransitionPlanOrderReaderCorruption, match="identity"):
        GetExactActiveTransitionPlanOrder(PlanProvider(_definition(other_id))).execute(_query())

    other_version = _plan(version=2)
    with pytest.raises(TransitionPlanOrderReaderCorruption, match="identity"):
        GetExactActiveTransitionPlanOrder(PlanProvider(_definition(other_version))).execute(
            _query()
        )

    with pytest.raises(TransitionPlanOrderReaderCorruption, match="type"):
        GetExactActiveTransitionPlanOrder(PlanProvider(object())).execute(_query())


def test_reader_revalidates_approved_definition_returned_by_provider() -> None:
    invalid = object.__new__(TransitionPlanDefinition)
    draft = _plan(status="DRAFT")
    object.__setattr__(invalid, "plan", draft)
    object.__setattr__(invalid, "content_hash", transition_plan_content_hash_v1(draft))
    object.__setattr__(invalid, "recorded_at", RECORDED_AT)

    with pytest.raises(TransitionPlanOrderReaderCorruption, match="invalid"):
        GetExactActiveTransitionPlanOrder(PlanProvider(invalid)).execute(_query())


def test_reader_rejects_naive_cutoff_before_calling_provider() -> None:
    provider = PlanProvider(_definition())
    with pytest.raises(ValueError, match="timezone-aware"):
        _query(as_of=datetime(2026, 8, 13, 8))
    assert provider.calls == []


def test_application_reader_has_no_infrastructure_or_broker_dependency() -> None:
    source_path = (
        Path(__file__).parents[3]
        / "apps"
        / "portfolio"
        / "application"
        / "transition_plan_order_reader.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    modules.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    assert not any(".infrastructure" in module for module in modules)
    assert not any(module.startswith("apps.broker_execution") for module in modules)
