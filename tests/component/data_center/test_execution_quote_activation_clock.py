"""Independent clock checks across the actual canonical activation Audit boundary."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from django.db import connection

import apps.data_center.infrastructure.publication_group_activation_repository as group_repository
from apps.audit.infrastructure.publication_activation_audit_writer import (
    DjangoPublicationActivationAuditWriter,
)
from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.data_center.application.execution_quote_activation import (
    ExecutionQuotePublicationActivationError,
    stage_and_activate_execution_quote_candidate,
)
from apps.data_center.infrastructure.publication_models import (
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
)
from tests.component.data_center.test_execution_quote_activation_workflow import (
    _bundle,
    _seed_execution_quote,
    _stage_arguments,
)

pytestmark = pytest.mark.django_db(
    transaction=True, available_apps=["apps.data_center", "apps.audit"]
)


@pytest.mark.parametrize("after_audit", ["retreat_within_lease", "lease_expiry_with_fresh_source"])
def test_activation_rechecks_monotonic_clock_and_lease_after_actual_audit(
    monkeypatch: pytest.MonkeyPatch,
    after_audit: str,
) -> None:
    """Both failures roll back pointer, publication state, event, and Outbox."""

    if connection.vendor != "postgresql":
        pytest.skip("Independent activation transaction checks run on native PostgreSQL")
    _row, raw, run_id, asset_code = _seed_execution_quote(execution_ttl=600, age_seconds=100)
    checked_at = datetime.now(UTC)
    current_clock = [checked_at + timedelta(seconds=5)]
    original = DjangoPublicationActivationAuditWriter.append_manifest_group_required

    def append_then_change_clock(self, *, request, writes):
        commits = original(self, request=request, writes=writes)
        assert len(commits) == 1
        assert SystemAuditEventModel.objects.count() == 1
        assert SystemAuditOutboxModel.objects.count() == 1
        current_clock[0] = (
            checked_at + timedelta(seconds=4)
            if after_audit == "retreat_within_lease"
            else checked_at + timedelta(minutes=5)
        )
        return commits

    monkeypatch.setattr(group_repository, "timezone", SimpleNamespace(now=lambda: current_clock[0]))
    monkeypatch.setattr(
        DjangoPublicationActivationAuditWriter,
        "append_manifest_group_required",
        append_then_change_clock,
    )

    with pytest.raises(ExecutionQuotePublicationActivationError):
        stage_and_activate_execution_quote_candidate(
            bundle=_bundle(
                audit_writer_factory=lambda: DjangoPublicationActivationAuditWriter(
                    DjangoSystemAuditEventOutboxCoordinator()
                ),
                authority_checked_at=checked_at,
            ),
            **_stage_arguments(raw, run_id, asset_code),
        )

    candidate = CanonicalPublicationModel.objects.get(run_id=run_id)
    pointer = CanonicalPublicationPointerModel.objects.get(
        dataset_key="equity.quote.snapshot", publication_key="execution"
    )
    assert candidate.state == "candidate"
    assert candidate.published_at is None
    assert pointer.publication_id is None
    assert SystemAuditEventModel.objects.count() == 0
    assert SystemAuditOutboxModel.objects.count() == 0
