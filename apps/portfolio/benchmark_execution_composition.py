"""Authenticated Portfolio benchmark issuance, revocation and transaction-bound current reads."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from uuid import UUID

from rest_framework.request import Request

from apps.portfolio.application.benchmark_daily_sources import (
    BenchmarkGovernanceActor,
    DayOwner,
    benchmark_day_sources,
)
from apps.portfolio.benchmark_daily_valuation_composition import get_current_benchmark_valuation
from apps.portfolio.domain.benchmark_approval_history import (
    BenchmarkApprovalConflict,
    BenchmarkApprovalDenied,
    BenchmarkApprovalEvent,
    BenchmarkApprovalHistory,
    BenchmarkApprovalUnavailable,
    benchmark_digest,
    benchmark_manifest,
)
from apps.portfolio.domain.benchmark_execution_approval import (
    BenchmarkExecutionReceipt,
    BenchmarkScope,
    BenchmarkValuationFacts,
)
from apps.portfolio.infrastructure.benchmark_approval_configuration import (
    configuration_valid_until,
    lock_benchmark_configuration,
    valuation_owner_selector,
)
from apps.portfolio.infrastructure.benchmark_approval_repository import (
    _append_approval_event,
    current_database_time,
    find_event,
    lock_approval_scope,
    read_approval_history,
    require_approval_transaction,
)


@dataclass(frozen=True, slots=True)
class _Source:
    valuation: BenchmarkValuationFacts
    seal: str
    manifest: str
    valid_until: datetime


def _owner(scope: BenchmarkScope, using: str) -> DayOwner:
    owner = benchmark_day_sources().owner(
        namespace=scope.account_namespace,
        account_id=scope.account_id,
        user_id=scope.owner_user_id,
        using=using,
    )
    if owner is None or owner.scope != scope:
        raise BenchmarkApprovalUnavailable("benchmark_current_account_scope_unavailable")
    return owner


def _operator(user_id: int, scope: BenchmarkScope, using: str) -> BenchmarkGovernanceActor:
    actor = benchmark_day_sources().governance_actor(
        user_id=user_id, owner_user_id=scope.owner_user_id, using=using
    )
    if actor is None:
        raise BenchmarkApprovalDenied("benchmark_scope_access_denied")
    return actor


def _source(valuation_id: UUID, valuation_version: int, using: str) -> _Source:
    if (
        type(valuation_id) is not UUID
        or type(valuation_version) is not int
        or valuation_version < 1
    ):
        raise BenchmarkApprovalUnavailable("benchmark_invalid_valuation_selector")
    facts = get_current_benchmark_valuation(
        valuation_id=valuation_id, valuation_version=valuation_version, using=using
    )
    if type(facts) is not BenchmarkValuationFacts or (
        facts.valuation_id,
        facts.valuation_version,
    ) != (valuation_id, valuation_version):
        raise BenchmarkApprovalUnavailable("benchmark_current_daily_valuation_unavailable")
    owner = _owner(facts.scope, using)
    lock_benchmark_configuration(using)
    now = current_database_time(using)
    expires = configuration_valid_until(facts=facts, as_of=now, using=using)
    if expires is None or not facts.recorded_at <= now < min(
        expires, facts.valid_until, owner.valid_until
    ):
        raise BenchmarkApprovalUnavailable("benchmark_current_configuration_unavailable")
    source = {
        "valuation": asdict(facts),
        "physical_row_pk": owner.physical_id,
        "identity": [owner.source_id, owner.source_version, owner.identity_hash],
        "account_policy": [owner.policy_id, owner.policy_version, owner.policy_hash],
    }
    return _Source(
        facts,
        benchmark_digest(source),
        benchmark_manifest(source),
        min(expires, facts.valid_until, owner.valid_until),
    )


def _new_event(
    *,
    history: BenchmarkApprovalHistory,
    request_id: UUID,
    action: str,
    scope: BenchmarkScope,
    valuation_id: UUID,
    valuation_version: int,
    seal: str,
    manifest: str,
    valid_until: datetime,
    actor: BenchmarkGovernanceActor,
    using: str,
) -> BenchmarkApprovalEvent:
    previous = history.head
    event = BenchmarkApprovalEvent(
        1 if previous is None else previous.sequence + 1,
        request_id,
        action,
        scope,
        valuation_id,
        valuation_version,
        seal,
        actor.user_id,
        actor.role,
        current_database_time(using),
        valid_until,
        "" if previous is None else previous.content_hash,
        manifest,
    )
    history.accept(event)
    _append_approval_event(event=event, using=using)
    return event


@contextmanager
def _authenticated_change(request: Request, using: str) -> Iterator[tuple[int, list[datetime]]]:
    deadlines: list[datetime] = []

    def recheck_expiry() -> None:
        if deadlines and current_database_time(using) >= min(deadlines):
            raise BenchmarkApprovalUnavailable("benchmark_expired_before_commit")

    with benchmark_day_sources().signer(
        request=request, using=using, before_commit=recheck_expiry
    ) as user_id:
        yield user_id, deadlines


def submit_benchmark_approval(
    *,
    request: Request,
    request_id: UUID,
    valuation_id: UUID,
    valuation_version: int,
    using: str = "default",
) -> BenchmarkApprovalEvent:
    """Submit an exact server-resolved daily valuation from the authenticated operator."""
    with _authenticated_change(request, using) as (user_id, deadlines):
        require_approval_transaction(using)
        candidate_owner = valuation_owner_selector(valuation_id, using)
        if (
            candidate_owner is None
            or benchmark_day_sources().governance_actor(
                user_id=user_id, owner_user_id=candidate_owner, using=using
            )
            is None
        ):
            raise BenchmarkApprovalDenied("benchmark_scope_access_denied")
        src = _source(valuation_id, valuation_version, using)
        deadlines.append(src.valid_until)
        scope = src.valuation.scope
        actor = _operator(user_id, scope, using)
        lock_approval_scope(scope=scope, using=using, write=True)
        history = read_approval_history(scope=scope, using=using)
        first = find_event(request_id=request_id, action="submitted", using=using)
        if first is not None:
            if (
                first != history.pending
                or first.actor_user_id != actor.user_id
                or first.source_seal != src.seal
            ):
                raise BenchmarkApprovalConflict("benchmark_submission_identity_conflict")
            return first
        return _new_event(
            history=history,
            request_id=request_id,
            action="submitted",
            scope=scope,
            valuation_id=valuation_id,
            valuation_version=valuation_version,
            seal=src.seal,
            manifest=src.manifest,
            valid_until=src.valid_until,
            actor=actor,
            using=using,
        )


def _authorized_subject(
    user_id: int, request_id: UUID, using: str
) -> tuple[BenchmarkApprovalEvent, BenchmarkGovernanceActor]:
    subject = find_event(request_id=request_id, action="submitted", using=using)
    if subject is None:
        raise BenchmarkApprovalDenied("benchmark_scope_access_denied")
    actor = _operator(user_id, subject.scope, using)
    _owner(subject.scope, using)
    return subject, actor


def approve_benchmark(
    *, request: Request, request_id: UUID, expected_submission_hash: str, using: str = "default"
) -> BenchmarkApprovalEvent:
    """Approve one still-current submission with a separately authenticated staff identity."""
    with _authenticated_change(request, using) as (user_id, deadlines):
        require_approval_transaction(using)
        subject, actor = _authorized_subject(user_id, request_id, using)
        if (
            subject.content_hash != expected_submission_hash
            or actor.user_id == subject.actor_user_id
        ):
            raise BenchmarkApprovalConflict("benchmark_independent_current_approval_required")
        src = _source(subject.valuation_id, subject.valuation_version, using)
        deadlines.append(src.valid_until)
        if (src.seal, src.valid_until) != (subject.source_seal, subject.valid_until):
            raise BenchmarkApprovalConflict("benchmark_source_changed")
        requester = benchmark_day_sources().governance_actor(
            user_id=subject.actor_user_id,
            owner_user_id=subject.scope.owner_user_id,
            using=using,
        )
        if requester is None or requester.role != subject.actor_role:
            raise BenchmarkApprovalUnavailable("benchmark_submitter_authority_changed")
        lock_approval_scope(scope=subject.scope, using=using, write=True)
        history = read_approval_history(scope=subject.scope, using=using)
        if (
            history.active is not None
            and history.active.request_id == request_id
            and history.active.actor_user_id == actor.user_id
            and history.active.actor_role == actor.role
        ):
            return history.active
        if history.pending != subject:
            raise BenchmarkApprovalConflict("benchmark_submission_replaced")
        return _new_event(
            history=history,
            request_id=request_id,
            action="approved",
            scope=subject.scope,
            valuation_id=subject.valuation_id,
            valuation_version=subject.valuation_version,
            seal=src.seal,
            manifest=src.manifest,
            valid_until=src.valid_until,
            actor=actor,
            using=using,
        )


def revoke_benchmark(
    *, request: Request, request_id: UUID, expected_approval_hash: str, using: str = "default"
) -> BenchmarkApprovalEvent:
    """Withdraw an exact approval even when its underlying valuation has expired."""
    with _authenticated_change(request, using) as (user_id, _deadlines):
        require_approval_transaction(using)
        subject, actor = _authorized_subject(user_id, request_id, using)
        lock_approval_scope(scope=subject.scope, using=using, write=True)
        history = read_approval_history(scope=subject.scope, using=using)
        approval = find_event(request_id=request_id, action="approved", using=using)
        if approval is None or approval.content_hash != expected_approval_hash:
            raise BenchmarkApprovalConflict("benchmark_approval_replaced")
        replay = find_event(request_id=request_id, action="revoked", using=using)
        if replay is not None and replay.actor_user_id == actor.user_id:
            return replay
        if history.active != approval:
            raise BenchmarkApprovalConflict("benchmark_approval_replaced")
        return _new_event(
            history=history,
            request_id=request_id,
            action="revoked",
            scope=subject.scope,
            valuation_id=approval.valuation_id,
            valuation_version=approval.valuation_version,
            seal=approval.source_seal,
            manifest=approval.source_manifest,
            valid_until=approval.valid_until,
            actor=actor,
            using=using,
        )


def select_current_benchmark_approval(
    *,
    account_namespace: str,
    account_id: str,
    owner_user_id: int,
    tenant_id: str,
    owner_id: str,
    using: str,
) -> BenchmarkExecutionReceipt | None:
    """Hold the latest independent approval and all its current sources through the caller's transaction."""
    scope = BenchmarkScope(account_namespace, account_id, owner_user_id, tenant_id, owner_id)
    lock_approval_scope(scope=scope, using=using, write=False)
    history = read_approval_history(scope=scope, using=using)
    active, subject = history.active, history.active_submission
    if active is None or active.scope != scope or subject is None:
        return None
    try:
        src = _source(active.valuation_id, active.valuation_version, using)
    except BenchmarkApprovalUnavailable:
        return None
    for event in (subject, active):
        actor = benchmark_day_sources().governance_actor(
            user_id=event.actor_user_id, owner_user_id=owner_user_id, using=using
        )
        if actor is None or actor.role != event.actor_role:
            return None
    if (
        src.seal != active.source_seal
        or src.valid_until != active.valid_until
        or not active.recorded_at <= current_database_time(using) < active.valid_until
    ):
        return None
    return BenchmarkExecutionReceipt(
        active.request_id, active.sequence, active.content_hash, src.valuation, active.valid_until
    )


