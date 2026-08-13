"""Pure tests for Account-owned owner assignment evidence."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.account.domain.account_owner_assignment_evidence import (
    ACCOUNT_OWNER_ASSIGNMENT_ARTIFACT_TYPE,
    ACCOUNT_OWNER_ASSIGNMENT_BLOCKERS,
    ACCOUNT_OWNER_ASSIGNMENT_OWNER,
    ACCOUNT_OWNER_ASSIGNMENT_PERMISSION,
    ACCOUNT_OWNER_ASSIGNMENT_SCHEMA,
    ACCOUNT_OWNER_ASSIGNMENT_STATUS,
    AccountOwnerAssignmentActor,
    AccountOwnerAssignmentEvidence,
    validate_account_owner_assignment_successor,
)

NOW = datetime(2026, 8, 13, 6, 0, tzinfo=UTC)


def _actor(
    prefix: str,
    user_id: int,
    role: str,
    *,
    is_staff: bool = False,
) -> AccountOwnerAssignmentActor:
    return AccountOwnerAssignmentActor(
        actor_id=f"{prefix}:{user_id}",
        user_id=user_id,
        role=role,
        is_staff=is_staff,
    )


def _evidence(**changes: object) -> AccountOwnerAssignmentEvidence:
    values: dict[str, object] = {
        "evidence_id": "account-owner-assignment-7",
        "evidence_version": "account-owner-assignment.v1",
        "account_namespace": "account",
        "account_id": "real-account-7",
        "underlying_unified_account_namespace": "simulated-account-row",
        "underlying_unified_account_id": 7,
        "assignment_state": "authoritative",
        "assigned_owner_user_id": 19,
        "row_observation_owner": "simulated_trading",
        "row_observation_artifact_type": "unified_account_row_observation",
        "row_observation_id": "simulated-account-row-7",
        "row_observation_version": "row-observation.v3",
        "row_observation_content_hash": "a" * 64,
        "provenance_kind": "creation",
        "provenance_ref_owner": "account",
        "provenance_ref_artifact_type": "account_creation_receipt",
        "provenance_ref_id": "account-creation-7",
        "provenance_ref_version": "account-creation.v1",
        "provenance_ref_content_hash": "b" * 64,
        "subject_content_hash": "9" * 64,
        "claimant": _actor("claimant", 19, "account_owner_claimant"),
        "approved_by": _actor(
            "approver",
            11,
            "account_owner_approver",
            is_staff=True,
        ),
        "issued_at": NOW,
        "approved_at": NOW + timedelta(seconds=1),
        "recorded_at": NOW + timedelta(seconds=2),
        "valid_until": NOW + timedelta(days=30),
    }
    values.update(changes)
    return AccountOwnerAssignmentEvidence(**values)  # type: ignore[arg-type]


def _legacy(**changes: object) -> AccountOwnerAssignmentEvidence:
    values: dict[str, object] = {
        "assignment_state": "legacy_default",
        "assigned_owner_user_id": None,
        "provenance_kind": "migration",
        "provenance_ref_artifact_type": "account_legacy_default_assignment_receipt",
        "provenance_ref_id": "legacy-default-assignment-7",
        "provenance_ref_version": "legacy-default-assignment.v1",
        "provenance_ref_content_hash": "c" * 64,
        "claimant": _actor("migration-claimant", 13, "legacy_assignment_reviewer"),
    }
    values.update(changes)
    return _evidence(**values)


def _manual(**changes: object) -> AccountOwnerAssignmentEvidence:
    values: dict[str, object] = {
        "provenance_kind": "manual_reclaim",
        "provenance_ref_artifact_type": "account_owner_reclaim_receipt",
        "provenance_ref_id": "account-owner-reclaim-7",
        "provenance_ref_version": "account-owner-reclaim.v1",
        "provenance_ref_content_hash": "d" * 64,
    }
    values.update(changes)
    return _evidence(**values)


def test_authoritative_assignment_is_fixed_inactive_evidence_only() -> None:
    evidence = _evidence()

    assert evidence.owner == ACCOUNT_OWNER_ASSIGNMENT_OWNER == "account"
    assert evidence.artifact_type == ACCOUNT_OWNER_ASSIGNMENT_ARTIFACT_TYPE
    assert evidence.schema == ACCOUNT_OWNER_ASSIGNMENT_SCHEMA
    assert evidence.permission == ACCOUNT_OWNER_ASSIGNMENT_PERMISSION == "evidence_only"
    assert evidence.status == ACCOUNT_OWNER_ASSIGNMENT_STATUS == "inactive"
    assert evidence.blocker_codes == ACCOUNT_OWNER_ASSIGNMENT_BLOCKERS
    assert evidence.activation_available is False
    assert evidence.must_not_execute is True


def test_canonical_account_identity_and_underlying_integer_are_not_cast() -> None:
    evidence = _evidence(account_id="7", underlying_unified_account_id=7)
    assert type(evidence.account_id) is str
    assert type(evidence.underlying_unified_account_id) is int

    with pytest.raises(TypeError, match="account_id"):
        _evidence(account_id=7)
    with pytest.raises(TypeError, match="underlying_unified_account_id"):
        _evidence(underlying_unified_account_id="7")
    with pytest.raises(ValueError, match="account_namespace"):
        _evidence(account_namespace="portfolio")
    with pytest.raises(ValueError, match="underlying_unified_account_namespace"):
        _evidence(underlying_unified_account_namespace="account")


def test_authoritative_requires_positive_owner_matching_claimant() -> None:
    evidence = _evidence()
    assert evidence.assigned_owner_user_id == evidence.claimant.user_id == 19

    with pytest.raises(ValueError, match="authoritative"):
        _evidence(assigned_owner_user_id=None)
    with pytest.raises(ValueError, match="claimant"):
        _evidence(assigned_owner_user_id=20)


def test_legacy_default_cannot_claim_an_owner() -> None:
    evidence = _legacy()
    assert evidence.assignment_state == "legacy_default"
    assert evidence.assigned_owner_user_id is None

    with pytest.raises(ValueError, match="cannot claim an owner"):
        _legacy(assigned_owner_user_id=19)


@pytest.mark.parametrize("state", ["unknown", "manual_reclaim", "", 1])
def test_assignment_state_is_closed(state: object) -> None:
    with pytest.raises((TypeError, ValueError), match="assignment_state"):
        _evidence(assignment_state=state)


def test_claimant_and_approver_must_be_independent_human_staff() -> None:
    claimant = _actor("claimant", 19, "account_owner_claimant")
    assert claimant.is_staff is False
    with pytest.raises(ValueError, match="different actors"):
        _evidence(
            approved_by=replace(
                claimant,
                role="account_owner_approver",
                is_staff=True,
            )
        )
    with pytest.raises(ValueError, match="different users"):
        _evidence(
            approved_by=AccountOwnerAssignmentActor(
                actor_id="approver:independent-id",
                user_id=19,
                role="account_owner_approver",
                is_staff=True,
            )
        )
    with pytest.raises(ValueError, match="must be human"):
        _evidence(
            approved_by=AccountOwnerAssignmentActor(
                actor_id="service:11",
                user_id=11,
                role="account_owner_approver",
                kind="service",
                is_staff=True,
            )
        )
    with pytest.raises(ValueError, match="human staff"):
        _evidence(
            approved_by=AccountOwnerAssignmentActor(
                actor_id="approver:12",
                user_id=12,
                role="account_owner_approver",
                is_staff=False,
            )
        )


def test_exact_row_observation_reference_is_required_and_hashed() -> None:
    evidence = _evidence()
    assert evidence.row_observation_owner == "simulated_trading"
    assert evidence.row_observation_artifact_type == "unified_account_row_observation"

    for field_name in (
        "row_observation_owner",
        "row_observation_artifact_type",
        "row_observation_id",
        "row_observation_version",
    ):
        with pytest.raises(ValueError, match=field_name):
            _evidence(**{field_name: ""})
    with pytest.raises(ValueError, match="row_observation_content_hash"):
        _evidence(row_observation_content_hash="A" * 64)
    with pytest.raises(ValueError, match="row_observation_owner"):
        _evidence(row_observation_owner="account")
    with pytest.raises(ValueError, match="row_observation_artifact_type"):
        _evidence(row_observation_artifact_type="mutable_account_row")


@pytest.mark.parametrize(
    ("factory", "kind", "artifact_type"),
    [
        (_evidence, "creation", "account_creation_receipt"),
        (_legacy, "migration", "account_legacy_default_assignment_receipt"),
        (_manual, "manual_reclaim", "account_owner_reclaim_receipt"),
    ],
)
def test_provenance_kind_requires_its_exact_account_owned_reference(
    factory: object,
    kind: str,
    artifact_type: str,
) -> None:
    evidence = factory()  # type: ignore[operator]
    assert evidence.provenance_kind == kind
    assert evidence.provenance_ref_owner == "account"
    assert evidence.provenance_ref_artifact_type == artifact_type

    with pytest.raises(ValueError, match="provenance"):
        factory(provenance_ref_artifact_type="wrong_receipt")  # type: ignore[operator]


def test_legacy_default_requires_migration_provenance() -> None:
    with pytest.raises(ValueError, match="legacy_default"):
        _legacy(
            provenance_kind="creation",
            provenance_ref_artifact_type="account_creation_receipt",
        )
    with pytest.raises(ValueError, match="migration provenance"):
        _evidence(
            provenance_kind="migration",
            provenance_ref_artifact_type="account_legacy_default_assignment_receipt",
        )


def test_manual_reclaim_is_authoritative_not_legacy_default() -> None:
    assert _manual().assignment_state == "authoritative"
    with pytest.raises(ValueError, match="legacy_default"):
        _manual(assignment_state="legacy_default", assigned_owner_user_id=None)


def test_clock_sequence_is_aware_and_preserves_distinct_events() -> None:
    evidence = _evidence()
    assert evidence.issued_at < evidence.approved_at < evidence.recorded_at

    with pytest.raises(ValueError, match="timezone-aware"):
        _evidence(issued_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="clock sequence"):
        _evidence(approved_at=NOW - timedelta(seconds=1))
    with pytest.raises(ValueError, match="clock sequence"):
        _evidence(valid_until=NOW + timedelta(seconds=2))


def test_identity_and_content_hashes_are_canonical_and_caller_checked() -> None:
    evidence = _evidence()
    assert len(evidence.identity_hash) == len(evidence.content_hash) == 64
    assert evidence.identity_hash != evidence.content_hash

    with pytest.raises(ValueError, match="identity_hash"):
        replace(evidence, identity_hash="0" * 64)
    with pytest.raises(ValueError, match="content_hash"):
        replace(evidence, content_hash="0" * 64)


@pytest.mark.parametrize(
    "field_name",
    [
        "account_id",
        "underlying_unified_account_id",
        "assigned_owner_user_id",
        "row_observation_content_hash",
        "provenance_ref_content_hash",
        "subject_content_hash",
        "approved_at",
    ],
)
def test_semantic_changes_are_sealed_by_content_hash(field_name: str) -> None:
    evidence = _evidence()
    if field_name == "account_id":
        changed = replace(evidence, account_id="real-account-8", content_hash="")
    elif field_name == "underlying_unified_account_id":
        changed = replace(evidence, underlying_unified_account_id=8, content_hash="")
    elif field_name == "assigned_owner_user_id":
        changed = replace(
            evidence,
            assigned_owner_user_id=20,
            claimant=_actor("claimant", 20, "account_owner_claimant"),
            content_hash="",
        )
    elif field_name == "row_observation_content_hash":
        changed = replace(evidence, row_observation_content_hash="e" * 64, content_hash="")
    elif field_name == "provenance_ref_content_hash":
        changed = replace(evidence, provenance_ref_content_hash="f" * 64, content_hash="")
    elif field_name == "subject_content_hash":
        changed = replace(evidence, subject_content_hash="8" * 64, content_hash="")
    elif field_name == "approved_at":
        changed = replace(
            evidence,
            approved_at=NOW + timedelta(milliseconds=1500),
            content_hash="",
        )
    else:
        raise AssertionError(f"unhandled semantic field: {field_name}")
    assert changed.identity_hash == evidence.identity_hash
    assert changed.content_hash != evidence.content_hash


def test_successor_binds_same_logical_account_and_underlying_row() -> None:
    previous = _evidence()
    successor = replace(
        previous,
        evidence_version="account-owner-assignment.v2",
        row_observation_version="row-observation.v4",
        row_observation_content_hash="e" * 64,
        issued_at=NOW + timedelta(days=1),
        approved_at=NOW + timedelta(days=1, seconds=1),
        recorded_at=NOW + timedelta(days=1, seconds=2),
        valid_until=NOW + timedelta(days=31),
        supersedes_content_hash=previous.content_hash,
        identity_hash="",
        content_hash="",
    )

    validate_account_owner_assignment_successor(previous, successor)

    with pytest.raises(ValueError, match="previous"):
        validate_account_owner_assignment_successor(
            previous,
            replace(
                successor,
                supersedes_content_hash="f" * 64,
                identity_hash="",
                content_hash="",
            ),
        )
    with pytest.raises(ValueError, match="account_id"):
        validate_account_owner_assignment_successor(
            previous,
            replace(successor, account_id="real-account-8", identity_hash="", content_hash=""),
        )
    with pytest.raises(ValueError, match="underlying_unified_account_id"):
        validate_account_owner_assignment_successor(
            previous,
            replace(
                successor,
                underlying_unified_account_id=8,
                identity_hash="",
                content_hash="",
            ),
        )
    with pytest.raises(ValueError, match="row_observation_id"):
        validate_account_owner_assignment_successor(
            previous,
            replace(
                successor,
                row_observation_id="simulated-account-row-8",
                identity_hash="",
                content_hash="",
            ),
        )


def test_payload_never_implies_activation_or_execution() -> None:
    payload = _evidence().to_payload()
    assert payload["activation_available"] is False
    assert payload["must_not_execute"] is True
