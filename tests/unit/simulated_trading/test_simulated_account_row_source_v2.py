from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import cast

import pytest

from apps.simulated_trading.domain.simulated_account_raw_observation import (
    SimulatedAccountRawObservation,
)
from apps.simulated_trading.domain.simulated_account_row_source_v2 import (
    SimulatedAccountRowSourceV2,
    resolve_simulated_account_row_source_v2_head,
    validate_simulated_account_row_source_v2_root,
    validate_simulated_account_row_source_v2_successor,
)


def _at(day: int) -> datetime:
    return datetime(2026, 8, day, 12, tzinfo=UTC)


def _raw(**changes: object) -> SimulatedAccountRawObservation:
    values: dict[str, object] = {
        "observation_id": "simulated-account-row-7",
        "observation_version": "event-v1",
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


def _source(
    *,
    raw: SimulatedAccountRawObservation | None = None,
    **changes: object,
) -> SimulatedAccountRowSourceV2:
    observation = raw or _raw()
    values: dict[str, object] = {
        "source_id": observation.observation_id,
        "source_version": observation.observation_version,
        "account_namespace": "account",
        "account_id": "0007",
        "underlying_unified_account_namespace": "simulated-account-row",
        "underlying_unified_account_id": observation.row_pk,
        "row_user_id": observation.row_user_id,
        "raw_account_type": observation.raw_account_type,
        "is_active": observation.is_active,
        "row_created_at": observation.row_created_at,
        "row_updated_at": observation.row_updated_at,
        "is_present": observation.is_present,
        "is_tombstone": observation.is_tombstone,
        "observed_at": observation.observed_at,
        "recorded_at": _at(4),
        "source_valid_until": observation.valid_until,
        "ttl_valid_until": _at(10),
        "valid_until": _at(10),
        "raw_observation_id": observation.observation_id,
        "raw_observation_version": observation.observation_version,
        "raw_observation_identity_hash": observation.identity_hash,
        "raw_observation_content_hash": observation.content_hash,
        "raw_observation_observed_at": observation.observed_at,
        "raw_observation_valid_until": observation.valid_until,
        "raw_observation_supersedes_content_hash": (observation.supersedes_content_hash),
    }
    values.update(changes)
    return SimulatedAccountRowSourceV2(**values)  # type: ignore[arg-type]


def _successor(
    previous: SimulatedAccountRowSourceV2,
    **changes: object,
) -> SimulatedAccountRowSourceV2:
    raw = _raw(
        observation_id=previous.raw_observation_id,
        observation_version="event-v2",
        row_pk=previous.underlying_unified_account_id,
        row_user_id=42,
        raw_account_type="PAPER",
        is_active=True,
        row_created_at=previous.row_created_at,
        row_updated_at=_at(5),
        is_present=True,
        is_tombstone=False,
        observed_at=_at(6),
        valid_until=_at(22),
        supersedes_content_hash=previous.raw_observation_content_hash,
    )
    values: dict[str, object] = {
        "source_id": raw.observation_id,
        "source_version": raw.observation_version,
        "account_namespace": previous.account_namespace,
        "account_id": previous.account_id,
        "underlying_unified_account_namespace": (previous.underlying_unified_account_namespace),
        "underlying_unified_account_id": previous.underlying_unified_account_id,
        "row_user_id": raw.row_user_id,
        "raw_account_type": raw.raw_account_type,
        "is_active": raw.is_active,
        "row_created_at": raw.row_created_at,
        "row_updated_at": raw.row_updated_at,
        "is_present": raw.is_present,
        "is_tombstone": raw.is_tombstone,
        "observed_at": raw.observed_at,
        "recorded_at": _at(7),
        "source_valid_until": raw.valid_until,
        "ttl_valid_until": _at(14),
        "valid_until": _at(14),
        "raw_observation_id": raw.observation_id,
        "raw_observation_version": raw.observation_version,
        "raw_observation_identity_hash": raw.identity_hash,
        "raw_observation_content_hash": raw.content_hash,
        "raw_observation_observed_at": raw.observed_at,
        "raw_observation_valid_until": raw.valid_until,
        "raw_observation_supersedes_content_hash": raw.supersedes_content_hash,
        "supersedes_content_hash": previous.content_hash,
    }
    values.update(changes)
    return SimulatedAccountRowSourceV2(**values)  # type: ignore[arg-type]


def test_v2_is_frozen_slotted_and_isolated_from_v1_execution_semantics() -> None:
    source = _source()

    assert {field.name for field in fields(SimulatedAccountRowSourceV2)} == {
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
        "raw_observation_id",
        "raw_observation_version",
        "raw_observation_identity_hash",
        "raw_observation_content_hash",
        "raw_observation_observed_at",
        "raw_observation_valid_until",
        "raw_observation_supersedes_content_hash",
        "supersedes_content_hash",
        "identity_hash",
        "content_hash",
        "owner_assignment_state",
        "raw_observation_owner",
        "raw_observation_artifact_type",
        "raw_observation_schema",
        "owner",
        "artifact_type",
        "schema",
        "permission",
        "status",
    }
    assert not hasattr(source, "__dict__")
    with pytest.raises(FrozenInstanceError):
        source.account_id = "0008"  # type: ignore[misc]
    assert source.owner == "simulated_trading"
    assert source.artifact_type == "simulated_account_row_v2"
    assert source.schema == "simulated-account-row.v2"
    assert source.permission == "evidence_only"
    assert source.status == "inactive"
    assert source.owner_assignment_state == "unknown"
    assert source.activation_available is False
    assert source.must_not_execute is True


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("owner", "account"),
        ("artifact_type", "simulated_account_row"),
        ("schema", "simulated-account-row.v1"),
        ("permission", "execute"),
        ("status", "active"),
        ("owner_assignment_state", "authoritative"),
        ("raw_observation_owner", "account"),
        ("raw_observation_artifact_type", "simulated_account_row"),
        ("raw_observation_schema", "simulated-account-raw-observation.v2"),
    ],
)
def test_source_and_raw_authority_headers_are_fixed(
    field_name: str,
    value: str,
) -> None:
    with pytest.raises(ValueError, match=f"{field_name} is fixed"):
        _source(**{field_name: value})


