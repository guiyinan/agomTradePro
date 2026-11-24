"""PostgreSQL transactional scope fences and tamper-evident Portfolio decisions."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from uuid import UUID

from django.core.signing import BadSignature, Signer
from django.db import IntegrityError, connections, transaction

from apps.portfolio.domain.benchmark_approval_history import (
    BenchmarkApprovalConflict,
    BenchmarkApprovalEvent,
    BenchmarkApprovalHistory,
    BenchmarkApprovalUnavailable,
    benchmark_scope_key,
)
from apps.portfolio.domain.benchmark_execution_approval import BenchmarkScope

from .benchmark_approval_models import BenchmarkApprovalEventModel, _claim_approval_event

_SIGNING_SALT = "portfolio.benchmark.execution-approval.event.v1"


def require_approval_transaction(using: str) -> None:
    """Require the same PostgreSQL read-committed transaction through the final write."""
    db = connections[using]
    if db.vendor != "postgresql" or not db.in_atomic_block:
        raise BenchmarkApprovalUnavailable("benchmark_requires_postgresql_transaction")
    with db.cursor() as c:
        c.execute("SHOW transaction_isolation")
        if c.fetchone() != ("read committed",):
            raise BenchmarkApprovalUnavailable("benchmark_requires_read_committed")


def lock_approval_scope(*, scope: BenchmarkScope, using: str, write: bool) -> None:
    """Share a stable scope lock with every SQL insertion and guard concurrent truncate."""
    require_approval_transaction(using)
    key = "portfolio.benchmark.approval:" + benchmark_scope_key(scope)
    with connections[using].cursor() as c:
        c.execute("LOCK TABLE portfolio_benchmark_approval_event IN ACCESS SHARE MODE NOWAIT")
        c.execute("""
            SELECT count(*) FROM pg_catalog.pg_trigger
            WHERE tgrelid = 'portfolio_benchmark_approval_event'::regclass
              AND tgname IN ('pf_bm_event_guard','pf_bm_event_truncate') AND tgenabled='A'
        """)
        if c.fetchone() != (2,):
            raise BenchmarkApprovalUnavailable("benchmark_ledger_fences_unavailable")
        func = "pg_try_advisory_xact_lock" if write else "pg_try_advisory_xact_lock_shared"
        c.execute(f"SELECT {func}(hashtextextended(%s, 0))", (key,))
        if c.fetchone() != (True,):
            raise BenchmarkApprovalUnavailable("benchmark_scope_busy")


def current_database_time(using: str) -> datetime:
    """Obtain a clock after acquiring the source and issuance locks."""
    with connections[using].cursor() as c:
        c.execute("SELECT clock_timestamp()")
        result: datetime = c.fetchone()[0]
    return result


def _restore(row: BenchmarkApprovalEventModel) -> BenchmarkApprovalEvent:
    scope = BenchmarkScope(
        row.account_namespace, row.account_id, row.owner_user_id, row.tenant_id, row.owner_id
    )
    event = BenchmarkApprovalEvent(
        row.sequence,
        row.request_id,
        row.action,
        scope,
        row.valuation_id,
        row.valuation_version,
        row.source_seal,
        row.actor_user_id,
        row.actor_role,
        row.recorded_at,
        row.valid_until,
        row.previous_hash,
        row.source_manifest,
    )
    try:
        signed_hash = Signer(salt=_SIGNING_SALT).unsign(row.signature)
    except BadSignature as error:
        raise BenchmarkApprovalConflict("benchmark_event_signature_invalid") from error
    if (
        signed_hash != event.content_hash
        or row.content_hash != signed_hash
        or benchmark_scope_key(scope) != row.scope_key
    ):
        raise BenchmarkApprovalConflict("benchmark_event_content_invalid")
    return event


def find_event(*, request_id: UUID, action: str, using: str) -> BenchmarkApprovalEvent | None:
    """Resolve an immutable event identity before acquiring its logical scope lock."""
    row = (
        BenchmarkApprovalEventModel._default_manager.using(using)
        .filter(request_id=request_id, action=action)
        .first()
    )
    return None if row is None else _restore(row)


def read_approval_history(*, scope: BenchmarkScope, using: str) -> BenchmarkApprovalHistory:
    """Validate a complete bounded-to-account event chain against independent signatures."""
    result = BenchmarkApprovalHistory()
    rows = (
        BenchmarkApprovalEventModel._default_manager.using(using)
        .filter(scope_key=benchmark_scope_key(scope))
        .order_by("sequence")
    )
    for row in rows:
        result.accept(_restore(row))
    return result


def _append_approval_event(*, event: BenchmarkApprovalEvent, using: str) -> None:
    """Persist one signed transition inside the scope's original transaction."""
    fields = asdict(event)
    fields.pop("scope")
    row = BenchmarkApprovalEventModel(
        **fields,
        **asdict(event.scope),
        scope_key=benchmark_scope_key(event.scope),
        content_hash=event.content_hash,
        signature=Signer(salt=_SIGNING_SALT).sign(event.content_hash),
    )
    try:
        with transaction.atomic(using=using), _claim_approval_event(row):
            row.save(using=using, force_insert=True)
    except IntegrityError as error:
        raise BenchmarkApprovalConflict("benchmark_event_identity_conflict") from error