def read_current_benchmark_approval(
    *,
    approval_id: UUID,
    expected_version: int,
    expected_content_hash: str,
    account_namespace: str,
    account_id: str,
    owner_user_id: int,
    tenant_id: str,
    owner_id: str,
    using: str,
) -> BenchmarkExecutionReceipt | None:
    """Return the exact current approval matching all supplied immutable selectors."""
    if (
        type(approval_id) is not UUID
        or type(expected_version) is not int
        or expected_version < 1
        or type(expected_content_hash) is not str
        or len(expected_content_hash) != 64
    ):
        return None
    receipt = select_current_benchmark_approval(
        account_namespace=account_namespace,
        account_id=account_id,
        owner_user_id=owner_user_id,
        tenant_id=tenant_id,
        owner_id=owner_id,
        using=using,
    )
    if receipt is None or (receipt.approval_id, receipt.approval_version, receipt.content_hash) != (
        approval_id,
        expected_version,
        expected_content_hash,
    ):
        return None
    return receipt


def read_benchmark_submission_for_review(
    *, request: Request, request_id: UUID, using: str = "default"
) -> tuple[BenchmarkApprovalEvent, str]:
    """Resolve the signed source manifest for the current account's authorized reviewer."""
    with benchmark_day_sources().approval_reviewer(request=request, using=using) as user_id:
        require_approval_transaction(using)
        subject, _actor = _authorized_subject(user_id, request_id, using)
        lock_approval_scope(scope=subject.scope, using=using, write=False)
        history = read_approval_history(scope=subject.scope, using=using)
        if history.pending == subject:
            try:
                current = _source(subject.valuation_id, subject.valuation_version, using)
            except BenchmarkApprovalUnavailable:
                return subject, "source_unavailable"
            return subject, "pending" if current.seal == subject.source_seal else "source_changed"
        if history.active is not None and history.active.request_id == request_id:
            return subject, "approved"
        revoked = find_event(request_id=request_id, action="revoked", using=using)
        return subject, "revoked" if revoked is not None else "replaced"
