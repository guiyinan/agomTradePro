"""Pure Application coverage for inactive pre-Risk registration and reads."""

from __future__ import annotations

import ast
from contextlib import AbstractContextManager, nullcontext
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Generic, TypeVar

import pytest

from apps.broker_execution.application.pre_risk_execution_scope import (
    BrokerOrderApprovalArtifactDefinition,
    BrokerPreRiskExecutionScopeRepository,
    BrokerPreRiskScopeConflict,
    BrokerPreRiskScopeCorruption,
    BrokerPreRiskScopeUnavailable,
    GetCurrentBrokerPreRiskExecutionScope,
    GetCurrentBrokerPreRiskExecutionScopeCommand,
    GetExactBrokerPreRiskExecutionScope,
    GetExactBrokerPreRiskExecutionScopeCommand,
    PortfolioInactiveApprovalReceiptDefinition,
    PortfolioTransitionPlanDefinition,
    RegisterBrokerPreRiskExecutionScope,
    RegisterBrokerPreRiskExecutionScopeCommand,
)
from apps.broker_execution.domain.pre_risk_execution_scope import (
    BrokerPreRiskExecutionScope,
)

NOW = datetime(2026, 8, 13, 4, tzinfo=UTC)
ORDER_ID = "56f9ae53-7606-46de-bf88-a6543f822d4a"
T = TypeVar("T")


def _plan(**changes: object) -> PortfolioTransitionPlanDefinition:
    values: dict[str, object] = {
        "plan_id": "transition-plan-1",
        "plan_version": 2,
        "content_hash": "a" * 64,
        "account_id": "portfolio-account-7",
        "recorded_at": NOW - timedelta(minutes=10),
        "valid_until": NOW + timedelta(hours=5),
    }
    values.update(changes)
    return PortfolioTransitionPlanDefinition(**values)  # type: ignore[arg-type]


def _receipt(**changes: object) -> PortfolioInactiveApprovalReceiptDefinition:
    values: dict[str, object] = {
        "receipt_id": "portfolio-receipt-1",
        "receipt_version": "portfolio-receipt.v1",
        "content_hash": "b" * 64,
        "subject_id": "portfolio-subject-1",
        "subject_version": "portfolio-subject.v1",
        "subject_content_hash": "c" * 64,
        "plan_id": "transition-plan-1",
        "plan_version": 2,
        "plan_content_hash": "a" * 64,
        "account_id": "portfolio-account-7",
        "recorded_at": NOW - timedelta(minutes=5),
        "issued_at": NOW - timedelta(minutes=6),
        "valid_until": NOW + timedelta(hours=4),
    }
    values.update(changes)
    return PortfolioInactiveApprovalReceiptDefinition(**values)  # type: ignore[arg-type]


def _order(**changes: object) -> BrokerOrderApprovalArtifactDefinition:
    values: dict[str, object] = {
        "artifact_id": ORDER_ID,
        "artifact_version": "broker-order-artifact.v1.3",
        "content_hash": "d" * 64,
        "identity_hash": "e" * 64,
        "account_id": 7,
        "order_version": 3,
        "approval_digest": "f" * 64,
        "risk_policy_version": "risk-policy-v4",
        "recorded_at": NOW - timedelta(minutes=2),
        "approved_at": NOW - timedelta(minutes=3),
        "valid_until": NOW + timedelta(hours=3),
    }
    values.update(changes)
    return BrokerOrderApprovalArtifactDefinition(**values)  # type: ignore[arg-type]


def _command(scope_id: str = "pre-risk-scope-1") -> RegisterBrokerPreRiskExecutionScopeCommand:
    return RegisterBrokerPreRiskExecutionScopeCommand(
        scope_id=scope_id,
        plan_id="transition-plan-1",
        plan_version=2,
        portfolio_receipt_id="portfolio-receipt-1",
        portfolio_receipt_version="portfolio-receipt.v1",
        order_artifact_id=ORDER_ID,
        order_artifact_version="broker-order-artifact.v1.3",
    )


class _SequenceProvider(Generic[T]):
    def __init__(self, values: list[T | None]) -> None:
        self.values = values
        self.calls: list[dict[str, object]] = []

    def _next(self, arguments: dict[str, object]) -> T | None:
        self.calls.append(arguments)
        index = min(len(self.calls) - 1, len(self.values) - 1)
        return self.values[index]


class _PlanProvider(_SequenceProvider[PortfolioTransitionPlanDefinition]):
    def get_exact_active(
        self, *, plan_id: str, plan_version: int, as_of: datetime
    ) -> PortfolioTransitionPlanDefinition | None:
        return self._next({"plan_id": plan_id, "plan_version": plan_version, "as_of": as_of})


class _ReceiptProvider(_SequenceProvider[PortfolioInactiveApprovalReceiptDefinition]):
    def get_exact_inactive(
        self, *, receipt_id: str, receipt_version: str, as_of: datetime
    ) -> PortfolioInactiveApprovalReceiptDefinition | None:
        return self._next(
            {
                "receipt_id": receipt_id,
                "receipt_version": receipt_version,
                "as_of": as_of,
            }
        )


