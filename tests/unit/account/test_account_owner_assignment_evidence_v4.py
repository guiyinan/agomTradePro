from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from apps.account.domain.account_owner_assignment_evidence import (
    AccountOwnerAssignmentActor,
)
from apps.account.domain.account_owner_assignment_evidence_v4 import (
    ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V4_ARTIFACT_TYPE,
    ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V4_SCHEMA,
    ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V4_ARTIFACT_TYPE,
    ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V4_SCHEMA,
    AccountOwnerAssignmentEvidenceV4,
    AccountOwnerAssignmentSubjectV4,
    resolve_account_owner_assignment_evidence_v4_final,
    validate_account_owner_assignment_evidence_v4_dual_mapping_root,
    validate_account_owner_assignment_evidence_v4_root,
    validate_account_owner_assignment_subject_v4_root,
)
from apps.account.domain.account_owner_assignment_provenance_receipt_v4 import (
    AccountOwnerAssignmentProvenanceReceiptV4,
)
from tests.unit.account.test_account_owner_assignment_provenance_receipt_v3 import (
    _receipt as _v3_receipt,
)
from tests.unit.account.test_account_owner_assignment_provenance_receipt_v4 import (
    _receipt as _v4_receipt,
)


def _at(
    day: int,
    hour: int = 12,
    minute: int = 0,
    second: int = 0,
    microsecond: int = 0,
) -> datetime:
    return datetime(2026, 8, day, hour, minute, second, microsecond, tzinfo=UTC)


def _subject(
    receipt: AccountOwnerAssignmentProvenanceReceiptV4 | None = None,
    **changes: object,
) -> AccountOwnerAssignmentSubjectV4:
    value = receipt or _v4_receipt()
    binding = value.binding
    root = binding.creation_root
    physical = root.physical_observation
    values: dict[str, object] = {
        "subject_id": "creation-subject-7",
        "subject_version": "v4.1",
        "receipt": value,
        "binding": binding,
        "physical_root": root,
        "receipt_identity_hash": value.identity_hash,
        "receipt_content_hash": value.content_hash,
        "policy_identity_hash": value.policy.identity_hash,
        "policy_content_hash": value.policy.content_hash,
        "binding_identity_hash": binding.identity_hash,
        "binding_content_hash": binding.content_hash,
        "allocation_identity_hash": binding.allocation.identity_hash,
        "allocation_content_hash": binding.allocation.content_hash,
        "creation_root_identity_hash": root.identity_hash,
        "creation_root_content_hash": root.content_hash,
        "account_claim_hash": binding.account_claim_hash,
        "underlying_claim_hash": binding.underlying_claim_hash,
        "physical_observation_content_hash": physical.content_hash,
        "physical_source_content_hash": physical.source_content_hash,
        "physical_raw_observation_content_hash": physical.raw_observation_content_hash,
        "requested_at": value.recorded_at + timedelta(hours=1),
        "valid_until": min(value.valid_until, value.policy.valid_until, root.valid_until),
    }
    values.update(changes)
    return AccountOwnerAssignmentSubjectV4(**values)  # type: ignore[arg-type]


def _evidence(
    subject: AccountOwnerAssignmentSubjectV4 | None = None,
    **changes: object,
) -> AccountOwnerAssignmentEvidenceV4:
    value = subject or _subject()
    claimant = value.claimant
    approved_at = value.requested_at + timedelta(hours=1)
    recorded_at = approved_at + timedelta(hours=1)
    approval_valid_until = value.valid_until + timedelta(days=1)
    values: dict[str, object] = {
        "evidence_id": "creation-evidence-7",
        "evidence_version": "v4.1",
        "subject": value,
        "policy_identity_hash": value.policy.identity_hash,
        "policy_content_hash": value.policy.content_hash,
        "assigned_owner_user_id": claimant.user_id,
        "approved_by": AccountOwnerAssignmentActor(
            claimant.actor_id,
            claimant.user_id,
            "account_owner_assignment_approver",
            is_staff=True,
        ),
        "approved_at": approved_at,
        "recorded_at": recorded_at,
        "approval_valid_until": approval_valid_until,
        "valid_until": min(value.valid_until, approval_valid_until),
        "account_claim_hash": value.account_claim_hash,
        "underlying_claim_hash": value.underlying_claim_hash,
    }
    values.update(changes)
    return AccountOwnerAssignmentEvidenceV4(**values)  # type: ignore[arg-type]


