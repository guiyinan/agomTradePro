"""Pure Application coverage for inactive Plan-to-Order binding workflow."""

from __future__ import annotations

import ast
import json
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.broker_execution.application.plan_order_binding import (
    BrokerPlanOrderBindingConflict,
    BrokerPlanOrderBindingCorruption,
    BrokerPlanOrderBindingUnavailable,
    ExactBrokerOrderArtifactDefinition,
    ExactPortfolioInactiveReceiptDefinition,
    ExactPortfolioPlanOrderDefinition,
    GetCurrentBrokerPlanOrderBinding,
    GetCurrentBrokerPlanOrderBindingCommand,
    GetExactBrokerPlanOrderBinding,
    GetExactBrokerPlanOrderBindingCommand,
    RegisterBrokerPlanOrderBinding,
    RegisterBrokerPlanOrderBindingCommand,
)
from apps.broker_execution.domain.plan_order_binding import (
    BROKER_PLAN_ORDER_BINDING_SCHEMA,
    BrokerPlanOrderBinding,
    canonical_plan_order_payload_hash_v1,
)

NOW = datetime(2026, 8, 13, 8, tzinfo=UTC)
ORDER_ID = "56f9ae53-7606-46de-bf88-a6543f822d4a"


def _row_json(*, quantity: int = 100) -> str:
    return json.dumps(
        {
            "asset_code": "600000.SH",
            "side": "buy",
            "quantity": quantity,
            "reference_price": "10.2500",
            "estimated_fee": "5.00",
            "status": "draft",
            "remaining_quantity": quantity,
            "constraints": [],
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _plan(**changes: object) -> ExactPortfolioPlanOrderDefinition:
    row = changes.pop("order_payload_json", _row_json())
    assert isinstance(row, str)
    values: dict[str, object] = {
        "plan_id": "plan-1",
        "plan_version": 2,
        "content_hash": "a" * 64,
        "account_id": "007",
        "order_ordinal": 0,
        "order_payload_json": row,
        "order_content_hash": canonical_plan_order_payload_hash_v1(row),
        "recorded_at": NOW - timedelta(minutes=3),
        "valid_until": NOW + timedelta(hours=3),
    }
    values.update(changes)
    return ExactPortfolioPlanOrderDefinition(**values)  # type: ignore[arg-type]


def _receipt(**changes: object) -> ExactPortfolioInactiveReceiptDefinition:
    values: dict[str, object] = {
        "receipt_id": "receipt-1",
        "receipt_version": "receipt.v1",
        "content_hash": "b" * 64,
        "subject_id": "subject-1",
        "subject_version": "subject.v1",
        "subject_content_hash": "c" * 64,
        "plan_id": "plan-1",
        "plan_version": 2,
        "plan_content_hash": "a" * 64,
        "account_id": "007",
        "issued_at": NOW - timedelta(minutes=2),
        "recorded_at": NOW - timedelta(minutes=2),
        "valid_until": NOW + timedelta(hours=2),
    }
    values.update(changes)
    return ExactPortfolioInactiveReceiptDefinition(**values)  # type: ignore[arg-type]


def _artifact(**changes: object) -> ExactBrokerOrderArtifactDefinition:
    values: dict[str, object] = {
        "artifact_id": ORDER_ID,
        "artifact_version": "broker-live-order-approval-artifact.v1.3",
        "identity_hash": "d" * 64,
        "content_hash": "e" * 64,
        "account_id": 7,
        "order_version": 3,
        "approval_digest": "f" * 64,
        "approved_at": NOW - timedelta(minutes=1),
        "recorded_at": NOW - timedelta(minutes=1),
        "valid_until": NOW + timedelta(hours=1),
    }
    values.update(changes)
    return ExactBrokerOrderArtifactDefinition(**values)  # type: ignore[arg-type]


def _command(**changes: object) -> RegisterBrokerPlanOrderBindingCommand:
    values: dict[str, object] = {
        "binding_id": "binding-1",
        "plan_id": "plan-1",
        "plan_version": 2,
        "plan_order_ordinal": 0,
        "portfolio_receipt_id": "receipt-1",
        "portfolio_receipt_version": "receipt.v1",
        "order_artifact_id": ORDER_ID,
        "order_artifact_version": "broker-live-order-approval-artifact.v1.3",
    }
    values.update(changes)
    return RegisterBrokerPlanOrderBindingCommand(**values)  # type: ignore[arg-type]


class _Provider:
    def __init__(self, *values: object) -> None:
        self.values = list(values)
        self.calls: list[dict[str, object]] = []

    def _next(self, kwargs: dict[str, object]) -> object:
        self.calls.append(kwargs)
        return self.values.pop(0) if len(self.values) > 1 else self.values[0]

    def get_exact_active(self, **kwargs: object) -> object:
        return self._next(kwargs)

    def get_exact_inactive(self, **kwargs: object) -> object:
        return self._next(kwargs)


class _Repository:
    def __init__(self) -> None:
        self.clock = NOW
        self.winner: BrokerPlanOrderBinding | None = None
        self.head: BrokerPlanOrderBinding | None = None
        self.exact: BrokerPlanOrderBinding | None = None
        self.appended: list[tuple[BrokerPlanOrderBinding, str | None, datetime]] = []

    def atomic(self) -> nullcontext[None]:
        return nullcontext()

    def now(self) -> datetime:
        return self.clock

    def get_binding_winner(self, **kwargs: object) -> BrokerPlanOrderBinding | None:
        if self.winner is None or self.winner.binding_id != kwargs["binding_id"]:
            return None
        return self.winner

    def get_current_head(self, **kwargs: object) -> BrokerPlanOrderBinding | None:
        return self.head

    def append(
        self,
        value: BrokerPlanOrderBinding,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> BrokerPlanOrderBinding:
        self.appended.append((value, expected_predecessor_hash, recorded_at))
        self.winner = value
        self.head = value
        self.exact = value
        return value

    def get_exact_by_hash(self, **kwargs: object) -> BrokerPlanOrderBinding | None:
        return self.exact


def _use_case(
    repository: _Repository | None = None,
    *,
    plans: tuple[object, ...] | None = None,
    receipts: tuple[object, ...] | None = None,
    artifacts: tuple[object, ...] | None = None,
) -> tuple[RegisterBrokerPlanOrderBinding, _Repository, _Provider, _Provider, _Provider]:
    repo = repository or _Repository()
    plan_provider = _Provider(*(plans or (_plan(),)))
    receipt_provider = _Provider(*(receipts or (_receipt(),)))
    artifact_provider = _Provider(*(artifacts or (_artifact(),)))
    return (
        RegisterBrokerPlanOrderBinding(
            plan_provider=plan_provider,
            receipt_provider=receipt_provider,
            order_provider=artifact_provider,
            repository=repo,
        ),
        repo,
        plan_provider,
        receipt_provider,
        artifact_provider,
    )


def test_register_uses_one_cutoff_double_reads_and_keeps_accounts_separate() -> None:
    use_case, repo, plans, receipts, artifacts = _use_case()

    value = use_case.execute(_command())

    assert value.portfolio_account_id == "007"
    assert value.broker_account_id == 7
    assert value.plan_order_payload_json == _row_json()
    assert value.valid_until == _artifact().valid_until
    assert value.activation_available is False
    assert value.must_not_execute is True
    assert [call["as_of"] for call in plans.calls] == [NOW, NOW]
    assert [call["as_of"] for call in receipts.calls] == [NOW, NOW]
    assert [call["as_of"] for call in artifacts.calls] == [NOW, NOW]
    assert repo.appended == [(value, None, NOW)]


@pytest.mark.parametrize("source", ["plan", "receipt", "artifact"])
def test_register_fails_closed_when_any_owner_source_changes(source: str) -> None:
    kwargs: dict[str, tuple[object, ...]] = {
        "plans": (_plan(), _plan(content_hash="1" * 64)),
        "receipts": (_receipt(), _receipt(content_hash="2" * 64)),
        "artifacts": (_artifact(), _artifact(content_hash="3" * 64)),
    }
    selected = {source + "s": kwargs[source + "s"]}
    use_case, repo, *_ = _use_case(**selected)  # type: ignore[arg-type]

    with pytest.raises(BrokerPlanOrderBindingCorruption, match="changed|receipt"):
        use_case.execute(_command())

    assert not repo.appended


@pytest.mark.parametrize(
    "receipt",
    [
        _receipt(plan_id="plan-2"),
        _receipt(plan_version=3),
        _receipt(plan_content_hash="0" * 64),
        _receipt(account_id="008"),
    ],
)
def test_receipt_must_bind_the_exact_plan(receipt: object) -> None:
    use_case, *_ = _use_case(receipts=(receipt,))
    with pytest.raises(BrokerPlanOrderBindingCorruption, match="receipt"):
        use_case.execute(_command())


def test_plan_provider_cannot_substitute_the_requested_ordinal() -> None:
    use_case, *_ = _use_case(plans=(_plan(order_ordinal=1),))
    with pytest.raises(BrokerPlanOrderBindingCorruption, match="ordinal"):
        use_case.execute(_command())


@pytest.mark.parametrize(
    "factory, changes",
    [
        (_plan, {"owner": "caller"}),
        (_plan, {"artifact_type": "approximate_plan"}),
        (_plan, {"order_content_hash": "0" * 64}),
        (_receipt, {"owner": "caller"}),
        (_receipt, {"execution_permission": "active"}),
        (_artifact, {"owner": "caller"}),
        (_artifact, {"artifact_type": "order_guess"}),
        (_artifact, {"activation_available": True}),
    ],
)
def test_source_dtos_reject_authority_hash_or_permission_substitution(
    factory: object, changes: dict[str, object]
) -> None:
    with pytest.raises(ValueError):
        factory(**changes)  # type: ignore[operator]


def test_existing_head_is_bound_by_cas_and_exact_successor() -> None:
    first_use_case, repo, *_ = _use_case()
    first = first_use_case.execute(_command())
    repo.clock = NOW + timedelta(minutes=1)
    next_use_case, *_ = _use_case(
        repo,
        plans=(_plan(recorded_at=NOW - timedelta(minutes=3)),),
        receipts=(_receipt(),),
        artifacts=(_artifact(content_hash="1" * 64),),
    )

    second = next_use_case.execute(_command(binding_id="binding-2"))

    assert second.supersedes_binding_hash == first.content_hash
    assert repo.appended[-1][1] == first.content_hash


def test_identity_replay_requires_exact_current_first_winner() -> None:
    use_case, repo, *_ = _use_case()
    winner = use_case.execute(_command())
    replay, *_ = _use_case(repo)
    assert replay.execute(_command()) == winner

    repo.head = None
    with pytest.raises(BrokerPlanOrderBindingConflict, match="current head"):
        replay.execute(_command())


def _exact_command(
    value: BrokerPlanOrderBinding, **changes: object
) -> GetExactBrokerPlanOrderBindingCommand:
    data: dict[str, object] = {
        "binding_id": value.binding_id,
        "expected_content_hash": value.content_hash,
        "as_of": NOW,
    }
    data.update(changes)
    return GetExactBrokerPlanOrderBindingCommand(**data)  # type: ignore[arg-type]


def _current_command(
    value: BrokerPlanOrderBinding, **changes: object
) -> GetCurrentBrokerPlanOrderBindingCommand:
    data = {
        "binding_id": value.binding_id,
        "expected_content_hash": value.content_hash,
        "portfolio_plan_id": value.portfolio_plan_id,
        "portfolio_plan_version": value.portfolio_plan_version,
        "portfolio_plan_content_hash": value.portfolio_plan_content_hash,
        "portfolio_account_id": value.portfolio_account_id,
        "portfolio_receipt_id": value.portfolio_receipt_id,
        "portfolio_receipt_version": value.portfolio_receipt_version,
        "portfolio_receipt_content_hash": value.portfolio_receipt_content_hash,
        "portfolio_subject_id": value.portfolio_subject_id,
        "portfolio_subject_version": value.portfolio_subject_version,
        "portfolio_subject_content_hash": value.portfolio_subject_content_hash,
        "plan_order_ordinal": value.plan_order_ordinal,
        "plan_order_content_hash": value.plan_order_content_hash,
        "broker_account_id": value.broker_account_id,
        "order_artifact_id": value.order_artifact_id,
        "order_artifact_version": value.order_artifact_version,
        "order_artifact_identity_hash": value.order_artifact_identity_hash,
        "order_artifact_content_hash": value.order_artifact_content_hash,
        "order_approval_digest": value.order_approval_digest,
        "order_version": value.order_version,
        "as_of": NOW,
    }
    data.update(changes)
    return GetCurrentBrokerPlanOrderBindingCommand(**data)  # type: ignore[arg-type]


def test_exact_and_closed_current_reads_return_only_active_inactive_binding() -> None:
    register, repo, *_ = _use_case()
    value = register.execute(_command())

    assert GetExactBrokerPlanOrderBinding(repo).execute(_exact_command(value)) == value
    assert GetCurrentBrokerPlanOrderBinding(repo).execute(_current_command(value)) == value


@pytest.mark.parametrize(
    "changes",
    [
        {"portfolio_plan_content_hash": "0" * 64},
        {"portfolio_receipt_content_hash": "1" * 64},
        {"portfolio_subject_content_hash": "2" * 64},
        {"plan_order_content_hash": "3" * 64},
        {"broker_account_id": 8},
        {"order_artifact_identity_hash": "4" * 64},
        {"order_artifact_content_hash": "5" * 64},
        {"order_approval_digest": "6" * 64},
        {"order_version": 4},
    ],
)
def test_current_read_rejects_every_source_selector_substitution(
    changes: dict[str, object]
) -> None:
    register, repo, *_ = _use_case()
    value = register.execute(_command())
    with pytest.raises(BrokerPlanOrderBindingCorruption, match="selector"):
        GetCurrentBrokerPlanOrderBinding(repo).execute(_current_command(value, **changes))


def test_exact_read_returns_none_outside_pit_window() -> None:
    register, repo, *_ = _use_case()
    value = register.execute(_command())
    repo.exact = value

    assert (
        GetExactBrokerPlanOrderBinding(repo).execute(_exact_command(value, as_of=value.valid_until))
        is None
    )


def test_application_contract_does_not_import_other_apps_or_infrastructure() -> None:
    path = Path("apps/broker_execution/application/plan_order_binding.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not any(name.startswith("apps.portfolio") for name in imports)
    assert not any("infrastructure" in name for name in imports)
