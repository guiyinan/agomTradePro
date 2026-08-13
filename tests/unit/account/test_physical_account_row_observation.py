from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime, timedelta, timezone
from typing import cast

import pytest

from apps.account.domain.physical_account_row_observation import (
    PhysicalAccountRowObservation,
    resolve_physical_account_row_observation_head,
    validate_physical_account_row_observation_successor,
)

HASH_A = "a" * 64


def _at(day: int) -> datetime:
    return datetime(2026, 8, day, 12, tzinfo=UTC)


def _observation(**changes: object) -> PhysicalAccountRowObservation:
    values: dict[str, object] = {
        "observation_id": "physical-row-0007",
        "observation_version": "v1",
        "account_namespace": "broker-account",
        "account_id": "0007",
        "underlying_unified_account_namespace": "simulated-account-row",
        "underlying_unified_account_id": 7,
        "raw_source_owner": "simulated_trading",
        "raw_source_artifact_type": "simulated_account_row",
        "raw_source_id": "row-7",
        "raw_source_version": "rv1",
        "raw_source_content_hash": HASH_A,
        "row_user_id": None,
        "account_type": "paper-v1",
        "is_active": True,
        "row_created_at": _at(1),
        "row_updated_at": _at(2),
        "observed_at": _at(3),
        "recorded_at": _at(4),
        "raw_source_valid_until": _at(20),
        "ttl_valid_until": _at(10),
        "valid_until": _at(10),
    }
    values.update(changes)
    return PhysicalAccountRowObservation(**values)  # type: ignore[arg-type]


def _successor(
    previous: PhysicalAccountRowObservation,
    **changes: object,
) -> PhysicalAccountRowObservation:
    values: dict[str, object] = {
        "observation_id": previous.observation_id,
        "observation_version": "v2",
        "account_namespace": previous.account_namespace,
        "account_id": previous.account_id,
        "underlying_unified_account_namespace": (previous.underlying_unified_account_namespace),
        "underlying_unified_account_id": previous.underlying_unified_account_id,
        "raw_source_owner": previous.raw_source_owner,
        "raw_source_artifact_type": previous.raw_source_artifact_type,
        "raw_source_id": previous.raw_source_id,
        "raw_source_version": "rv2",
        "raw_source_content_hash": "b" * 64,
        "row_user_id": 42,
        "account_type": "paper-v2",
        "is_active": True,
        "row_created_at": previous.row_created_at,
        "row_updated_at": _at(5),
        "observed_at": _at(6),
        "recorded_at": _at(7),
        "raw_source_valid_until": _at(22),
        "ttl_valid_until": _at(14),
        "valid_until": _at(14),
        "supersedes_content_hash": previous.content_hash,
    }
    values.update(changes)
    return PhysicalAccountRowObservation(**values)  # type: ignore[arg-type]


def test_nullable_or_present_row_user_never_becomes_an_owner_assignment() -> None:
    without_user = _observation()
    with_user = _observation(row_user_id=42)

    assert without_user.owner_assignment_state == "unknown"
    assert with_user.owner_assignment_state == "unknown"
    assert "owner_user_id" not in with_user.to_payload()

    with pytest.raises(ValueError, match="owner_assignment_state is fixed"):
        _observation(owner_assignment_state="authoritative")


def test_account_string_and_underlying_integer_are_preserved_without_casting() -> None:
    observation = _observation(account_id="0007", underlying_unified_account_id=7)

    assert observation.account_id == "0007"
    assert type(observation.account_id) is str
    assert observation.underlying_unified_account_id == 7
    assert type(observation.underlying_unified_account_id) is int
    assert observation.to_payload()["account_id"] == "0007"

    with pytest.raises(TypeError, match="account_id must be an exact string"):
        _observation(account_id=7)
    with pytest.raises(TypeError, match="underlying.*exact integer"):
        _observation(underlying_unified_account_id="7")
    with pytest.raises(TypeError, match="underlying.*exact integer"):
        _observation(underlying_unified_account_id=True)


def test_mutable_row_fields_change_content_hash_and_are_valid_successors() -> None:
    previous = _observation()
    successor = _successor(previous)

    validate_physical_account_row_observation_successor(previous, successor)

    assert successor.row_user_id == 42
    assert successor.account_type == "paper-v2"
    assert successor.content_hash != previous.content_hash
    assert successor.identity_hash != previous.identity_hash
    assert successor.owner_assignment_state == "unknown"


@pytest.mark.parametrize(  # type: ignore[misc]
    ("changes", "message"),
    [
        ({"supersedes_content_hash": "c" * 64}, "exact previous"),
        ({"observation_id": "other"}, "observation_id"),
        ({"observation_version": "v1"}, "version must advance"),
        ({"account_id": "0008"}, "account_id"),
        ({"underlying_unified_account_id": 8}, "underlying"),
        ({"raw_source_id": "row-8"}, "raw_source_id"),
        ({"raw_source_version": "rv1"}, "raw_source_version"),
        ({"row_updated_at": _at(3), "observed_at": _at(3)}, "observed_at"),
        (
            {"row_updated_at": _at(4), "observed_at": _at(4), "recorded_at": _at(4)},
            "recorded_at",
        ),
    ],
)
def test_successor_requires_same_logical_row_and_exact_progression(
    changes: dict[str, object],
    message: str,
) -> None:
    previous = _observation()
    successor = _successor(previous, **changes)

    with pytest.raises(ValueError, match=message):
        validate_physical_account_row_observation_successor(previous, successor)


