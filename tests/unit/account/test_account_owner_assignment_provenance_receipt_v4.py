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
from apps.account.domain.account_owner_assignment_provenance_receipt_v4 import (
    ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_ARTIFACT_TYPE,
    ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_SCHEMA,
    AccountOwnerAssignmentProvenanceReceiptV4,
    resolve_account_owner_assignment_provenance_receipt_v4_head,
    validate_account_owner_assignment_provenance_receipt_v4_binding,
    validate_account_owner_assignment_provenance_receipt_v4_root,
    validate_account_owner_assignment_provenance_receipt_v4_successor,
)
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)
from apps.account.domain.single_owner_authority_policy_v1 import (
    SingleOwnerAuthorityPolicyV1,
)
from tests.unit.account.test_account_owner_assignment_provenance_receipt_v3 import (
    _receipt as _v3_receipt,
)
from tests.unit.account.test_canonical_account_creation_binding_v2 import _binding


def _at(
    day: int,
    hour: int = 12,
    minute: int = 0,
    second: int = 0,
    microsecond: int = 0,
) -> datetime:
    return datetime(2026, 8, day, hour, minute, second, microsecond, tzinfo=UTC)


def _policy(
    binding: CanonicalAccountCreationBindingV2 | None = None,
    **changes: object,
) -> SingleOwnerAuthorityPolicyV1:
    value = binding or _binding()
    values: dict[str, object] = {
        "policy_id": "personal-project",
        "policy_version": "1",
        "tenant_id": "tenant-a",
        "owner_id": "owner-a",
        "account_namespace": value.account_namespace_claim,
        "account_id": value.account_id_claim,
        "owner_user_id": value.allocation.requested_row_user_id,
        "authorization_content_hash": "a" * 64,
        "observed_at": _at(8),
        "valid_from": _at(8),
        "valid_until": _at(14),
    }
    values.update(changes)
    return SingleOwnerAuthorityPolicyV1(**values)  # type: ignore[arg-type]


def _receipt(
    binding: CanonicalAccountCreationBindingV2 | None = None,
    **changes: object,
) -> AccountOwnerAssignmentProvenanceReceiptV4:
    value = binding or _binding()
    policy_change = changes.pop("policy", None)
    policy = policy_change if policy_change is not None else _policy(value)
    values: dict[str, object] = {
        "receipt_id": "creation-claim-7",
        "receipt_version": "v4.1",
        "policy": policy,
        "policy_identity_hash": getattr(policy, "identity_hash", "0" * 64),
        "policy_content_hash": getattr(policy, "content_hash", "0" * 64),
        "binding": value,
        "account_namespace": value.account_namespace_claim,
        "account_id": value.account_id_claim,
        "underlying_unified_account_namespace": value.underlying_unified_account_namespace_claim,
        "underlying_unified_account_id": value.underlying_unified_account_id_claim,
        "allocation_identity_hash": value.allocation.identity_hash,
        "allocation_content_hash": value.allocation.content_hash,
        "creation_root_identity_hash": value.creation_root.identity_hash,
        "creation_root_content_hash": value.creation_root.content_hash,
        "binding_identity_hash": value.identity_hash,
        "binding_content_hash": value.content_hash,
        "account_claim_hash": value.account_claim_hash,
        "underlying_claim_hash": value.underlying_claim_hash,
        "physical_observation_content_hash": value.creation_root.physical_observation.content_hash,
        "physical_source_content_hash": value.creation_root.physical_observation.source_content_hash,
        "physical_raw_observation_content_hash": (
            value.creation_root.physical_observation.raw_observation_content_hash
        ),
        "assigned_owner_user_id": value.allocation.requested_row_user_id,
        "claimant": AccountOwnerAssignmentActor(
            "django-user:42",
            value.allocation.requested_row_user_id,
            "account_owner_claimant",
            is_staff=True,
        ),
        "issued_at": _at(8, 13),
        "recorded_at": _at(8, 14),
        "valid_until": _at(13),
    }
    values.update(changes)
    return AccountOwnerAssignmentProvenanceReceiptV4(**values)  # type: ignore[arg-type]


def test_v4_accepts_real_staff_owner_and_seals_complete_policy_graph() -> None:
    receipt = _receipt()
    payload = receipt.to_payload()

    assert receipt.owner == "account"
    assert receipt.artifact_type == ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_ARTIFACT_TYPE
    assert receipt.schema == ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V4_SCHEMA
    assert receipt.policy.account_id == receipt.binding.account_id_claim
    assert receipt.claimant.is_staff is True
    assert receipt.claimant.user_id == receipt.policy.owner_user_id == 42
    assert receipt.activation_available is False
    assert receipt.must_not_execute is True
    assert not hasattr(receipt, "__dict__")
    assert payload["policy"] == receipt.policy.to_payload()
    assert payload["policy_identity_hash"] == receipt.policy.identity_hash
    assert payload["policy_content_hash"] == receipt.policy.content_hash
    assert payload["binding"] == receipt.binding.to_payload()
    assert len(receipt.identity_hash) == len(receipt.content_hash) == 64

    with pytest.raises(FrozenInstanceError):
        receipt.receipt_version = "v4.2"  # type: ignore[misc]


