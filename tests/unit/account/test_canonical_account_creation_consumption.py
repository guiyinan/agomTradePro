from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, fields, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast

import pytest

from apps.account.domain.canonical_account_creation import (
    CanonicalAccountCreationAllocation,
    CanonicalAccountCreationBinding,
)
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)
from apps.account.domain.canonical_account_creation_consumption import (
    CanonicalAccountCreationConsumptionClaim,
    resolve_canonical_account_creation_consumption_claim_identity,
)
from tests.unit.account.test_canonical_account_creation import (
    _allocation,
)
from tests.unit.account.test_canonical_account_creation import _binding as _binding_v1
from tests.unit.account.test_canonical_account_creation_binding_v2 import _binding as _binding_v2

Consumer = CanonicalAccountCreationBinding | CanonicalAccountCreationBindingV2


def _claim(**changes: object) -> CanonicalAccountCreationConsumptionClaim:
    generation = cast(str, changes.pop("consumer_generation", "v1"))
    default_consumer: Consumer = _binding_v1() if generation == "v1" else _binding_v2()
    consumer = cast(Consumer, changes.pop("consumer", default_consumer))
    if type(consumer) is CanonicalAccountCreationBinding:
        physical = consumer.physical_observation
        root_hash: str | None = None
    else:
        physical = consumer.creation_root.physical_observation
        root_hash = consumer.creation_root.content_hash
    values: dict[str, object] = {
        "claim_id": "allocation-consumption-7",
        "claim_version": "v1",
        "allocation": consumer.allocation,
        "consumer_generation": generation,
        "consumer": consumer,
        "account_namespace": physical.account_namespace,
        "account_id": physical.account_id,
        "underlying_unified_account_namespace": (physical.underlying_unified_account_namespace),
        "underlying_unified_account_id": physical.underlying_unified_account_id,
        "physical_v2_content_hash": physical.content_hash,
        "physical_v3_root_content_hash": root_hash,
        "recorded_at": consumer.recorded_at,
    }
    values.update(changes)
    return CanonicalAccountCreationConsumptionClaim(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("generation", ["v1", "v2"])
def test_both_consumer_generations_are_fixed_frozen_inactive_evidence(
    generation: str,
) -> None:
    claim = _claim(consumer_generation=generation)
    field_names = {field.name for field in fields(CanonicalAccountCreationConsumptionClaim)}

    assert claim.owner == "account"
    assert claim.artifact_type == "canonical_account_creation_consumption_claim"
    assert claim.schema == "canonical-account-creation-consumption-claim.v1"
    assert claim.permission == "evidence_only"
    assert claim.status == "inactive"
    assert claim.activation_available is False
    assert claim.must_not_execute is True
    assert not hasattr(claim, "__dict__")
    assert "valid_until" not in field_names
    assert not any("supersedes" in field_name for field_name in field_names)
    with pytest.raises(FrozenInstanceError):
        claim.claim_version = "v2"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("owner", "simulated_trading"),
        ("artifact_type", "canonical_account_creation_binding"),
        ("schema", "canonical-account-creation-consumption-claim.v2"),
        ("permission", "execute"),
        ("status", "active"),
    ],
)
def test_fixed_semantics_cannot_be_promoted(field_name: str, value: str) -> None:
    with pytest.raises(ValueError, match="fixed"):
        _claim(**{field_name: value})


def test_payload_embeds_complete_allocation_but_only_exact_consumer_header() -> None:
    claim = _claim(consumer_generation="v2")
    payload = claim.to_payload()

    assert payload["allocation"] == {
        **claim.allocation.to_payload(),
        "identity_hash": claim.allocation.identity_hash,
        "content_hash": claim.allocation.content_hash,
    }
    assert payload["consumer_ref"] == {
        "owner": claim.consumer.owner,
        "artifact_type": claim.consumer.artifact_type,
        "schema": claim.consumer.schema,
        "consumer_id": claim.consumer.binding_id,
        "consumer_version": claim.consumer.binding_version,
        "identity_hash": claim.consumer.identity_hash,
        "content_hash": claim.consumer.content_hash,
    }
    assert "consumer" not in payload
    assert "allocation" not in cast(dict[str, object], payload["consumer_ref"])
    assert "creation_root" not in cast(dict[str, object], payload["consumer_ref"])


@pytest.mark.parametrize(
    ("generation", "consumer", "message"),
    [
        ("v1", _binding_v2(), "v1 consumer"),
        ("v2", _binding_v1(), "v2 consumer"),
    ],
)
def test_generation_selects_one_exact_consumer_contract(
    generation: str,
    consumer: Consumer,
    message: str,
) -> None:
    with pytest.raises(TypeError, match=message):
        _claim(consumer_generation=generation, consumer=consumer)
    with pytest.raises(ValueError, match="exactly v1 or v2"):
        _claim(consumer_generation="v3")
    with pytest.raises(TypeError, match="exact string"):
        _claim(consumer_generation=cast(str, 1))


