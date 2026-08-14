from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from apps.account.domain.account_owner_assignment_evidence import AccountOwnerAssignmentActor
from apps.account.domain.account_owner_assignment_provenance_receipt import (
    AccountOwnerAssignmentProvenanceReceipt,
)
from apps.account.domain.account_owner_assignment_provenance_receipt_v2 import (
    AccountOwnerAssignmentProvenanceReceiptV2,
    resolve_account_owner_assignment_provenance_receipt_v2_head,
    validate_account_owner_assignment_provenance_receipt_v2_root,
    validate_account_owner_assignment_provenance_receipt_v2_row,
    validate_account_owner_assignment_provenance_receipt_v2_successor,
)
from apps.account.domain.physical_account_row_observation_v2 import PhysicalAccountRowObservationV2
from apps.simulated_trading.domain.simulated_account_raw_observation import (
    SimulatedAccountRawObservation,
)
from apps.simulated_trading.domain.simulated_account_row_source_v2 import (
    SimulatedAccountRowSourceV2,
)


def _at(day: int) -> datetime:
    return datetime(2026, 8, day, 12, tzinfo=UTC)


def _row(**changes: object) -> PhysicalAccountRowObservationV2:
    raw = SimulatedAccountRawObservation(
        "raw-7", "v1", 7, 8, "SIMULATED", True, _at(1), _at(2), True, False, _at(3), _at(20)
    )
    source = SimulatedAccountRowSourceV2(
        raw.observation_id,
        raw.observation_version,
        "account",
        "0007",
        "simulated-account-row",
        7,
        8,
        "SIMULATED",
        True,
        _at(1),
        _at(2),
        True,
        False,
        _at(3),
        _at(4),
        _at(20),
        _at(12),
        _at(12),
        raw.observation_id,
        raw.observation_version,
        raw.identity_hash,
        raw.content_hash,
        _at(3),
        _at(20),
        None,
    )
    values: dict[str, object] = {
        "observation_id": "physical-7",
        "observation_version": "v1",
        "account_namespace": "account",
        "account_id": "0007",
        "underlying_unified_account_namespace": "simulated-account-row",
        "underlying_unified_account_id": 7,
        "row_user_id": 8,
        "raw_account_type": "SIMULATED",
        "is_active": True,
        "row_created_at": _at(1),
        "row_updated_at": _at(2),
        "is_present": True,
        "is_tombstone": False,
        "source_id": source.source_id,
        "source_version": source.source_version,
        "source_identity_hash": source.identity_hash,
        "source_content_hash": source.content_hash,
        "source_supersedes_content_hash": None,
        "source_observed_at": _at(3),
        "source_recorded_at": _at(4),
        "source_valid_until": _at(20),
        "source_ttl_valid_until": _at(12),
        "source_effective_valid_until": _at(12),
        "raw_observation_id": raw.observation_id,
        "raw_observation_version": raw.observation_version,
        "raw_observation_identity_hash": raw.identity_hash,
        "raw_observation_content_hash": raw.content_hash,
        "raw_observation_supersedes_content_hash": None,
        "raw_observation_observed_at": _at(3),
        "raw_observation_valid_until": _at(20),
        "recorded_at": _at(5),
        "ttl_valid_until": _at(10),
        "valid_until": _at(10),
    }
    values.update(changes)
    return PhysicalAccountRowObservationV2(**values)  # type: ignore[arg-type]


def _receipt(
    row: PhysicalAccountRowObservationV2 | None = None, **changes: object
) -> AccountOwnerAssignmentProvenanceReceiptV2:
    value = row or _row()
    values: dict[str, object] = {
        "receipt_id": "claim-7",
        "receipt_version": "v1",
        "provenance_kind": "creation",
        "assignment_state": "claimed_owner",
        "assigned_owner_user_id": 8,
        "account_namespace": value.account_namespace,
        "account_id": value.account_id,
        "underlying_unified_account_namespace": value.underlying_unified_account_namespace,
        "underlying_unified_account_id": value.underlying_unified_account_id,
        "row_observation_owner": value.owner,
        "row_observation_artifact_type": value.artifact_type,
        "row_observation_schema": value.schema,
        "row_observation_id": value.observation_id,
        "row_observation_version": value.observation_version,
        "row_observation_identity_hash": value.identity_hash,
        "row_observation_content_hash": value.content_hash,
        "row_observation_supersedes_content_hash": value.supersedes_content_hash,
        "row_observation_recorded_at": value.recorded_at,
        "row_observation_valid_until": value.valid_until,
        "source_content_hash": value.source_content_hash,
        "raw_observation_content_hash": value.raw_observation_content_hash,
        "row_is_active": value.is_active,
        "row_is_present": value.is_present,
        "row_is_tombstone": value.is_tombstone,
        "row_user_id": value.row_user_id,
        "claimant": AccountOwnerAssignmentActor("human-8", 8, "account_owner_claimant"),
        "issued_at": _at(5),
        "recorded_at": _at(6),
        "valid_until": _at(9),
    }
    values.update(changes)
    return AccountOwnerAssignmentProvenanceReceiptV2(**values)  # type: ignore[arg-type]


