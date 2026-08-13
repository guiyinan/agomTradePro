from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import cast

import pytest

from apps.account.domain.physical_account_row_observation_v2 import (
    PhysicalAccountRowObservationV2,
    resolve_physical_account_row_observation_v2_head,
    validate_physical_account_row_observation_v2_root,
    validate_physical_account_row_observation_v2_successor,
)
from apps.simulated_trading.domain.simulated_account_raw_observation import (
    SimulatedAccountRawObservation,
)
from apps.simulated_trading.domain.simulated_account_row_source_v2 import (
    SimulatedAccountRowSourceV2,
)


def _at(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 8, day, hour, tzinfo=UTC)


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
        "ttl_valid_until": _at(12),
        "valid_until": _at(12),
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


def _observation(
    *,
    source: SimulatedAccountRowSourceV2 | None = None,
    **changes: object,
) -> PhysicalAccountRowObservationV2:
    value = source or _source()
    values: dict[str, object] = {
        "observation_id": "physical-account-row-7",
        "observation_version": "capture-v1",
        "account_namespace": value.account_namespace,
        "account_id": value.account_id,
        "underlying_unified_account_namespace": (value.underlying_unified_account_namespace),
        "underlying_unified_account_id": value.underlying_unified_account_id,
        "row_user_id": value.row_user_id,
        "raw_account_type": value.raw_account_type,
        "is_active": value.is_active,
        "row_created_at": value.row_created_at,
        "row_updated_at": value.row_updated_at,
        "is_present": value.is_present,
        "is_tombstone": value.is_tombstone,
        "source_id": value.source_id,
        "source_version": value.source_version,
        "source_identity_hash": value.identity_hash,
        "source_content_hash": value.content_hash,
        "source_supersedes_content_hash": value.supersedes_content_hash,
        "source_observed_at": value.observed_at,
        "source_recorded_at": value.recorded_at,
        "source_valid_until": value.source_valid_until,
        "source_ttl_valid_until": value.ttl_valid_until,
        "source_effective_valid_until": value.valid_until,
        "raw_observation_id": value.raw_observation_id,
        "raw_observation_version": value.raw_observation_version,
        "raw_observation_identity_hash": value.raw_observation_identity_hash,
        "raw_observation_content_hash": value.raw_observation_content_hash,
        "raw_observation_supersedes_content_hash": (value.raw_observation_supersedes_content_hash),
        "raw_observation_observed_at": value.raw_observation_observed_at,
        "raw_observation_valid_until": value.raw_observation_valid_until,
        "recorded_at": _at(5),
        "ttl_valid_until": _at(10),
        "valid_until": _at(10),
    }
    values.update(changes)
    return PhysicalAccountRowObservationV2(**values)  # type: ignore[arg-type]


def _successor_source(previous: PhysicalAccountRowObservationV2) -> SimulatedAccountRowSourceV2:
    raw = _raw(
        observation_id=previous.raw_observation_id,
        observation_version="event-v2",
        row_pk=previous.underlying_unified_account_id,
        row_user_id=42,
        raw_account_type="PAPER",
        is_active=True,
        row_created_at=previous.row_created_at,
        row_updated_at=_at(6),
        is_present=True,
        is_tombstone=False,
        observed_at=_at(7),
        valid_until=_at(25),
        supersedes_content_hash=previous.raw_observation_content_hash,
    )
    return _source(
        raw=raw,
        account_namespace=previous.account_namespace,
        account_id=previous.account_id,
        underlying_unified_account_namespace=(previous.underlying_unified_account_namespace),
        underlying_unified_account_id=previous.underlying_unified_account_id,
        recorded_at=_at(8),
        ttl_valid_until=_at(18),
        valid_until=_at(18),
        supersedes_content_hash=previous.source_content_hash,
    )


def _successor(
    previous: PhysicalAccountRowObservationV2,
    *,
    source: SimulatedAccountRowSourceV2 | None = None,
    **changes: object,
) -> PhysicalAccountRowObservationV2:
    values: dict[str, object] = {
        "observation_version": "capture-v2",
        "recorded_at": _at(9),
        "ttl_valid_until": _at(15),
        "valid_until": _at(15),
        "supersedes_content_hash": previous.content_hash,
    }
    values.update(changes)
    return _observation(source=source or _successor_source(previous), **values)


