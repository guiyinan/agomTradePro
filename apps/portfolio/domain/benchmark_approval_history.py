"""Version and independence rules for a single canonical account's benchmark ledger."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from .benchmark_execution_approval import BenchmarkScope


def _encode(value: object) -> str:
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValueError("naive benchmark timestamp")
        return value.astimezone(UTC).isoformat()
    if isinstance(value, (UUID, date)):
        return str(value)
    raise TypeError("invalid canonical benchmark field")


def benchmark_manifest(value: object) -> str:
    """Preserve the exact canonical upstream IDs, versions, hashes and validity windows."""
    return json.dumps(
        value, default=_encode, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def benchmark_digest(value: object) -> str:
    """Seal a closed versioned payload with normalized UTC instants."""
    return hashlib.sha256(benchmark_manifest(value).encode("utf-8")).hexdigest()


def benchmark_scope_key(scope: BenchmarkScope) -> str:
    """Keep all owners and revisions of the same physical namespace identity in one chain."""
    return benchmark_digest([scope.account_namespace, scope.account_id])


class BenchmarkApprovalConflict(ValueError):
    """The caller's expected state, evidence or signatory no longer matches."""


class BenchmarkApprovalUnavailable(ValueError):
    """A current Portfolio or Account source is missing or expired."""


class BenchmarkApprovalDenied(ValueError):
    """The authenticated operator cannot govern this specific account."""


@dataclass(frozen=True, slots=True)
class BenchmarkApprovalEvent:
    """Signed event header containing the complete source commitment and audit identity."""

    sequence: int
    request_id: UUID
    action: str
    scope: BenchmarkScope
    valuation_id: UUID
    valuation_version: int
    source_seal: str
    actor_user_id: int
    actor_role: str
    recorded_at: datetime
    valid_until: datetime
    previous_hash: str
    source_manifest: str

    @property
    def content_hash(self) -> str:
        """Return the content address of this exact event, including its predecessor."""
        return benchmark_digest({"schema": "portfolio.benchmark.approval.v1", **asdict(self)})


@dataclass(slots=True)
class BenchmarkApprovalHistory:
    """Reduce a verified account chain without ever falling back to an older approval."""

    head: BenchmarkApprovalEvent | None = None
    pending: BenchmarkApprovalEvent | None = None
    active: BenchmarkApprovalEvent | None = None
    active_submission: BenchmarkApprovalEvent | None = None

    def accept(self, event: BenchmarkApprovalEvent) -> None:
        """Validate predecessor, separate actors and the exact sealed source at each step."""
        prior = self.head
        if (
            event.sequence != (1 if prior is None else prior.sequence + 1)
            or event.previous_hash != ("" if prior is None else prior.content_hash)
            or (prior is not None and event.recorded_at < prior.recorded_at)
        ):
            raise BenchmarkApprovalConflict("benchmark_chain_not_current")
        if event.action == "submitted":
            if event.recorded_at >= event.valid_until:
                raise BenchmarkApprovalConflict("benchmark_submission_expired")
            self.pending = event
        elif event.action == "approved":
            subject = self.pending
            if subject is None or not _same_proposal(subject, event):
                raise BenchmarkApprovalConflict("benchmark_submission_replaced")
            if (
                event.actor_user_id == subject.actor_user_id
                or event.recorded_at >= event.valid_until
            ):
                raise BenchmarkApprovalConflict("benchmark_independent_current_approval_required")
            self.active, self.active_submission, self.pending = event, subject, None
        elif event.action == "revoked":
            active = self.active
            if active is None or not _same_proposal(active, event):
                raise BenchmarkApprovalConflict("benchmark_approval_replaced")
            self.active = self.active_submission = None
        else:
            raise BenchmarkApprovalConflict("unknown_benchmark_transition")
        self.head = event


def _same_proposal(first: BenchmarkApprovalEvent, second: BenchmarkApprovalEvent) -> bool:
    return (
        first.request_id,
        first.scope,
        first.valuation_id,
        first.valuation_version,
        first.source_seal,
        first.source_manifest,
        first.valid_until,
    ) == (
        second.request_id,
        second.scope,
        second.valuation_id,
        second.valuation_version,
        second.source_seal,
        second.source_manifest,
        second.valid_until,
    )