def test_exact_row_binding_recomputes_hashes_and_rejects_v1() -> None:
    row = _row()
    receipt = _receipt(row)
    validate_account_owner_assignment_provenance_receipt_v2_row(receipt, row)
    with pytest.raises((TypeError, ValueError)):
        validate_account_owner_assignment_provenance_receipt_v2_row(receipt, object())  # type: ignore[arg-type]
    assert AccountOwnerAssignmentProvenanceReceipt is not AccountOwnerAssignmentProvenanceReceiptV2
    for field in (
        "row_observation_content_hash",
        "source_content_hash",
        "raw_observation_content_hash",
    ):
        with pytest.raises(ValueError):
            validate_account_owner_assignment_provenance_receipt_v2_row(
                replace(receipt, **{field: "0" * 64, "content_hash": ""}), row
            )


def test_terminal_cannot_be_issued_and_expiry_never_falls_back() -> None:
    first = _receipt()
    with pytest.raises(ValueError):
        replace(first, row_is_active=False, content_hash="")
    assert (
        resolve_account_owner_assignment_provenance_receipt_v2_head((first,), as_of=_at(9)) is None
    )


def test_actor_semantics_and_exact_identifier_types() -> None:
    with pytest.raises((TypeError, ValueError)):
        _receipt(account_id=7)
    with pytest.raises((TypeError, ValueError)):
        _receipt(underlying_unified_account_id="7")
    with pytest.raises(ValueError):
        _receipt(assigned_owner_user_id=13)
    migration = _receipt(
        provenance_kind="migration",
        assignment_state="legacy_default_claim",
        assigned_owner_user_id=None,
        claimant=AccountOwnerAssignmentActor(
            "reviewer-9", 9, "legacy_assignment_reviewer", is_staff=True
        ),
    )
    assert migration.assigned_owner_user_id is None
    assert migration.must_not_execute and not migration.activation_available


def test_manual_reclaim_claims_only_the_authenticated_human() -> None:
    receipt = _receipt(
        provenance_kind="manual_reclaim",
        assigned_owner_user_id=12,
        claimant=AccountOwnerAssignmentActor("human-12", 12, "account_owner_claimant"),
    )
    assert receipt.row_user_id == 8
    assert receipt.assigned_owner_user_id == 12


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("owner", "portfolio"),
        ("artifact_type", "account_owner_assignment_provenance_receipt"),
        ("schema", "account-owner-assignment-provenance-receipt.v1"),
        ("permission", "execution_eligible"),
        ("status", "active"),
        ("blocker_codes", ()),
        ("row_observation_owner", "simulated_trading"),
        ("row_observation_schema", "physical-account-row-observation.v1"),
    ],
)
def test_v2_authority_and_inactive_semantics_are_fixed(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        _receipt(**{field: value})


@pytest.mark.parametrize(
    "changes",
    [
        {"row_is_present": False, "row_is_tombstone": True},
        {"row_is_active": False},
        {"row_is_present": True, "row_is_tombstone": True},
        {"issued_at": _at(4)},
        {"recorded_at": _at(10)},
        {"valid_until": _at(11)},
        {"row_user_id": True},
        {"identity_hash": "0" * 64},
        {"content_hash": "0" * 64},
    ],
)
def test_terminal_clock_type_and_caller_hash_tamper_are_rejected(
    changes: dict[str, object],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        _receipt(**changes)


def test_root_and_successor_receipt_links_fail_closed() -> None:
    first = _receipt()
    validate_account_owner_assignment_provenance_receipt_v2_root(first)
    with pytest.raises(ValueError, match="root predecessor"):
        validate_account_owner_assignment_provenance_receipt_v2_root(
            replace(first, supersedes_content_hash="0" * 64, content_hash="")
        )
    with pytest.raises(ValueError, match="row"):
        validate_account_owner_assignment_provenance_receipt_v2_successor(
            first,
            replace(
                first,
                receipt_version="v2",
                row_observation_version="v2",
                row_observation_supersedes_content_hash="0" * 64,
                issued_at=_at(7),
                recorded_at=_at(8),
                supersedes_content_hash=first.content_hash,
                identity_hash="",
                content_hash="",
            ),
        )
