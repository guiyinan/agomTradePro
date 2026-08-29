from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    AuthenticatedAccountPrincipalV3,
    CurrentAccountActorAuthorityV3,
    CurrentAccountOwnerAssignmentApproverProviderV3,
)
from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentServerActor,
)
from apps.account.application.account_owner_assignment_evidence_v3 import (
    GetCurrentAccountOwnerAssignmentEvidenceV3Command,
)
from apps.account.application.owner_tenant_authority_v1 import (
    DelegatingOwnerTenantAuthorityApproverProviderV1,
    GetCurrentOwnerTenantAuthorityV1,
    GetCurrentOwnerTenantAuthorityV1Command,
    IssueOwnerTenantAuthorityV1,
    IssueOwnerTenantAuthorityV1Command,
    OwnerTenantAuthorityV1Conflict,
    OwnerTenantAuthorityV1Unavailable,
    SupersedeOwnerTenantAuthorityV1,
    SupersedeOwnerTenantAuthorityV1Command,
)
from apps.account.domain.account_owner_assignment_evidence import (
    AccountOwnerAssignmentActor,
)
from apps.account.domain.account_owner_assignment_evidence_v3 import (
    AccountOwnerAssignmentEvidenceV3,
)
from apps.account.domain.owner_tenant_authority_v1 import (
    OwnerTenantAuthorityV1,
    validate_owner_tenant_authority_v1_root,
    validate_owner_tenant_authority_v1_successor,
)
from tests.unit.account.test_account_owner_assignment_evidence_v3 import _evidence
from tests.unit.account.test_account_owner_assignment_provenance_receipt_v3 import _at


def _authority(**changes: object) -> OwnerTenantAuthorityV1:
    assignment = _evidence()
    values: dict[str, object] = {
        "authority_id": "authority-7",
        "authority_version": "v1",
        "tenant_id": "tenant-cn-1",
        "owner_id": "owner-agom-42",
        "account_namespace": assignment.subject.binding.account_namespace_claim,
        "account_id": assignment.subject.binding.account_id_claim,
        "actor_id": "human-42",
        "actor_user_id": 42,
        "assignment_evidence_id": "creation-evidence-7",
        "assignment_evidence_version": "v3.1",
        "assignment_evidence_content_hash": assignment.content_hash,
        "status": "active",
        "approved_by": AccountOwnerAssignmentActor(
            "tenant-admin-9",
            9,
            "owner_tenant_authority_approver",
            is_staff=True,
        ),
        "approved_at": _at(9),
        "recorded_at": _at(9),
        "valid_until": _at(11),
    }
    values.update(changes)
    return OwnerTenantAuthorityV1(**values)  # type: ignore[arg-type]


class _Assignments:
    def __init__(self, value: AccountOwnerAssignmentEvidenceV3 | None = _evidence()) -> None:
        self.value = value

    def execute(
        self, command: GetCurrentAccountOwnerAssignmentEvidenceV3Command
    ) -> AccountOwnerAssignmentEvidenceV3 | None:
        if self.value is None or not self.value.is_current_at(command.as_of):
            return None
        return self.value


class _AdminAuthorityReader:
    def get_exact_current(
        self,
        *,
        principal_id: str,
        user_id: int,
        expected_authentication_context_hash: str,
        as_of: datetime,
    ) -> CurrentAccountActorAuthorityV3 | None:
        del as_of
        return CurrentAccountActorAuthorityV3(
            principal_id=principal_id,
            user_id=user_id,
            authentication_context_hash=expected_authentication_context_hash,
            actor_id="tenant-admin-9",
            is_authenticated=True,
            is_active=True,
            is_staff=True,
            is_superuser=False,
            rbac_role="admin",
            source_id="admin-source-9",
            source_version="v3",
            source_content_hash="9" * 64,
            recorded_at=_at(8),
            valid_until=_at(12),
        )