class _OrderProvider(_SequenceProvider[BrokerOrderApprovalArtifactDefinition]):
    def get_exact_inactive(
        self, *, artifact_id: str, artifact_version: str, as_of: datetime
    ) -> BrokerOrderApprovalArtifactDefinition | None:
        return self._next(
            {
                "artifact_id": artifact_id,
                "artifact_version": artifact_version,
                "as_of": as_of,
            }
        )


class _Repository(BrokerPreRiskExecutionScopeRepository):
    def __init__(self) -> None:
        self.clock = NOW
        self.by_identity: dict[tuple[str, str], BrokerPreRiskExecutionScope] = {}
        self.heads: dict[tuple[int, str], BrokerPreRiskExecutionScope] = {}
        self.append_calls: list[tuple[str | None, datetime]] = []

    def atomic(self) -> AbstractContextManager[None]:
        return nullcontext()

    def now(self) -> datetime:
        return self.clock

    def get_scope_winner(
        self, *, scope_id: str, scope_version: str, as_of: datetime
    ) -> BrokerPreRiskExecutionScope | None:
        del as_of
        return self.by_identity.get((scope_id, scope_version))

    def get_current_head(
        self, *, broker_account_id: int, order_artifact_id: str, as_of: datetime
    ) -> BrokerPreRiskExecutionScope | None:
        del as_of
        return self.heads.get((broker_account_id, order_artifact_id))

    def append(
        self,
        scope: BrokerPreRiskExecutionScope,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> BrokerPreRiskExecutionScope:
        self.append_calls.append((expected_predecessor_hash, recorded_at))
        key = (scope.broker_account_id, scope.order_artifact_id)
        current = self.heads.get(key)
        actual = current.content_hash if current else None
        if actual != expected_predecessor_hash:
            raise BrokerPreRiskScopeConflict("CAS conflict")
        identity = (scope.scope_id, scope.scope_version)
        winner = self.by_identity.setdefault(identity, scope)
        if winner == scope:
            self.heads[key] = winner
        return winner

    def get_exact_by_hash(
        self,
        *,
        scope_id: str,
        scope_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> BrokerPreRiskExecutionScope | None:
        value = self.by_identity.get((scope_id, scope_version))
        if value is None or value.content_hash != expected_content_hash:
            return None
        return value if value.is_knowable_at(as_of) else None


def _use_case(
    repository: _Repository,
    *,
    plans: list[PortfolioTransitionPlanDefinition | None] | None = None,
    receipts: list[PortfolioInactiveApprovalReceiptDefinition | None] | None = None,
    orders: list[BrokerOrderApprovalArtifactDefinition | None] | None = None,
) -> tuple[
    RegisterBrokerPreRiskExecutionScope,
    _PlanProvider,
    _ReceiptProvider,
    _OrderProvider,
]:
    plan_provider = _PlanProvider(plans or [_plan()])
    receipt_provider = _ReceiptProvider(receipts or [_receipt()])
    order_provider = _OrderProvider(orders or [_order()])
    return (
        RegisterBrokerPreRiskExecutionScope(
            plan_provider=plan_provider,
            receipt_provider=receipt_provider,
            order_provider=order_provider,
            repository=repository,
        ),
        plan_provider,
        receipt_provider,
        order_provider,
    )


def test_register_double_reads_with_one_server_cutoff_and_appends_inactive_scope() -> None:
    repository = _Repository()
    use_case, plan_provider, receipt_provider, order_provider = _use_case(repository)

    scope = use_case.execute(_command())

    assert len(plan_provider.calls) == len(receipt_provider.calls) == 2
    assert len(order_provider.calls) == 2
    assert {
        call["as_of"]
        for provider in (plan_provider, receipt_provider, order_provider)
        for call in provider.calls
    } == {NOW}
    assert scope.recorded_at == NOW
    assert scope.valid_until == NOW + timedelta(hours=3)
    assert scope.broker_account_id == 7
    assert scope.portfolio_account_id == "portfolio-account-7"
    assert scope.order_risk_policy_version == "risk-policy-v4"
    assert scope.activation_available is False
    assert scope.must_not_execute is True
    assert repository.append_calls == [(None, NOW)]


def test_register_command_is_id_only_and_cannot_inject_authority() -> None:
    names = {field.name for field in fields(RegisterBrokerPreRiskExecutionScopeCommand)}

    assert names == {
        "scope_id",
        "scope_version",
        "plan_id",
        "plan_version",
        "portfolio_receipt_id",
        "portfolio_receipt_version",
        "order_artifact_id",
        "order_artifact_version",
    }
    assert not names & {
        "content_hash",
        "broker_account_id",
        "portfolio_account_id",
        "permission",
        "activation_available",
        "must_not_execute",
    }


def test_registration_rejects_owner_drift_between_first_and_final_reads() -> None:
    repository = _Repository()
    use_case, _, _, _ = _use_case(
        repository,
        orders=[_order(), _order(risk_policy_version="risk-policy-v5")],
    )

    with pytest.raises(BrokerPreRiskScopeCorruption, match="changed"):
        use_case.execute(_command())

    assert not repository.by_identity


def test_registration_rejects_receipt_plan_substitution() -> None:
    repository = _Repository()
    use_case, _, _, _ = _use_case(
        repository,
        receipts=[_receipt(plan_content_hash="8" * 64)],
    )

    with pytest.raises(BrokerPreRiskScopeCorruption, match="exact plan"):
        use_case.execute(_command())


def test_registration_fails_closed_when_one_exact_owner_source_is_missing() -> None:
    repository = _Repository()
    use_case, _, _, _ = _use_case(repository, orders=[None])

    with pytest.raises(BrokerPreRiskScopeUnavailable, match="order artifact"):
        use_case.execute(_command())


def test_same_identity_replay_returns_current_first_winner() -> None:
    repository = _Repository()
    use_case, _, _, _ = _use_case(repository)
    winner = use_case.execute(_command())

    replay, _, _, _ = _use_case(repository)
    assert replay.execute(_command()) == winner
    assert len(repository.append_calls) == 1


def test_same_account_order_forms_one_supersession_chain() -> None:
    repository = _Repository()
    first_use_case, _, _, _ = _use_case(repository)
    first = first_use_case.execute(_command())
    repository.clock = NOW + timedelta(minutes=1)

    second_use_case, _, _, _ = _use_case(repository)
    second = second_use_case.execute(_command("pre-risk-scope-2"))

    assert second.supersedes_scope_hash == first.content_hash
    assert repository.append_calls[-1] == (first.content_hash, repository.clock)
    assert repository.heads[(7, ORDER_ID)] == second


def test_identity_winner_must_still_be_current_logical_head() -> None:
    repository = _Repository()
    first_use_case, _, _, _ = _use_case(repository)
    first_use_case.execute(_command())
    repository.clock = NOW + timedelta(minutes=1)
    second_use_case, _, _, _ = _use_case(repository)
    second_use_case.execute(_command("pre-risk-scope-2"))

    replay, _, _, _ = _use_case(repository)
    with pytest.raises(BrokerPreRiskScopeConflict, match="current head"):
        replay.execute(_command())


def _current_command(
    scope: BrokerPreRiskExecutionScope, **changes: object
) -> GetCurrentBrokerPreRiskExecutionScopeCommand:
    values: dict[str, object] = {
        "scope_id": scope.scope_id,
        "expected_content_hash": scope.content_hash,
        "broker_account_id": scope.broker_account_id,
        "order_artifact_id": scope.order_artifact_id,
        "order_artifact_version": scope.order_artifact_version,
        "order_artifact_content_hash": scope.order_artifact_content_hash,
        "plan_id": scope.plan_id,
        "plan_version": scope.plan_version,
        "plan_content_hash": scope.plan_content_hash,
        "portfolio_receipt_id": scope.portfolio_receipt_id,
        "portfolio_receipt_version": scope.portfolio_receipt_version,
        "portfolio_receipt_content_hash": scope.portfolio_receipt_content_hash,
        "as_of": NOW,
    }
    values.update(changes)
    return GetCurrentBrokerPreRiskExecutionScopeCommand(**values)  # type: ignore[arg-type]


def test_exact_and_current_readers_are_inactive_pit_and_closed_selector() -> None:
    repository = _Repository()
    use_case, _, _, _ = _use_case(repository)
    scope = use_case.execute(_command())

    exact = GetExactBrokerPreRiskExecutionScope(repository).execute(
        GetExactBrokerPreRiskExecutionScopeCommand(
            scope_id=scope.scope_id,
            expected_content_hash=scope.content_hash,
            as_of=NOW,
        )
    )
    current = GetCurrentBrokerPreRiskExecutionScope(repository).execute(_current_command(scope))

    assert exact == scope
    assert current == scope
    assert exact is not None and exact.activation_available is False


def test_current_reader_rejects_closed_selector_substitution() -> None:
    repository = _Repository()
    use_case, _, _, _ = _use_case(repository)
    scope = use_case.execute(_command())

    with pytest.raises(BrokerPreRiskScopeCorruption, match="selector substitution"):
        GetCurrentBrokerPreRiskExecutionScope(repository).execute(
            _current_command(scope, plan_content_hash="0" * 64)
        )


def test_current_reader_returns_none_for_superseded_scope() -> None:
    repository = _Repository()
    first_use_case, _, _, _ = _use_case(repository)
    first = first_use_case.execute(_command())
    repository.clock = NOW + timedelta(minutes=1)
    second_use_case, _, _, _ = _use_case(repository)
    second_use_case.execute(_command("pre-risk-scope-2"))

    assert (
        GetCurrentBrokerPreRiskExecutionScope(repository).execute(
            _current_command(first, as_of=repository.clock)
        )
        is None
    )


def test_application_has_no_other_app_or_infrastructure_dependency() -> None:
    path = Path("apps/broker_execution/application/pre_risk_execution_scope.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}

    assert not any(".infrastructure" in name for name in imported)
    assert not any(
        name.startswith("apps.") and not name.startswith("apps.broker_execution.domain")
        for name in imported
    )
