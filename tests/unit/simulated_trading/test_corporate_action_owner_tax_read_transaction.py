"""Controlled facts exercise the actual audit read-scope ownership contract."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.audit.application.system_audit_event_outbox import SystemAuditEventOutboxConflict
from apps.audit.infrastructure import system_audit_event_outbox_coordinator as audit_module
from apps.simulated_trading import corporate_action_owner_tax_prepare_composition as preparation
from tests.unit.simulated_trading.test_corporate_action_tax_assessment import _assessment


@pytest.mark.parametrize("caller_depth", (0, 1, 2))
def test_tax_preview_joins_outer_read_transaction_without_weakening_audit_scope(
    monkeypatch: pytest.MonkeyPatch, caller_depth: int
) -> None:
    """Standalone and outer callers read at depth one; nested callers remain blocked."""
    now = datetime(2025, 3, 31, tzinfo=UTC)
    candidate = _assessment()
    blocks: list[object] = [object() for _ in range(caller_depth)]
    entered: list[int] = []
    original_pairs: list[int] = []

    class Connection:
        atomic_blocks = blocks

        @property
        def in_atomic_block(self) -> bool:
            return bool(blocks)

        def get_autocommit(self) -> bool:
            return not blocks

    @contextmanager
    def atomic(*, using: str) -> Iterator[None]:
        assert using == "default"
        marker = object()
        blocks.append(marker)
        entered.append(len(blocks))
        try:
            yield
        finally:
            assert blocks.pop() is marker

    connections = {"default": Connection()}
    monkeypatch.setattr(audit_module, "connections", connections)
    monkeypatch.setattr(preparation, "connections", connections, raising=False)
    monkeypatch.setattr(preparation, "transaction", SimpleNamespace(atomic=atomic))
    monkeypatch.setattr(preparation.timezone, "now", lambda: now)
    provider = SimpleNamespace(prepare_current=lambda **kwargs: candidate)
    monkeypatch.setattr(
        preparation,
        "DeferredOwnerTaxQualification",
        lambda **kwargs: SimpleNamespace(build_provider=lambda **kwargs: provider),
    )
    account_query = Mock()
    account_query.using.return_value.select_for_update.return_value.filter.return_value.first.return_value = (
        object()
    )
    monkeypatch.setattr(
        preparation, "SimulatedAccountModel", SimpleNamespace(_base_manager=account_query)
    )
    head = SimpleNamespace(
        owner_user_id=candidate.owner_user_id,
        recorded_at=now - timedelta(seconds=1),
        semantic_sha256=candidate.semantic_sha256,
        assessment_revision_id=candidate.assessment_revision_id,
        supersedes_assessment_revision_id=None,
    )
    header_query = Mock()
    header_query.using.return_value.select_for_update.return_value.filter.return_value.order_by.return_value = [
        head
    ]
    monkeypatch.setattr(preparation, "Header", SimpleNamespace(_base_manager=header_query))
    repository = Mock()
    monkeypatch.setattr(
        preparation, "DjangoCorporateActionTaxAssessmentRepository", lambda **kwargs: repository
    )
    monkeypatch.setattr(preparation, "_head", lambda rows: head)
    audit = audit_module.DjangoSystemAuditEventOutboxCoordinator(using="default")
    monkeypatch.setattr(
        preparation, "build_tax_assessment_audit_coordinator", lambda **kwargs: audit
    )

    def verify_original(row: object, *, as_of: datetime) -> None:
        assert row is head and as_of == now
        assert audit._read_active is True and audit._active is False
        original_pairs.append(len(blocks))

    monkeypatch.setattr(
        preparation,
        "DjangoRetainedTaxAssessmentAuditVerifier",
        lambda **kwargs: SimpleNamespace(verify_original=verify_original),
    )

    def prepare() -> preparation.OwnerCorporateActionTaxPreview:
        return preparation.prepare_owner_corporate_action_tax_assessment(
            action=candidate.action,
            operation="tax_recognize",
            canonical_account_id="synthetic-owned-account",
            settlement_date=candidate.target_settlement_date,
            environment="synthetic-test",
        )

    if caller_depth > 1:
        with pytest.raises(SystemAuditEventOutboxConflict, match="outermost transaction"):
            prepare()
        assert not original_pairs
    else:
        result = prepare()
        assert result.assessment == candidate
        assert original_pairs == [1]
        repository.verify_retained_integrity.assert_called_once_with(head)
        repository.verify_stored.assert_called_once_with(head, candidate)
    assert len(blocks) == caller_depth
    assert audit._read_active is False and audit._active is False
    if caller_depth == 1:
        assert entered == []
