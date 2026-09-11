"""Domain contract tests for re-observation-backed EvidenceV5."""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from apps.account.domain.account_owner_assignment_evidence import AccountOwnerAssignmentActor
from apps.account.domain.account_owner_assignment_evidence_v5 import (
    ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_ARTIFACT_TYPE,
    ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_SCHEMA,
    AccountOwnerAssignmentEvidenceV5,
    resolve_account_owner_assignment_evidence_v5_final,
    validate_account_owner_assignment_evidence_v5_dual_mapping_root,
    validate_account_owner_assignment_evidence_v5_root,
)
from apps.account.domain.account_owner_assignment_subject_v5 import AccountOwnerAssignmentSubjectV5
from tests.unit.account.test_account_owner_assignment_subject_v5 import _subject


def _at(day: int, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(2026, 8, day, hour, minute, tzinfo=UTC)


def _evidence(
    subject: AccountOwnerAssignmentSubjectV5 | None = None,
    **changes: object,
) -> AccountOwnerAssignmentEvidenceV5:
    value = subject or _subject()
    claimant = value.claimant
    approved_at = value.requested_at + timedelta(minutes=5)
    recorded_at = approved_at + timedelta(minutes=5)
    approval_valid_until = value.valid_until + timedelta(minutes=30)
    values: dict[str, object] = {
        "evidence_id": "ownership-evidence-v5-7",
        "evidence_version": "v5.1",
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
    return AccountOwnerAssignmentEvidenceV5(**values)  # type: ignore[arg-type]


def test_v5_accepts_same_real_staff_owner_and_remains_inactive() -> None:
    evidence = _evidence()
    payload = evidence.to_payload()

    assert evidence.artifact_type == ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_ARTIFACT_TYPE
    assert evidence.schema == ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_SCHEMA
    assert evidence.claimant.actor_id == evidence.approved_by.actor_id
    assert evidence.claimant.user_id == evidence.approved_by.user_id == 42
    assert evidence.claimant.role != evidence.approved_by.role
    assert evidence.claimant.is_staff is evidence.approved_by.is_staff is True
    assert evidence.policy is evidence.subject.policy
    assert evidence.requested_at == evidence.subject.requested_at
    assert evidence.permission == "evidence_only"
    assert evidence.status == "inactive"
    assert evidence.assignment_state == "authoritative"
    assert evidence.activation_available is False
    assert evidence.must_not_execute is True
    assert evidence.is_knowable_at(evidence.recorded_at) is True
    assert evidence.is_current_at(evidence.recorded_at) is True
    assert evidence.is_current_at(evidence.valid_until) is False
    assert payload["subject"] == evidence.subject.to_payload()
    assert payload["approved_by"] == evidence.approved_by.to_payload()
    assert payload["activation_available"] is False
    assert payload["must_not_execute"] is True
    assert len(evidence.identity_hash) == len(evidence.content_hash) == 64
    assert evidence.identity_hash != evidence.subject.identity_hash
    assert evidence.content_hash != evidence.subject.content_hash
    assert not hasattr(evidence, "__dict__")
    validate_account_owner_assignment_evidence_v5_root(evidence)
    validate_account_owner_assignment_evidence_v5_dual_mapping_root(
        evidence,
        account_claim_hash=evidence.account_claim_hash,
        underlying_claim_hash=evidence.underlying_claim_hash,
    )
    with pytest.raises(FrozenInstanceError):
        evidence.status = "active"  # type: ignore[misc]


def test_v5_uses_current_reobservation_after_the_creation_root_expires() -> None:
    evidence = _evidence()

    assert evidence.subject.binding.creation_root.is_knowable_at(evidence.recorded_at) is False
    assert evidence.subject.reobservation.is_current_at(evidence.recorded_at) is True
    assert evidence.is_current_at(evidence.recorded_at) is True


def test_v5_current_cutoff_and_shorter_approval_validity_are_exact() -> None:
    subject = _subject()
    approval_valid_until = subject.valid_until - timedelta(minutes=5)
    evidence = _evidence(
        subject,
        approval_valid_until=approval_valid_until,
        valid_until=approval_valid_until,
    )

    assert evidence.valid_until == approval_valid_until
    assert evidence.is_current_at(approval_valid_until - timedelta(microseconds=1)) is True
    assert evidence.is_current_at(approval_valid_until) is False
    with pytest.raises(ValueError, match="timezone-aware"):
        evidence.is_current_at(approval_valid_until.replace(tzinfo=None))


def test_v5_fields_are_closed_and_versioned() -> None:
    assert {field.name for field in fields(AccountOwnerAssignmentEvidenceV5)} == {
        "evidence_id",
        "evidence_version",
        "subject",
        "policy_identity_hash",
        "policy_content_hash",
        "assigned_owner_user_id",
        "approved_by",
        "approved_at",
        "recorded_at",
        "approval_valid_until",
        "valid_until",
        "account_claim_hash",
        "underlying_claim_hash",
        "identity_hash",
        "content_hash",
        "owner",
        "artifact_type",
        "schema",
        "assignment_state",
        "permission",
        "status",
        "blocker_codes",
    }


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
def test_v5_rejects_second_identity_wrong_role_or_false_staff(
    approved_by: AccountOwnerAssignmentActor,
) -> None:
    with pytest.raises(ValueError, match="same current staff owner"):
        _evidence(approved_by=approved_by)


@pytest.mark.parametrize(
    "changes, error_type, message",
    [
        ({"approved_by": object()}, TypeError, "approved_by"),
        ({"assigned_owner_user_id": True}, TypeError, "positive integer"),
        ({"assigned_owner_user_id": 0}, ValueError, "positive integer|owner"),
        ({"assigned_owner_user_id": 7}, ValueError, "owner"),
        ({"policy_identity_hash": "0" * 64}, ValueError, "upstream evidence"),
        ({"policy_content_hash": "0" * 64}, ValueError, "upstream evidence"),
        ({"account_claim_hash": "0" * 64}, ValueError, "upstream evidence"),
        ({"underlying_claim_hash": "0" * 64}, ValueError, "upstream evidence"),
        ({"evidence_id": "bad id"}, ValueError, "token"),
        ({"evidence_version": 5}, TypeError, "exact string"),
    ],
)
def test_v5_rejects_type_identity_and_source_substitution(
    changes: dict[str, object], error_type: type[Exception], message: str
) -> None:
    with pytest.raises(error_type, match=message):
        _evidence(**changes)


def test_v5_rejects_cross_version_or_untyped_subject() -> None:
    with pytest.raises(TypeError, match="subject.*v5"):
        replace(
            _evidence(),
            subject=cast(AccountOwnerAssignmentSubjectV5, object()),
            identity_hash="",
            content_hash="",
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"approved_at": _at(15, 14, 29)},
        {"recorded_at": _at(15, 14, 34)},
        {"approval_valid_until": _at(15, 14, 40)},
        {"valid_until": _at(15, 14, 59)},
        {"approved_at": datetime(2026, 8, 15, 14, 35)},
    ],
)
def test_v5_rejects_invalid_clock_or_validity(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="clock|validity|expired|timezone-aware|current subject"):
        _evidence(**changes)