def test_subject_binds_complete_v4_receipt_graph_and_is_inactive() -> None:
    subject = _subject()
    payload = subject.to_payload()

    assert subject.owner == "account"
    assert subject.artifact_type == ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V4_ARTIFACT_TYPE
    assert subject.schema == ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V4_SCHEMA
    assert subject.policy == subject.receipt.policy
    assert subject.claimant == subject.receipt.claimant
    assert subject.activation_available is False
    assert subject.must_not_execute is True
    assert not hasattr(subject, "__dict__")
    assert payload["receipt"] == subject.receipt.to_payload()
    assert payload["binding"] == subject.binding.to_payload()
    assert payload["physical_root"] == subject.physical_root.to_payload()
    assert payload["policy_identity_hash"] == subject.policy.identity_hash
    assert payload["policy_content_hash"] == subject.policy.content_hash
    assert payload["requested_at"] == "2026-08-08T15:00:00.000000Z"
    assert len(subject.identity_hash) == len(subject.content_hash) == 64

    with pytest.raises(FrozenInstanceError):
        subject.subject_version = "v4.2"  # type: ignore[misc]


@pytest.mark.parametrize(
    "field_name",
    [
        "receipt_identity_hash",
        "receipt_content_hash",
        "policy_identity_hash",
        "policy_content_hash",
        "binding_identity_hash",
        "binding_content_hash",
        "allocation_identity_hash",
        "allocation_content_hash",
        "creation_root_identity_hash",
        "creation_root_content_hash",
        "account_claim_hash",
        "underlying_claim_hash",
        "physical_observation_content_hash",
        "physical_source_content_hash",
        "physical_raw_observation_content_hash",
    ],
)
def test_subject_explicit_seals_reject_upstream_replacement(field_name: str) -> None:
    with pytest.raises(ValueError, match="upstream evidence"):
        _subject(**{field_name: "0" * 64})


def test_subject_rejects_policy_hash_or_graph_scope_substitution() -> None:
    value = _v4_receipt()
    with pytest.raises(ValueError, match="policy hash|upstream evidence"):
        _subject(policy_identity_hash="0" * 64)
    with pytest.raises(ValueError, match="policy hash|upstream evidence"):
        _subject(policy_content_hash="0" * 64)
    with pytest.raises(TypeError, match="exact.*Binding"):
        _subject(binding=cast(object, object()))

    object.__setattr__(value.policy, "tenant_id", "tenant-other")
    with pytest.raises(ValueError, match="content_hash"):
        _subject(value)


def test_subject_rejects_future_expired_or_revoked_source_facts() -> None:
    value = _v4_receipt()
    with pytest.raises(ValueError, match="clock sequence"):
        _subject(value, requested_at=value.valid_until)

    object.__setattr__(value.policy, "status", "revoked")
    with pytest.raises(ValueError, match="content_hash"):
        _subject(value)


def test_subject_current_boundary_and_exact_root_validator_are_fail_closed() -> None:
    subject = _subject()
    validate_account_owner_assignment_subject_v4_root(subject)
    assert subject.is_current_at(subject.requested_at) is True
    assert subject.is_current_at(subject.valid_until) is False
    with pytest.raises(ValueError, match="timezone-aware"):
        subject.is_current_at(datetime(2026, 8, 8, 15))
    with pytest.raises(TypeError, match="exact.*v4"):
        validate_account_owner_assignment_subject_v4_root(
            cast(AccountOwnerAssignmentSubjectV4, object())
        )


