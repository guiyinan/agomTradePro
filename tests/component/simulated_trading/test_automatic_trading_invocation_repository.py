"""Native PostgreSQL checks for caller-keyed automatic run persistence."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from django.db import close_old_connections, connection, connections
from django.utils import timezone

from apps.simulated_trading.application.automatic_invocation import (
    AutoTradingInvocationConflict,
    AutoTradingInvocationRequest,
    AutoTradingInvocationUnavailable,
    FrozenAutoTradingScope,
)
from apps.simulated_trading.domain.auto_trading_outcomes import (
    AccountAutoTradingOutcome,
    AutoTradingBatchOutcome,
)
from apps.simulated_trading.infrastructure.automatic_trading_invocation_repository import (
    DjangoAutoTradingInvocationRepository,
)
from apps.simulated_trading.infrastructure.models import AutomaticTradingInvocationModel
from tests.support.account_authority_generation_flush import (  # noqa: F401
    preserve_account_authority_generation,
)
from tests.support.native_postgres_database import assert_native_postgres_test_database

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def _require_native_postgres(django_db_use_migrations: bool) -> None:
    """Run storage and concurrency claims only against the configured test database."""

    if not django_db_use_migrations:
        pytest.skip("automatic invocation repository proof requires migrations")
    if connection.vendor != "postgresql":
        pytest.skip("automatic invocation claim races require native PostgreSQL")
    assert_native_postgres_test_database()


def _request(*, invocation_key: str | None = None) -> AutoTradingInvocationRequest:
    """Build one unique exact caller request with omission preserved."""

    return AutoTradingInvocationRequest(
        namespace=f"test-owner-{uuid4().hex}",
        invocation_key=invocation_key or f"run-{uuid4().hex}",
        trade_date=None,
        requested_account_ids=None,
    )


def _scope() -> FrozenAutoTradingScope:
    """Build an ordered, resolved scope for one run record."""

    return FrozenAutoTradingScope(date(2026, 10, 19), (81, 73))


def _outcome(scope: FrozenAutoTradingScope) -> AutoTradingBatchOutcome:
    """Build a strict no-op result matching the exact frozen account order."""

    accounts = tuple(
        AccountAutoTradingOutcome(account_id, 0, 0) for account_id in scope.account_ids
    )
    return AutoTradingBatchOutcome(scope.account_ids, accounts)


def _parallel_claim(
    request: AutoTradingInvocationRequest,
    scope: FrozenAutoTradingScope,
    barrier: Barrier,
) -> tuple[bool, UUID, int]:
    """Race two real database connections for one unique invocation key."""

    close_old_connections()
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SET statement_timeout = '10000ms'")
            cursor.execute("SELECT pg_backend_pid()")
            backend_row = cursor.fetchone()
        assert backend_row is not None
        backend_pid = int(backend_row[0])
        barrier.wait(timeout=10)
        claim = DjangoAutoTradingInvocationRepository().claim(request, scope)
        return claim.acquired, claim.invocation_id, backend_pid
    finally:
        connections["default"].close()


def test_concurrent_claims_acquire_one_preparation_for_one_run_identity() -> None:
    """A unique-key race creates one UUID and grants only one caller the token."""

    request = _request()
    scope = _scope()
    barrier = Barrier(2, timeout=10)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(_parallel_claim, request, scope, barrier),
            executor.submit(_parallel_claim, request, scope, barrier),
        ]
        results = [future.result(timeout=20) for future in futures]

    assert sum(acquired for acquired, _, _ in results) == 1
    assert len({invocation_id for _, invocation_id, _ in results}) == 1
    assert len({backend_pid for _, _, backend_pid in results}) == 2
    row = AutomaticTradingInvocationModel.objects.get(
        namespace=request.namespace,
        invocation_key=request.invocation_key,
    )
    assert row.state == AutomaticTradingInvocationModel.STATE_PREPARING
    assert isinstance(row.claim_token, UUID)
    assert row.request_hash == request.content_hash
    assert row.request_payload == request.to_payload()
    assert row.trade_date == scope.trade_date
    assert row.account_ids == list(scope.account_ids)
    assert timezone.is_aware(row.created_at)
    assert timezone.is_aware(row.updated_at)


def test_setup_release_requires_exact_token_and_started_run_never_reenters() -> None:
    """Only pre-engine setup can release; started work is permanently non-acquirable."""

    repository = DjangoAutoTradingInvocationRepository()
    request = _request()
    first_scope = _scope()
    first = repository.claim(request, first_scope)
    assert first.acquired is True
    pending = repository.claim(request, first_scope)
    assert pending.acquired is False
    assert pending.invocation_id == first.invocation_id
    assert pending.claim_token == first.claim_token
    assert pending.outcome is None

    with pytest.raises(AutoTradingInvocationUnavailable):
        repository.release_preparation(
            invocation_id=first.invocation_id,
            claim_token=uuid4(),
        )
    row = AutomaticTradingInvocationModel.objects.get(invocation_id=first.invocation_id)
    assert row.state == AutomaticTradingInvocationModel.STATE_PREPARING
    assert row.claim_token == first.claim_token

    repository.release_preparation(
        invocation_id=first.invocation_id,
        claim_token=first.claim_token,
    )
    changed_resolved_scope = FrozenAutoTradingScope(date(2026, 10, 20), (22,))
    retry = repository.claim(request, changed_resolved_scope)
    assert retry.acquired is True
    assert retry.invocation_id == first.invocation_id
    assert retry.claim_token != first.claim_token
    assert retry.scope == first_scope

    with pytest.raises(AutoTradingInvocationUnavailable):
        repository.mark_started(
            invocation_id=retry.invocation_id,
            claim_token=first.claim_token,
        )
    repository.mark_started(
        invocation_id=retry.invocation_id,
        claim_token=retry.claim_token,
    )
    started_row = AutomaticTradingInvocationModel.objects.get(invocation_id=retry.invocation_id)
    assert started_row.started_at is not None
    assert timezone.is_aware(started_row.started_at)
    assert timezone.is_aware(started_row.updated_at)
    read_only = repository.claim(request, changed_resolved_scope)
    assert read_only.acquired is False
    assert read_only.invocation_id == retry.invocation_id
    assert read_only.scope == first_scope
    assert read_only.outcome is None
    assert read_only.claim_token == retry.claim_token

    with pytest.raises(AutoTradingInvocationUnavailable):
        repository.release_preparation(
            invocation_id=retry.invocation_id,
            claim_token=retry.claim_token,
        )
    with pytest.raises(AutoTradingInvocationUnavailable):
        repository.mark_started(
            invocation_id=retry.invocation_id,
            claim_token=retry.claim_token,
        )


def test_finished_run_replays_strict_result_and_rejects_corrupt_payload() -> None:
    """Finished outcomes replay unchanged and never downgrade into a new claim."""

    repository = DjangoAutoTradingInvocationRepository()
    request = _request()
    scope = _scope()
    claim = repository.claim(request, scope)
    repository.mark_started(invocation_id=claim.invocation_id, claim_token=claim.claim_token)
    expected = _outcome(scope)
    wrong_scope_result = AutoTradingBatchOutcome(
        (22,),
        (AccountAutoTradingOutcome(22, 0, 0),),
    )
    with pytest.raises(AutoTradingInvocationUnavailable, match="frozen account scope"):
        repository.finish(
            invocation_id=claim.invocation_id,
            claim_token=claim.claim_token,
            outcome=wrong_scope_result,
        )
    started_row = AutomaticTradingInvocationModel.objects.get(invocation_id=claim.invocation_id)
    assert started_row.state == AutomaticTradingInvocationModel.STATE_STARTED
    assert started_row.outcome_payload is None
    repository.finish(
        invocation_id=claim.invocation_id,
        claim_token=claim.claim_token,
        outcome=expected,
    )

    replay = repository.claim(
        request,
        FrozenAutoTradingScope(date(2026, 10, 20), (22,)),
    )
    assert replay.acquired is False
    assert replay.invocation_id == claim.invocation_id
    assert replay.scope == scope
    assert repository.find_scope(request) == scope
    changed_request = AutoTradingInvocationRequest(
        namespace=request.namespace,
        invocation_key=request.invocation_key,
        trade_date=date(2026, 10, 20),
        requested_account_ids=None,
    )
    with pytest.raises(AutoTradingInvocationConflict):
        repository.find_scope(changed_request)
    assert replay.outcome == expected
    assert replay.outcome is not None
    assert replay.outcome.to_payload() == expected.to_payload()

    row = AutomaticTradingInvocationModel.objects.get(invocation_id=claim.invocation_id)
    assert row.request_hash == request.content_hash
    assert row.request_payload == request.to_payload()
    assert row.trade_date == scope.trade_date
    assert row.account_ids == list(scope.account_ids)
    corrupt_payload = expected.to_payload()
    corrupt_payload["buy_count"] = corrupt_payload["buy_count"] + 1
    AutomaticTradingInvocationModel.objects.filter(pk=row.pk).update(
        outcome_payload=corrupt_payload
    )
    with pytest.raises(AutoTradingInvocationUnavailable, match="strict validation"):
        repository.claim(request, scope)
    row.refresh_from_db()
    assert row.state == AutomaticTradingInvocationModel.STATE_FINISHED
    assert row.finished_at is not None
    assert timezone.is_aware(row.finished_at)
    assert timezone.is_aware(row.updated_at)
