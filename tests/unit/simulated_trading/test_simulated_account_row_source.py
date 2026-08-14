from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime, timedelta, timezone
from typing import cast

import pytest

from apps.simulated_trading.domain.simulated_account_row_source import (
    SimulatedAccountRowSource,
    resolve_simulated_account_row_source_head,
    validate_simulated_account_row_source_successor,
)


def _at(day: int) -> datetime:
    return datetime(2026, 8, day, 12, tzinfo=UTC)


def _source(**changes: object) -> SimulatedAccountRowSource:
    values: dict[str, object] = {
        "source_id": "simulated-row-0007",
        "source_version": "v1",
        "account_namespace": "account",
        "account_id": "0007",
        "underlying_unified_account_namespace": "simulated-account-row",
        "underlying_unified_account_id": 7,
        "row_user_id": None,
        "raw_account_type": "SIMULATED",
        "is_active": True,
        "row_created_at": _at(1),
        "row_updated_at": _at(2),
        "is_present": True,
        "is_tombstone": False,
        "observed_at": _at(3),
        "recorded_at": _at(4),
        "source_valid_until": _at(20),
        "ttl_valid_until": _at(10),
        "valid_until": _at(10),
    }
    values.update(changes)
    return SimulatedAccountRowSource(**values)  # type: ignore[arg-type]


def _successor(
    previous: SimulatedAccountRowSource,
    **changes: object,
) -> SimulatedAccountRowSource:
    values: dict[str, object] = {
        "source_id": previous.source_id,
        "source_version": "v2",
        "account_namespace": previous.account_namespace,
        "account_id": previous.account_id,
        "underlying_unified_account_namespace": (previous.underlying_unified_account_namespace),
        "underlying_unified_account_id": previous.underlying_unified_account_id,
        "row_user_id": 42,
        "raw_account_type": "real",
        "is_active": True,
        "row_created_at": previous.row_created_at,
        "row_updated_at": _at(5),
        "is_present": True,
        "is_tombstone": False,
        "observed_at": _at(6),
        "recorded_at": _at(7),
        "source_valid_until": _at(22),
        "ttl_valid_until": _at(14),
        "valid_until": _at(14),
        "supersedes_content_hash": previous.content_hash,
    }
    values.update(changes)
    return SimulatedAccountRowSource(**values)  # type: ignore[arg-type]


def test_fixed_owner_and_execution_semantics_cannot_be_overridden() -> None:
    source = _source()

    assert source.owner == "simulated_trading"
    assert source.artifact_type == "simulated_account_row"
    assert source.schema == "simulated-account-row.v1"
    assert source.permission == "evidence_only"
    assert source.status == "inactive"
    assert source.owner_assignment_state == "unknown"
    assert source.activation_available is False
    assert source.must_not_execute is True

    with pytest.raises(ValueError, match="owner is fixed"):
        _source(owner="account")
    with pytest.raises(ValueError, match="artifact_type is fixed"):
        _source(artifact_type="unified_account")
    with pytest.raises(ValueError, match="schema is fixed"):
        _source(schema="simulated-account-row.v2")
    with pytest.raises(ValueError, match="permission is fixed"):
        _source(permission="execute")
    with pytest.raises(ValueError, match="status is fixed"):
        _source(status="active")
    with pytest.raises(ValueError, match="owner_assignment_state is fixed"):
        _source(owner_assignment_state="authoritative")


def test_account_string_and_underlying_integer_are_preserved_without_casting() -> None:
    source = _source(account_id="0007", underlying_unified_account_id=7)

    assert source.account_id == "0007"
    assert type(source.account_id) is str
    assert source.underlying_unified_account_id == 7
    assert type(source.underlying_unified_account_id) is int
    assert source.to_payload()["account_id"] == "0007"

    with pytest.raises(TypeError, match="account_id must be an exact string"):
        _source(account_id=7)
    with pytest.raises(TypeError, match="underlying.*exact integer"):
        _source(underlying_unified_account_id="7")
    with pytest.raises(TypeError, match="underlying.*exact integer"):
        _source(underlying_unified_account_id=True)


