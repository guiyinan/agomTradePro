"""Fail-closed contracts for the four live-order Evidence checkpoints."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, cast

import pytest

from apps.broker_execution.application import use_cases
from apps.broker_execution.application.agent_use_cases import (
    AcknowledgeSubmittingUseCase,
    LeaseAgentOrdersUseCase,
)
from apps.broker_execution.application.evidence_gate import (
    BROKER_ORDER_EVIDENCE_BLOCKER,
    blocked_lease_result,
    require_broker_order_evidence,
)
from apps.broker_execution.application.ports import BrokerExecutionRepositoryProtocol
from apps.broker_execution.application.use_case_errors import BrokerExecutionConflictError
from apps.broker_execution.application.use_cases import (
    CreateLiveOrderFromExecutionPlanUseCase,
    PreviewOrMutateOrderUseCase,
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


def _repository(**methods: Any) -> BrokerExecutionRepositoryProtocol:
    return cast(BrokerExecutionRepositoryProtocol, SimpleNamespace(**methods))


@pytest.mark.parametrize("checkpoint", ["create", "approve", "lease", "submitting"])
def test_each_formal_evidence_checkpoint_is_fail_closed(checkpoint: str) -> None:
    with pytest.raises(BrokerExecutionConflictError, match=f"\\[{checkpoint}\\]"):
        require_broker_order_evidence(checkpoint=checkpoint)


def test_create_is_blocked_before_providers_or_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(use_cases, "require_action", lambda _actor, _action: (7, "owner", False))
    called: list[str] = []
    creator = CreateLiveOrderFromExecutionPlanUseCase(
        repository=_repository(create_live_order=lambda **_kwargs: called.append("repository")),
        account_projection_provider=lambda **_kwargs: called.append("account"),
        risk_evaluator=SimpleNamespace(execute=lambda **_kwargs: called.append("risk")),
        latest_quote_provider=lambda _symbol: called.append("quote"),
    )

    with pytest.raises(BrokerExecutionConflictError, match="Evidence"):
        creator.execute(actor=_Actor(), plan={}, idempotency_key="create-1")

    assert called == []


def test_approve_preview_is_readable_but_commit_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(use_cases, "require_action", lambda _actor, _action: (7, "owner", False))
    mutations: list[dict[str, Any]] = []
    repository = _repository(
        get_order=lambda **_kwargs: {
            "account_id": 7,
            "asset_code": "510300.SH",
            "side": "BUY",
            "quantity": "100",
            "limit_price": "3.90",
            "filled_quantity": "0",
            "status": "WAITING_APPROVAL",
        },
        has_account_access=lambda **_kwargs: True,
        mutate_order=lambda **kwargs: mutations.append(kwargs),
    )
    use_case = PreviewOrMutateOrderUseCase(repository)

    preview = use_case.execute(
        actor=_Actor(),
        client_order_id="00000000-0000-0000-0000-000000000001",
        action="approve",
        reason="reviewed",
        preview_only=True,
    )
    assert preview["commit_allowed"] is False
    assert preview["blocker_codes"] == [BROKER_ORDER_EVIDENCE_BLOCKER]
    assert preview["must_not_execute"] is True

    with pytest.raises(BrokerExecutionConflictError, match="\\[approve\\]"):
        use_case.execute(
            actor=_Actor(),
            client_order_id="00000000-0000-0000-0000-000000000001",
            action="approve",
            reason="reviewed",
            preview_only=False,
            expected_version=1,
            idempotency_key="approve-1",
        )
    assert mutations == []


def test_reject_and_cancel_are_not_blocked_by_evidence_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(use_cases, "require_action", lambda _actor, _action: (7, "owner", False))
    mutations: list[dict[str, Any]] = []

    def order_for(**_kwargs: object) -> dict[str, object]:
        return {
            "account_id": 7,
            "asset_code": "510300.SH",
            "side": "BUY",
            "quantity": "100",
            "limit_price": "3.90",
            "filled_quantity": "0",
            "status": "WAITING_APPROVAL",
        }

    repository = _repository(
        get_order=order_for,
        has_account_access=lambda **_kwargs: True,
        mutate_order=lambda **kwargs: mutations.append(kwargs) or {"success": True},
    )
    result = PreviewOrMutateOrderUseCase(repository).execute(
        actor=_Actor(),
        client_order_id="00000000-0000-0000-0000-000000000001",
        action="reject",
        reason="declined",
        preview_only=False,
        expected_version=1,
        idempotency_key="reject-1",
    )
    assert result == {"success": True}
    assert len(mutations) == 1


def test_agent_poll_is_stably_empty_and_submitting_is_blocked() -> None:
    calls: list[str] = []
    repository = _repository(
        lease_agent_orders=lambda **_kwargs: calls.append("lease"),
        acknowledge_submitting=lambda **_kwargs: calls.append("submitting"),
    )
    agent = {"agent_pk": 3, "allowed_account_ids": [7]}

    assert LeaseAgentOrdersUseCase(repository).execute(agent=agent) == blocked_lease_result()
    with pytest.raises(BrokerExecutionConflictError, match="\\[submitting\\]"):
        AcknowledgeSubmittingUseCase(repository).execute(
            agent=agent,
            client_order_id="00000000-0000-0000-0000-000000000001",
            lease_token="lease-token",
        )
    assert calls == []
