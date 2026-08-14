from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest

from apps.account.domain.account_owner_assignment_evidence import AccountOwnerAssignmentActor
from apps.account.domain.account_owner_assignment_evidence_v3 import (
    AccountOwnerAssignmentEvidenceV3,
    AccountOwnerAssignmentSubjectV3,
    resolve_account_owner_assignment_evidence_v3_final,
    validate_account_owner_assignment_evidence_v3_dual_mapping_root,
    validate_account_owner_assignment_evidence_v3_root,
)
from apps.account.domain.account_owner_assignment_provenance_receipt_v3 import (
    AccountOwnerAssignmentProvenanceReceiptV3,
)
from tests.unit.account.test_account_owner_assignment_provenance_receipt_v3 import _receipt


def _subject(
    receipt: AccountOwnerAssignmentProvenanceReceiptV3 | None = None, **changes: object
) -> AccountOwnerAssignmentSubjectV3:
    value = receipt or _receipt()
    requested_at = value.recorded_at + timedelta(hours=1)
    binding = value.binding
    root = binding.creation_root
    physical = root.physical_observation
    values: dict[str, object] = {
        "subject_id": "creation-subject-7",
        "subject_version": "v3.1",
        "receipt": value,
        "binding": binding,
        "physical_root": root,
        "receipt_identity_hash": value.identity_hash,
        "receipt_content_hash": value.content_hash,
        "binding_identity_hash": binding.identity_hash,
        "binding_content_hash": binding.content_hash,
        "creation_root_identity_hash": root.identity_hash,
        "creation_root_content_hash": root.content_hash,
        "account_claim_hash": binding.account_claim_hash,
        "underlying_claim_hash": binding.underlying_claim_hash,
        "physical_observation_content_hash": physical.content_hash,
        "physical_source_content_hash": physical.source_content_hash,
        "physical_raw_observation_content_hash": physical.raw_observation_content_hash,
        "requested_at": requested_at,
        "valid_until": min(value.valid_until, value.binding.creation_root.valid_until),
    }
    values.update(changes)
    return AccountOwnerAssignmentSubjectV3(**values)  # type: ignore[arg-type]


def _evidence(
    subject: AccountOwnerAssignmentSubjectV3 | None = None, **changes: object
) -> AccountOwnerAssignmentEvidenceV3:
    value = subject or _subject()
    approved_at = value.requested_at + timedelta(hours=1)
    recorded_at = approved_at + timedelta(hours=1)
    approval_valid_until = value.valid_until + timedelta(days=1)
    values: dict[str, object] = {
        "evidence_id": "creation-evidence-7",
        "evidence_version": "v3.1",
        "subject": value,
        "assigned_owner_user_id": value.claimant.user_id,
        "approved_by": AccountOwnerAssignmentActor(
            "staff-approver-9", 9, "account_owner_assignment_approver", is_staff=True
        ),
        "approved_at": approved_at,
        "recorded_at": recorded_at,
        "approval_valid_until": approval_valid_until,
        "valid_until": min(value.valid_until, approval_valid_until),
    }
    values.update(changes)
    return AccountOwnerAssignmentEvidenceV3(**values)  # type: ignore[arg-type]


def test_subject_revalidates_exact_receipt_binding_and_physical_root() -> None:
    subject = _subject()
    assert subject.receipt.binding == subject.binding
    assert subject.binding.creation_root == subject.physical_root
    assert subject.claimant == subject.receipt.claimant
    assert subject.activation_available is False
    assert subject.must_not_execute is True
    with pytest.raises((TypeError, ValueError), match="exact|bind"):
        _subject(binding=cast(object, object()))
    with pytest.raises(ValueError, match="validity"):
        _subject(valid_until=subject.valid_until - timedelta(seconds=1))


@pytest.mark.parametrize(
    "field_name",
    [
        "receipt_identity_hash",
        "receipt_content_hash",
        "binding_identity_hash",
        "binding_content_hash",
        "creation_root_identity_hash",
        "creation_root_content_hash",
        "account_claim_hash",
        "underlying_claim_hash",
        "physical_observation_content_hash",
        "physical_source_content_hash",
        "physical_raw_observation_content_hash",
    ],
)
def test_subject_explicit_upstream_seals_fail_closed(field_name: str) -> None:
    with pytest.raises(ValueError, match="exact upstream evidence"):
        _subject(**{field_name: "0" * 64})