def test_valid_until_is_exact_minimum_of_source_and_ttl() -> None:
    ttl_first = _observation()
    source_first = _observation(
        raw_source_valid_until=_at(9),
        ttl_valid_until=_at(20),
        valid_until=_at(9),
    )

    assert ttl_first.valid_until == _at(10)
    assert source_first.valid_until == _at(9)

    with pytest.raises(ValueError, match="minimum"):
        _observation(valid_until=_at(20))


@pytest.mark.parametrize(  # type: ignore[misc]
    "changes",
    [
        {"observed_at": datetime(2026, 8, 3, 12)},
        {"recorded_at": datetime(2026, 8, 4, 12)},
        {"row_updated_at": _at(1) - timedelta(seconds=1)},
        {"observed_at": _at(2) - timedelta(seconds=1)},
        {"recorded_at": _at(3) - timedelta(seconds=1)},
        {"raw_source_valid_until": _at(4)},
        {"ttl_valid_until": _at(4)},
    ],
)
def test_naive_or_inverted_clocks_fail_closed(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _observation(**changes)


def test_canonical_json_uses_utc_z_and_equivalent_instants_hash_identically() -> None:
    offset = timezone(timedelta(hours=8))
    utc_value = _observation()
    offset_value = _observation(
        row_created_at=_at(1).astimezone(offset),
        row_updated_at=_at(2).astimezone(offset),
        observed_at=_at(3).astimezone(offset),
        recorded_at=_at(4).astimezone(offset),
        raw_source_valid_until=_at(20).astimezone(offset),
        ttl_valid_until=_at(10).astimezone(offset),
        valid_until=_at(10).astimezone(offset),
    )

    assert offset_value.content_hash == utc_value.content_hash
    assert cast(str, utc_value.to_payload()["recorded_at"]).endswith("Z")


def test_fixed_source_and_inactive_execution_semantics_cannot_be_overridden() -> None:
    observation = _observation()

    assert observation.owner == "account"
    assert observation.artifact_type == "physical_account_row_observation"
    assert observation.schema == "physical-account-row-observation.v1"
    assert observation.permission == "evidence_only"
    assert observation.status == "inactive"
    assert observation.activation_available is False
    assert observation.must_not_execute is True

    with pytest.raises(ValueError, match="raw_source_owner is fixed"):
        _observation(raw_source_owner="account")
    with pytest.raises(ValueError, match="status is fixed"):
        _observation(status="active")


def test_exact_bool_integer_hash_and_token_validation() -> None:
    with pytest.raises(TypeError, match="exact boolean"):
        _observation(is_active=1)
    with pytest.raises(TypeError, match="row_user_id"):
        _observation(row_user_id=True)
    with pytest.raises(ValueError, match="SHA-256"):
        _observation(raw_source_content_hash="A" * 64)
    with pytest.raises(ValueError, match="canonical token"):
        _observation(account_type="paper account")


def test_tamper_subclass_and_container_shape_fail_closed() -> None:
    observation = _observation()
    object.__setattr__(observation, "is_active", False)
    with pytest.raises(ValueError, match="content_hash"):
        observation.to_payload()
        PhysicalAccountRowObservation.__post_init__(observation)

    class SubObservation(PhysicalAccountRowObservation):
        pass

    sub = object.__new__(SubObservation)
    for field in fields(PhysicalAccountRowObservation):
        object.__setattr__(sub, field.name, getattr(_observation(), field.name))
    with pytest.raises(TypeError, match="exact Physical"):
        validate_physical_account_row_observation_successor(sub, _successor(_observation()))
    with pytest.raises(TypeError, match="exact tuple"):
        resolve_physical_account_row_observation_head(
            cast(tuple[PhysicalAccountRowObservation, ...], [_observation()]),
            as_of=_at(5),
        )
    with pytest.raises(TypeError, match="chain values"):
        resolve_physical_account_row_observation_head(
            cast(
                tuple[PhysicalAccountRowObservation, ...],
                ({"content_hash": HASH_A},),
            ),
            as_of=_at(5),
        )


def test_pit_head_does_not_fallback_from_final_expired_or_inactive_row() -> None:
    first = _observation(
        raw_source_valid_until=_at(30),
        ttl_valid_until=_at(30),
        valid_until=_at(30),
    )
    inactive = _successor(first, is_active=False)

    assert resolve_physical_account_row_observation_head((first,), as_of=_at(5)) is first
    assert resolve_physical_account_row_observation_head((first, inactive), as_of=_at(8)) is None

    expired = _successor(first, ttl_valid_until=_at(8), valid_until=_at(8))
    assert resolve_physical_account_row_observation_head((first, expired), as_of=_at(9)) is None
