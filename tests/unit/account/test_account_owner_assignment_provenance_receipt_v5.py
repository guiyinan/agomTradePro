from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from apps.account.domain.account_owner_assignment_evidence import (
    AccountOwnerAssignmentActor,
)
from apps.account.domain.account_owner_assignment_provenance_receipt_v5 import (
    ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V5_ARTIFACT_TYPE,
    ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V5_SCHEMA,
    AccountOwnerAssignmentProvenanceReceiptV5,
    resolve_account_owner_assignment_provenance_receipt_v5_head,
    validate_account_owner_assignment_provenance_receipt_v5_binding,
    validate_account_owner_assignment_provenance_receipt_v5_root,
    validate_account_owner_assignment_provenance_receipt_v5_successor,
)
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)
from apps.account.domain.canonical_account_ownership_reobservation_v1 import (
    CanonicalAccountOwnershipReobservationV1,
)
from apps.account.domain.single_owner_authority_policy_v1 import (
    SingleOwnerAuthorityPolicyV1,
)
from tests.unit.account.test_account_owner_assignment_provenance_receipt_v4 import (
    _policy,
)
from tests.unit.account.test_account_owner_assignment_provenance_receipt_v4 import (
    _receipt as _v4_receipt,
)
from tests.unit.account.test_allocated_physical_account_row_observation_v3 import (
    _root,
)
from tests.unit.account.test_canonical_account_ownership_reobservation_v1 import (
    _binding as _reobservation_binding,
)
from tests.unit.account.test_physical_account_row_observation_v2 import (
    _observation,
    _raw,
    _source,
)


def _at(
    day: int,
    hour: int = 12,
    minute: int = 0,
    second: int = 0,
    microsecond: int = 0,
) -> datetime:
    return datetime(2026, 8, day, hour, minute, second, microsecond, tzinfo=UTC)


def _expired_creation_binding() -> CanonicalAccountCreationBindingV2:
    root = _root(ttl_valid_until=_at(9), valid_until=_at(9))
    return _reobservation_binding(root=root, recorded_at=_at(8))


def _current_physical(*, valid_until: datetime = _at(30)) -> object:
    raw = _raw(
        row_pk=7,
        row_user_id=42,
        raw_account_type="SIMULATED",
        row_created_at=_at(2),
        row_updated_at=_at(3),
        observed_at=_at(4),
        valid_until=valid_until,
    )
    source = _source(
        raw=raw,
        account_id="acct-0007",
        recorded_at=_at(5),
        source_valid_until=valid_until,
        ttl_valid_until=valid_until,
        valid_until=valid_until,
    )
    return _observation(
        source=source,
        observation_id="physical-account-row-reobserve-v5",
        observation_version="reobservation-v5",
        recorded_at=_at(6),
        ttl_valid_until=valid_until,
        valid_until=valid_until,
    )


def _reobservation(
    *,
    binding: CanonicalAccountCreationBindingV2 | None = None,
    current_physical: object | None = None,
    recorded_at: datetime = _at(15),
    valid_until: datetime = _at(30),
    **changes: object,
) -> CanonicalAccountOwnershipReobservationV1:
    values: dict[str, object] = {
        "observation_id": "account-owner-reobservation-v5",
        "observation_version": "v1",
        "binding": binding or _expired_creation_binding(),
        "current_physical": current_physical or _current_physical(),
        "recorded_at": recorded_at,
        "valid_until": valid_until,
    }
    values.update(changes)
    return CanonicalAccountOwnershipReobservationV1(**values)  # type: ignore[arg-type]