def test_claim_revalidates_the_exact_allocation_and_consumer() -> None:
    with pytest.raises(ValueError, match="exact allocation"):
        _claim(allocation=_allocation(allocation_id="allocation-other"))
    with pytest.raises(TypeError, match="exact CanonicalAccountCreationAllocation"):
        _claim(allocation=cast(CanonicalAccountCreationAllocation, object()))

    claim = _claim()
    object.__setattr__(claim.consumer, "account_id_claim", "acct-tampered")
    with pytest.raises(ValueError):
        claim.to_payload()

    claim = _claim(consumer_generation="v2")
    object.__setattr__(claim.allocation, "canonical_account_id", "acct-tampered")
    with pytest.raises(ValueError):
        claim.to_payload()


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("account_namespace", "other", "Account raw key"),
        ("account_id", "acct-other", "Account raw key"),
        (
            "underlying_unified_account_namespace",
            "other-row",
            "underlying raw key",
        ),
        ("underlying_unified_account_id", 8, "underlying raw key"),
        ("physical_v2_content_hash", "a" * 64, "physical_v2_content_hash"),
    ],
)
@pytest.mark.parametrize("generation", ["v1", "v2"])
def test_raw_keys_and_physical_v2_hash_are_exact(
    generation: str,
    field_name: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _claim(consumer_generation=generation, **{field_name: value})


def test_physical_v3_root_hash_branch_matrix_is_closed() -> None:
    with pytest.raises(ValueError, match="requires.*None"):
        _claim(physical_v3_root_content_hash="a" * 64)
    with pytest.raises(ValueError, match="requires physical_v3"):
        _claim(consumer_generation="v2", physical_v3_root_content_hash=None)
    with pytest.raises(ValueError, match="does not match"):
        _claim(consumer_generation="v2", physical_v3_root_content_hash="a" * 64)
    with pytest.raises(TypeError, match="exact string"):
        _claim(
            consumer_generation="v2",
            physical_v3_root_content_hash=cast(str, True),
        )


def test_dual_identity_claims_are_domain_separated_and_candidate_independent() -> None:
    v1 = _claim()
    v2 = _claim(
        consumer_generation="v2",
        claim_id="different-claim",
        consumer=_binding_v2(binding_id="different-consumer"),
    )

    assert v1.account_claim_hash == v2.account_claim_hash
    assert v1.underlying_claim_hash == v2.underlying_claim_hash
    assert v1.account_claim_hash != v1.underlying_claim_hash
    assert v1.identity_hash != v2.identity_hash
    assert v1.content_hash != v2.content_hash


@pytest.mark.parametrize(
    "field_name",
    ["account_claim_hash", "underlying_claim_hash", "identity_hash", "content_hash"],
)
def test_all_claim_seals_are_recomputed(field_name: str) -> None:
    claim = _claim()
    assert (
        _claim(
            **{
                "account_claim_hash": claim.account_claim_hash,
                "underlying_claim_hash": claim.underlying_claim_hash,
                "identity_hash": claim.identity_hash,
                "content_hash": claim.content_hash,
            }
        )
        == claim
    )
    with pytest.raises(ValueError, match=field_name):
        _claim(**{field_name: "0" * 64})


def test_atomic_recording_clock_is_exact_and_canonical() -> None:
    consumer = _binding_v1()
    claim = _claim(consumer=consumer)
    equivalent = _claim(
        consumer=replace(
            consumer,
            recorded_at=consumer.recorded_at.astimezone(timezone(timedelta(hours=8))),
            identity_hash="",
            content_hash="",
            account_claim_hash="",
            underlying_claim_hash="",
        ),
        recorded_at=consumer.recorded_at.astimezone(timezone(timedelta(hours=8))),
    )
    assert equivalent.content_hash == claim.content_hash

    with pytest.raises(ValueError, match="exact same recorded_at"):
        _claim(recorded_at=consumer.recorded_at + timedelta(seconds=1))
    with pytest.raises(ValueError, match="timezone-aware"):
        _claim(recorded_at=datetime(2026, 8, 7, 12))


def test_strict_scalar_runtime_types_fail_closed() -> None:
    with pytest.raises(TypeError, match="exact integer"):
        _claim(underlying_unified_account_id=True)
    with pytest.raises(TypeError, match="exact string"):
        _claim(claim_id=1)
    with pytest.raises(TypeError, match="exact string"):
        _claim(physical_v2_content_hash=True)


def test_claim_identity_is_allocation_derived_and_generation_scoped() -> None:
    allocation = _allocation()
    assert resolve_canonical_account_creation_consumption_claim_identity(
        allocation, consumer_generation="v1"
    ) == (f"allocation-consumption-{allocation.identity_hash}", "v1")
    assert resolve_canonical_account_creation_consumption_claim_identity(
        allocation, consumer_generation="v2"
    ) == (f"allocation-consumption-{allocation.identity_hash}", "v2")


def test_claim_identity_rejects_substitution_and_unknown_generation() -> None:
    with pytest.raises(TypeError, match="exact CanonicalAccountCreationAllocation"):
        resolve_canonical_account_creation_consumption_claim_identity(
            object(), consumer_generation="v1"  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="exactly v1 or v2"):
        resolve_canonical_account_creation_consumption_claim_identity(
            _allocation(), consumer_generation="v3"
        )


def test_domain_module_has_only_standard_library_and_same_domain_imports() -> None:
    source_path = (
        Path(__file__).parents[3]
        / "apps"
        / "account"
        / "domain"
        / "canonical_account_creation_consumption.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}

    assert not any(
        name.startswith("apps.") and not name.startswith("apps.account.domain.") for name in imports
    )
    assert imports <= {
        "__future__",
        "apps.account.domain.canonical_account_creation",
        "apps.account.domain.canonical_account_creation_binding_v2",
        "dataclasses",
        "datetime",
        "hashlib",
        "json",
        "typing",
    }
