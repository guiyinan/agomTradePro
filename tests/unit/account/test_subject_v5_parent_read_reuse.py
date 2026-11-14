"""Parent graph reads are bounded within a phase and fresh at the next fence."""

from types import SimpleNamespace

import pytest

from apps.account.infrastructure import (
    canonical_account_creation_consumption_repository as consumption,
)
from apps.account.infrastructure.account_owner_assignment_provenance_receipt_v5_repository import (
    DjangoAccountOwnerAssignmentProvenanceReceiptV5Repository,
)
from apps.account.infrastructure.account_owner_assignment_subject_v5_repository import (
    DjangoAccountOwnerAssignmentSubjectV5Repository,
)
from apps.account.infrastructure.canonical_account_ownership_reobservation_v1_repository import (
    DjangoCanonicalAccountOwnershipReobservationV1Repository,
)
from apps.account.infrastructure.owner_tenant_authority_v3_read_context import (
    OwnerTenantAuthorityV3OperationReadContext,
)


@pytest.fixture(params=("standalone", "facade"))
def graph(monkeypatch, request):
    reads = []
    state = {"broken": False}

    class Query:
        def __init__(self, table):
            self.table = table

        def using(self, alias):
            assert alias == "default"
            return self

        def all(self):
            return self

        def select_for_update(self):
            return self

        def order_by(self, key):
            assert key == "pk"
            reads.append(self.table)
            if state["broken"]:
                raise consumption.CanonicalAccountCreationBindingV2Corruption("changed parent")
            return ()

    for name in (
        "CanonicalAccountCreationAllocationModel",
        "AllocatedPhysicalAccountRowObservationV3Model",
        "CanonicalAccountCreationBindingModel",
        "CanonicalAccountCreationBindingV2Model",
        "CanonicalAccountCreationConsumptionClaimModel",
    ):
        monkeypatch.setattr(consumption, name, SimpleNamespace(_base_manager=Query(name)))
    subject = DjangoAccountOwnerAssignmentSubjectV5Repository()
    parents = (
        subject._bindings,
        subject._receipts._bindings,
        subject._reobservations._binding_repository,
        subject._receipts._reobservations._binding_repository,
    )
    if request.param == "facade":
        from datetime import timedelta

        from apps.account.account_owner_assignment_evidence_v5_composition import (
            build_account_owner_assignment_evidence_v5_facade,
        )
        from apps.simulated_trading.account_physical_row_v2_composition import (
            build_account_physical_row_v2_provider,
        )
        from tests.unit.account.test_owner_tenant_authority_v3_operation_read_reuse import (
            _binding,
            _principal,
        )

        facade = build_account_owner_assignment_evidence_v5_facade(
            principal=_principal(),
            policy_binding=_binding(),
            actor_source_id="actor-42",
            actor_source_version="v3",
            actor_source_content_hash="c" * 64,
            validity_period=timedelta(minutes=30),
            physical_row_provider=build_account_physical_row_v2_provider(),
        )
        subject = facade._repository._subjects
        receipt = facade._current._subjects._current_receipt_reader
        parents = (
            subject._bindings,
            subject._receipts._bindings,
            receipt._binding_reader._repository,
            receipt._reobservation_reader._repository._binding_repository,
        )
    connection = object()
    context = OwnerTenantAuthorityV3OperationReadContext(
        using="default",
        connection_provider=lambda: connection,
    )
    return parents, context, reads, state


def test_stabilized_subject_graph_reads_one_complete_parent_world_per_phase(graph):
    parents, context, reads, _ = graph
    with context.phase():
        for parent in parents:
            parent._closed_world(lock=False)
    assert len(reads) == 5
    with context.phase():
        for parent in parents:
            parent._closed_world(lock=False)
    assert len(reads) == 10


def test_shared_parent_instances_do_not_cache_outside_stabilized_phase(graph):
    parents, _, reads, _ = graph
    for parent in parents:
        parent._closed_world(lock=False)
    assert len(reads) == 20


def test_fresh_final_phase_detects_changed_parent_and_lock_mode_never_reuses_read(graph):
    parents, context, reads, state = graph
    with context.phase():
        parents[0]._closed_world(lock=False)
        parents[0]._closed_world(lock=True)
    assert len(reads) == 10
    state["broken"] = True
    with pytest.raises(consumption.CanonicalAccountCreationBindingV2Corruption):
        with context.phase():
            parents[1]._closed_world(lock=False)


@pytest.mark.parametrize("parent", ("bindings", "reobservations"))
def test_cross_alias_parent_cannot_be_injected_into_receipt_graph(parent):
    repository = (
        consumption.DjangoCanonicalAccountCreationConsumptionRepository(using="other")
        if parent == "bindings"
        else DjangoCanonicalAccountOwnershipReobservationV1Repository(using="other")
    )
    with pytest.raises(ValueError, match="database alias"):
        DjangoAccountOwnerAssignmentProvenanceReceiptV5Repository(**{parent: repository})