def test_raw_identity_is_exactly_bound_to_source_identity_without_aliases() -> None:
    source = _source()

    assert source.raw_observation_id == source.source_id
    assert source.raw_observation_version == source.source_version
    assert source.raw_observation_identity_hash == _raw().identity_hash

    with pytest.raises(ValueError, match="raw_observation_id must equal source_id"):
        _source(raw_observation_id="simulated-account-row-8")
    with pytest.raises(ValueError, match="raw_observation_version must equal source_version"):
        _source(raw_observation_version="event-v2")
    with pytest.raises(ValueError, match="raw observation identity_hash"):
        _source(raw_observation_identity_hash="a" * 64)


def test_raw_observation_clocks_are_preserved_without_clock_washing() -> None:
    source = _source()

    assert source.observed_at == source.raw_observation_observed_at
    assert source.source_valid_until == source.raw_observation_valid_until

    with pytest.raises(ValueError, match="observed_at must equal raw observation"):
        _source(raw_observation_observed_at=_at(3) + timedelta(seconds=1))
    with pytest.raises(ValueError, match="source_valid_until must equal raw observation"):
        _source(raw_observation_valid_until=_at(19))


def test_effective_validity_is_exact_minimum_of_raw_validity_and_ttl() -> None:
    ttl_first = _source()
    raw_first = _source(ttl_valid_until=_at(25), valid_until=_at(20))

    assert ttl_first.valid_until == _at(10)
    assert raw_first.valid_until == _at(20)

    with pytest.raises(ValueError, match="minimum"):
        _source(valid_until=_at(20))