class _Approvers:
    def __init__(self, actor: AccountOwnerAssignmentServerActor | None = None) -> None:
        self.actor = actor or AccountOwnerAssignmentServerActor(
            "tenant-admin-9",
            9,
            "owner_tenant_authority_approver",
            is_staff=True,
        )

    def get_current(self, *, as_of: datetime) -> AccountOwnerAssignmentServerActor | None:
        del as_of
        return self.actor


class _Repository:
    unit_of_work_key = "django:default"

    def __init__(self, now: datetime = _at(9)) -> None:
        self.current_time = now
        self.rows: list[OwnerTenantAuthorityV1] = []

    def atomic(self) -> nullcontext[None]:
        return nullcontext()

    def now(self) -> datetime:
        return self.current_time

    def get_winner(
        self, *, authority_id: str, authority_version: str, as_of: datetime
    ) -> OwnerTenantAuthorityV1 | None:
        return next(
            (
                row
                for row in self.rows
                if row.authority_id == authority_id
                and row.authority_version == authority_version
                and row.recorded_at <= as_of
            ),
            None,
        )

    def get_head(self, *, authority_id: str, as_of: datetime) -> OwnerTenantAuthorityV1 | None:
        known = [
            row
            for row in self.rows
            if row.authority_id == authority_id and row.recorded_at <= as_of
        ]
        return known[-1] if known else None

    def get_exact(
        self,
        *,
        authority_id: str,
        authority_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> OwnerTenantAuthorityV1 | None:
        return next(
            (
                row
                for row in self.rows
                if (
                    row.authority_id,
                    row.authority_version,
                    row.content_hash,
                )
                == (authority_id, authority_version, expected_content_hash)
                and row.recorded_at <= as_of
            ),
            None,
        )

    def append(
        self,
        authority: OwnerTenantAuthorityV1,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> OwnerTenantAuthorityV1:
        assert authority.recorded_at == recorded_at
        assert authority.supersedes_content_hash == expected_predecessor_hash
        self.rows.append(authority)
        return authority


def test_domain_root_successor_and_scope_immutability() -> None:
    root = _authority()
    validate_owner_tenant_authority_v1_root(root)
    successor = _authority(
        authority_version="v2",
        approved_at=_at(10),
        recorded_at=_at(10),
        valid_until=_at(12),
        supersedes_content_hash=root.content_hash,
    )
    validate_owner_tenant_authority_v1_successor(root, successor)
    with pytest.raises(ValueError, match="widen|substitute"):
        validate_owner_tenant_authority_v1_successor(
            root, replace(successor, tenant_id="tenant-other", content_hash="")
        )
    revoked = replace(successor, status="revoked", content_hash="")
    validate_owner_tenant_authority_v1_successor(root, revoked)
    assert revoked.is_current_at(_at(10)) is False


def test_issue_root_uses_assignment_and_independent_approver() -> None:
    evidence = _evidence()
    repository = _Repository()
    service = IssueOwnerTenantAuthorityV1(
        assignments=_Assignments(evidence),
        approvers=_Approvers(),
        repository=repository,
        validity_period=timedelta(days=2),
    )
    command = IssueOwnerTenantAuthorityV1Command(
        "authority-7",
        "v1",
        "tenant-cn-1",
        "owner-agom-42",
        evidence.evidence_id,
        evidence.evidence_version,
        evidence.content_hash,
    )
    result = service.execute(command)
    assert (result.actor_id, result.actor_user_id) == ("human-42", 42)
    assert result.account_id == evidence.subject.binding.account_id_claim
    assert result.tenant_id == "tenant-cn-1"
    assert service.execute(command) == result
    assert len(repository.rows) == 1


def test_authenticated_admin_is_projected_to_dedicated_approval_role() -> None:
    principal = AuthenticatedAccountPrincipalV3(
        principal_id="principal-admin-9",
        user_id=9,
        authentication_context_hash="8" * 64,
        authenticated_at=_at(8),
        valid_until=_at(12),
    )
    delegate = CurrentAccountOwnerAssignmentApproverProviderV3(
        principal=principal,
        authority_reader=_AdminAuthorityReader(),
    )
    provider = DelegatingOwnerTenantAuthorityApproverProviderV1(delegate)
    actor = provider.get_current(as_of=_at(9))
    assert actor is not None
    assert actor.role == "owner_tenant_authority_approver"
    assert actor.is_staff is True


def test_current_authority_revalidates_upstream_assignment() -> None:
    evidence = _evidence()
    repository = _Repository()
    root = IssueOwnerTenantAuthorityV1(
        assignments=_Assignments(evidence),
        approvers=_Approvers(),
        repository=repository,
        validity_period=timedelta(days=2),
    ).execute(
        IssueOwnerTenantAuthorityV1Command(
            "authority-7",
            "v1",
            "tenant-cn-1",
            "owner-agom-42",
            evidence.evidence_id,
            evidence.evidence_version,
            evidence.content_hash,
        )
    )
    reader = GetCurrentOwnerTenantAuthorityV1(repository, assignment_reader=_Assignments(None))
    assert (
        reader.execute(
            GetCurrentOwnerTenantAuthorityV1Command(
                root.authority_id,
                root.authority_version,
                root.content_hash,
                _at(9),
            )
        )
        is None
    )


def test_issue_rejects_self_approval_and_assignment_unavailability() -> None:
    evidence = _evidence()
    command = IssueOwnerTenantAuthorityV1Command(
        "authority-7",
        "v1",
        "tenant-cn-1",
        "owner-agom-42",
        evidence.evidence_id,
        evidence.evidence_version,
        evidence.content_hash,
    )
    services = (
        IssueOwnerTenantAuthorityV1(
            assignments=_Assignments(None),
            approvers=_Approvers(),
            repository=_Repository(_at(9)),
            validity_period=timedelta(days=1),
        ),
        IssueOwnerTenantAuthorityV1(
            assignments=_Assignments(evidence),
            approvers=_Approvers(
                AccountOwnerAssignmentServerActor(
                    "human-42",
                    42,
                    "owner_tenant_authority_approver",
                    is_staff=True,
                )
            ),
            repository=_Repository(_at(9)),
            validity_period=timedelta(days=1),
        ),
    )
    for service in services:
        with pytest.raises(OwnerTenantAuthorityV1Unavailable):
            service.execute(command)


def test_revocation_becomes_final_head_without_predecessor_fallback() -> None:
    evidence = _evidence()
    repository = _Repository()
    issuer = IssueOwnerTenantAuthorityV1(
        assignments=_Assignments(evidence),
        approvers=_Approvers(),
        repository=repository,
        validity_period=timedelta(days=2),
    )
    root = issuer.execute(
        IssueOwnerTenantAuthorityV1Command(
            "authority-7",
            "v1",
            "tenant-cn-1",
            "owner-agom-42",
            evidence.evidence_id,
            evidence.evidence_version,
            evidence.content_hash,
        )
    )
    repository.current_time = _at(10)
    revoker = SupersedeOwnerTenantAuthorityV1(
        assignments=_Assignments(evidence),
        approvers=_Approvers(),
        repository=repository,
        validity_period=timedelta(days=2),
    )
    revoked = revoker.execute(
        SupersedeOwnerTenantAuthorityV1Command(
            "authority-7",
            "v2",
            "v1",
            root.content_hash,
            evidence.evidence_id,
            evidence.evidence_version,
            evidence.content_hash,
            "revoked",
        )
    )
    assert revoked.status == "revoked"
    reader = GetCurrentOwnerTenantAuthorityV1(repository, assignment_reader=_Assignments(evidence))
    assert (
        reader.execute(
            GetCurrentOwnerTenantAuthorityV1Command(
                root.authority_id,
                root.authority_version,
                root.content_hash,
                _at(10),
            )
        )
        is None
    )
    with pytest.raises(OwnerTenantAuthorityV1Conflict, match="predecessor"):
        revoker.execute(
            SupersedeOwnerTenantAuthorityV1Command(
                "authority-7",
                "v3",
                "v1",
                root.content_hash,
                evidence.evidence_id,
                evidence.evidence_version,
                evidence.content_hash,
                "active",
            )
        )
