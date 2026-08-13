from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.account.domain.account_owner_assignment_evidence import (
    AccountOwnerAssignmentActor,
    AccountOwnerAssignmentEvidence,
)
from apps.account.domain.account_owner_assignment_evidence_v2 import (
    AccountOwnerAssignmentEvidenceV2,
    AccountOwnerAssignmentSubjectV2,
    resolve_account_owner_assignment_evidence_v2_head,
    validate_account_owner_assignment_evidence_v2_root,
    validate_account_owner_assignment_evidence_v2_successor,
)
from tests.unit.account.test_account_owner_assignment_provenance_receipt_v2 import (
    _receipt,
    _row,
)


def _at(day: int) -> datetime:
    return datetime(2026, 8, day, 12, tzinfo=UTC)


def _subject(**changes: object) -> AccountOwnerAssignmentSubjectV2:
    row = changes.pop("physical", _row())
    receipt = changes.pop("receipt", _receipt(row))
    values: dict[str, object] = {
        "subject_id": "subject-7",
        "subject_version": "v1",
        "physical": row,
        "receipt": receipt,
        "requested_at": _at(7),
        "valid_until": _at(9),
    }
    values.update(changes)
    return AccountOwnerAssignmentSubjectV2(**values)  # type: ignore[arg-type]


def _evidence(**changes: object) -> AccountOwnerAssignmentEvidenceV2:
    subject = changes.pop("subject", _subject())
    values: dict[str, object] = {
        "evidence_id": "assignment-7",
        "evidence_version": "v1",
        "subject": subject,
        "assignment_state": "authoritative",
        "assigned_owner_user_id": 8,
        "approved_by": AccountOwnerAssignmentActor(
            "approver-9", 9, "account_owner_assignment_approver", is_staff=True
        ),
        "approved_at": _at(7),
        "recorded_at": _at(8),
        "approval_valid_until": _at(9),
        "valid_until": _at(9),
    }
    values.update(changes)
    return AccountOwnerAssignmentEvidenceV2(**values)  # type: ignore[arg-type]


def test_subject_and_evidence_seal_all_upstream_layers() -> None:
    value = _evidence()
    payload = value.to_payload()
    assert payload["physical_content_hash"] == value.subject.physical.content_hash
    assert payload["physical_source_content_hash"] == value.subject.physical.source_content_hash
    assert (
        payload["physical_raw_content_hash"] == value.subject.physical.raw_observation_content_hash
    )
    assert payload["receipt_content_hash"] == value.subject.receipt.content_hash
    assert value.activation_available is False and value.must_not_execute is True


def test_subject_rejects_v1_substitution() -> None:
    with pytest.raises(TypeError, match="v1 substitution"):
        _subject(receipt=object())