def test_v2_is_frozen_slotted_and_has_independent_fixed_semantics() -> None:
    observation = _observation()

    assert {field.name for field in fields(PhysicalAccountRowObservationV2)} == {
        "observation_id",
        "observation_version",
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
        "source_id",
        "source_version",
        "source_identity_hash",
        "source_content_hash",
        "source_supersedes_content_hash",
        "source_observed_at",
        "source_recorded_at",
        "source_valid_until",
        "source_ttl_valid_until",
        "source_effective_valid_until",
        "raw_observation_id",
        "raw_observation_version",
        "raw_observation_identity_hash",
        "raw_observation_content_hash",
        "raw_observation_supersedes_content_hash",
        "raw_observation_observed_at",
        "raw_observation_valid_until",
        "recorded_at",
        "ttl_valid_until",
        "valid_until",
        "supersedes_content_hash",
        "identity_hash",
        "content_hash",
        "owner_assignment_state",
        "source_owner",
        "source_artifact_type",
        "source_schema",
        "raw_observation_owner",
        "raw_observation_artifact_type",
        "raw_observation_schema",
        "owner",
        "artifact_type",
        "schema",
        "permission",
        "status",
    }
    assert not hasattr(observation, "__dict__")
    with pytest.raises(FrozenInstanceError):
        observation.account_id = "0008"  # type: ignore[misc]
    assert observation.owner == "account"
    assert observation.artifact_type == "physical_account_row_observation_v2"
    assert observation.schema == "physical-account-row-observation.v2"
    assert observation.permission == "evidence_only"
    assert observation.status == "inactive"
    assert observation.owner_assignment_state == "unknown"
    assert observation.activation_available is False
    assert observation.must_not_execute is True


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("owner", "simulated_trading"),
        ("artifact_type", "physical_account_row_observation"),
        ("schema", "physical-account-row-observation.v1"),
        ("permission", "execute"),
        ("status", "active"),
        ("owner_assignment_state", "authoritative"),
        ("source_owner", "account"),
        ("source_artifact_type", "simulated_account_row"),
        ("source_schema", "simulated-account-row.v1"),
        ("raw_observation_owner", "account"),
        ("raw_observation_artifact_type", "simulated_account_row_v2"),
        ("raw_observation_schema", "simulated-account-raw-observation.v2"),
    ],
)
def test_account_source_and_raw_authority_headers_are_fixed(
    field_name: str,
    value: str,
) -> None:
    with pytest.raises(ValueError, match=f"{field_name} is fixed"):
        _observation(**{field_name: value})


def test_exact_source_and_raw_hashes_are_recomputed_from_sealed_facts() -> None:
    baseline = _observation()

    assert baseline.source_identity_hash == _source().identity_hash
    assert baseline.source_content_hash == _source().content_hash
    assert baseline.raw_observation_identity_hash == _raw().identity_hash
    assert baseline.raw_observation_content_hash == _raw().content_hash

    with pytest.raises(ValueError, match="source identity_hash"):
        _observation(source_identity_hash="a" * 64)
    with pytest.raises(ValueError, match="source content_hash"):
        _observation(source_content_hash="b" * 64)
    with pytest.raises(ValueError, match="raw observation identity_hash"):
        _observation(raw_observation_identity_hash="c" * 64)
    with pytest.raises(ValueError, match="raw observation content_hash"):
        _observation(raw_observation_content_hash="d" * 64)


def test_source_and_raw_identity_clocks_and_validity_are_preserved() -> None:
    observation = _observation()

    assert observation.source_id == observation.raw_observation_id
    assert observation.source_version == observation.raw_observation_version
    assert observation.source_observed_at == observation.raw_observation_observed_at
    assert observation.source_valid_until == observation.raw_observation_valid_until
    assert observation.source_effective_valid_until == min(
        observation.source_valid_until,
        observation.source_ttl_valid_until,
    )
    assert observation.valid_until == min(
        observation.source_effective_valid_until,
        observation.ttl_valid_until,
    )

    with pytest.raises(ValueError, match="source_id must equal raw observation"):
        _observation(source_id="simulated-account-row-8")
    with pytest.raises(ValueError, match="source_observed_at must equal raw observation"):
        _observation(source_observed_at=_at(3, 13))
    with pytest.raises(ValueError, match="source_valid_until must equal raw observation"):
        _observation(source_valid_until=_at(19))
    with pytest.raises(ValueError, match="source effective validity"):
        _observation(source_effective_valid_until=_at(11))
    with pytest.raises(ValueError, match="Account effective validity"):
        _observation(valid_until=_at(11))