def test_raw_row_fields_never_claim_owner_or_normalized_account_type() -> None:
    source = _source(row_user_id=42, raw_account_type="SIMULATED")
    payload = source.to_payload()

    assert source.row_user_id == 42
    assert source.raw_account_type == "SIMULATED"
    assert source.owner_assignment_state == "unknown"
    assert "owner_user_id" not in payload
    assert "provenance" not in payload

    with pytest.raises(TypeError, match="row_user_id"):
        _source(row_user_id=True)
    with pytest.raises(ValueError, match="row_user_id"):
        _source(row_user_id=0)


def test_presence_and_tombstone_are_explicit_opposite_states() -> None:
    present = _source()
    tombstone = _source(is_present=False, is_tombstone=True)

    assert present.is_present is True
    assert present.is_tombstone is False
    assert tombstone.is_present is False
    assert tombstone.is_tombstone is True

    with pytest.raises(ValueError, match="exact opposites"):
        _source(is_present=True, is_tombstone=True)
    with pytest.raises(ValueError, match="exact opposites"):
        _source(is_present=False, is_tombstone=False)
    with pytest.raises(TypeError, match="is_present must be an exact boolean"):
        _source(is_present=1)


def test_valid_until_is_exact_minimum_of_source_and_ttl() -> None:
    ttl_first = _source()
    source_first = _source(
        source_valid_until=_at(9),
        ttl_valid_until=_at(20),
        valid_until=_at(9),
    )

    assert ttl_first.valid_until == _at(10)
    assert source_first.valid_until == _at(9)

    with pytest.raises(ValueError, match="minimum"):
        _source(valid_until=_at(20))


@pytest.mark.parametrize(
    "changes",
    [
        {"row_created_at": datetime(2026, 8, 1, 12)},
        {"row_updated_at": _at(1) - timedelta(seconds=1)},
        {"observed_at": _at(2) - timedelta(seconds=1)},
        {"recorded_at": _at(3) - timedelta(seconds=1)},
        {"source_valid_until": _at(4)},
        {"ttl_valid_until": _at(4)},
    ],
)
def test_naive_or_inverted_clocks_fail_closed(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _source(**changes)


def test_canonical_hash_covers_every_explicit_source_fact() -> None:
    baseline = _source()
    variants: tuple[dict[str, object], ...] = (
        {"account_namespace": "account-v2"},
        {"account_id": "0008"},
        {"underlying_unified_account_namespace": "simulated-row-v2"},
        {"underlying_unified_account_id": 8},
        {"row_user_id": 42},
        {"raw_account_type": "simulated"},
        {"is_active": False},
        {"row_created_at": _at(1) + timedelta(seconds=1)},
        {"row_updated_at": _at(2) + timedelta(seconds=1)},
        {"is_present": False, "is_tombstone": True},
        {"observed_at": _at(3) + timedelta(seconds=1)},
        {"recorded_at": _at(4) + timedelta(seconds=1)},
        {"source_valid_until": _at(19)},
        {"ttl_valid_until": _at(9), "valid_until": _at(9)},
        {"supersedes_content_hash": "a" * 64},
    )

    for changes in variants:
        assert _source(**changes).content_hash != baseline.content_hash

    payload = baseline.to_payload()
    assert {
        "source_id",
        "source_version",
        "account_namespace",
        "account_id",
        "underlying_unified_account_namespace",
        "underlying_unified_account_id",
        "row_user_id",
        "raw_account_type",
        "is_active",
        "row_created_at",
        "row_updated_at",
        "is_present",
        "is_tombstone",
        "observed_at",
        "recorded_at",
        "source_valid_until",
        "ttl_valid_until",
        "valid_until",
        "owner_assignment_state",
        "supersedes_content_hash",
    } <= payload.keys()


def test_identity_hash_is_source_id_and_version_identity() -> None:
    baseline = _source()
    same_identity_different_content = _source(row_user_id=42)
    next_identity = _source(source_version="v2")

    assert same_identity_different_content.identity_hash == baseline.identity_hash
    assert same_identity_different_content.content_hash != baseline.content_hash
    assert next_identity.identity_hash != baseline.identity_hash
    assert next_identity.content_hash != baseline.content_hash


def test_equivalent_instants_hash_identically_and_serialize_as_utc_z() -> None:
    offset = timezone(timedelta(hours=8))
    utc_source = _source()
    offset_source = _source(
        row_created_at=_at(1).astimezone(offset),
        row_updated_at=_at(2).astimezone(offset),
        observed_at=_at(3).astimezone(offset),
        recorded_at=_at(4).astimezone(offset),
        source_valid_until=_at(20).astimezone(offset),
        ttl_valid_until=_at(10).astimezone(offset),
        valid_until=_at(10).astimezone(offset),
    )

    assert offset_source.content_hash == utc_source.content_hash
    assert cast(str, utc_source.to_payload()["recorded_at"]).endswith("Z")


def test_successor_binds_predecessor_and_advances_revision_and_clocks() -> None:
    previous = _source()
    successor = _successor(previous)

    validate_simulated_account_row_source_successor(previous, successor)

    assert successor.supersedes_content_hash == previous.content_hash
    assert successor.source_version == "v2"
    assert successor.observed_at > previous.observed_at
    assert successor.recorded_at > previous.recorded_at
    assert successor.content_hash != previous.content_hash


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"supersedes_content_hash": "c" * 64}, "exact previous"),
        ({"source_id": "simulated-row-0008"}, "source_id"),
        ({"source_version": "v1"}, "source_version must advance"),
        ({"account_namespace": "other"}, "account_namespace"),
        ({"account_id": "0008"}, "account_id"),
        ({"underlying_unified_account_namespace": "other-row"}, "underlying"),
        ({"underlying_unified_account_id": 8}, "underlying"),
        ({"row_created_at": _at(1) + timedelta(seconds=1)}, "row_created_at"),
        ({"row_updated_at": _at(2) - timedelta(seconds=1)}, "row_updated_at"),
        (
            {"row_updated_at": _at(3), "observed_at": _at(3)},
            "observed_at",
        ),
        (
            {"row_updated_at": _at(4), "observed_at": _at(4), "recorded_at": _at(4)},
            "recorded_at",
        ),
    ],
)
def test_successor_rejects_fork_identity_or_clock_regression(
    changes: dict[str, object],
    message: str,
) -> None:
    previous = _source()
    successor = _successor(previous, **changes)

    with pytest.raises(ValueError, match=message):
        validate_simulated_account_row_source_successor(previous, successor)