@pytest.mark.parametrize(
    "changes",
    [
        {"row_created_at": datetime(2026, 8, 1, 12)},
        {"row_updated_at": _at(1) - timedelta(seconds=1)},
        {"observed_at": _at(2) - timedelta(seconds=1)},
        {"recorded_at": _at(3) - timedelta(seconds=1)},
        {"source_valid_until": _at(4), "raw_observation_valid_until": _at(4)},
        {"ttl_valid_until": _at(4)},
        {"raw_observation_observed_at": datetime(2026, 8, 3, 12)},
        {"raw_observation_valid_until": datetime(2026, 8, 20, 12)},
    ],
)
def test_naive_or_inverted_source_and_raw_clocks_fail_closed(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        _source(**changes)


def test_scalar_types_tokens_hashes_presence_and_nullable_user_fail_closed() -> None:
    invalid: tuple[tuple[dict[str, object], type[Exception], str], ...] = (
        ({"source_id": 7}, TypeError, "exact string"),
        ({"account_id": " 0007"}, ValueError, "canonical token"),
        ({"underlying_unified_account_id": True}, TypeError, "exact integer"),
        ({"underlying_unified_account_id": 0}, ValueError, "positive"),
        ({"row_user_id": True}, TypeError, "row_user_id.*exact integer"),
        ({"row_user_id": 0}, ValueError, "row_user_id.*positive"),
        ({"is_active": 1}, TypeError, "is_active.*exact boolean"),
        ({"is_present": True, "is_tombstone": True}, ValueError, "opposites"),
        ({"is_present": False, "is_tombstone": False}, ValueError, "opposites"),
        (
            {"raw_observation_content_hash": "A" * 64},
            ValueError,
            "lowercase SHA-256",
        ),
    )
    for changes, error, message in invalid:
        with pytest.raises(error, match=message):
            _source(**changes)


def test_canonical_hash_covers_every_source_fact_and_raw_authority_binding() -> None:
    baseline = _source()
    alternate_raw = _raw(row_user_id=42)
    variants: tuple[dict[str, object], ...] = (
        {"account_namespace": "account-v2"},
        {"account_id": "0008"},
        {"underlying_unified_account_namespace": "simulated-row-v2"},
        {"underlying_unified_account_id": 8},
        {"row_user_id": 42},
        {"raw_account_type": "PAPER"},
        {"is_active": False},
        {
            "row_created_at": _at(1) + timedelta(seconds=1),
            "row_updated_at": _at(2) + timedelta(seconds=1),
        },
        {"row_updated_at": _at(2) + timedelta(seconds=1)},
        {"is_present": False, "is_tombstone": True},
        {"recorded_at": _at(4) + timedelta(seconds=1)},
        {"ttl_valid_until": _at(9), "valid_until": _at(9)},
        {
            "raw_observation_identity_hash": alternate_raw.identity_hash,
            "raw_observation_content_hash": alternate_raw.content_hash,
        },
        {"raw_observation_content_hash": "b" * 64},
        {"raw_observation_supersedes_content_hash": "d" * 64},
        {"supersedes_content_hash": "c" * 64},
    )

    assert len(baseline.identity_hash) == 64
    assert len(baseline.content_hash) == 64
    for changes in variants:
        assert _source(**changes).content_hash != baseline.content_hash

    payload = baseline.to_payload()
    assert {
        "source_id",
        "source_version",
        "raw_observation_owner",
        "raw_observation_artifact_type",
        "raw_observation_schema",
        "raw_observation_id",
        "raw_observation_version",
        "raw_observation_identity_hash",
        "raw_observation_content_hash",
        "raw_observation_observed_at",
        "raw_observation_valid_until",
        "raw_observation_supersedes_content_hash",
        "recorded_at",
        "ttl_valid_until",
        "valid_until",
    } <= payload.keys()


def test_identity_hash_is_only_the_v2_source_id_and_version_identity() -> None:
    baseline = _source()
    same_identity = _source(row_user_id=42)
    next_raw = _raw(observation_version="event-v2")
    next_identity = _source(raw=next_raw)

    assert same_identity.identity_hash == baseline.identity_hash
    assert same_identity.content_hash != baseline.content_hash
    assert next_identity.identity_hash != baseline.identity_hash


def test_equivalent_instants_hash_identically_and_payload_uses_utc_z() -> None:
    offset = timezone(timedelta(hours=8))
    source = _source()
    equivalent = _source(
        row_created_at=_at(1).astimezone(offset),
        row_updated_at=_at(2).astimezone(offset),
        observed_at=_at(3).astimezone(offset),
        recorded_at=_at(4).astimezone(offset),
        source_valid_until=_at(20).astimezone(offset),
        ttl_valid_until=_at(10).astimezone(offset),
        valid_until=_at(10).astimezone(offset),
        raw_observation_observed_at=_at(3).astimezone(offset),
        raw_observation_valid_until=_at(20).astimezone(offset),
    )

    assert equivalent.content_hash == source.content_hash
    assert cast(str, equivalent.to_payload()["raw_observation_observed_at"]).endswith("Z")


def test_supplied_hashes_and_post_construction_tampering_are_revalidated() -> None:
    source = _source()
    assert _source(identity_hash=source.identity_hash, content_hash=source.content_hash) == source
    with pytest.raises(ValueError, match="identity_hash"):
        _source(identity_hash="a" * 64)
    with pytest.raises(ValueError, match="content_hash"):
        _source(content_hash="b" * 64)

    object.__setattr__(source, "raw_observation_content_hash", "c" * 64)
    with pytest.raises(ValueError, match="content_hash"):
        source.to_payload()


def test_root_and_successor_bind_exact_revisions_of_one_logical_row() -> None:
    root = _source()
    successor = _successor(root)

    validate_simulated_account_row_source_v2_root(root)
    validate_simulated_account_row_source_v2_successor(root, successor)

    with pytest.raises(ValueError, match="root must not declare"):
        validate_simulated_account_row_source_v2_root(_source(supersedes_content_hash="a" * 64))
    with pytest.raises(ValueError, match="raw observation must not declare"):
        validate_simulated_account_row_source_v2_root(
            _source(raw_observation_supersedes_content_hash="a" * 64)
        )
    with pytest.raises(ValueError, match="exact previous"):
        validate_simulated_account_row_source_v2_successor(
            root,
            _successor(root, supersedes_content_hash="b" * 64),
        )
    with pytest.raises(ValueError, match="exact previous raw observation"):
        validate_simulated_account_row_source_v2_successor(
            root,
            _successor(root, raw_observation_supersedes_content_hash="b" * 64),
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {
                "source_id": "simulated-account-row-8",
                "raw_observation_id": "simulated-account-row-8",
                "raw_observation_identity_hash": _raw(
                    observation_id="simulated-account-row-8",
                    observation_version="event-v2",
                ).identity_hash,
            },
            "source_id",
        ),
        (
            {
                "source_version": "event-v1",
                "raw_observation_version": "event-v1",
                "raw_observation_identity_hash": _raw().identity_hash,
            },
            "source_version must advance",
        ),
        ({"account_namespace": "other"}, "account_namespace"),
        ({"account_id": "0008"}, "account_id"),
        ({"underlying_unified_account_namespace": "other-row"}, "underlying"),
        ({"underlying_unified_account_id": 8}, "underlying"),
        ({"row_created_at": _at(1) + timedelta(seconds=1)}, "row_created_at"),
        ({"row_updated_at": _at(2) - timedelta(seconds=1)}, "row_updated_at cannot regress"),
        (
            {
                "row_updated_at": _at(3),
                "observed_at": _at(3),
                "raw_observation_observed_at": _at(3),
            },
            "observed_at must advance",
        ),
    ],
)
def test_successor_rejects_forks_aliases_and_clock_regression(
    changes: dict[str, object],
    message: str,
) -> None:
    previous = _source()
    successor = _successor(previous, **changes)

    with pytest.raises(ValueError, match=message):
        validate_simulated_account_row_source_v2_successor(previous, successor)