@pytest.mark.parametrize(
    ("actor", "message"),
    [
        (
            AccountOwnerAssignmentActor(
                "human-8", 10, "account_owner_assignment_approver", is_staff=True
            ),
            "distinct",
        ),
        (
            AccountOwnerAssignmentActor(
                "approver-10", 8, "account_owner_assignment_approver", is_staff=True
            ),
            "distinct",
        ),
        (AccountOwnerAssignmentActor("approver-10", 10, "wrong", is_staff=True), "approver"),
        (
            AccountOwnerAssignmentActor("approver-10", 10, "account_owner_assignment_approver"),
            "approver",
        ),
    ],
)
def test_independent_staff_approval_is_mandatory(
    actor: AccountOwnerAssignmentActor, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _evidence(approved_by=actor)


@pytest.mark.parametrize(
    ("state", "owner"),
    [("claimed_owner", None), ("claimed_owner", 9), ("legacy_default", 8)],
)
def test_claimed_owner_can_only_become_exact_authoritative_owner(
    state: str, owner: int | None
) -> None:
    with pytest.raises(ValueError, match="claimed owner"):
        _evidence(assignment_state=state, assigned_owner_user_id=owner)


def test_legacy_claim_becomes_ownerless_legacy_default() -> None:
    row = _row()
    reviewer = AccountOwnerAssignmentActor(
        "reviewer-11", 11, "legacy_assignment_reviewer", is_staff=True
    )
    receipt = _receipt(
        row,
        provenance_kind="migration",
        assignment_state="legacy_default_claim",
        assigned_owner_user_id=None,
        claimant=reviewer,
    )
    subject = _subject(physical=row, receipt=receipt)
    value = _evidence(
        subject=subject, assignment_state="legacy_default", assigned_owner_user_id=None
    )
    assert value.assignment_state == "legacy_default" and value.assigned_owner_user_id is None


def test_approval_ttl_can_shorten_but_never_extend_upstream_validity() -> None:
    value = _evidence(
        approval_valid_until=_at(8) + timedelta(hours=12),
        valid_until=_at(8) + timedelta(hours=12),
    )
    assert value.valid_until < value.subject.valid_until
    with pytest.raises(ValueError, match="minimum"):
        replace(value, valid_until=value.subject.valid_until, content_hash="")


@pytest.mark.parametrize("field", ["content_hash", "identity_hash"])
def test_subject_tamper_is_detected(field: str) -> None:
    subject = _subject()
    with pytest.raises(ValueError, match=field):
        replace(subject, **{field: "0" * 64})


@pytest.mark.parametrize(
    "field", ["content_hash", "identity_hash", "account_claim_hash", "underlying_claim_hash"]
)
def test_evidence_tamper_is_detected(field: str) -> None:
    value = _evidence()
    with pytest.raises(ValueError, match=field):
        replace(value, **{field: "0" * 64})


def test_dual_roots_are_domain_separated_and_candidate_independent() -> None:
    first = _evidence()
    alternate = _evidence(
        evidence_id="assignment-other",
        approved_by=AccountOwnerAssignmentActor(
            "approver-10", 10, "account_owner_assignment_approver", is_staff=True
        ),
    )
    assert first.account_claim_hash == alternate.account_claim_hash
    assert first.underlying_claim_hash == alternate.underlying_claim_hash
    assert first.account_claim_hash != first.underlying_claim_hash


def _successor(previous: AccountOwnerAssignmentEvidenceV2) -> AccountOwnerAssignmentEvidenceV2:
    subject = replace(
        previous.subject,
        subject_version="v2",
        identity_hash="",
        content_hash="",
    )
    return replace(
        previous,
        evidence_version="v2",
        subject=subject,
        recorded_at=previous.recorded_at + timedelta(minutes=1),
        supersedes_content_hash=previous.content_hash,
        identity_hash="",
        content_hash="",
    )


def test_root_and_successor_bind_exact_predecessor_and_both_mappings() -> None:
    root = _evidence()
    successor = _successor(root)
    validate_account_owner_assignment_evidence_v2_root(root)
    validate_account_owner_assignment_evidence_v2_successor(root, successor)


@pytest.mark.parametrize(
    "change",
    [
        {"supersedes_content_hash": "0" * 64},
        {"evidence_id": "branch"},
        {"evidence_version": "v1"},
        {"account_claim_hash": "0" * 64},
        {"underlying_claim_hash": "0" * 64},
    ],
)
def test_successor_rejects_branch_and_chain_tampering(change: dict[str, object]) -> None:
    root = _evidence()
    successor = _successor(root)
    with pytest.raises(ValueError):
        validate_account_owner_assignment_evidence_v2_successor(root, replace(successor, **change))


def test_root_rejects_predecessor() -> None:
    with pytest.raises(ValueError, match="predecessor"):
        validate_account_owner_assignment_evidence_v2_root(
            _evidence(supersedes_content_hash="0" * 64)
        )


def test_pit_never_falls_back_from_expired_final_head() -> None:
    root = _evidence()
    successor = _successor(root)
    assert (
        resolve_account_owner_assignment_evidence_v2_head((root, successor), as_of=_at(9)) is None
    )


def test_pit_returns_none_before_recording_and_value_while_current() -> None:
    root = _evidence()
    assert resolve_account_owner_assignment_evidence_v2_head((root,), as_of=_at(7)) is None
    assert resolve_account_owner_assignment_evidence_v2_head((root,), as_of=_at(8)) is root


def test_v1_evidence_cannot_enter_v2_chain() -> None:
    with pytest.raises(TypeError, match="exact v2"):
        validate_account_owner_assignment_evidence_v2_successor(
            _evidence(), AccountOwnerAssignmentEvidence  # type: ignore[arg-type]
        )
