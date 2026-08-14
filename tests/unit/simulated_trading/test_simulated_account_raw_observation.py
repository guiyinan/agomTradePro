from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import cast

import pytest

from apps.simulated_trading.domain.simulated_account_raw_observation import (
    SimulatedAccountRawObservation,
    resolve_simulated_account_raw_observation_head,
    validate_simulated_account_raw_observation_root,
    validate_simulated_account_raw_observation_successor,
)


def _at(day: int) -> datetime:
    return datetime(2026, 8, day, 12, tzinfo=UTC)


def _observation(**changes: object) -> SimulatedAccountRawObservation:
    values: dict[str, object] = {
        "observation_id": "simulated-account-row-7",
        "observation_version": "v1",
        "row_pk": 7,
        "row_user_id": None,
        "raw_account_type": "SIMULATED",
        "is_active": True,
        "row_created_at": _at(1),
        "row_updated_at": _at(2),
        "is_present": True,
        "is_tombstone": False,
        "observed_at": _at(3),
        "valid_until": _at(20),
    }
    values.update(changes)
    return SimulatedAccountRawObservation(**values)  # type: ignore[arg-type]


def _successor(
    previous: SimulatedAccountRawObservation,
    **changes: object,
) -> SimulatedAccountRawObservation:
    values: dict[str, object] = {
        "observation_id": previous.observation_id,
        "observation_version": "v2",
        "row_pk": previous.row_pk,
        "row_user_id": 42,
        "raw_account_type": "PAPER",
        "is_active": True,
        "row_created_at": previous.row_created_at,
        "row_updated_at": _at(5),
        "is_present": True,
        "is_tombstone": False,
        "observed_at": _at(6),
        "valid_until": _at(25),
        "supersedes_content_hash": previous.content_hash,
    }
    values.update(changes)
    return SimulatedAccountRawObservation(**values)  # type: ignore[arg-type]


def test_exact_fields_are_frozen_slotted_and_execution_semantics_are_fixed() -> None:
    observation = _observation()

    assert {field.name for field in fields(SimulatedAccountRawObservation)} == {
        "observation_id",
        "observation_version",
        "row_pk",
        "row_user_id",
        "raw_account_type",
        "is_active",
        "row_created_at",
        "row_updated_at",
        "is_present",
        "is_tombstone",
        "observed_at",
        "valid_until",
        "supersedes_content_hash",
        "identity_hash",
        "content_hash",
        "owner",
        "artifact_type",
        "schema",
        "permission",
        "status",
    }
    assert not hasattr(observation, "__dict__")
    with pytest.raises(FrozenInstanceError):
        observation.row_pk = 8  # type: ignore[misc]
    assert observation.owner == "simulated_trading"
    assert observation.artifact_type == "simulated_account_raw_observation"
    assert observation.schema == "simulated-account-raw-observation.v1"
    assert observation.permission == "evidence_only"
    assert observation.status == "inactive"
    assert observation.activation_available is False
    assert observation.must_not_execute is True

    for field_name, value in (
        ("owner", "account"),
        ("artifact_type", "simulated_account_row"),
        ("schema", "simulated-account-raw-observation.v2"),
        ("permission", "execute"),
        ("status", "active"),
    ):
        with pytest.raises(ValueError, match=f"{field_name} is fixed"):
            _observation(**{field_name: value})


