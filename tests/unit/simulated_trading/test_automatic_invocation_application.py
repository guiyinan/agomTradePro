"""Application guarantees for one idempotent, non-resumable auto-trading run."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal
from uuid import UUID, uuid4

import pytest

from apps.simulated_trading.application.automatic_invocation import (
    AutomaticInvocationEngine,
    AutoTradingInvocationClaim,
    AutoTradingInvocationConflict,
    AutoTradingInvocationRepository,
    AutoTradingInvocationRequest,
    ExecuteAutomaticInvocation,
    FrozenAutoTradingScope,
)
from apps.simulated_trading.domain.auto_trading_outcomes import (
    AccountAutoTradingOutcome,
    AutoTradingBatchOutcome,
    AutoTradingIssueKind,
    AutoTradingOutcome,
)
from core.exceptions import AuthorizationError

_TRADE_DATE = date(2026, 10, 19)
_INVOCATION_ID = UUID("3ee7df6e-c8d6-4db2-8b01-3fe25cb78c89")
_FIRST_CLAIM_TOKEN = UUID("29e6c654-d0b2-42c9-b9a4-5b265de3b24a")


@dataclass(slots=True)
class _StoredInvocation:
    """One test-owned durable record with an explicit preparation boundary."""

    request_hash: str
    scope: FrozenAutoTradingScope
    invocation_id: UUID
    claim_token: UUID
    phase: Literal["preparing", "released", "started", "finished"]
    outcome: AutoTradingBatchOutcome | None = None


class _MemoryInvocationRepository(AutoTradingInvocationRepository):
    """Typed in-memory port implementation for Application-only contract tests."""

    def __init__(self) -> None:
        """Start with no saved invocations or state transitions."""
        self._records: dict[tuple[str, str], _StoredInvocation] = {}
        self.events: list[str] = []
        self.claim_requests: list[tuple[AutoTradingInvocationRequest, FrozenAutoTradingScope]] = []
        self.release_calls: list[tuple[UUID, UUID]] = []
        self.started_calls: list[tuple[UUID, UUID]] = []
        self.finish_calls: list[tuple[UUID, UUID, AutoTradingBatchOutcome]] = []
        self.fail_finish = False

    def find_scope(self, request: AutoTradingInvocationRequest) -> FrozenAutoTradingScope | None:
        """Return the originally selected scope or reject changed request content."""
        self.events.append("find_scope")
        identity = (request.namespace, request.invocation_key)
        record = self._records.get(identity)
        if record is None:
            return None
        if record.request_hash != request.content_hash:
            raise AutoTradingInvocationConflict("the invocation key has different input")
        return record.scope

    def claim(
        self, request: AutoTradingInvocationRequest, scope: FrozenAutoTradingScope
    ) -> AutoTradingInvocationClaim:
        """Acquire a fresh or released preparation once, otherwise return its state."""
        self.events.append("claim")
        self.claim_requests.append((request, scope))
        identity = (request.namespace, request.invocation_key)
        record = self._records.get(identity)
        if record is None:
            record = _StoredInvocation(
                request_hash=request.content_hash,
                scope=scope,
                invocation_id=_INVOCATION_ID,
                claim_token=_FIRST_CLAIM_TOKEN,
                phase="preparing",
            )
            self._records[identity] = record
            acquired = True
        else:
            if record.request_hash != request.content_hash:
                raise AutoTradingInvocationConflict("the invocation key has different input")
            if record.scope != scope:
                raise AssertionError("the application did not use the frozen scope")
            if record.phase == "released":
                record.claim_token = uuid4()
                record.phase = "preparing"
                record.outcome = None
                acquired = True
            else:
                acquired = False
        return AutoTradingInvocationClaim(
            invocation_id=record.invocation_id,
            claim_token=record.claim_token,
            scope=record.scope,
            acquired=acquired,
            outcome=record.outcome,
        )

    def release_preparation(self, *, invocation_id: UUID, claim_token: UUID) -> None:
        """Release only the matching claim before the engine-start boundary."""
        self.events.append("release_preparation")
        record = self._record_for_claim(invocation_id, claim_token, expected="preparing")
        record.phase = "released"
        self.release_calls.append((invocation_id, claim_token))

    def mark_started(self, *, invocation_id: UUID, claim_token: UUID) -> None:
        """Record the exact transition after which execution must not re-enter."""
        self.events.append("mark_started")
        record = self._record_for_claim(invocation_id, claim_token, expected="preparing")
        record.phase = "started"
        self.started_calls.append((invocation_id, claim_token))

    def finish(
        self,
        *,
        invocation_id: UUID,
        claim_token: UUID,
        outcome: AutoTradingBatchOutcome,
    ) -> None:
        """Persist a typed result, with an injectable storage failure at this port."""
        self.events.append("finish")
        self.finish_calls.append((invocation_id, claim_token, outcome))
        if self.fail_finish:
            raise RuntimeError("test-owned finalization storage failure")
        record = self._record_for_claim(invocation_id, claim_token, expected="started")
        record.phase = "finished"
        record.outcome = outcome

    def _record_for_claim(
        self,
        invocation_id: UUID,
        claim_token: UUID,
        *,
        expected: Literal["preparing", "started"],
    ) -> _StoredInvocation:
        """Find a claim only when its owner, token, and state still match."""
        for record in self._records.values():
            if record.invocation_id == invocation_id:
                if record.claim_token != claim_token or record.phase != expected:
                    raise AssertionError("claim token or invocation phase changed")
                return record
        raise AssertionError("invocation claim was not created")


class _ScriptedEngine(AutomaticInvocationEngine):
    """Return real typed account outcomes or fail after Application starts it."""

    def __init__(
        self,
        results: dict[int, AccountAutoTradingOutcome],
        events: list[str],
        *,
        run_error: Exception | None = None,
    ) -> None:
        """Configure one deterministic engine boundary for a test scenario."""
        self.results = results
        self.events = events
        self.run_error = run_error
        self.calls: list[tuple[date, list[int] | None]] = []

    def run_daily_trading(
        self, trade_date: date, account_ids: list[int] | None = None
    ) -> dict[int, AccountAutoTradingOutcome]:
        """Record the frozen arguments before returning or raising the scenario."""
        self.events.append("engine_run")
        self.calls.append((trade_date, account_ids))
        if self.run_error is not None:
            raise self.run_error
        return self.results


def _request(
    *,
    invocation_key: str = "daily-run-001",
    trade_date: date | None = None,
    account_ids: tuple[int, ...] | None = None,
) -> AutoTradingInvocationRequest:
    """Build a caller request while preserving omitted date and scope fields."""
    return AutoTradingInvocationRequest(
        namespace="simulated-daily-auto-trading",
        invocation_key=invocation_key,
        trade_date=trade_date,
        requested_account_ids=account_ids,
    )


def _scope(
    *, trade_date: date = _TRADE_DATE, account_ids: tuple[int, ...] = (17,)
) -> FrozenAutoTradingScope:
    """Build one resolved default scope for the application boundary."""
    return FrozenAutoTradingScope(trade_date=trade_date, account_ids=account_ids)


def test_omitted_date_and_scope_resolve_once_then_replay_frozen_result() -> None:
    """A retry reuses the original default date and accounts, never new defaults."""
    repository = _MemoryInvocationRepository()
    use_case = ExecuteAutomaticInvocation(repository)
    frozen_scope = _scope(account_ids=(17, 22))
    events = repository.events
    engine = _ScriptedEngine(
        {
            17: AccountAutoTradingOutcome(account_id=17, buy_count=1, sell_count=0),
            22: AccountAutoTradingOutcome(account_id=22, buy_count=0, sell_count=1),
        },
        events,
    )
    resolved_scopes: list[FrozenAutoTradingScope] = []
    authorized_scopes: list[FrozenAutoTradingScope] = []
    built_ids: list[UUID] = []

    def resolve_scope() -> FrozenAutoTradingScope:
        """Expose changing defaults so replay must use the persisted selection."""
        events.append("resolve_scope")
        selected = (
            frozen_scope
            if not resolved_scopes
            else _scope(trade_date=date(2026, 10, 20), account_ids=(99,))
        )
        resolved_scopes.append(selected)
        return selected

    def authorize_scope(scope: FrozenAutoTradingScope) -> None:
        """Record each authorization check against the exact resolved scope."""
        events.append("authorize_scope")
        authorized_scopes.append(scope)

    def build_engine(invocation_id: UUID) -> AutomaticInvocationEngine:
        """Record the one allowed construction for this invocation."""
        events.append("build_engine")
        built_ids.append(invocation_id)
        return engine

    request = _request()
    first = use_case.execute(
        request,
        resolve_scope=resolve_scope,
        authorize_scope=authorize_scope,
        build_engine=build_engine,
    )
    replay = use_case.execute(
        request,
        resolve_scope=resolve_scope,
        authorize_scope=authorize_scope,
        build_engine=build_engine,
    )

    assert resolved_scopes == [frozen_scope]
    assert authorized_scopes == [frozen_scope, frozen_scope]
    assert engine.calls == [(_TRADE_DATE, [17, 22])]
    assert built_ids == [_INVOCATION_ID]
    assert first.scope == frozen_scope
    assert replay.scope == frozen_scope
    assert replay.replayed is True
    assert replay.outcome == first.outcome
    assert replay.outcome.buy_count == 1
    assert replay.outcome.sell_count == 1
    assert events.index("mark_started") < events.index("engine_run")
    assert repository.release_calls == []


def test_same_key_with_changed_request_body_conflicts_before_scope_or_engine() -> None:
    """Changing an omitted-date request cannot silently retarget a run key."""
    repository = _MemoryInvocationRepository()
    use_case = ExecuteAutomaticInvocation(repository)
    events = repository.events
    engine = _ScriptedEngine(
        {17: AccountAutoTradingOutcome(account_id=17, buy_count=1, sell_count=0)},
        events,
    )

    def build_engine(_: UUID) -> AutomaticInvocationEngine:
        """Provide the initial execution and fail if a changed request reaches it."""
        events.append("build_engine")
        return engine

    original_request = _request()
    changed_request = _request(trade_date=_TRADE_DATE)
    assert original_request.content_hash != changed_request.content_hash

    use_case.execute(
        original_request,
        resolve_scope=lambda: _scope(),
        authorize_scope=lambda _: None,
        build_engine=build_engine,
    )
    claims_before_retry = len(repository.claim_requests)
    build_calls_before_retry = len([event for event in events if event == "build_engine"])

    with pytest.raises(AutoTradingInvocationConflict):
        use_case.execute(
            changed_request,
            resolve_scope=lambda: pytest.fail("conflicting input must not resolve a new scope"),
            authorize_scope=lambda _: pytest.fail(
                "conflicting input must not authorize a new scope"
            ),
            build_engine=lambda _: pytest.fail("conflicting input must not construct an engine"),
        )

    assert len(repository.claim_requests) == claims_before_retry
    assert len([event for event in events if event == "build_engine"]) == build_calls_before_retry
    assert engine.calls == [(_TRADE_DATE, [17])]


def test_engine_setup_failure_releases_preparation_and_exact_retry_can_start() -> None:
    """Only a pre-start construction failure is releasable for the same request."""
    repository = _MemoryInvocationRepository()
    use_case = ExecuteAutomaticInvocation(repository)
    frozen_scope = _scope()
    events = repository.events
    request = _request()
    resolved_scopes: list[FrozenAutoTradingScope] = []
    engine = _ScriptedEngine(
        {17: AccountAutoTradingOutcome(account_id=17, buy_count=1, sell_count=0)},
        events,
    )
    build_attempts = 0

    def resolve_scope() -> FrozenAutoTradingScope:
        """Count initial default resolution without changing the saved scope."""
        events.append("resolve_scope")
        resolved_scopes.append(frozen_scope)
        return frozen_scope

    def fail_setup(_: UUID) -> AutomaticInvocationEngine:
        """Fail before engine entry to exercise the preparation release boundary."""
        nonlocal build_attempts
        events.append("build_engine")
        build_attempts += 1
        raise RuntimeError("test-owned engine setup failure")

    with pytest.raises(RuntimeError, match="engine setup failure"):
        use_case.execute(
            request,
            resolve_scope=resolve_scope,
            authorize_scope=lambda _: None,
            build_engine=fail_setup,
        )

    assert len(repository.release_calls) == 1
    assert repository.started_calls == []
    assert engine.calls == []

    def retry_setup(_: UUID) -> AutomaticInvocationEngine:
        """Return the engine only after the exact prior request reacquires prep."""
        nonlocal build_attempts
        events.append("build_engine")
        build_attempts += 1
        return engine

    result = use_case.execute(
        request,
        resolve_scope=lambda: pytest.fail("retry must retain the originally frozen scope"),
        authorize_scope=lambda _: None,
        build_engine=retry_setup,
    )

    assert resolved_scopes == [frozen_scope]
    assert build_attempts == 2
    assert len(repository.release_calls) == 1
    assert len(repository.claim_requests) == 2
    assert len(repository.started_calls) == 1
    assert engine.calls == [(_TRADE_DATE, [17])]
    assert result.replayed is False
    assert result.outcome.buy_count == 1


def test_started_engine_exception_is_indeterminate_and_never_reentered() -> None:
    """A run exception keeps the started claim and the next call reads its result."""
    repository = _MemoryInvocationRepository()
    use_case = ExecuteAutomaticInvocation(repository)
    events = repository.events
    request = _request()
    engine = _ScriptedEngine(
        {},
        events,
        run_error=RuntimeError("test-owned execution failure after start"),
    )
    build_calls: list[UUID] = []

    def build_engine(invocation_id: UUID) -> AutomaticInvocationEngine:
        """Count engine entry construction, not a second execution opportunity."""
        events.append("build_engine")
        build_calls.append(invocation_id)
        return engine

    first = use_case.execute(
        request,
        resolve_scope=lambda: _scope(),
        authorize_scope=lambda _: None,
        build_engine=build_engine,
    )
    replay = use_case.execute(
        request,
        resolve_scope=lambda: pytest.fail("a saved invocation must not resolve new defaults"),
        authorize_scope=lambda _: None,
        build_engine=lambda _: pytest.fail("a started run must not re-enter the engine"),
    )

    issue = first.outcome.accounts[0].issues[0]
    assert first.replayed is False
    assert issue.code == "EXECUTION_OUTCOME_UNKNOWN"
    assert issue.effects_indeterminate is True
    assert issue.kind is AutoTradingIssueKind.FAILED
    assert replay.replayed is True
    assert replay.outcome == first.outcome
    assert build_calls == [_INVOCATION_ID]
    assert engine.calls == [(_TRADE_DATE, [17])]
    assert repository.release_calls == []
    assert len(repository.started_calls) == 1
    assert len(repository.finish_calls) == 1


def test_empty_frozen_scope_finishes_noop_without_constructing_an_engine() -> None:
    """An authorized empty scope is a no-op and does not build external services."""
    repository = _MemoryInvocationRepository()
    use_case = ExecuteAutomaticInvocation(repository)
    events = repository.events
    empty_scope = _scope(account_ids=())

    result = use_case.execute(
        _request(),
        resolve_scope=lambda: empty_scope,
        authorize_scope=lambda scope: events.append(
            "authorize_empty_scope" if scope.account_ids == () else "authorize_other_scope"
        ),
        build_engine=lambda _: pytest.fail("empty scope must not construct the engine"),
    )

    assert result.scope == empty_scope
    assert result.outcome.requested_account_ids == ()
    assert result.outcome.outcome is AutoTradingOutcome.NOOP
    assert result.outcome.stored == 0
    assert repository.started_calls == [(_INVOCATION_ID, _FIRST_CLAIM_TOKEN)]
    assert len(repository.finish_calls) == 1
    assert "authorize_empty_scope" in events
    assert "build_engine" not in events
    assert "engine_run" not in events


def test_finalization_failure_preserves_confirmed_buy_sell_but_marks_stored_unknown() -> None:
    """A failed result write cannot erase confirmed trades or claim stored certainty."""
    repository = _MemoryInvocationRepository()
    repository.fail_finish = True
    use_case = ExecuteAutomaticInvocation(repository)
    events = repository.events
    engine = _ScriptedEngine(
        {17: AccountAutoTradingOutcome(account_id=17, buy_count=2, sell_count=3)},
        events,
    )

    result = use_case.execute(
        _request(),
        resolve_scope=lambda: _scope(),
        authorize_scope=lambda _: None,
        build_engine=lambda _: engine,
    )

    account = result.outcome.accounts[0]
    assert (account.buy_count, account.sell_count, account.confirmed_trade_count) == (2, 3, 5)
    assert account.stored is None
    assert account.counts_unavailable is True
    assert account.issues[-1].code == "EXECUTION_OUTCOME_UNKNOWN"
    assert account.issues[-1].stage == "invocation_result"
    assert account.issues[-1].kind is AutoTradingIssueKind.FAILED
    assert account.issues[-1].effects_indeterminate is True
    assert result.outcome.buy_count == 2
    assert result.outcome.sell_count == 3
    assert result.outcome.confirmed_trade_count == 5
    assert result.outcome.stored is None
    assert result.outcome.counts_unavailable is True
    assert repository.release_calls == []
    assert len(repository.started_calls) == 1
    assert len(repository.finish_calls) == 1


def test_readback_reauthorizes_frozen_scope_before_returning_saved_result() -> None:
    """Revoked access raises before the prior result or another claim is exposed."""
    repository = _MemoryInvocationRepository()
    use_case = ExecuteAutomaticInvocation(repository)
    request = _request()
    frozen_scope = _scope(account_ids=(17, 22))
    events = repository.events
    engine = _ScriptedEngine(
        {
            17: AccountAutoTradingOutcome(account_id=17, buy_count=1, sell_count=0),
            22: AccountAutoTradingOutcome(account_id=22, buy_count=0, sell_count=1),
        },
        events,
    )
    authorized_scopes: list[FrozenAutoTradingScope] = []

    def authorize_scope(scope: FrozenAutoTradingScope) -> None:
        """Revoke access only on the readback authorization attempt."""
        events.append("authorize_scope")
        authorized_scopes.append(scope)
        if len(authorized_scopes) == 2:
            raise AuthorizationError("该账户范围的访问权限已撤销")

    first = use_case.execute(
        request,
        resolve_scope=lambda: frozen_scope,
        authorize_scope=authorize_scope,
        build_engine=lambda _: engine,
    )
    claims_before_readback = len(repository.claim_requests)

    with pytest.raises(AuthorizationError, match="访问权限已撤销"):
        use_case.execute(
            request,
            resolve_scope=lambda: pytest.fail("readback must not choose a new default scope"),
            authorize_scope=authorize_scope,
            build_engine=lambda _: pytest.fail("readback must not reconstruct the engine"),
        )

    assert first.outcome.confirmed_trade_count == 2
    assert authorized_scopes == [frozen_scope, frozen_scope]
    assert len(repository.claim_requests) == claims_before_readback
    assert engine.calls == [(_TRADE_DATE, [17, 22])]
    assert repository.events[-2:] == ["find_scope", "authorize_scope"]