def test_successor_recorded_knowledge_clock_must_advance() -> None:
    previous = _source(
        recorded_at=_at(8),
        ttl_valid_until=_at(15),
        valid_until=_at(15),
    )
    successor = _successor(previous, recorded_at=_at(7))

    with pytest.raises(ValueError, match="recorded_at must advance"):
        validate_simulated_account_row_source_v2_successor(previous, successor)


def test_pit_final_head_never_falls_back_from_inactive_tombstone_or_expiry() -> None:
    first = _source(
        ttl_valid_until=_at(20),
        valid_until=_at(20),
    )
    inactive = _successor(first, is_active=False)
    tombstone = _successor(first, is_present=False, is_tombstone=True)
    expired = _successor(first, ttl_valid_until=_at(8), valid_until=_at(8))

    assert resolve_simulated_account_row_source_v2_head((first,), as_of=_at(5)) is first
    assert resolve_simulated_account_row_source_v2_head((first, inactive), as_of=_at(8)) is None
    assert resolve_simulated_account_row_source_v2_head((first, tombstone), as_of=_at(8)) is None
    assert resolve_simulated_account_row_source_v2_head((first, expired), as_of=_at(9)) is None


def test_pit_uses_recorded_knowledge_time_and_rejects_non_root_chains() -> None:
    first = _source(ttl_valid_until=_at(20), valid_until=_at(20))
    tombstone = _successor(first, is_present=False, is_tombstone=True)

    assert resolve_simulated_account_row_source_v2_head((), as_of=_at(5)) is None
    assert resolve_simulated_account_row_source_v2_head((first, tombstone), as_of=_at(5)) is first
    assert resolve_simulated_account_row_source_v2_head((first, tombstone), as_of=_at(8)) is None
    with pytest.raises(ValueError, match="root must not declare"):
        resolve_simulated_account_row_source_v2_head((tombstone,), as_of=_at(8))


def test_exact_runtime_types_chain_shapes_and_as_of_fail_closed() -> None:
    root = _source()

    class SubSource(SimulatedAccountRowSourceV2):
        pass

    sub = object.__new__(SubSource)
    for field in fields(SimulatedAccountRowSourceV2):
        object.__setattr__(sub, field.name, getattr(root, field.name))
    with pytest.raises(TypeError, match="root must be an exact"):
        validate_simulated_account_row_source_v2_root(sub)
    with pytest.raises(TypeError, match="previous must be an exact"):
        validate_simulated_account_row_source_v2_successor(sub, _successor(root))
    with pytest.raises(TypeError, match="exact tuple"):
        resolve_simulated_account_row_source_v2_head(
            cast(tuple[SimulatedAccountRowSourceV2, ...], [root]),
            as_of=_at(5),
        )
    with pytest.raises(TypeError, match="chain values"):
        resolve_simulated_account_row_source_v2_head(
            cast(tuple[SimulatedAccountRowSourceV2, ...], ({"source_id": "row"},)),
            as_of=_at(5),
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        resolve_simulated_account_row_source_v2_head(
            (root,),
            as_of=datetime(2026, 8, 5, 12),
        )


def test_domain_contract_uses_only_the_standard_library() -> None:
    source_path = (
        Path(__file__).parents[3]
        / "apps"
        / "simulated_trading"
        / "domain"
        / "simulated_account_row_source_v2.py"
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