@pytest.mark.parametrize(
    "changes",
    [
        {"row_created_at": datetime(2026, 8, 1, 12)},
        {"row_updated_at": _at(1) - timedelta(seconds=1)},
        {
            "source_observed_at": _at(2) - timedelta(seconds=1),
            "raw_observation_observed_at": _at(2) - timedelta(seconds=1),
        },
        {"source_recorded_at": _at(3) - timedelta(seconds=1)},
        {"recorded_at": _at(4) - timedelta(seconds=1)},
        {
            "source_valid_until": _at(4),
            "raw_observation_valid_until": _at(4),
            "source_effective_valid_until": _at(4),
        },
        {
            "source_ttl_valid_until": _at(4),
            "source_effective_valid_until": _at(4),
        },
        {"ttl_valid_until": _at(5)},
        {"source_recorded_at": datetime(2026, 8, 4, 12)},
        {"raw_observation_valid_until": datetime(2026, 8, 20, 12)},
    ],
)
def test_naive_or_inverted_three_layer_clocks_fail_closed(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        _observation(**changes)


def test_scalar_types_tokens_hashes_presence_and_nullable_user_fail_closed() -> None:
    invalid: tuple[tuple[dict[str, object], type[Exception], str], ...] = (
        ({"observation_id": 7}, TypeError, "exact string"),
        ({"account_id": " 0007"}, ValueError, "canonical token"),
        ({"underlying_unified_account_id": True}, TypeError, "exact integer"),
        ({"underlying_unified_account_id": 0}, ValueError, "positive"),
        ({"row_user_id": True}, TypeError, "row_user_id.*exact integer"),
        ({"row_user_id": 0}, ValueError, "row_user_id.*positive"),
        ({"is_active": 1}, TypeError, "is_active.*exact boolean"),
        ({"is_present": True, "is_tombstone": True}, ValueError, "opposites"),
        ({"is_present": False, "is_tombstone": False}, ValueError, "opposites"),
        ({"source_content_hash": "A" * 64}, ValueError, "lowercase SHA-256"),
    )
    for changes, error, message in invalid:
        with pytest.raises(error, match=message):
            _observation(**changes)


def test_canonical_hash_covers_account_source_raw_and_terminal_facts() -> None:
    baseline = _observation()
    variants: tuple[dict[str, object], ...] = (
        {"recorded_at": _at(5, 13)},
        {"ttl_valid_until": _at(9), "valid_until": _at(9)},
        {"supersedes_content_hash": "a" * 64},
    )

    assert len(baseline.identity_hash) == 64
    assert len(baseline.content_hash) == 64
    for changes in variants:
        assert _observation(**changes).content_hash != baseline.content_hash

    terminal_source = _source(raw=_raw(is_active=False, is_present=False, is_tombstone=True))
    assert _observation(source=terminal_source).content_hash != baseline.content_hash
    payload = baseline.to_payload()
    assert {
        "source_owner",
        "source_artifact_type",
        "source_schema",
        "source_id",
        "source_version",
        "source_identity_hash",
        "source_content_hash",
        "source_supersedes_content_hash",
        "source_observed_at",
        "source_recorded_at",
        "source_valid_until",
        "source_ttl_valid_until",
        "source_effective_valid_until",
        "raw_observation_owner",
        "raw_observation_artifact_type",
        "raw_observation_schema",
        "raw_observation_id",
        "raw_observation_version",
        "raw_observation_identity_hash",
        "raw_observation_content_hash",
        "raw_observation_supersedes_content_hash",
        "raw_observation_observed_at",
        "raw_observation_valid_until",
        "recorded_at",
        "ttl_valid_until",
        "valid_until",
    } <= payload.keys()


def test_identity_hash_is_only_the_account_v2_observation_identity() -> None:
    baseline = _observation()
    same_identity = _observation(recorded_at=_at(5, 13))
    next_identity = _observation(observation_version="capture-v2")

    assert same_identity.identity_hash == baseline.identity_hash
    assert same_identity.content_hash != baseline.content_hash
    assert next_identity.identity_hash != baseline.identity_hash


def test_equivalent_instants_hash_identically_and_payload_uses_utc_z() -> None:
    offset = timezone(timedelta(hours=8))
    observation = _observation()
    equivalent = _observation(
        row_created_at=_at(1).astimezone(offset),
        row_updated_at=_at(2).astimezone(offset),
        source_observed_at=_at(3).astimezone(offset),
        source_recorded_at=_at(4).astimezone(offset),
        source_valid_until=_at(20).astimezone(offset),
        source_ttl_valid_until=_at(12).astimezone(offset),
        source_effective_valid_until=_at(12).astimezone(offset),
        raw_observation_observed_at=_at(3).astimezone(offset),
        raw_observation_valid_until=_at(20).astimezone(offset),
        recorded_at=_at(5).astimezone(offset),
        ttl_valid_until=_at(10).astimezone(offset),
        valid_until=_at(10).astimezone(offset),
    )

    assert equivalent.content_hash == observation.content_hash
    assert cast(str, equivalent.to_payload()["recorded_at"]).endswith("Z")


def test_supplied_hashes_and_post_construction_tampering_are_revalidated() -> None:
    observation = _observation()
    assert (
        _observation(
            identity_hash=observation.identity_hash,
            content_hash=observation.content_hash,
        )
        == observation
    )
    with pytest.raises(ValueError, match="identity_hash"):
        _observation(identity_hash="a" * 64)
    with pytest.raises(ValueError, match="content_hash"):
        _observation(content_hash="b" * 64)

    object.__setattr__(observation, "source_content_hash", "c" * 64)
    with pytest.raises(ValueError, match="source content_hash"):
        observation.to_payload()


def test_root_requires_all_three_predecessors_to_be_absent() -> None:
    root = _observation()

    validate_physical_account_row_observation_v2_root(root)
    for changes, message in (({"supersedes_content_hash": "a" * 64}, "observation predecessor"),):
        with pytest.raises(ValueError, match=message):
            validate_physical_account_row_observation_v2_root(_observation(**changes))
    with pytest.raises(ValueError, match="source predecessor"):
        validate_physical_account_row_observation_v2_root(
            _observation(source=_source(supersedes_content_hash="b" * 64))
        )
    raw_with_predecessor = _raw(supersedes_content_hash="c" * 64)
    with pytest.raises(ValueError, match="raw observation predecessor"):
        validate_physical_account_row_observation_v2_root(
            _observation(source=_source(raw=raw_with_predecessor))
        )


def test_successor_binds_all_three_exact_predecessors() -> None:
    root = _observation()
    successor = _successor(root)

    validate_physical_account_row_observation_v2_successor(root, successor)
    assert successor.supersedes_content_hash == root.content_hash
    assert successor.source_supersedes_content_hash == root.source_content_hash
    assert successor.raw_observation_supersedes_content_hash == root.raw_observation_content_hash

    for changes, message in (({"supersedes_content_hash": "a" * 64}, "previous observation"),):
        with pytest.raises(ValueError, match=message):
            validate_physical_account_row_observation_v2_successor(
                root,
                _successor(root, **changes),
            )
    wrong_source = _successor_source(root)
    object.__setattr__(wrong_source, "supersedes_content_hash", "b" * 64)
    object.__setattr__(wrong_source, "content_hash", "")
    wrong_source.__post_init__()
    with pytest.raises(ValueError, match="previous source"):
        validate_physical_account_row_observation_v2_successor(
            root,
            _successor(root, source=wrong_source),
        )
    wrong_raw = _raw(
        observation_id=root.raw_observation_id,
        observation_version="event-v2",
        row_pk=root.underlying_unified_account_id,
        row_user_id=42,
        raw_account_type="PAPER",
        row_created_at=root.row_created_at,
        row_updated_at=_at(6),
        observed_at=_at(7),
        valid_until=_at(25),
        supersedes_content_hash="c" * 64,
    )
    wrong_raw_source = _source(
        raw=wrong_raw,
        account_namespace=root.account_namespace,
        account_id=root.account_id,
        underlying_unified_account_namespace=root.underlying_unified_account_namespace,
        underlying_unified_account_id=root.underlying_unified_account_id,
        recorded_at=_at(8),
        ttl_valid_until=_at(18),
        valid_until=_at(18),
        supersedes_content_hash=root.source_content_hash,
    )
    with pytest.raises(ValueError, match="previous raw observation"):
        validate_physical_account_row_observation_v2_successor(
            root,
            _successor(root, source=wrong_raw_source),
        )


def test_successor_rejects_identity_forks_versions_and_clock_regression() -> None:
    root = _observation()
    successor = _successor(root)

    with pytest.raises(ValueError, match="observation_id"):
        validate_physical_account_row_observation_v2_successor(
            root,
            _successor(root, observation_id="physical-account-row-8"),
        )
    with pytest.raises(ValueError, match="observation_version must advance"):
        validate_physical_account_row_observation_v2_successor(
            root,
            _successor(root, observation_version=root.observation_version),
        )
    with pytest.raises(ValueError, match="recorded_at must advance"):
        validate_physical_account_row_observation_v2_successor(
            root,
            _successor(root, recorded_at=root.recorded_at),
        )

    object.__setattr__(successor, "source_version", root.source_version)
    object.__setattr__(successor, "source_identity_hash", root.source_identity_hash)
    with pytest.raises(ValueError):
        validate_physical_account_row_observation_v2_successor(root, successor)


def test_pit_final_head_never_falls_back_from_inactive_tombstone_or_expiry() -> None:
    first = _observation(ttl_valid_until=_at(18), valid_until=_at(12))
    inactive_raw = _raw(
        observation_id=first.raw_observation_id,
        observation_version="event-v2",
        row_pk=first.underlying_unified_account_id,
        row_user_id=42,
        raw_account_type="PAPER",
        is_active=False,
        row_created_at=first.row_created_at,
        row_updated_at=_at(6),
        is_present=True,
        is_tombstone=False,
        observed_at=_at(7),
        valid_until=_at(25),
        supersedes_content_hash=first.raw_observation_content_hash,
    )
    inactive_source = _source(
        raw=inactive_raw,
        account_namespace=first.account_namespace,
        account_id=first.account_id,
        underlying_unified_account_namespace=(first.underlying_unified_account_namespace),
        underlying_unified_account_id=first.underlying_unified_account_id,
        recorded_at=_at(8),
        ttl_valid_until=_at(18),
        valid_until=_at(18),
        supersedes_content_hash=first.source_content_hash,
    )
    inactive = _successor(first, source=inactive_source)

    tombstone_raw = _raw(
        observation_version="event-v2",
        row_pk=first.underlying_unified_account_id,
        row_created_at=first.row_created_at,
        row_updated_at=_at(6),
        is_present=False,
        is_tombstone=True,
        observed_at=_at(7),
        valid_until=_at(25),
        supersedes_content_hash=first.raw_observation_content_hash,
    )
    tombstone_source = _source(
        raw=tombstone_raw,
        account_namespace=first.account_namespace,
        account_id=first.account_id,
        underlying_unified_account_namespace=(first.underlying_unified_account_namespace),
        underlying_unified_account_id=first.underlying_unified_account_id,
        recorded_at=_at(8),
        ttl_valid_until=_at(18),
        valid_until=_at(18),
        supersedes_content_hash=first.source_content_hash,
    )
    tombstone = _successor(first, source=tombstone_source)
    expired = _successor(first, ttl_valid_until=_at(10), valid_until=_at(10))

    assert resolve_physical_account_row_observation_v2_head((first,), as_of=_at(6)) is first
    assert (
        resolve_physical_account_row_observation_v2_head((first, inactive), as_of=_at(10)) is None
    )
    assert (
        resolve_physical_account_row_observation_v2_head((first, tombstone), as_of=_at(10)) is None
    )
    assert resolve_physical_account_row_observation_v2_head((first, expired), as_of=_at(11)) is None


def test_pit_uses_account_recording_time_and_rejects_non_root_chains() -> None:
    first = _observation(ttl_valid_until=_at(18), valid_until=_at(12))
    successor = _successor(first)

    assert resolve_physical_account_row_observation_v2_head((), as_of=_at(6)) is None
    assert (
        resolve_physical_account_row_observation_v2_head((first, successor), as_of=_at(6)) is first
    )
    assert (
        resolve_physical_account_row_observation_v2_head((first, successor), as_of=_at(10))
        is successor
    )
    with pytest.raises(ValueError, match="observation predecessor"):
        resolve_physical_account_row_observation_v2_head(
            (successor,),
            as_of=_at(10),
        )


def test_exact_runtime_types_chain_shapes_and_as_of_fail_closed() -> None:
    root = _observation()

    class SubObservation(PhysicalAccountRowObservationV2):
        pass

    sub = object.__new__(SubObservation)
    for field in fields(PhysicalAccountRowObservationV2):
        object.__setattr__(sub, field.name, getattr(root, field.name))
    with pytest.raises(TypeError, match="root must be an exact"):
        validate_physical_account_row_observation_v2_root(sub)
    with pytest.raises(TypeError, match="previous must be an exact"):
        validate_physical_account_row_observation_v2_successor(sub, _successor(root))
    with pytest.raises(TypeError, match="exact tuple"):
        resolve_physical_account_row_observation_v2_head(
            cast(tuple[PhysicalAccountRowObservationV2, ...], [root]),
            as_of=_at(6),
        )
    with pytest.raises(TypeError, match="chain values"):
        resolve_physical_account_row_observation_v2_head(
            cast(tuple[PhysicalAccountRowObservationV2, ...], ({"id": "row"},)),
            as_of=_at(6),
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        resolve_physical_account_row_observation_v2_head(
            (root,),
            as_of=datetime(2026, 8, 6, 12),
        )


def test_domain_contract_uses_only_the_standard_library() -> None:
    source_path = (
        Path(__file__).parents[3]
        / "apps"
        / "account"
        / "domain"
        / "physical_account_row_observation_v2.py"
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