def _receipt(
    *,
    binding: CanonicalAccountCreationBindingV2 | None = None,
    reobservation: CanonicalAccountOwnershipReobservationV1 | None = None,
    policy: SingleOwnerAuthorityPolicyV1 | None = None,
    **changes: object,
) -> AccountOwnerAssignmentProvenanceReceiptV5:
    current_reobservation = reobservation or _reobservation(binding=binding)
    value = binding or current_reobservation.binding
    current_policy = policy or _policy(binding=value, valid_until=_at(30))
    current_physical = current_reobservation.current_physical
    values: dict[str, object] = {
        "receipt_id": "ownership-claim-v5-7",
        "receipt_version": "v5.1",
        "policy": current_policy,
        "policy_identity_hash": current_policy.identity_hash,
        "policy_content_hash": current_policy.content_hash,
        "binding": value,
        "reobservation": current_reobservation,
        "account_namespace": value.account_namespace_claim,
        "account_id": value.account_id_claim,
        "underlying_unified_account_namespace": (value.underlying_unified_account_namespace_claim),
        "underlying_unified_account_id": value.underlying_unified_account_id_claim,
        "allocation_identity_hash": value.allocation.identity_hash,
        "allocation_content_hash": value.allocation.content_hash,
        "binding_identity_hash": value.identity_hash,
        "binding_content_hash": value.content_hash,
        "account_claim_hash": value.account_claim_hash,
        "underlying_claim_hash": value.underlying_claim_hash,
        "reobservation_identity_hash": current_reobservation.identity_hash,
        "reobservation_content_hash": current_reobservation.content_hash,
        "current_physical_observation_content_hash": current_physical.content_hash,
        "current_physical_source_content_hash": current_physical.source_content_hash,
        "current_physical_raw_observation_content_hash": (
            current_physical.raw_observation_content_hash
        ),
        "assigned_owner_user_id": value.allocation.requested_row_user_id,
        "claimant": AccountOwnerAssignmentActor(
            "django-user:42",
            value.allocation.requested_row_user_id,
            "account_owner_claimant",
            is_staff=True,
        ),
        "issued_at": _at(15, 13),
        "recorded_at": _at(15, 14),
        "valid_until": _at(16),
    }
    values.update(changes)
    return AccountOwnerAssignmentProvenanceReceiptV5(**values)  # type: ignore[arg-type]


def _successor(
    previous: AccountOwnerAssignmentProvenanceReceiptV5,
    **changes: object,
) -> AccountOwnerAssignmentProvenanceReceiptV5:
    values: dict[str, object] = {
        "receipt_version": "v5.2",
        "issued_at": _at(15, 15),
        "recorded_at": _at(15, 16),
        "valid_until": _at(16),
        "supersedes_content_hash": previous.content_hash,
        "identity_hash": "",
        "content_hash": "",
    }
    values.update(changes)
    return replace(previous, **values)


def test_v5_accepts_expired_creation_graph_with_current_reobservation() -> None:
    receipt = _receipt()
    payload = receipt.to_payload()
    minimum_valid_until = min(receipt.policy.valid_until, receipt.reobservation.valid_until)

    assert receipt.binding.creation_root.is_knowable_at(_at(15)) is False
    assert receipt.binding.is_knowable_at(_at(15)) is True
    assert receipt.reobservation.is_current_at(_at(15)) is True
    assert receipt.policy.is_current_at(_at(15)) is True
    assert receipt.owner == "account"
    assert receipt.artifact_type == ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V5_ARTIFACT_TYPE
    assert receipt.schema == ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V5_SCHEMA
    assert receipt.valid_until < minimum_valid_until
    assert receipt.is_current_at(receipt.recorded_at) is True
    assert receipt.is_current_at(receipt.valid_until) is False
    assert receipt.activation_available is False
    assert receipt.must_not_execute is True
    assert not hasattr(receipt, "__dict__")
    assert payload["policy"] == receipt.policy.to_payload()
    assert payload["binding"] == receipt.binding.to_payload()
    assert payload["reobservation"] == receipt.reobservation.to_payload()
    assert payload["activation_available"] is False
    assert payload["must_not_execute"] is True
    assert len(receipt.identity_hash) == len(receipt.content_hash) == 64

    validate_account_owner_assignment_provenance_receipt_v5_root(receipt)
    validate_account_owner_assignment_provenance_receipt_v5_binding(receipt, receipt.binding)

    with pytest.raises(FrozenInstanceError):
        receipt.receipt_version = "v5.2"  # type: ignore[misc]


def test_v5_fields_are_closed_and_hash_domain_is_versioned() -> None:
    assert {field.name for field in fields(AccountOwnerAssignmentProvenanceReceiptV5)} == {
        "receipt_id",
        "receipt_version",
        "policy",
        "policy_identity_hash",
        "policy_content_hash",
        "binding",
        "reobservation",
        "account_namespace",
        "account_id",
        "underlying_unified_account_namespace",
        "underlying_unified_account_id",
        "allocation_identity_hash",
        "allocation_content_hash",
        "binding_identity_hash",
        "binding_content_hash",
        "account_claim_hash",
        "underlying_claim_hash",
        "reobservation_identity_hash",
        "reobservation_content_hash",
        "current_physical_observation_content_hash",
        "current_physical_source_content_hash",
        "current_physical_raw_observation_content_hash",
        "assigned_owner_user_id",
        "claimant",
        "issued_at",
        "recorded_at",
        "valid_until",
        "supersedes_content_hash",
        "identity_hash",
        "content_hash",
        "owner",
        "artifact_type",
        "schema",
        "provenance_kind",
        "assignment_state",
        "permission",
        "status",
        "blocker_codes",
    }
    receipt = _receipt()
    old = _v4_receipt()
    assert receipt.identity_hash != old.identity_hash
    assert receipt.content_hash != old.content_hash
    assert receipt.provenance_kind == "ownership_reobservation"