def test_exact_scalar_types_tokens_presence_and_nullable_user_fail_closed() -> None:
    observation = _observation(row_user_id=42)
    assert type(observation.row_pk) is int
    assert type(observation.row_user_id) is int
    assert observation.raw_account_type == "SIMULATED"

    invalid: tuple[tuple[dict[str, object], type[Exception], str], ...] = (
        ({"observation_id": 7}, TypeError, "exact string"),
        ({"observation_version": " v1"}, ValueError, "canonical token"),
        ({"raw_account_type": "paper account"}, ValueError, "canonical token"),
        ({"row_pk": True}, TypeError, "row_pk.*exact integer"),
        ({"row_pk": 0}, ValueError, "row_pk.*positive"),
        ({"row_user_id": True}, TypeError, "row_user_id.*exact integer"),
        ({"row_user_id": 0}, ValueError, "row_user_id.*positive"),
        ({"is_active": 1}, TypeError, "is_active.*exact boolean"),
        ({"is_present": 1}, TypeError, "is_present.*exact boolean"),
        (
            {"is_present": True, "is_tombstone": True},
            ValueError,
            "exact opposites",
        ),
        (
            {"is_present": False, "is_tombstone": False},
            ValueError,
            "exact opposites",
        ),
    )
    for changes, error, message in invalid:
        with pytest.raises(error, match=message):
            _observation(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"row_created_at": datetime(2026, 8, 1, 12)},
        {"row_updated_at": datetime(2026, 8, 2, 12)},
        {"observed_at": datetime(2026, 8, 3, 12)},
        {"valid_until": datetime(2026, 8, 20, 12)},
        {"row_updated_at": _at(1) - timedelta(seconds=1)},
        {"observed_at": _at(2) - timedelta(seconds=1)},
        {"valid_until": _at(3)},
    ],
)
def test_all_clocks_are_aware_and_ordered(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _observation(**changes)


def test_canonical_sha256_covers_all_identity_and_row_facts() -> None:
    baseline = _observation()
    variants: tuple[dict[str, object], ...] = (
        {"observation_id": "simulated-account-row-8"},
        {"observation_version": "v2"},
        {"row_pk": 8},
        {"row_user_id": 42},
        {"raw_account_type": "PAPER"},
        {"is_active": False},
        {
            "row_created_at": _at(1) + timedelta(seconds=1),
            "row_updated_at": _at(2) + timedelta(seconds=1),
        },
        {"row_updated_at": _at(2) + timedelta(seconds=1)},
        {"is_present": False, "is_tombstone": True},
        {"observed_at": _at(3) + timedelta(seconds=1)},
        {"valid_until": _at(19)},
        {"supersedes_content_hash": "a" * 64},
    )

    assert len(baseline.identity_hash) == 64
    assert len(baseline.content_hash) == 64
    for changes in variants:
        assert _observation(**changes).content_hash != baseline.content_hash
    assert _observation(observation_version="v2").identity_hash != baseline.identity_hash


def test_canonical_time_hashes_equivalent_instants_and_payload_uses_utc_z() -> None:
    offset = timezone(timedelta(hours=8))
    offset_value = _observation(
        row_created_at=_at(1).astimezone(offset),
        row_updated_at=_at(2).astimezone(offset),
        observed_at=_at(3).astimezone(offset),
        valid_until=_at(20).astimezone(offset),
    )

    assert offset_value.content_hash == _observation().content_hash
    assert cast(str, offset_value.to_payload()["observed_at"]).endswith("Z")


def test_supplied_hashes_and_post_construction_tampering_are_revalidated() -> None:
    baseline = _observation()
    assert (
        _observation(
            identity_hash=baseline.identity_hash,
            content_hash=baseline.content_hash,
        )
        == baseline
    )
    with pytest.raises(ValueError, match="identity_hash"):
        _observation(identity_hash="a" * 64)
    with pytest.raises(ValueError, match="content_hash"):
        _observation(content_hash="b" * 64)
    with pytest.raises(ValueError, match="SHA-256"):
        _observation(content_hash="A" * 64)

    object.__setattr__(baseline, "is_active", False)
    with pytest.raises(ValueError, match="content_hash"):
        baseline.to_payload()


def test_root_has_no_predecessor_and_successor_binds_exact_previous_revision() -> None:
    root = _observation()
    successor = _successor(root)

    validate_simulated_account_raw_observation_root(root)
    validate_simulated_account_raw_observation_successor(root, successor)

    with pytest.raises(ValueError, match="root must not declare"):
        validate_simulated_account_raw_observation_root(
            _observation(supersedes_content_hash="a" * 64)
        )
    with pytest.raises(ValueError, match="exact previous"):
        validate_simulated_account_raw_observation_successor(
            root,
            _successor(root, supersedes_content_hash="b" * 64),
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"observation_id": "simulated-account-row-8"}, "observation_id"),
        ({"observation_version": "v1"}, "version must advance"),
        ({"row_pk": 8}, "row_pk"),
        ({"row_created_at": _at(1) + timedelta(seconds=1)}, "row_created_at"),
        ({"row_updated_at": _at(1)}, "row_updated_at cannot regress"),
        (
            {"row_updated_at": _at(3), "observed_at": _at(3)},
            "observed_at must advance",
        ),
    ],
)
def test_successor_preserves_logical_row_and_advances_clocks(
    changes: dict[str, object],
    message: str,
) -> None:
    previous = _observation()
    successor = _successor(previous, **changes)

    with pytest.raises(ValueError, match=message):
        validate_simulated_account_raw_observation_successor(previous, successor)


def test_observed_pit_resolver_returns_raw_inactive_or_tombstone_final_head() -> None:
    root = _observation(valid_until=_at(30))
    tombstone = _successor(
        root,
        is_active=False,
        is_present=False,
        is_tombstone=True,
    )

    assert resolve_simulated_account_raw_observation_head((), as_of=_at(4)) is None
    assert resolve_simulated_account_raw_observation_head((root, tombstone), as_of=_at(4)) is root
    assert (
        resolve_simulated_account_raw_observation_head((root, tombstone), as_of=_at(7)) is tombstone
    )


def test_final_expiry_returns_none_without_falling_back_to_valid_predecessor() -> None:
    root = _observation(valid_until=_at(30))
    expired = _successor(root, valid_until=_at(8))

    assert resolve_simulated_account_raw_observation_head((root, expired), as_of=_at(9)) is None


def test_exact_runtime_types_and_chain_shapes_fail_closed() -> None:
    root = _observation()

    class SubObservation(SimulatedAccountRawObservation):
        pass

    sub = object.__new__(SubObservation)
    for field in fields(SimulatedAccountRawObservation):
        object.__setattr__(sub, field.name, getattr(root, field.name))
    with pytest.raises(TypeError, match="root must be an exact"):
        validate_simulated_account_raw_observation_root(sub)
    with pytest.raises(TypeError, match="previous must be an exact"):
        validate_simulated_account_raw_observation_successor(sub, _successor(root))
    with pytest.raises(TypeError, match="exact tuple"):
        resolve_simulated_account_raw_observation_head(
            cast(tuple[SimulatedAccountRawObservation, ...], [root]),
            as_of=_at(4),
        )
    with pytest.raises(TypeError, match="chain values"):
        resolve_simulated_account_raw_observation_head(
            cast(tuple[SimulatedAccountRawObservation, ...], ({"row_pk": 7},)),
            as_of=_at(4),
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        resolve_simulated_account_raw_observation_head(
            (root,),
            as_of=datetime(2026, 8, 4, 12),
        )


def test_domain_contract_uses_only_the_standard_library() -> None:
    source_path = (
        Path(__file__).parents[3]
        / "apps"
        / "simulated_trading"
        / "domain"
        / "simulated_account_raw_observation.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}

    assert not any(name.startswith("apps.") for name in imported)
    assert imported <= {
        "__future__",
        "dataclasses",
        "datetime",
        "hashlib",
        "json",
    }