def test_pit_head_never_falls_back_from_inactive_tombstone_or_expiry() -> None:
    first = _source(
        source_valid_until=_at(30),
        ttl_valid_until=_at(30),
        valid_until=_at(30),
    )
    inactive = _successor(first, is_active=False)
    tombstone = _successor(first, is_present=False, is_tombstone=True)
    expired = _successor(first, ttl_valid_until=_at(8), valid_until=_at(8))

    assert resolve_simulated_account_row_source_head((first,), as_of=_at(5)) is first
    assert resolve_simulated_account_row_source_head((first, inactive), as_of=_at(8)) is None
    assert resolve_simulated_account_row_source_head((first, tombstone), as_of=_at(8)) is None
    assert resolve_simulated_account_row_source_head((first, expired), as_of=_at(9)) is None


def test_pit_uses_recorded_knowledge_time_and_not_future_versions() -> None:
    first = _source(
        source_valid_until=_at(30),
        ttl_valid_until=_at(30),
        valid_until=_at(30),
    )
    tombstone = _successor(first, is_present=False, is_tombstone=True)

    assert resolve_simulated_account_row_source_head((first, tombstone), as_of=_at(5)) is first
    assert resolve_simulated_account_row_source_head((first, tombstone), as_of=_at(8)) is None


def test_tamper_subclass_and_container_substitution_fail_closed() -> None:
    source = _source()
    object.__setattr__(source, "raw_account_type", "real")
    with pytest.raises(ValueError, match="content_hash"):
        source.to_payload()

    class SubSource(SimulatedAccountRowSource):
        pass

    sub = object.__new__(SubSource)
    for field in fields(SimulatedAccountRowSource):
        object.__setattr__(sub, field.name, getattr(_source(), field.name))
    with pytest.raises(TypeError, match="exact SimulatedAccountRowSource"):
        validate_simulated_account_row_source_successor(sub, _successor(_source()))
    with pytest.raises(TypeError, match="exact tuple"):
        resolve_simulated_account_row_source_head(
            cast(tuple[SimulatedAccountRowSource, ...], [_source()]),
            as_of=_at(5),
        )
    with pytest.raises(TypeError, match="chain values"):
        resolve_simulated_account_row_source_head(
            cast(tuple[SimulatedAccountRowSource, ...], ({"source_id": "row"},)),
            as_of=_at(5),
        )