@pytest.mark.parametrize(
    "field_name",
    [
        "allocation_identity_hash",
        "allocation_content_hash",
        "binding_identity_hash",
        "binding_content_hash",
        "account_claim_hash",
        "underlying_claim_hash",
        "reobservation_identity_hash",
        "reobservation_content_hash",
        "current_physical_observation_content_hash",
        "current_physical_source_content_hash",
        "current_physical_raw_observation_content_hash",
        "policy_identity_hash",
        "policy_content_hash",
    ],
)
def test_v5_rejects_each_replaced_upstream_seal(field_name: str) -> None:
    with pytest.raises(ValueError):
        _receipt(**{field_name: "0" * 64})


def test_v5_rejects_nested_tampering_and_replaced_binding() -> None:
    receipt = _receipt()
    object.__setattr__(receipt.reobservation.current_physical, "row_user_id", 99)
    with pytest.raises(ValueError):
        receipt.to_payload()

    original = _receipt()
    alternate_binding = _reobservation_binding(
        root=original.binding.creation_root,
        recorded_at=original.binding.recorded_at,
        binding_id="different-binding-v5",
    )
    with pytest.raises(ValueError, match="reobservation must bind"):
        replace(original, binding=alternate_binding, identity_hash="", content_hash="")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"account_namespace": "other-account"}, "Binding"),
        ({"account_id": "acct-other"}, "Binding"),
        ({"underlying_unified_account_id": 8}, "Binding"),
        ({"assigned_owner_user_id": 43}, "match"),
        (
            {
                "claimant": AccountOwnerAssignmentActor(
                    "django-user:43", 43, "account_owner_claimant", is_staff=True
                )
            },
            "match",
        ),
        (
            {
                "claimant": AccountOwnerAssignmentActor(
                    "django-user:42", 42, "different_claimant_role", is_staff=True
                )
            },
            "claimant role",
        ),
        ({"issued_at": _at(15, 11, 59)}, "clock"),
        ({"recorded_at": _at(15, 12, 59)}, "clock"),
        ({"valid_until": _at(15, 14)}, "clock"),
        ({"valid_until": _at(31)}, "outlive"),
    ],
)
def test_v5_rejects_scope_owner_and_clock_substitution(
    changes: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _receipt(**changes)


def test_v5_rejects_wrong_policy_scope_and_expired_current_reobservation() -> None:
    binding = _expired_creation_binding()
    with pytest.raises(ValueError, match="policy.*scope"):
        _receipt(policy=_policy(binding=binding, account_id="other-account"))

    expired = _reobservation(
        binding=binding,
        current_physical=_current_physical(valid_until=_at(16)),
        recorded_at=_at(15),
        valid_until=_at(16),
    )
    with pytest.raises(ValueError, match="reobservation"):
        _receipt(
            reobservation=expired,
            issued_at=_at(17, 13),
            recorded_at=_at(17, 14),
            valid_until=_at(18),
        )


def test_v5_rejects_future_or_naive_reobservation_and_noncanonical_hash_type() -> None:
    with pytest.raises(ValueError, match="clock"):
        _receipt(reobservation=_reobservation(recorded_at=_at(16)))
    with pytest.raises(ValueError, match="timezone-aware"):
        _receipt(recorded_at=datetime(2026, 8, 15, 14))
    with pytest.raises(TypeError, match="exact string"):
        _receipt(identity_hash=cast(object, True))
    with pytest.raises(TypeError, match="exact AccountOwnerAssignmentActor"):
        receipt = _receipt()
        replace(
            receipt,
            claimant=cast(AccountOwnerAssignmentActor, object()),
            identity_hash="",
            content_hash="",
        )


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("receipt_id", True, "exact string"),
        ("receipt_id", "bad token", "bounded canonical token"),
        ("receipt_id", "", "bounded canonical token"),
        ("underlying_unified_account_id", True, "exact positive integer"),
        ("underlying_unified_account_id", 0, "exact positive integer"),
        ("policy_identity_hash", True, "exact string"),
        ("policy_identity_hash", "g" * 64, "lowercase SHA-256"),
        ("owner", True, "exact string"),
        ("owner", "other", "fixed"),
        ("blocker_codes", ["other"], "exact tuple"),
        ("blocker_codes", ("other",), "fixed"),
        ("identity_hash", "a" * 64, "identity_hash is invalid"),
    ],
)
def test_v5_rejects_primitive_and_fixed_semantic_substitution(
    field_name: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        _receipt(**{field_name: value})


def test_v5_rejects_each_wrong_nested_runtime_type() -> None:
    receipt = _receipt()
    with pytest.raises(TypeError, match="exact SingleOwnerAuthorityPolicyV1"):
        replace(receipt, policy=cast(SingleOwnerAuthorityPolicyV1, object()))
    with pytest.raises(TypeError, match="exact CanonicalAccountCreationBindingV2"):
        replace(receipt, binding=cast(CanonicalAccountCreationBindingV2, object()))
    with pytest.raises(
        TypeError,
        match="exact CanonicalAccountOwnershipReobservationV1",
    ):
        replace(receipt, reobservation=cast(CanonicalAccountOwnershipReobservationV1, object()))


def test_v5_policy_currentness_and_knowable_reads_are_fail_closed() -> None:
    binding = _expired_creation_binding()
    with pytest.raises(ValueError, match="policy"):
        _receipt(policy=_policy(binding=binding, status="revoked"))

    receipt = _receipt()
    assert receipt.is_knowable_at(receipt.recorded_at - datetime.resolution) is False
    assert receipt.is_knowable_at(receipt.recorded_at) is True
    assert receipt.is_knowable_at(receipt.valid_until) is True
    with pytest.raises(ValueError, match="timezone-aware"):
        receipt.is_knowable_at(datetime(2026, 8, 15, 14))


def test_v5_binding_validator_rejects_wrong_types_mismatch_hashes_and_scope() -> None:
    receipt = _receipt()
    with pytest.raises(TypeError, match="exact v5 receipt"):
        validate_account_owner_assignment_provenance_receipt_v5_binding(
            cast(AccountOwnerAssignmentProvenanceReceiptV5, object()), receipt.binding
        )
    with pytest.raises(TypeError, match="exact CanonicalAccountCreationBindingV2"):
        validate_account_owner_assignment_provenance_receipt_v5_binding(
            receipt, cast(CanonicalAccountCreationBindingV2, object())
        )

    bad_policy = _receipt()
    object.__setattr__(bad_policy, "policy", cast(SingleOwnerAuthorityPolicyV1, object()))
    with pytest.raises(TypeError, match="exact SingleOwnerAuthorityPolicyV1"):
        validate_account_owner_assignment_provenance_receipt_v5_binding(
            bad_policy, bad_policy.binding
        )

    bad_reobservation = _receipt()
    object.__setattr__(
        bad_reobservation,
        "reobservation",
        cast(CanonicalAccountOwnershipReobservationV1, object()),
    )
    with pytest.raises(TypeError, match="exact CanonicalAccountOwnershipReobservationV1"):
        validate_account_owner_assignment_provenance_receipt_v5_binding(
            bad_reobservation, bad_reobservation.binding
        )

    alternate_binding = _reobservation_binding(
        root=receipt.binding.creation_root,
        recorded_at=receipt.binding.recorded_at,
        binding_id="different-binding-validator-v5",
        identity_hash="",
        content_hash="",
    )
    with pytest.raises(ValueError, match="exact canonical Binding"):
        validate_account_owner_assignment_provenance_receipt_v5_binding(receipt, alternate_binding)

    bad_hashes = _receipt()
    object.__setattr__(bad_hashes, "policy_identity_hash", "0" * 64)
    with pytest.raises(ValueError, match="single-owner policy hashes"):
        validate_account_owner_assignment_provenance_receipt_v5_binding(
            bad_hashes, bad_hashes.binding
        )

    wrong_scope = _receipt()
    wrong_policy = _policy(binding=wrong_scope.binding, account_id="other-account")
    object.__setattr__(wrong_scope, "policy", wrong_policy)
    object.__setattr__(wrong_scope, "policy_identity_hash", wrong_policy.identity_hash)
    object.__setattr__(wrong_scope, "policy_content_hash", wrong_policy.content_hash)
    with pytest.raises(ValueError, match="policy account scope"):
        validate_account_owner_assignment_provenance_receipt_v5_binding(
            wrong_scope, wrong_scope.binding
        )


def test_v5_root_successor_and_head_resolver_never_fall_back() -> None:
    first = _receipt()
    second = _successor(first)

    validate_account_owner_assignment_provenance_receipt_v5_root(first)
    validate_account_owner_assignment_provenance_receipt_v5_successor(first, second)
    assert (
        resolve_account_owner_assignment_provenance_receipt_v5_head(
            (first, second), as_of=second.recorded_at
        )
        is second
    )
    assert (
        resolve_account_owner_assignment_provenance_receipt_v5_head(
            (first,), as_of=first.recorded_at
        )
        is first
    )
    assert (
        resolve_account_owner_assignment_provenance_receipt_v5_head(
            (first,), as_of=first.valid_until
        )
        is None
    )
    assert (
        resolve_account_owner_assignment_provenance_receipt_v5_head((), as_of=first.recorded_at)
        is None
    )
    assert (
        resolve_account_owner_assignment_provenance_receipt_v5_head(
            (first,), as_of=first.recorded_at - datetime.resolution
        )
        is None
    )
    with pytest.raises(TypeError, match="exact tuple"):
        resolve_account_owner_assignment_provenance_receipt_v5_head(  # type: ignore[arg-type]
            [first], as_of=first.recorded_at
        )

    with pytest.raises(ValueError, match="predecessor"):
        validate_account_owner_assignment_provenance_receipt_v5_root(second)


def test_v5_successor_checks_predecessor_version_type_and_clocks() -> None:
    first = _receipt()
    successor = _successor(first)
    with pytest.raises(ValueError, match="predecessor"):
        validate_account_owner_assignment_provenance_receipt_v5_successor(
            first,
            replace(
                successor,
                supersedes_content_hash="0" * 64,
                identity_hash="",
                content_hash="",
            ),
        )
    with pytest.raises(ValueError, match="receipt_version"):
        validate_account_owner_assignment_provenance_receipt_v5_successor(
            first,
            _successor(first, receipt_version=first.receipt_version),
        )
    with pytest.raises(ValueError, match="successor changed receipt_id"):
        validate_account_owner_assignment_provenance_receipt_v5_successor(
            first,
            _successor(first, receipt_id="different-receipt-v5"),
        )
    with pytest.raises(ValueError, match="clocks"):
        validate_account_owner_assignment_provenance_receipt_v5_successor(
            first,
            _successor(first, issued_at=first.issued_at),
        )
    with pytest.raises(TypeError, match="exact v5 values"):
        validate_account_owner_assignment_provenance_receipt_v5_successor(
            cast(AccountOwnerAssignmentProvenanceReceiptV5, object()), successor
        )
    with pytest.raises(TypeError, match="exact v5 values"):
        validate_account_owner_assignment_provenance_receipt_v5_successor(
            first, cast(AccountOwnerAssignmentProvenanceReceiptV5, object())
        )


def test_v5_root_validator_rejects_wrong_runtime_type() -> None:
    with pytest.raises(TypeError, match="exact v5 receipt"):
        validate_account_owner_assignment_provenance_receipt_v5_root(
            cast(AccountOwnerAssignmentProvenanceReceiptV5, object())
        )


def test_v4_rejects_the_same_expired_root_and_preserves_its_golden_hashes() -> None:
    old = _v4_receipt()
    assert old.identity_hash == ("dc5cb20e7c0d2747b8c5ea6dde87614e9eaf46fd6b2533ac4c0994649b8f2605")
    assert old.content_hash == ("434c4b3f66c823750a916a00d7917585132198b49ac8cbea3dfd54f1ae21d136")

    binding = _expired_creation_binding()
    policy = _policy(binding=binding, valid_until=_at(30))
    with pytest.raises(ValueError, match="creation root"):
        _v4_receipt(
            binding=binding,
            policy=policy,
            issued_at=_at(15, 13),
            recorded_at=_at(15, 14),
            valid_until=_at(16),
        )


def test_v5_domain_module_has_only_stdlib_and_account_domain_imports() -> None:
    source_path = (
        Path(__file__).parents[3]
        / "apps"
        / "account"
        / "domain"
        / "account_owner_assignment_provenance_receipt_v5.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}

    assert not any(name.startswith(("django", "pandas", "numpy", "requests")) for name in imports)
    assert imports <= {
        "__future__",
        "apps.account.domain.account_owner_assignment_evidence",
        "apps.account.domain.canonical_account_creation_binding_v2",
        "apps.account.domain.canonical_account_ownership_reobservation_v1",
        "apps.account.domain.single_owner_authority_policy_v1",
        "dataclasses",
        "datetime",
        "hashlib",
        "json",
    }
