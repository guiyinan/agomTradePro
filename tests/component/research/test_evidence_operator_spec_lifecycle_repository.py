"""Django component proof for approved Evidence operator spec activations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from django.core.exceptions import ValidationError

from apps.research.application.evidence_operator_spec_lifecycle import (
    ActivateEvidenceOperatorSpec,
    ActivateEvidenceOperatorSpecCommand,
    EvidenceOperatorSpecConflict,
    EvidenceOperatorSpecOwnerApproval,
    EvidenceOperatorSpecUnavailable,
)
from apps.research.domain.evidence_contracts import (
    ClaimKind,
    DecisionPermission,
    EvidenceOperatorSpec,
    MethodKind,
)
from apps.research.domain.evidence_operator_spec_lifecycle import (
    ActivatedEvidenceOperatorSpec,
    EvidenceOperatorSpecDefinition,
)
from apps.research.infrastructure.evidence_operator_spec_lifecycle_models import (
    ActivatedEvidenceOperatorSpecModel,
    EvidenceOperatorSpecApprovalReceiptModel,
)
from apps.research.infrastructure.evidence_operator_spec_lifecycle_repository import (
    DjangoEvidenceOperatorSpecLifecycleRepository,
)

NOW = datetime(2026, 8, 12, 8, tzinfo=UTC)


def _definition(
    *,
    version: str = "v1",
    supersedes: str | None = None,
) -> EvidenceOperatorSpecDefinition:
    return EvidenceOperatorSpecDefinition.create(
        operator_spec=EvidenceOperatorSpec.create(
            operator_id="scenario-probability",
            operator_version=version,
            research_family="r7",
            output_artifact_type="scenario_probability",
            claim_kind=ClaimKind.FORECAST,
            method_kind=MethodKind.STATISTICAL,
            required_input_roles=("sample_policy",),
            dependency_flags=frozenset(),
            maximum_permission=DecisionPermission.ADVISORY,
            requires_track_record=True,
            activated_at=NOW - timedelta(hours=1),
            valid_until=NOW + timedelta(days=30),
        ),
        supersedes_activation_hash=supersedes,
    )


def _approval(
    definition: EvidenceOperatorSpecDefinition,
    *,
    version: str = "v1",
) -> EvidenceOperatorSpecOwnerApproval:
    spec = definition.operator_spec
    return EvidenceOperatorSpecOwnerApproval(
        approval_id=f"approval-{version}",
        approval_version=version,
        owner_record_id=f"owner-record-{version}",
        owner_record_version=version,
        owner_record_hash="a" * 64,
        operator_id=spec.operator_id,
        operator_version=spec.operator_version,
        definition_hash=definition.content_hash,
        supersedes_activation_hash=definition.supersedes_activation_hash,
        approved_by="risk-owner",
        issued_at=NOW - timedelta(hours=2),
        valid_until=NOW + timedelta(days=10),
    )


@dataclass(frozen=True)
class _Clock:
    value: datetime

    def now(self) -> datetime:
        return self.value


class _DefinitionProvider:
    def __init__(self, definition: EvidenceOperatorSpecDefinition) -> None:
        self.definition = definition

    def get_exact(
        self,
        *,
        operator_id: str,
        operator_version: str,
        as_of: datetime,
    ) -> EvidenceOperatorSpecDefinition | None:
        del as_of
        spec = self.definition.operator_spec
        if (operator_id, operator_version) != (spec.operator_id, spec.operator_version):
            return None
        return self.definition


class _ApprovalQuery:
    def __init__(self, approval: EvidenceOperatorSpecOwnerApproval) -> None:
        self.approval = approval

    def get_exact(
        self,
        *,
        approval_id: str,
        approval_version: str,
        operator_id: str,
        operator_version: str,
        definition_hash: str,
        supersedes_activation_hash: str | None,
        as_of: datetime,
    ) -> EvidenceOperatorSpecOwnerApproval | None:
        del as_of
        expected = (
            self.approval.approval_id,
            self.approval.approval_version,
            self.approval.operator_id,
            self.approval.operator_version,
            self.approval.definition_hash,
            self.approval.supersedes_activation_hash,
        )
        if (
            approval_id,
            approval_version,
            operator_id,
            operator_version,
            definition_hash,
            supersedes_activation_hash,
        ) != expected:
            return None
        return self.approval


@pytest.mark.django_db(transaction=True)
def test_activation_appends_receipt_and_record_then_replays_exact_and_active() -> None:
    definition = _definition()
    repository = DjangoEvidenceOperatorSpecLifecycleRepository(clock=_Clock(NOW))
    service = ActivateEvidenceOperatorSpec(
        definition_provider=_DefinitionProvider(definition),
        approval_query=_ApprovalQuery(_approval(definition)),
        store=repository,
    )

    record = service.execute(
        ActivateEvidenceOperatorSpecCommand(
            operator_id="scenario-probability",
            operator_version="v1",
            approval_id="approval-v1",
            approval_version="v1",
            as_of=NOW,
        )
    )
    assert EvidenceOperatorSpecApprovalReceiptModel.objects.count() == 1
    assert ActivatedEvidenceOperatorSpecModel.objects.count() == 1
    assert (
        repository.get_exact_by_hash(
            operator_id="scenario-probability",
            operator_version="v1",
            expected_content_hash=record.content_hash,
            as_of=NOW,
        )
        == record
    )
    assert repository.get_active(operator_id="scenario-probability", as_of=NOW) == record

    assert (
        service.execute(
            ActivateEvidenceOperatorSpecCommand(
                operator_id="scenario-probability",
                operator_version="v1",
                approval_id="approval-v1",
                approval_version="v1",
                as_of=NOW,
            )
        )
        == record
    )
    assert EvidenceOperatorSpecApprovalReceiptModel.objects.count() == 1
    assert ActivatedEvidenceOperatorSpecModel.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_empty_active_query_and_all_direct_mutation_paths_fail_closed() -> None:
    repository = DjangoEvidenceOperatorSpecLifecycleRepository(clock=_Clock(NOW))
    with pytest.raises(EvidenceOperatorSpecUnavailable, match="no approved"):
        repository.get_active(operator_id="missing", as_of=NOW)

    with pytest.raises(ValidationError):
        EvidenceOperatorSpecApprovalReceiptModel.objects.create(
            approval_id="caller-controlled",
        )
    with pytest.raises(ValidationError):
        ActivatedEvidenceOperatorSpecModel.objects.bulk_create([])


@pytest.mark.django_db(transaction=True)
def test_database_rejects_competing_roots_and_children() -> None:
    """Database uniqueness closes concurrent root and successor fork races."""

    repository = DjangoEvidenceOperatorSpecLifecycleRepository(clock=_Clock(NOW))
    root_definition = _definition()
    root = ActivatedEvidenceOperatorSpec.create(
        definition=root_definition,
        approval=_approval(root_definition).to_receipt(),
        recorded_at=NOW,
    )
    with repository.atomic():
        assert repository.append_graph(root) == root

    competing_root_definition = _definition(version="v2")
    competing_root_approval = _approval(competing_root_definition, version="v2")
    competing_root = ActivatedEvidenceOperatorSpec.create(
        definition=competing_root_definition,
        approval=competing_root_approval.to_receipt(),
        recorded_at=NOW,
    )
    with repository.atomic(), pytest.raises(EvidenceOperatorSpecConflict):
        repository.append_graph(competing_root)

    child_definition = _definition(version="v3", supersedes=root.content_hash)
    child_approval = _approval(child_definition, version="v3")
    child = ActivatedEvidenceOperatorSpec.create(
        definition=child_definition,
        approval=child_approval.to_receipt(),
        recorded_at=NOW,
    )
    with repository.atomic():
        assert repository.append_graph(child) == child

    fork_definition = _definition(version="v4", supersedes=root.content_hash)
    fork_approval = _approval(fork_definition, version="v4")
    fork = ActivatedEvidenceOperatorSpec.create(
        definition=fork_definition,
        approval=fork_approval.to_receipt(),
        recorded_at=NOW,
    )
    with repository.atomic(), pytest.raises(EvidenceOperatorSpecConflict):
        repository.append_graph(fork)

    assert ActivatedEvidenceOperatorSpecModel.objects.count() == 2