def test_staff_approval_is_independent_and_owner_equals_claimant() -> None:
    evidence = _evidence()
    assert evidence.assignment_state == "authoritative"
    assert evidence.assigned_owner_user_id == evidence.subject.claimant.user_id
    assert evidence.approved_by.is_staff is True
    for approver in (
        AccountOwnerAssignmentActor(
            evidence.subject.claimant.actor_id,
            9,
            "account_owner_assignment_approver",
            is_staff=True,
        ),
        AccountOwnerAssignmentActor(
            "other-actor",
            evidence.subject.claimant.user_id,
            "account_owner_assignment_approver",
            is_staff=True,
        ),
    ):
        with pytest.raises(ValueError, match="distinct"):
            _evidence(approved_by=approver)
    with pytest.raises(ValueError, match="authoritative owner"):
        _evidence(assigned_owner_user_id=999)
    with pytest.raises(ValueError, match="human staff"):
        _evidence(
            approved_by=AccountOwnerAssignmentActor(
                "human-approver", 9, "account_owner_assignment_approver"
            )
        )


def test_dual_mapping_roots_are_domain_separated_and_candidate_independent() -> None:
    first = _evidence()
    second = _evidence(
        evidence_id="another-candidate",
        evidence_version="v3.2",
        approved_by=AccountOwnerAssignmentActor(
            "staff-approver-10", 10, "account_owner_assignment_approver", is_staff=True
        ),
    )
    assert first.account_claim_hash == second.account_claim_hash
    assert first.underlying_claim_hash == second.underlying_claim_hash
    assert first.account_claim_hash != first.underlying_claim_hash
    validate_account_owner_assignment_evidence_v3_dual_mapping_root(
        first,
        account_claim_hash=first.account_claim_hash,
        underlying_claim_hash=first.underlying_claim_hash,
    )
    with pytest.raises(ValueError, match="dual mapping"):
        validate_account_owner_assignment_evidence_v3_dual_mapping_root(
            first,
            account_claim_hash="0" * 64,
            underlying_claim_hash=first.underlying_claim_hash,
        )


def test_evidence_is_frozen_inactive_non_executable_and_root_only() -> None:
    evidence = _evidence()
    validate_account_owner_assignment_evidence_v3_root(evidence)
    assert evidence.permission == "evidence_only"
    assert evidence.status == "inactive"
    assert evidence.activation_available is False
    assert evidence.must_not_execute is True
    assert not hasattr(evidence, "supersedes_content_hash")
    with pytest.raises(FrozenInstanceError):
        evidence.status = "active"  # type: ignore[misc]
    for changes in (
        {"assignment_state": "legacy_default"},
        {"permission": "execution_eligible"},
        {"status": "active"},
        {"blocker_codes": ()},
    ):
        with pytest.raises(ValueError, match="fixed"):
            _evidence(**changes)


def test_historical_final_is_permanent_and_never_accepts_successors() -> None:
    evidence = _evidence()
    before = evidence.recorded_at - timedelta(microseconds=1)
    after_expiry = evidence.valid_until + timedelta(days=10)
    assert resolve_account_owner_assignment_evidence_v3_final((evidence,), as_of=before) is None
    assert (
        resolve_account_owner_assignment_evidence_v3_final((evidence,), as_of=after_expiry)
        is evidence
    )
    assert evidence.is_current_at(after_expiry) is False
    with pytest.raises(ValueError, match="successors"):
        resolve_account_owner_assignment_evidence_v3_final(
            (
                evidence,
                replace(evidence, evidence_version="v3.2", identity_hash="", content_hash=""),
            ),
            as_of=after_expiry,
        )


def test_domain_does_not_import_prior_receipt_or_evidence_generations() -> None:
    source_path = (
        Path(__file__).parents[3]
        / "apps"
        / "account"
        / "domain"
        / "account_owner_assignment_evidence_v3.py"
    )
    imported = {
        node.module
        for node in ast.walk(ast.parse(source_path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "apps.account.domain.account_owner_assignment_provenance_receipt_v2" not in imported
    assert "apps.account.domain.account_owner_assignment_evidence_v2" not in imported
