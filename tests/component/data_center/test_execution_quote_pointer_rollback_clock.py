"""Independent chronology checks for the real execution-pointer rollback UOW."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

import apps.data_center.infrastructure.execution_quote_pointer_rollback_repository as repo_module
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.data_center.application.execution_quote_pointer_rollback import (
    ExecutionQuotePointerRollbackAuditObservation,
    ExecutionQuotePointerRollbackAuditReceipt,
    ExecutionQuotePointerRollbackError,
    rollback_execution_quote_pointer,
)
from apps.data_center.infrastructure.publication_models import (
    CanonicalPublicationPointerModel,
    PublicationRollbackModel,
)
from tests.component.data_center.test_execution_quote_pointer_rollback import (
    _command,
    _reader_context,
    _rollback_bundle,
    _two_activated_publications,
)

pytestmark = pytest.mark.django_db(
    transaction=True, available_apps=["apps.data_center", "apps.audit"]
)


def test_pointer_rollback_rejects_clock_regression_after_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clock retreat inside the authority window still rolls back every write."""

    target, current = _two_activated_publications()
    command = _command(target=target, current=current)
    checked_at = datetime.now(UTC) + timedelta(seconds=5)
    phase = {"audit_completed": False}
    bundle = _rollback_bundle()
    canonical_writer = bundle.audit_writer_factory()

    class _AuditBoundary:
        database_alias = canonical_writer.database_alias

        def execute_in_caller_transaction(
            self,
            observation: ExecutionQuotePointerRollbackAuditObservation,
            *,
            exact_replay: bool,
        ) -> ExecutionQuotePointerRollbackAuditReceipt:
            receipt = canonical_writer.execute_in_caller_transaction(
                observation, exact_replay=exact_replay
            )
            phase["audit_completed"] = True
            return receipt

    class _Clock:
        @staticmethod
        def now() -> datetime:
            return checked_at - timedelta(seconds=1) if phase["audit_completed"] else checked_at

    monkeypatch.setattr(repo_module, "timezone", _Clock)

    with pytest.raises(ExecutionQuotePointerRollbackError):
        rollback_execution_quote_pointer(
            command=command,
            bundle=replace(bundle, audit_writer_factory=lambda: _AuditBoundary()),
            preflight_context=_reader_context(),
        )

    pointer = CanonicalPublicationPointerModel.objects.get(
        dataset_key="equity.quote.snapshot", publication_key="execution"
    )
    assert str(pointer.publication_id) == str(current.publication_id)
    target.refresh_from_db()
    current.refresh_from_db()
    assert target.state == "superseded"
    assert current.state == "published"
    assert PublicationRollbackModel.objects.count() == 0
    assert (
        SystemAuditEventModel.objects.filter(event_type="data.publication.rolled_back").count() == 0
    )
    assert SystemAuditOutboxModel.objects.count() == 2
