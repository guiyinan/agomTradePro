"""Pure tests for Account-owned owner-assignment provenance receipts."""

from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta, timezone
from typing import cast

import pytest

from apps.account.domain.account_owner_assignment_evidence import (
    AccountOwnerAssignmentActor,
)
from apps.account.domain.account_owner_assignment_provenance_receipt import (
    ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_BLOCKERS,
    ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_OWNER,
    ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_PERMISSION,
    ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_SCHEMA,
    ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_STATUS,
    AccountOwnerAssignmentProvenanceReceipt,
    resolve_account_owner_assignment_provenance_receipt_head,
    validate_account_owner_assignment_provenance_receipt_row,
    validate_account_owner_assignment_provenance_receipt_successor,
)
from apps.account.domain.physical_account_row_observation import (
    PhysicalAccountRowObservation,
)

NOW = datetime(2026, 8, 13, 6, 0, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def _actor(
    prefix: str,
    user_id: int,
    role: str = "account_owner_claimant",
    *,
    is_staff: bool = False,
) -> AccountOwnerAssignmentActor:
    return AccountOwnerAssignmentActor(
        actor_id=f"{prefix}:{user_id}",
        user_id=user_id,
        role=role,
        is_staff=is_staff,
    )


def _row(**changes: object) -> PhysicalAccountRowObservation:
    values: dict[str, object] = {
        "observation_id": "physical-account-row-7",
        "observation_version": "physical-account-row.v1",
        "account_namespace": "account",
        "account_id": "real-account-7",
        "underlying_unified_account_namespace": "simulated-account-row",
        "underlying_unified_account_id": 7,
        "raw_source_owner": "simulated_trading",
        "raw_source_artifact_type": "simulated_account_row",
        "raw_source_id": "simulated-account-row-7",
        "raw_source_version": "simulated-account-row.v1",
        "raw_source_content_hash": HASH_A,
        "row_user_id": 19,
        "account_type": "real",
        "is_active": True,
        "row_created_at": NOW - timedelta(minutes=10),
        "row_updated_at": NOW - timedelta(minutes=9),
        "observed_at": NOW - timedelta(minutes=8),
        "recorded_at": NOW - timedelta(minutes=7),
        "raw_source_valid_until": NOW + timedelta(days=30),
        "ttl_valid_until": NOW + timedelta(days=20),
        "valid_until": NOW + timedelta(days=20),
    }
    values.update(changes)
    return PhysicalAccountRowObservation(**values)  # type: ignore[arg-type]


def _receipt(
    *,
    row: PhysicalAccountRowObservation | None = None,
    **changes: object,
) -> AccountOwnerAssignmentProvenanceReceipt:
    exact_row = row or _row()
    values: dict[str, object] = {
        "receipt_id": "account-assignment-provenance-7",
        "receipt_version": "account-assignment-provenance.v1",
        "provenance_kind": "creation",
        "artifact_type": "account_creation_receipt",
        "assignment_state": "authoritative",
        "assigned_owner_user_id": 19,
        "account_namespace": "account",
        "account_id": "real-account-7",
        "underlying_unified_account_namespace": "simulated-account-row",
        "underlying_unified_account_id": 7,
        "row_observation_owner": exact_row.owner,
        "row_observation_artifact_type": exact_row.artifact_type,
        "row_observation_id": exact_row.observation_id,
        "row_observation_version": exact_row.observation_version,
        "row_observation_identity_hash": exact_row.identity_hash,
        "row_observation_content_hash": exact_row.content_hash,
        "row_observation_valid_until": exact_row.valid_until,
        "claimant": _actor("claimant", 19),
        "issued_at": NOW - timedelta(minutes=6),
        "recorded_at": NOW - timedelta(minutes=5),
        "valid_until": NOW + timedelta(days=10),
    }
    values.update(changes)
    return AccountOwnerAssignmentProvenanceReceipt(**values)  # type: ignore[arg-type]


def _manual_reclaim(
    *,
    row: PhysicalAccountRowObservation | None = None,
    **changes: object,
) -> AccountOwnerAssignmentProvenanceReceipt:
    values: dict[str, object] = {
        "provenance_kind": "manual_reclaim",
        "artifact_type": "account_owner_reclaim_receipt",
    }
    values.update(changes)
    return _receipt(row=row, **values)


def _migration(
    *,
    row: PhysicalAccountRowObservation | None = None,
    **changes: object,
) -> AccountOwnerAssignmentProvenanceReceipt:
    values: dict[str, object] = {
        "provenance_kind": "migration",
        "artifact_type": "account_legacy_default_assignment_receipt",
        "assignment_state": "legacy_default",
        "assigned_owner_user_id": None,
        "claimant": _actor(
            "migration-reviewer",
            23,
            "legacy_assignment_reviewer",
            is_staff=True,
        ),
    }
    values.update(changes)
    return _receipt(row=row, **values)


def _successor_row(previous: PhysicalAccountRowObservation) -> PhysicalAccountRowObservation:
    return replace(
        previous,
        observation_version="physical-account-row.v2",
        raw_source_version="simulated-account-row.v2",
        raw_source_content_hash=HASH_B,
        row_updated_at=NOW + timedelta(days=1),
        observed_at=NOW + timedelta(days=1, minutes=1),
        recorded_at=NOW + timedelta(days=1, minutes=2),
        raw_source_valid_until=NOW + timedelta(days=40),
        ttl_valid_until=NOW + timedelta(days=30),
        valid_until=NOW + timedelta(days=30),
        supersedes_content_hash=previous.content_hash,
        identity_hash="",
        content_hash="",
    )


def _successor_receipt(
    previous: AccountOwnerAssignmentProvenanceReceipt,
    *,
    row: PhysicalAccountRowObservation,
    **changes: object,
) -> AccountOwnerAssignmentProvenanceReceipt:
    values: dict[str, object] = {
        "receipt_version": "account-assignment-provenance.v2",
        "row_observation_owner": row.owner,
        "row_observation_artifact_type": row.artifact_type,
        "row_observation_id": row.observation_id,
        "row_observation_version": row.observation_version,
        "row_observation_identity_hash": row.identity_hash,
        "row_observation_content_hash": row.content_hash,
        "row_observation_valid_until": row.valid_until,
        "issued_at": NOW + timedelta(days=1, minutes=1),
        "recorded_at": NOW + timedelta(days=1, minutes=3),
        "valid_until": NOW + timedelta(days=25),
        "supersedes_content_hash": previous.content_hash,
        "identity_hash": "",
        "content_hash": "",
    }
    values.update(changes)
    return replace(previous, **values)


def test_receipt_is_fixed_account_owned_inactive_evidence_only() -> None:
    receipt = _receipt()

    assert receipt.owner == ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_OWNER == "account"
    assert receipt.schema == ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_SCHEMA
    assert receipt.permission == ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_PERMISSION
    assert receipt.permission == "evidence_only"
    assert receipt.status == ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_STATUS == "inactive"
    assert receipt.blocker_codes == ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_BLOCKERS
    assert receipt.activation_available is False
    assert receipt.must_not_execute is True

    with pytest.raises(ValueError, match="status is fixed"):
        _receipt(status="active")
    with pytest.raises(ValueError, match="permission is fixed"):
        _receipt(permission="execution_eligible")


@pytest.mark.parametrize(
    ("factory", "kind", "artifact_type", "state", "owner_user_id"),
    [
        (_receipt, "creation", "account_creation_receipt", "authoritative", 19),
        (
            _manual_reclaim,
            "manual_reclaim",
            "account_owner_reclaim_receipt",
            "authoritative",
            19,
        ),
        (
            _migration,
            "migration",
            "account_legacy_default_assignment_receipt",
            "legacy_default",
            None,
        ),
    ],
)
def test_one_closed_discriminator_enforces_all_three_receipt_kinds(
    factory: object,
    kind: str,
    artifact_type: str,
    state: str,
    owner_user_id: int | None,
) -> None:
    receipt = factory()  # type: ignore[operator]

    assert type(receipt) is AccountOwnerAssignmentProvenanceReceipt
    assert receipt.provenance_kind == kind
    assert receipt.artifact_type == artifact_type
    assert receipt.assignment_state == state
    assert receipt.assigned_owner_user_id == owner_user_id


@pytest.mark.parametrize(
    "changes",
    [
        {"provenance_kind": "unknown", "artifact_type": "account_creation_receipt"},
        {"provenance_kind": "creation", "artifact_type": "account_owner_reclaim_receipt"},
        {
            "provenance_kind": "creation",
            "assignment_state": "legacy_default",
            "assigned_owner_user_id": None,
        },
        {
            "provenance_kind": "manual_reclaim",
            "artifact_type": "account_owner_reclaim_receipt",
            "assignment_state": "legacy_default",
            "assigned_owner_user_id": None,
        },
        {
            "provenance_kind": "migration",
            "artifact_type": "account_legacy_default_assignment_receipt",
            "assignment_state": "authoritative",
        },
    ],
)
def test_kind_artifact_and_assignment_matrix_is_closed(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="provenance|artifact|assignment"):
        _receipt(**changes)


def test_authoritative_claimant_is_the_exact_assigned_owner() -> None:
    receipt = _manual_reclaim()

    assert receipt.claimant.user_id == receipt.assigned_owner_user_id == 19
    assert receipt.claimant.role == "account_owner_claimant"

    with pytest.raises(ValueError, match="claimant user"):
        _receipt(assigned_owner_user_id=20)
    with pytest.raises(ValueError, match="positive owner"):
        _receipt(assigned_owner_user_id=True)


def test_migration_claimant_attests_legacy_state_and_never_becomes_owner() -> None:
    row = _row(row_user_id=1)
    receipt = _migration(row=row)

    validate_account_owner_assignment_provenance_receipt_row(receipt, row)
    assert row.row_user_id == 1
    assert receipt.claimant.user_id == 23
    assert receipt.assigned_owner_user_id is None
    assert "row_user_id" not in receipt.to_payload()

    with pytest.raises(ValueError, match="cannot claim an owner"):
        _migration(row=row, assigned_owner_user_id=row.row_user_id)
    with pytest.raises(ValueError, match="human staff reviewer"):
        _migration(
            row=row,
            claimant=_actor(
                "migration-reviewer",
                23,
                "legacy_assignment_reviewer",
                is_staff=False,
            ),
        )


def test_claimant_role_is_kind_specific_and_cannot_be_0013_system_metadata() -> None:
    with pytest.raises(ValueError, match="claimant role"):
        _receipt(claimant=_actor("claimant", 19, "legacy_assignment_reviewer"))
    with pytest.raises(ValueError, match="claimant role"):
        _migration(
            claimant=_actor(
                "system",
                23,
                "account_owner_claimant",
                is_staff=True,
            )
        )
    with pytest.raises(TypeError, match="exact AccountOwnerAssignmentActor"):
        _receipt(claimant=None)


def test_receipt_seals_exact_physical_row_identity_content_and_validity() -> None:
    row = _row()
    receipt = _receipt(row=row)

    validate_account_owner_assignment_provenance_receipt_row(receipt, row)
    assert receipt.row_observation_owner == "account"
    assert receipt.row_observation_artifact_type == "physical_account_row_observation"
    assert receipt.row_observation_id == row.observation_id
    assert receipt.row_observation_version == row.observation_version
    assert receipt.row_observation_identity_hash == row.identity_hash
    assert receipt.row_observation_content_hash == row.content_hash
    assert receipt.row_observation_valid_until == row.valid_until


def test_row_identity_hash_is_recomputed_from_the_exact_physical_identity() -> None:
    with pytest.raises(ValueError, match="row_observation_identity_hash"):
        _receipt(row_observation_identity_hash=HASH_C)
    with pytest.raises(ValueError, match="row_observation_owner is fixed"):
        _receipt(row_observation_owner="simulated_trading")
    with pytest.raises(ValueError, match="row_observation_artifact_type is fixed"):
        _receipt(row_observation_artifact_type="unified_account_row_observation")


@pytest.mark.parametrize(
    "changes",
    [
        {"account_id": "real-account-8"},
        {"underlying_unified_account_id": 8},
        {"row_observation_content_hash": HASH_C},
        {"row_observation_valid_until": NOW + timedelta(days=19)},
    ],
)
def test_row_validator_rejects_every_mismatched_seal(changes: dict[str, object]) -> None:
    row = _row()
    receipt = _receipt(row=row, **changes)

    with pytest.raises(ValueError, match="does not bind the exact physical row"):
        validate_account_owner_assignment_provenance_receipt_row(receipt, row)


def test_receipt_must_be_recorded_while_bound_row_is_knowable() -> None:
    future_row = _row(
        row_updated_at=NOW - timedelta(minutes=4),
        observed_at=NOW - timedelta(minutes=3),
        recorded_at=NOW - timedelta(minutes=2),
    )
    receipt = _receipt(row=future_row)

    with pytest.raises(ValueError, match="row was not knowable"):
        validate_account_owner_assignment_provenance_receipt_row(receipt, future_row)


def test_receipt_validity_is_aware_ordered_and_bounded_by_row() -> None:
    row = _row()
    receipt = _receipt(row=row)
    assert receipt.issued_at <= receipt.recorded_at < receipt.valid_until <= row.valid_until

    with pytest.raises(ValueError, match="timezone-aware"):
        _receipt(recorded_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="clock sequence"):
        _receipt(issued_at=NOW, recorded_at=NOW - timedelta(seconds=1))
    with pytest.raises(ValueError, match="row observation validity"):
        _receipt(valid_until=row.valid_until + timedelta(seconds=1))


def test_identity_and_content_hashes_are_canonical_and_caller_checked() -> None:
    receipt = _receipt()

    assert len(receipt.identity_hash) == len(receipt.content_hash) == 64
    assert receipt.identity_hash != receipt.content_hash
    with pytest.raises(ValueError, match="identity_hash"):
        replace(receipt, identity_hash=HASH_C)
    with pytest.raises(ValueError, match="content_hash"):
        replace(receipt, content_hash=HASH_C)


@pytest.mark.parametrize(
    "field_name",
    [
        "assigned_owner_user_id",
        "row_observation_content_hash",
        "row_observation_valid_until",
        "claimant",
        "recorded_at",
        "supersedes_content_hash",
    ],
)
def test_every_semantic_change_is_sealed_by_content_hash(field_name: str) -> None:
    receipt = _receipt()
    if field_name == "assigned_owner_user_id":
        changed = replace(
            receipt,
            assigned_owner_user_id=20,
            claimant=_actor("claimant", 20),
            content_hash="",
        )
    elif field_name == "row_observation_content_hash":
        changed = replace(receipt, row_observation_content_hash=HASH_C, content_hash="")
    elif field_name == "row_observation_valid_until":
        changed = replace(
            receipt,
            row_observation_valid_until=NOW + timedelta(days=19),
            content_hash="",
        )
    elif field_name == "claimant":
        changed = replace(
            receipt,
            assigned_owner_user_id=20,
            claimant=_actor("other-claimant", 20),
            content_hash="",
        )
    elif field_name == "recorded_at":
        changed = replace(
            receipt,
            recorded_at=receipt.recorded_at + timedelta(seconds=1),
            content_hash="",
        )
    elif field_name == "supersedes_content_hash":
        changed = replace(receipt, supersedes_content_hash=HASH_C, content_hash="")
    else:
        raise AssertionError(f"unhandled field: {field_name}")

    assert changed.identity_hash == receipt.identity_hash
    assert changed.content_hash != receipt.content_hash


def test_equivalent_timezone_instants_hash_identically_and_payload_uses_utc_z() -> None:
    offset = timezone(timedelta(hours=8))
    utc_receipt = _receipt()
    offset_receipt = _receipt(
        row_observation_valid_until=utc_receipt.row_observation_valid_until.astimezone(offset),
        issued_at=utc_receipt.issued_at.astimezone(offset),
        recorded_at=utc_receipt.recorded_at.astimezone(offset),
        valid_until=utc_receipt.valid_until.astimezone(offset),
    )

    assert offset_receipt.content_hash == utc_receipt.content_hash
    assert cast(str, utc_receipt.to_payload()["recorded_at"]).endswith("Z")


def test_successor_binds_predecessor_and_same_logical_claim() -> None:
    row = _row()
    previous = _receipt(row=row)
    next_row = _successor_row(row)
    successor = _successor_receipt(previous, row=next_row)

    validate_account_owner_assignment_provenance_receipt_row(successor, next_row)
    validate_account_owner_assignment_provenance_receipt_successor(previous, successor)

    with pytest.raises(ValueError, match="exact previous receipt"):
        validate_account_owner_assignment_provenance_receipt_successor(
            previous,
            replace(successor, supersedes_content_hash=HASH_C, content_hash=""),
        )
    with pytest.raises(ValueError, match="account_id"):
        validate_account_owner_assignment_provenance_receipt_successor(
            previous,
            replace(successor, account_id="real-account-8", content_hash=""),
        )
    with pytest.raises(ValueError, match="claimant"):
        validate_account_owner_assignment_provenance_receipt_successor(
            previous,
            replace(
                successor,
                claimant=_actor("other-claimant", 19),
                content_hash="",
            ),
        )
    with pytest.raises(ValueError, match="recorded_at"):
        validate_account_owner_assignment_provenance_receipt_successor(
            previous,
            replace(
                successor,
                issued_at=previous.issued_at,
                recorded_at=previous.recorded_at,
                content_hash="",
            ),
        )


def test_pit_head_requires_root_and_never_falls_back_from_expired_successor() -> None:
    row = _row()
    root = _receipt(row=row)
    next_row = _successor_row(row)
    successor = _successor_receipt(
        root,
        row=next_row,
        recorded_at=NOW + timedelta(days=2),
        valid_until=NOW + timedelta(days=3),
    )

    assert (
        resolve_account_owner_assignment_provenance_receipt_head(
            (root, successor),
            as_of=NOW,
        )
        is root
    )
    assert (
        resolve_account_owner_assignment_provenance_receipt_head(
            (root, successor),
            as_of=NOW + timedelta(days=2, minutes=1),
        )
        is successor
    )
    assert (
        resolve_account_owner_assignment_provenance_receipt_head(
            (root, successor),
            as_of=NOW + timedelta(days=4),
        )
        is None
    )

    non_root = replace(root, supersedes_content_hash=HASH_C, content_hash="")
    with pytest.raises(ValueError, match="start at a root"):
        resolve_account_owner_assignment_provenance_receipt_head(
            (non_root,),
            as_of=NOW,
        )


def test_exact_types_tamper_and_container_shapes_fail_closed() -> None:
    row = _row()
    receipt = _receipt(row=row)
    successor = _successor_receipt(receipt, row=_successor_row(row))

    object.__setattr__(receipt, "account_id", "real-account-tampered")
    with pytest.raises(ValueError, match="content_hash"):
        receipt.to_payload()

    clean = _receipt(row=row)

    class ReceiptSubclass(AccountOwnerAssignmentProvenanceReceipt):
        pass

    sub = object.__new__(ReceiptSubclass)
    for field in fields(AccountOwnerAssignmentProvenanceReceipt):
        object.__setattr__(sub, field.name, getattr(clean, field.name))
    with pytest.raises(TypeError, match="exact AccountOwnerAssignmentProvenanceReceipt"):
        validate_account_owner_assignment_provenance_receipt_successor(sub, successor)
    with pytest.raises(TypeError, match="exact tuple"):
        resolve_account_owner_assignment_provenance_receipt_head(
            cast(tuple[AccountOwnerAssignmentProvenanceReceipt, ...], [clean]),
            as_of=NOW,
        )


def test_payload_contains_only_claimant_side_and_never_approval_authority() -> None:
    payload = _receipt().to_payload()

    assert payload["claimant"] == _actor("claimant", 19).to_payload()
    assert "approved_by" not in payload
    assert payload["activation_available"] is False
    assert payload["must_not_execute"] is True
