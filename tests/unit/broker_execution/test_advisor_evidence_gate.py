"""Fail-closed contracts for the Advisor-to-Broker draft bridge."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from apps.broker_execution.application.use_case_errors import BrokerExecutionConflictError
from apps.broker_execution.application.use_cases import (
    ADVISOR_EVIDENCE_BLOCK_MESSAGE,
    ADVISOR_EVIDENCE_BLOCKER,
    CreateLiveOrdersFromAdvisorExecutionPlanUseCase,
    PreviewOrCreateAdvisorLiveOrdersUseCase,
)


@dataclass
class _Profile:
    rbac_role: str = "owner"


@dataclass
class _Actor:
    id: int = 7
    is_authenticated: bool = True
    is_superuser: bool = False
    account_profile: _Profile = field(default_factory=_Profile)


class _OrderCreator:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"created_count": 1}


def _execution_plan() -> dict[str, Any]:
    return {
        "status": "READY_FOR_CONFIRMATION",
        "execution_mode": "real_confirm_only",
        "orders_count": 1,
        "orders": [
            {
                "order_intent_id": "intent-1",
                "account_id": 7,
                "asset_code": "510300.SH",
                "side": "ADD",
                "suggested_quantity": 100,
                "estimated_price": "3.90",
                "source_recommendation_ids": ["recommendation-1"],
            }
        ],
    }


def test_preview_remains_read_only_and_publishes_stable_evidence_blocker() -> None:
    creator = _OrderCreator()
    use_case = PreviewOrCreateAdvisorLiveOrdersUseCase(
        sheet_provider=lambda **_kwargs: {"execution_plan": _execution_plan()},
        order_creator=creator,
    )

    result = use_case.execute(actor=_Actor(), account_id=7, preview_only=True)

    assert result["preview_only"] is True
    assert result["commit_allowed"] is False
    assert result["display_only"] is True
    assert result["must_not_use_for_decision"] is True
    assert result["must_not_execute"] is True
    assert result["blocker_codes"] == [ADVISOR_EVIDENCE_BLOCKER]
    assert result["warning"] == ADVISOR_EVIDENCE_BLOCK_MESSAGE
    assert creator.calls == []


def test_commit_is_blocked_before_order_creator_even_with_matching_digest() -> None:
    creator = _OrderCreator()
    use_case = PreviewOrCreateAdvisorLiveOrdersUseCase(
        sheet_provider=lambda **_kwargs: {"execution_plan": _execution_plan()},
        order_creator=creator,
    )
    preview = use_case.execute(actor=_Actor(), account_id=7, preview_only=True)

    with pytest.raises(BrokerExecutionConflictError, match="Evidence is integrated"):
        use_case.execute(
            actor=_Actor(),
            account_id=7,
            preview_only=False,
            expected_plan_digest=preview["plan_digest"],
            idempotency_key="advisor-commit-1",
        )

    assert creator.calls == []


def test_lower_level_plan_converter_cannot_bypass_evidence_gate() -> None:
    creator = _OrderCreator()
    use_case = CreateLiveOrdersFromAdvisorExecutionPlanUseCase(order_creator=creator)

    with pytest.raises(BrokerExecutionConflictError, match="Evidence is integrated"):
        use_case.execute(
            actor=_Actor(),
            execution_plan=_execution_plan(),
            idempotency_prefix="advisor-direct-1",
        )

    assert creator.calls == []


def test_classic_workbench_does_not_offer_commit_when_preview_is_blocked() -> None:
    template = (
        Path(__file__).resolve().parents[3]
        / "apps"
        / "broker_execution"
        / "templates"
        / "broker_execution"
        / "workbench.html"
    ).read_text(encoding="utf-8")

    assert "show(preview);if(!preview.commit_allowed)return;" in template
