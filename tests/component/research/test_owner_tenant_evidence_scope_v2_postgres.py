"""Actual owner/current and Evidence PIT reads over explicit synthetic local provenance."""

from dataclasses import replace
from datetime import timedelta

import pytest
from django.db import connections

from apps.account.application.owner_tenant_authority_v2 import (
    GetCurrentOwnerTenantAuthorityV2Command,
    IssueOwnerTenantAuthorityV2Command,
)
from apps.research.evidence_composition import make_evidence_read_repository
from apps.research.infrastructure.evidence_models import (
    EvidenceEnvelopeModel,
    EvidenceOperatorSpecModel,
    EvidenceTrackRecordModel,
)
from apps.research.infrastructure.evidence_repository import _build_evidence_store
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
from tests.component.account.test_owner_tenant_authority_v2_composition import (
    _facade,
    _physical_fixture,
    _seed_live_compatible,
)
from tests.unit.research.test_evidence_contracts import _spec

pytest_plugins = ["tests.component.account.test_owner_tenant_authority_v2_composition"]


@pytest.fixture
def owner_evidence_alias(owner_physical_alias):
    models = (EvidenceOperatorSpecModel, EvidenceTrackRecordModel, EvidenceEnvelopeModel)
    with connections[owner_physical_alias].schema_editor() as editor:
        for model in models:
            editor.create_model(model)
    try:
        yield owner_physical_alias
    finally:
        with connections[owner_physical_alias].schema_editor() as editor:
            for model in reversed(models):
                editor.delete_model(model)


def test_actual_current_owner_reads_historical_evidence_and_live_owner_loss_denies(
    owner_evidence_alias, monkeypatch
):
    from core.integration.owner_tenant_evidence_scope_v2 import (
        OwnerTenantAuthorityV2EvidenceReadFacade,
    )

    alias = owner_evidence_alias
    record = _seed_live_compatible(alias, monkeypatch)
    row = _physical_fixture(alias, record)
    owner = _facade(alias, record)
    assignment = record.authority.assignment
    root = owner.issue(
        IssueOwnerTenantAuthorityV2Command(
            "research-read-root",
            "v2.1",
            assignment.evidence_id,
            assignment.evidence_version,
            assignment.content_hash,
        )
    )
    spec = replace(
        _spec(),
        activated_at=root.recorded_at - timedelta(days=1),
        valid_until=root.valid_until,
        content_hash="",
    )
    # Explicit synthetic historical Research fixture; not a production publication.
    store = _build_evidence_store(using=alias)
    with store.atomic():
        store.append_operator_spec(spec, recorded_at=root.recorded_at - timedelta(hours=1))
    historical_cutoff = root.recorded_at - timedelta(minutes=30)
    reader = OwnerTenantAuthorityV2EvidenceReadFacade(
        authority_reader=owner,
        evidence_reader=make_evidence_read_repository(using=alias),
        authority_command=GetCurrentOwnerTenantAuthorityV2Command(
            root.authority_id,
            root.authority_version,
            root.content_hash,
        ),
        server_bound_artifacts=frozenset({spec.artifact_ref}),
        scope_ttl=timedelta(minutes=1),
        using=alias,
    )
    evidence_queries = []

    def observe(execute, sql, params, many, context):
        if EvidenceOperatorSpecModel._meta.db_table in sql:
            assert connections[alias].in_atomic_block
            evidence_queries.append(sql)
        return execute(sql, params, many, context)

    def reject_default(execute, sql, params, many, context):
        raise AssertionError("V2 scoped read queried the default alias")

    def read():
        return reader.get_operator_spec(
            operator_id=spec.operator_id,
            operator_version=spec.operator_version,
            expected_content_hash=spec.content_hash,
            evidence_as_of=historical_cutoff,
        )

    with connections["default"].execute_wrapper(reject_default):
        with connections[alias].execute_wrapper(observe):
            assert (
                reader.get_operator_spec(
                    operator_id=spec.operator_id,
                    operator_version=spec.operator_version,
                    expected_content_hash="0" * 64,
                    evidence_as_of=historical_cutoff,
                )
                is None
            )
            assert (
                reader.get_operator_spec(
                    operator_id=spec.operator_id,
                    operator_version=spec.operator_version,
                    expected_content_hash=spec.content_hash,
                    evidence_as_of=root.valid_until + timedelta(days=1),
                )
                is None
            )
            assert evidence_queries == []
            assert read() == spec
            assert evidence_queries
            count = len(evidence_queries)
            SimulatedAccountModel.objects.using(alias).filter(pk=row.pk).update(user_id=None)
            assert read() is None
            assert len(evidence_queries) == count