def test_v4_golden_hashes_are_versioned_and_policy_bound() -> None:
    receipt = _receipt()

    assert (
        receipt.identity_hash == "dc5cb20e7c0d2747b8c5ea6dde87614e9eaf46fd6b2533ac4c0994649b8f2605"
    )
    assert (
        receipt.content_hash == "434c4b3f66c823750a916a00d7917585132198b49ac8cbea3dfd54f1ae21d136"
    )
    assert receipt.identity_hash != _v3_receipt().identity_hash
    assert receipt.content_hash != _v3_receipt().content_hash


@pytest.mark.parametrize(
    "field_name",
    [
        "allocation_identity_hash",
        "allocation_content_hash",
        "creation_root_identity_hash",
        "creation_root_content_hash",
        "binding_identity_hash",
        "binding_content_hash",
        "account_claim_hash",
        "underlying_claim_hash",
        "physical_observation_content_hash",
        "physical_source_content_hash",
        "physical_raw_observation_content_hash",
    ],
)
def test_v4_preserves_all_v3_binding_source_and_row_hash_checks(field_name: str) -> None:
    with pytest.raises(ValueError):
        _receipt(**{field_name: "0" * 64})

    receipt = _receipt()
    validate_account_owner_assignment_provenance_receipt_v4_binding(receipt, receipt.binding)


def test_v4_binds_exact_policy_hashes_and_revalidates_nested_policy() -> None:
    receipt = _receipt()

    with pytest.raises(ValueError, match="policy identity hash"):
        replace(receipt, policy_identity_hash="0" * 64, identity_hash="", content_hash="")
    with pytest.raises(ValueError, match="policy content hash"):
        replace(receipt, policy_content_hash="0" * 64, identity_hash="", content_hash="")

    object.__setattr__(receipt.policy, "owner_id", "forged-owner")
    with pytest.raises(ValueError, match="content_hash"):
        receipt.to_payload()


