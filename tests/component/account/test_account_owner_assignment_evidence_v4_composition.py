"""Component coverage for the authenticated Evidence v4 composition root."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from django.db import connections, transaction

from apps.account.account_owner_assignment_evidence_v4_composition import (
    build_account_owner_assignment_evidence_v4_facade,
)
from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    AuthenticatedAccountPrincipalV3,
)
from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentConflict,
)
from apps.account.application.account_owner_assignment_evidence_v4 import (
    ApproveAccountOwnerAssignmentEvidenceV4Command,
    GetCurrentAccountOwnerAssignmentEvidenceV4Command,
    RegisterAccountOwnerAssignmentSubjectV4Command,
)
from apps.account.application.single_owner_actor_authority import (
    SingleOwnerPolicyBinding,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v4_models import (
    AccountOwnerAssignmentEvidenceV4Model,
    AccountOwnerAssignmentSubjectV4Model,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_repository import (
    DjangoSingleOwnerAuthorityPolicyV1Repository,
)
from tests.component.account.test_account_owner_assignment_evidence_v4_repository import (
    _seed,
)

pytest_plugins = (
    "tests.component.account.test_account_owner_assignment_evidence_v4_repository",
    "tests.component.account.test_account_owner_assignment_provenance_receipt_v4_repository",
)


def _facade(record, using: str):
    """Build a facade from the server-owned facts in one seeded receipt."""

    authority = record.authority
    policy = record.evidence.subject.policy
    principal = AuthenticatedAccountPrincipalV3(
        principal_id=authority.principal_id,
        user_id=authority.user_id,
        authentication_context_hash=authority.authentication_context_hash,
        authenticated_at=authority.recorded_at,
        valid_until=authority.valid_until,
    )
    binding = SingleOwnerPolicyBinding(
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        expected_content_hash=policy.content_hash,
        tenant_id=policy.tenant_id,
        owner_id=policy.owner_id,
        account_namespace=policy.account_namespace,
        account_id=policy.account_id,
    )
    return build_account_owner_assignment_evidence_v4_facade(
        principal=principal,
        policy_binding=binding,
        actor_source_id=authority.source_id,
        actor_source_version=authority.source_version,
        actor_source_content_hash=authority.source_content_hash,
        validity_period=timedelta(minutes=30),
        using=using,
    )


def _register_command(record) -> RegisterAccountOwnerAssignmentSubjectV4Command:
    """Build only the immutable source selectors accepted by Register."""

    subject = record.evidence.subject
    binding = subject.binding
    root = subject.physical_root
    return RegisterAccountOwnerAssignmentSubjectV4Command(
        subject_id=subject.subject_id,
        subject_version=subject.subject_version,
        receipt_id=subject.receipt.receipt_id,
        receipt_version=subject.receipt.receipt_version,
        expected_receipt_content_hash=subject.receipt.content_hash,
        binding_id=binding.binding_id,
        binding_version=binding.binding_version,
        expected_binding_content_hash=binding.content_hash,
        physical_root_id=root.observation_id,
        physical_root_version=root.observation_version,
        expected_physical_root_content_hash=root.content_hash,
    )


def _approve_command(subject, evidence_id: str) -> ApproveAccountOwnerAssignmentEvidenceV4Command:
    """Build the explicit approval selector for one registered Subject."""

    return ApproveAccountOwnerAssignmentEvidenceV4Command(
        evidence_id=evidence_id,
        evidence_version="v4.1",
        subject_id=subject.subject_id,
        subject_version=subject.subject_version,
        expected_subject_content_hash=subject.content_hash,
    )


def _current_command(evidence) -> GetCurrentAccountOwnerAssignmentEvidenceV4Command:
    """Build the exact current selector returned by the approval result."""

    return GetCurrentAccountOwnerAssignmentEvidenceV4Command(
        evidence_id=evidence.evidence_id,
        evidence_version=evidence.evidence_version,
        expected_content_hash=evidence.content_hash,
        as_of=evidence.recorded_at,
    )


def test_facade_register_approve_replay_and_current_use_one_alias(
    assignment_alias: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise the real chain over synthetic creation and policy facts."""

    record = _seed(assignment_alias, monkeypatch)
    facade = _facade(record, assignment_alias)
    register_command = _register_command(record)

    def reject_default_query(execute, sql, params, many, context):
        raise AssertionError("Evidence v4 composition queried the default alias")

    with connections["default"].execute_wrapper(reject_default_query):
        subject = facade.register(register_command)
        approval_command = _approve_command(subject, "facade-evidence")
        evidence = facade.approve(approval_command)
        assert facade.approve(approval_command) == evidence
        assert facade.get_current(_current_command(evidence)) == evidence

    assert AccountOwnerAssignmentSubjectV4Model.objects.using(assignment_alias).count() == 1
    assert AccountOwnerAssignmentEvidenceV4Model.objects.using(assignment_alias).count() == 1


def test_facade_outer_rollback_and_committed_policy_revocation_fail_closed(
    assignment_alias: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rollback synthetic creation/policy evidence and reject a revoked policy."""

    record = _seed(assignment_alias, monkeypatch)
    facade = _facade(record, assignment_alias)
    register_command = _register_command(record)

    with pytest.raises(RuntimeError, match="facade outer rollback"):
        with transaction.atomic(using=assignment_alias):
            subject = facade.register(register_command)
            rolled_back = facade.approve(_approve_command(subject, "facade-evidence"))
            assert rolled_back.subject == subject
            raise RuntimeError("facade outer rollback")
    assert AccountOwnerAssignmentSubjectV4Model.objects.using(assignment_alias).count() == 0
    assert AccountOwnerAssignmentEvidenceV4Model.objects.using(assignment_alias).count() == 0

    subject = facade.register(register_command)
    approval_command = _approve_command(subject, "facade-evidence")
    evidence = facade.approve(approval_command)
    assert AccountOwnerAssignmentEvidenceV4Model.objects.using(assignment_alias).count() == 1

    revoked_at = evidence.recorded_at + timedelta(seconds=1)
    monkeypatch.setattr("django.utils.timezone.now", lambda: revoked_at)
    policy = record.evidence.subject.policy
    revoked = replace(
        policy,
        policy_version="revoked",
        status="revoked",
        observed_at=revoked_at,
        identity_hash="",
        content_hash="",
    )
    policy_repository = DjangoSingleOwnerAuthorityPolicyV1Repository(using=assignment_alias)
    with policy_repository.atomic():
        policy_repository.append(
            policy=revoked,
            expected_previous_content_hash=policy.content_hash,
        )

    with pytest.raises(AccountOwnerAssignmentConflict, match="current sources"):
        facade.approve(approval_command)
    assert facade.get_current(replace(_current_command(evidence), as_of=revoked_at)) is None
