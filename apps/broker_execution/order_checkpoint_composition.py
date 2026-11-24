"""Transaction-bound joins for advancement of one previously signed Broker order."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from django.db import DatabaseError, connections

from apps.broker_execution.application.checkpoint_authority import BrokerCheckpointIntent
from apps.broker_execution.application.use_case_errors import BrokerExecutionConflictError
from apps.broker_execution.ash09_checkpoint_composition import (
    bounded_checkpoint_diagnostic,
    resolve_current_intent,
)
from apps.broker_execution.domain.services import approval_digest_for_order


@dataclass(frozen=True, slots=True)
class VerifiedOrderCheckpoint:
    """The original source versions pinned on creation and their earliest deadline."""

    intent: BrokerCheckpointIntent
    execution_scope_hash: str
    risk_approval_hash: str
    valid_until: datetime
    execution_scope_id: str
    execution_scope_version: str
    risk_approval_id: str
    risk_approval_version: str

    def require_unexpired(self, at: datetime) -> None:
        """Fail if a locked source expired while other business checks were running."""
        if at >= self.valid_until:
            raise BrokerExecutionConflictError("broker_checkpoint_approval_expired")

    def require_order(self, payload: Mapping[str, object]) -> None:
        """Compare exactly the economics that will be sent to the Agent."""
        if approval_digest_for_order(payload) != self.intent.sources.order.approval_digest:
            raise BrokerExecutionConflictError("broker_checkpoint_order_content_mismatch")

    def pin(self) -> dict[str, str]:
        """Return the exact authority and economic references preserved in the audit trail."""
        plan = self.intent.sources.plan
        account = self.intent.sources.account
        return {
            "order_id": str(self.intent.client_order_id),
            "order_version": str(self.intent.order_version),
            "order_artifact_version": plan.order_artifact_version,
            "order_artifact_hash": plan.order_artifact_content_hash,
            "account_id": str(account.broker_account_id),
            "account_binding_id": account.binding_id,
            "account_binding_version": account.binding_version,
            "account_binding_hash": account.content_hash,
            "plan_id": plan.portfolio_plan_id,
            "plan_version": str(plan.portfolio_plan_version),
            "plan_hash": plan.portfolio_plan_content_hash,
            "plan_binding_hash": plan.content_hash,
            "plan_order_ordinal": str(plan.plan_order_ordinal),
            "plan_order_hash": plan.plan_order_content_hash,
            "plan_approval_id": plan.portfolio_receipt_id,
            "plan_approval_version": plan.portfolio_receipt_version,
            "plan_approval_hash": plan.portfolio_receipt_content_hash,
            "execution_scope_id": self.execution_scope_id,
            "execution_scope_version": self.execution_scope_version,
            "execution_scope_hash": self.execution_scope_hash,
            "risk_approval_id": self.risk_approval_id,
            "risk_approval_version": self.risk_approval_version,
            "risk_approval_hash": self.risk_approval_hash,
        }


class _CheckpointReader(Protocol):
    def __call__(
        self, *, intent: BrokerCheckpointIntent, using: str
    ) -> VerifiedOrderCheckpoint: ...


_reader: _CheckpointReader | None = None


def register_order_checkpoint_reader(reader: _CheckpointReader) -> None:
    """Install the application-owned Portfolio and Risk composition at startup."""
    global _reader
    _reader = reader


def verify_existing_order(
    *,
    client_order_id: UUID,
    account_id: int,
    owner_user_id: int,
    payload: Mapping[str, object],
    authority_pin: object,
    using: str = "default",
) -> VerifiedOrderCheckpoint:
    """Reject a changed grant, changed Risk approval or different physical order economics."""
    checked = verify_order_checkpoint(
        client_order_id=client_order_id,
        account_id=account_id,
        owner_user_id=owner_user_id,
        using=using,
    )
    if authority_pin != checked.pin():
        raise BrokerExecutionConflictError("broker_checkpoint_authority_changed")
    checked.require_order(payload)
    return checked


def _lock_intent_ledgers(using: str) -> None:
    db = connections[using]
    if db.vendor != "postgresql" or not db.in_atomic_block:
        raise BrokerExecutionConflictError("broker_checkpoint_transaction_required")
    with db.cursor() as cursor:
        cursor.execute("SHOW transaction_isolation")
        if cursor.fetchone() != ("read committed",):
            raise BrokerExecutionConflictError("broker_checkpoint_read_committed_required")
        # A successor is a new row and would not conflict with a lock on its predecessor.
        cursor.execute("""LOCK TABLE broker_execution_order_approval_artifact,
                          broker_execution_plan_order_binding,
                          broker_execution_portfolio_account_binding,
                          broker_execution_pre_risk_scope IN SHARE MODE NOWAIT""")


def verify_order_checkpoint(
    *, client_order_id: UUID, account_id: int, owner_user_id: int, using: str
) -> VerifiedOrderCheckpoint:
    """Re-read every signed source while the caller holds the order transaction open."""
    if not connections[using].in_atomic_block:
        raise BrokerExecutionConflictError("broker_checkpoint_transaction_required")
    try:
        with bounded_checkpoint_diagnostic(using=using):
            return _read_locked_checkpoint(client_order_id, account_id, owner_user_id, using)
    except DatabaseError as exc:
        raise BrokerExecutionConflictError("broker_checkpoint_storage_unavailable") from exc


def _read_locked_checkpoint(
    client_order_id: UUID, account_id: int, owner_user_id: int, using: str
) -> VerifiedOrderCheckpoint:
    _lock_intent_ledgers(using)
    intent = resolve_current_intent(
        client_order_id=client_order_id, account_id=account_id, using=using
    )
    if intent.owner_user_id != owner_user_id:
        raise BrokerExecutionConflictError("broker_checkpoint_owner_mismatch")
    if _reader is None:
        raise BrokerExecutionConflictError("broker_checkpoint_sources_unavailable")
    return _reader(intent=intent, using=using)