@pytest.mark.parametrize(
    "field_name,bad_value,error_type",
    [
        ("owner", "research", ValueError),
        ("artifact_type", "account_owner_assignment_evidence_v4", ValueError),
        ("schema", "account-owner-assignment-evidence.v4", ValueError),
        ("assignment_state", "pending", ValueError),
        ("permission", "trade", ValueError),
        ("status", "active", ValueError),
        ("blocker_codes", (), ValueError),
        ("blocker_codes", ["account_owner_assignment_evidence_v5_not_integrated"], TypeError),
        ("owner", 1, TypeError),
    ],
)
def test_v5_fixed_semantics_fail_closed(
    field_name: str, bad_value: object, error_type: type[Exception]
) -> None:
    with pytest.raises(error_type, match="fixed|exact tuple|exact string"):
        _evidence(**{field_name: bad_value})


def test_v5_hash_and_nested_subject_tamper_fail_closed() -> None:
    evidence = _evidence()
    with pytest.raises(ValueError, match="identity_hash"):
        replace(evidence, identity_hash="0" * 64)
    with pytest.raises(ValueError, match="content_hash"):
        replace(evidence, content_hash="0" * 64)
    object.__setattr__(evidence.subject, "content_hash", "0" * 64)
    with pytest.raises(ValueError, match="content_hash"):
        evidence.to_payload()


def test_v5_dual_mapping_and_exact_type_guards() -> None:
    evidence = _evidence()
    with pytest.raises(ValueError, match="dual mapping"):
        validate_account_owner_assignment_evidence_v5_dual_mapping_root(
            evidence,
            account_claim_hash="0" * 64,
            underlying_claim_hash=evidence.underlying_claim_hash,
        )
    with pytest.raises(ValueError, match="lowercase"):
        validate_account_owner_assignment_evidence_v5_dual_mapping_root(
            evidence,
            account_claim_hash="bad",
            underlying_claim_hash=evidence.underlying_claim_hash,
        )
    with pytest.raises(TypeError, match="exact.*v5"):
        validate_account_owner_assignment_evidence_v5_root(
            cast(AccountOwnerAssignmentEvidenceV5, object())
        )


def test_v5_final_resolver_is_historical_root_only() -> None:
    evidence = _evidence()
    assert (
        resolve_account_owner_assignment_evidence_v5_final((), as_of=evidence.recorded_at) is None
    )
    assert (
        resolve_account_owner_assignment_evidence_v5_final(
            (evidence,), as_of=evidence.recorded_at - timedelta(microseconds=1)
        )
        is None
    )
    assert (
        resolve_account_owner_assignment_evidence_v5_final(
            (evidence,), as_of=evidence.valid_until + timedelta(days=1)
        )
        is evidence
    )
    with pytest.raises(ValueError, match="successors"):
        resolve_account_owner_assignment_evidence_v5_final(
            (
                evidence,
                replace(evidence, evidence_version="v5.2", identity_hash="", content_hash=""),
            ),
            as_of=evidence.recorded_at,
        )
    with pytest.raises(TypeError, match="exact tuple"):
        resolve_account_owner_assignment_evidence_v5_final(  # type: ignore[arg-type]
            [evidence], as_of=evidence.recorded_at
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        resolve_account_owner_assignment_evidence_v5_final(
            (evidence,), as_of=evidence.recorded_at.replace(tzinfo=None)
        )


def test_v5_domain_imports_only_standard_library_and_domain_modules() -> None:
    path = Path("apps/account/domain/account_owner_assignment_evidence_v5.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    )
    assert imports <= {"__future__", "hashlib", "json", "dataclasses", "datetime", "apps"}
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "apps.account.domain.account_owner_assignment_evidence_v4" not in imported_modules