@pytest.mark.parametrize(
    "changes",
    [
        {"account_id": "other-account"},
        {"underlying_unified_account_id": 8},
        {"assigned_owner_user_id": 7},
        {
            "claimant": AccountOwnerAssignmentActor(
                "django-user:7", 7, "account_owner_claimant", is_staff=True
            )
        },
        {"recorded_at": _at(8, 11)},
        {"valid_until": _at(15)},
    ],
)
def test_v4_preserves_v3_identity_scope_and_clock_guards(changes: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        _receipt(**changes)


@pytest.mark.parametrize(
    "policy_changes",
    [
        {"account_id": "other-account"},
        {"owner_user_id": 7},
        {"observed_at": _at(8, 15)},
        {"valid_until": _at(8, 13, 59)},
        {"status": "revoked"},
    ],
)
def test_v4_rejects_wrong_scope_owner_future_observation_or_expired_policy(
    policy_changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="policy"):
        _receipt(policy=_policy(**policy_changes))


def test_v4_current_and_knowable_reads_fail_closed_at_policy_and_receipt_boundaries() -> None:
    policy = _policy(valid_until=_at(9))
    receipt = _receipt(policy=policy, valid_until=_at(9))

    assert receipt.is_knowable_at(receipt.recorded_at - timedelta(microseconds=1)) is False
    assert receipt.is_knowable_at(receipt.recorded_at) is True
    assert receipt.is_current_at(receipt.recorded_at) is True
    assert receipt.is_current_at(policy.valid_until) is False
    assert receipt.is_knowable_at(policy.valid_until) is True
    with pytest.raises(ValueError, match="timezone-aware"):
        receipt.is_current_at(datetime(2026, 8, 8, 14))


def test_v3_still_rejects_staff_and_its_golden_seals_are_unchanged() -> None:
    old = _v3_receipt()
    assert old.identity_hash == "7cff67d26781585ccb84b1f1a283c780302d7927a6394ced48a3c5843b4a4602"
    assert old.content_hash == "074949ccfe8d470b3058c18b458a0bbf54029d69bca1d1e3c234b7f3564ba1d1"

    with pytest.raises(ValueError, match="non-staff"):
        _v3_receipt(
            claimant=AccountOwnerAssignmentActor(
                "django-user:42", 42, "account_owner_claimant", is_staff=True
            )
        )


def test_v4_root_successor_and_point_in_time_head_never_fall_back() -> None:
    first = _receipt(valid_until=_at(11))
    validate_account_owner_assignment_provenance_receipt_v4_root(first)
    second = replace(
        first,
        receipt_version="v4.2",
        issued_at=_at(9, 13),
        recorded_at=_at(9, 14),
        valid_until=_at(12),
        supersedes_content_hash=first.content_hash,
        identity_hash="",
        content_hash="",
    )

    validate_account_owner_assignment_provenance_receipt_v4_successor(first, second)
    assert (
        resolve_account_owner_assignment_provenance_receipt_v4_head(
            (first, second), as_of=second.recorded_at
        )
        is second
    )
    assert (
        resolve_account_owner_assignment_provenance_receipt_v4_head(
            (first, second), as_of=second.valid_until
        )
        is None
    )
    with pytest.raises(ValueError, match="predecessor"):
        validate_account_owner_assignment_provenance_receipt_v4_root(second)


@pytest.mark.parametrize(
    "policy_changes",
    [{"policy_id": "other-policy"}, {"tenant_id": "tenant-other"}, {"owner_id": "owner-other"}],
)
def test_v4_successor_rejects_cross_policy_tenant_or_owner_switch(
    policy_changes: dict[str, object],
) -> None:
    first = _receipt(valid_until=_at(11))
    second = _receipt(
        policy=_policy(**policy_changes),
        receipt_version="v4.2",
        issued_at=_at(9, 13),
        recorded_at=_at(9, 14),
        valid_until=_at(12),
        supersedes_content_hash=first.content_hash,
    )

    with pytest.raises(ValueError, match="policy"):
        validate_account_owner_assignment_provenance_receipt_v4_successor(first, second)


def test_v4_successor_rejects_predecessor_hash_version_and_old_type_substitution() -> None:
    first = _receipt(valid_until=_at(11))
    successor = replace(
        first,
        receipt_version="v4.2",
        issued_at=_at(9, 13),
        recorded_at=_at(9, 14),
        valid_until=_at(12),
        supersedes_content_hash=first.content_hash,
        identity_hash="",
        content_hash="",
    )

    with pytest.raises(ValueError, match="predecessor"):
        validate_account_owner_assignment_provenance_receipt_v4_successor(
            first, replace(successor, supersedes_content_hash="0" * 64, content_hash="")
        )
    with pytest.raises(ValueError, match="receipt_version"):
        validate_account_owner_assignment_provenance_receipt_v4_successor(
            first,
            replace(
                successor,
                receipt_version=first.receipt_version,
                identity_hash="",
                content_hash="",
            ),
        )
    with pytest.raises(TypeError, match="exact v4"):
        validate_account_owner_assignment_provenance_receipt_v4_successor(
            cast(AccountOwnerAssignmentProvenanceReceiptV4, _v3_receipt()), successor
        )
    with pytest.raises(TypeError, match="exact v4"):
        validate_account_owner_assignment_provenance_receipt_v4_binding(
            cast(AccountOwnerAssignmentProvenanceReceiptV4, _v3_receipt()), first.binding
        )


def test_v4_resolver_rejects_non_tuple_and_empty_or_future_heads() -> None:
    receipt = _receipt()

    assert (
        resolve_account_owner_assignment_provenance_receipt_v4_head((), as_of=receipt.recorded_at)
        is None
    )
    assert (
        resolve_account_owner_assignment_provenance_receipt_v4_head(
            (receipt,), as_of=receipt.recorded_at - timedelta(microseconds=1)
        )
        is None
    )
    with pytest.raises(TypeError, match="exact tuple"):
        resolve_account_owner_assignment_provenance_receipt_v4_head(  # type: ignore[arg-type]
            [receipt], as_of=receipt.recorded_at
        )


def test_v4_domain_module_has_only_stdlib_and_account_domain_imports() -> None:
    source_path = (
        Path(__file__).parents[3]
        / "apps"
        / "account"
        / "domain"
        / "account_owner_assignment_provenance_receipt_v4.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}

    assert "apps.account.domain.account_owner_assignment_provenance_receipt_v3" not in imports
    assert "apps.account.domain.account_owner_assignment_provenance_receipt_v2" not in imports
    assert not any(name.startswith(("django", "pandas", "numpy", "requests")) for name in imports)
    assert imports <= {
        "__future__",
        "apps.account.domain.account_owner_assignment_evidence",
        "apps.account.domain.canonical_account_creation_binding_v2",
        "apps.account.domain.single_owner_authority_policy_v1",
        "dataclasses",
        "datetime",
        "hashlib",
        "json",
    }