def test_evidence_accepts_same_real_staff_admin_in_both_distinct_roles() -> None:
    evidence = _evidence()
    payload = evidence.to_payload()

    assert evidence.owner == "account"
    assert evidence.artifact_type == ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V4_ARTIFACT_TYPE
    assert evidence.schema == ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V4_SCHEMA
    assert evidence.claimant.actor_id == evidence.approved_by.actor_id
    assert evidence.claimant.user_id == evidence.approved_by.user_id == 42
    assert evidence.claimant.role != evidence.approved_by.role
    assert evidence.claimant.is_staff is evidence.approved_by.is_staff is True
    assert evidence.policy_identity_hash == evidence.policy.identity_hash
    assert evidence.policy_content_hash == evidence.policy.content_hash
    assert evidence.requested_at == evidence.subject.requested_at
    assert evidence.permission == "evidence_only"
    assert evidence.status == "inactive"
    assert evidence.assignment_state == "authoritative"
    assert evidence.activation_available is False
    assert evidence.must_not_execute is True
    assert payload["subject"] == evidence.subject.to_payload()
    assert payload["approved_by"] == evidence.approved_by.to_payload()
    assert payload["approved_at"] == "2026-08-08T16:00:00.000000Z"
    assert len(evidence.identity_hash) == len(evidence.content_hash) == 64
    validate_account_owner_assignment_evidence_v4_root(evidence)

    with pytest.raises(FrozenInstanceError):
        evidence.status = "active"  # type: ignore[misc]


@pytest.mark.parametrize(
    "approved_by",
    [
        AccountOwnerAssignmentActor(
            "different-actor", 42, "account_owner_assignment_approver", is_staff=True
        ),
        AccountOwnerAssignmentActor(
            "django-user:42", 43, "account_owner_assignment_approver", is_staff=True
        ),
        AccountOwnerAssignmentActor("django-user:42", 42, "account_owner_claimant", is_staff=True),
        AccountOwnerAssignmentActor(
            "django-user:42", 42, "account_owner_assignment_approver", is_staff=False
        ),
    ],
)
def test_evidence_rejects_second_identity_wrong_role_or_false_staff(
    approved_by: AccountOwnerAssignmentActor,
) -> None:
    with pytest.raises(ValueError, match="same current staff owner"):
        _evidence(approved_by=approved_by)


def test_evidence_rejects_wrong_policy_seals_owner_and_scope() -> None:
    evidence = _evidence()
    with pytest.raises(ValueError, match="upstream evidence"):
        replace(evidence, policy_identity_hash="0" * 64, identity_hash="", content_hash="")
    with pytest.raises(ValueError, match="upstream evidence"):
        replace(evidence, policy_content_hash="0" * 64, identity_hash="", content_hash="")
    with pytest.raises(ValueError, match="owner"):
        _evidence(assigned_owner_user_id=7)
    with pytest.raises(ValueError, match="upstream evidence"):
        _evidence(account_claim_hash="0" * 64)
    with pytest.raises(ValueError, match="upstream evidence"):
        _evidence(underlying_claim_hash="0" * 64)


@pytest.mark.parametrize(
    "changes",
    [
        {"approved_at": _at(8, 14, 59)},
        {"recorded_at": _at(13)},
        {"approval_valid_until": _at(8, 16, 59)},
        {"valid_until": _at(13, 12, 1)},
    ],
)
def test_evidence_preserves_source_clock_order_and_validity_boundaries(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="clock|validity|expired|current subject"):
        _evidence(**changes)

    evidence = _evidence()
    assert evidence.is_knowable_at(evidence.recorded_at) is True
    assert evidence.is_current_at(evidence.recorded_at) is True
    assert evidence.is_current_at(evidence.valid_until) is False
    assert evidence.is_knowable_at(evidence.valid_until + timedelta(days=1)) is True


def test_evidence_final_resolver_is_root_only_and_never_changes_old_v3() -> None:
    evidence = _evidence()
    assert (
        resolve_account_owner_assignment_evidence_v4_final((), as_of=evidence.recorded_at) is None
    )
    assert (
        resolve_account_owner_assignment_evidence_v4_final(
            (evidence,), as_of=evidence.recorded_at - timedelta(microseconds=1)
        )
        is None
    )
    assert (
        resolve_account_owner_assignment_evidence_v4_final(
            (evidence,), as_of=evidence.valid_until + timedelta(days=1)
        )
        is evidence
    )
    with pytest.raises(ValueError, match="successors"):
        resolve_account_owner_assignment_evidence_v4_final(
            (
                evidence,
                replace(evidence, evidence_version="v4.2", identity_hash="", content_hash=""),
            ),
            as_of=evidence.recorded_at,
        )
    with pytest.raises(TypeError, match="exact tuple"):
        resolve_account_owner_assignment_evidence_v4_final(  # type: ignore[arg-type]
            [evidence], as_of=evidence.recorded_at
        )

    old = _v3_receipt()
    assert old.identity_hash == "7cff67d26781585ccb84b1f1a283c780302d7927a6394ced48a3c5843b4a4602"
    assert old.content_hash == "074949ccfe8d470b3058c18b458a0bbf54029d69bca1d1e3c234b7f3564ba1d1"
    with pytest.raises(ValueError, match="non-staff"):
        _v3_receipt(
            claimant=AccountOwnerAssignmentActor(
                "django-user:42", 42, "account_owner_claimant", is_staff=True
            )
        )


def test_evidence_mapping_roots_are_explicit_and_candidate_independent() -> None:
    evidence = _evidence()
    validate_account_owner_assignment_evidence_v4_dual_mapping_root(
        evidence,
        account_claim_hash=evidence.account_claim_hash,
        underlying_claim_hash=evidence.underlying_claim_hash,
    )
    with pytest.raises(ValueError, match="dual mapping"):
        validate_account_owner_assignment_evidence_v4_dual_mapping_root(
            evidence,
            account_claim_hash="0" * 64,
            underlying_claim_hash=evidence.underlying_claim_hash,
        )


def test_evidence_fixed_semantics_and_hash_tamper_are_closed() -> None:
    for changes in (
        {"assignment_state": "legacy_default"},
        {"permission": "execution_eligible"},
        {"status": "active"},
        {"blocker_codes": ()},
        {"artifact_type": "account_owner_assignment_evidence_v3"},
    ):
        with pytest.raises(ValueError, match="fixed"):
            _evidence(**changes)

    with pytest.raises(ValueError, match="identity_hash"):
        _evidence(identity_hash="0" * 64)
    with pytest.raises(ValueError, match="content_hash"):
        _evidence(content_hash="0" * 64)


def test_v4_domain_module_is_pure_and_does_not_modify_v3() -> None:
    source_path = (
        Path(__file__).parents[3]
        / "apps"
        / "account"
        / "domain"
        / "account_owner_assignment_evidence_v4.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}

    assert "apps.account.domain.account_owner_assignment_evidence_v3" not in imports
    assert "apps.account.domain.account_owner_assignment_provenance_receipt_v3" not in imports
    assert not any(name.startswith(("django", "pandas", "numpy", "requests")) for name in imports)
    assert imports <= {
        "__future__",
        "apps.account.domain.account_owner_assignment_evidence",
        "apps.account.domain.account_owner_assignment_provenance_receipt_v4",
        "apps.account.domain.allocated_physical_account_row_observation_v3",
        "apps.account.domain.canonical_account_creation_binding_v2",
        "apps.account.domain.single_owner_authority_policy_v1",
        "dataclasses",
        "datetime",
        "hashlib",
        "json",
    }
