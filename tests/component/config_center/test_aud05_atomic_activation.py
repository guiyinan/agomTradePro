"""Database-level AUD-05 atomicity and immutable identity regressions."""

from __future__ import annotations

import os
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from django.db import close_old_connections, connection

from apps.config_center.domain.runtime_config import (
    RuntimeConfigProfile,
    RuntimeConfigRevision,
    RuntimeConfigSnapshot,
    RuntimeConfigValue,
    RuntimeProfileStatus,
    hash_runtime_profile_values,
)
from apps.config_center.infrastructure.models import (
    RuntimeConfigProfileModel,
    RuntimeConfigRevisionModel,
    RuntimeConfigSnapshotModel,
    RuntimeConfigValueModel,
)
from apps.config_center.infrastructure.runtime_config_repositories import (
    RuntimeConfigActivationUnitOfWork,
    RuntimeConfigProfileRepository,
    RuntimeConfigRevisionRepository,
    RuntimeConfigSnapshotRepository,
    RuntimeConfigValueRepository,
)

pytestmark = pytest.mark.django_db(transaction=True)

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clear_runtime_rows() -> None:
    """Keep this component file independent of rows from other test modules."""

    RuntimeConfigValueModel._default_manager.all().delete()
    RuntimeConfigRevisionModel._default_manager.all().delete()
    RuntimeConfigSnapshotModel._default_manager.all().delete()
    RuntimeConfigProfileModel._default_manager.all().delete()


def _profile(
    *,
    profile_id: str | None = None,
    profile_key: str = "aud05",
    environment: str = "production",
    version: int = 1,
    status: RuntimeProfileStatus = RuntimeProfileStatus.ACTIVE,
    based_on_profile: str = "",
    value: int = 1,
) -> RuntimeConfigProfile:
    """Build a deterministic profile whose identity hash matches its value."""

    return RuntimeConfigProfile(
        profile_id=profile_id or str(uuid4()),
        profile_key=profile_key,
        environment=environment,
        version=version,
        status=status,
        based_on_profile=based_on_profile,
        content_hash=(
            hash_runtime_profile_values({"aud05.value": value})
            if status is RuntimeProfileStatus.ACTIVE
            else ""
        ),
        created_by="aud05-test",
        activated_by="aud05-test" if status is RuntimeProfileStatus.ACTIVE else "",
        created_at=NOW,
        activated_at=NOW if status is RuntimeProfileStatus.ACTIVE else None,
        change_reason="AUD-05 component evidence",
    )


def _value(profile_id: str, *, value: int = 1) -> RuntimeConfigValue:
    """Build the one non-secret value used by the transaction fixtures."""

    return RuntimeConfigValue(
        profile_id=profile_id,
        definition_key="aud05.value",
        value_json=value,
        source="aud05-test",
    )


def _revision(
    profile: RuntimeConfigProfile,
    *,
    before_hash: str = "",
    value: int = 1,
) -> RuntimeConfigRevision:
    """Build immutable revision evidence for a candidate successor."""

    return RuntimeConfigRevision(
        revision_id=str(uuid4()),
        profile_id=profile.profile_id,
        before_hash=before_hash,
        after_hash=profile.content_hash,
        changed_keys=("aud05.value",),
        before_projection={},
        after_projection={"aud05.value": value},
        actor="aud05-test",
        reason="atomic activation evidence",
        changed_at=NOW,
    )


def _snapshot(profile: RuntimeConfigProfile, *, value: int = 1) -> RuntimeConfigSnapshot:
    """Build a snapshot bound to the candidate profile identity."""

    values = {"aud05.value": value}
    return RuntimeConfigSnapshot(
        snapshot_id=str(uuid4()),
        profile_id=profile.profile_id,
        profile_key=profile.profile_key,
        profile_version=profile.version,
        snapshot_hash=hash_runtime_profile_values(values),
        resolved_values=values,
        generated_at=NOW,
        effective_from=NOW,
        validation_report={"valid": True},
    )


def _candidate(
    previous: RuntimeConfigProfile | None = None,
    *,
    profile_key: str = "aud05",
    environment: str = "production",
    value: int = 1,
) -> tuple[
    RuntimeConfigProfile,
    tuple[RuntimeConfigValue, ...],
    RuntimeConfigRevision,
    RuntimeConfigSnapshot,
]:
    """Build one complete atomic activation payload."""

    profile = _profile(
        profile_key=profile_key,
        environment=environment,
        version=previous.version + 1 if previous is not None else 1,
        based_on_profile=previous.profile_id if previous is not None else "",
        value=value,
    )
    values = (_value(profile.profile_id, value=value),)
    revision = _revision(
        profile,
        before_hash=previous.content_hash if previous else "",
        value=value,
    )
    snapshot = _snapshot(profile, value=value)
    return profile, values, revision, snapshot


def _active_rows(environment: str = "production") -> list[RuntimeConfigProfileModel]:
    """Return active profile rows in deterministic version order."""

    return list(
        RuntimeConfigProfileModel._default_manager.filter(
            environment=environment,
            status=RuntimeProfileStatus.ACTIVE.value,
        ).order_by("version")
    )


def _graph_fingerprint() -> tuple[list[dict[str, object]], ...]:
    """Capture all four runtime rowsets for exact transaction comparisons."""

    return (
        list(
            RuntimeConfigProfileModel._default_manager.order_by("profile_id").values(
                "profile_id",
                "profile_key",
                "environment",
                "version",
                "status",
                "based_on_profile",
                "content_hash",
                "created_by",
                "activated_by",
                "created_at",
                "activated_at",
                "change_reason",
                "release_ref",
            )
        ),
        list(
            RuntimeConfigValueModel._default_manager.order_by("value_id").values(
                "value_id",
                "profile_id",
                "definition_key",
                "value_json",
                "secret_ref",
                "source",
                "validation_status",
                "validation_error",
                "created_at",
                "updated_at",
            )
        ),
        list(
            RuntimeConfigRevisionModel._default_manager.order_by("revision_id").values(
                "revision_id",
                "profile_id",
                "before_hash",
                "after_hash",
                "changed_keys",
                "before_projection",
                "after_projection",
                "actor",
                "reason",
                "changed_at",
                "release_ref",
                "validation_evidence",
            )
        ),
        list(
            RuntimeConfigSnapshotModel._default_manager.order_by("snapshot_id").values(
                "snapshot_id",
                "profile_id",
                "profile_key",
                "profile_version",
                "snapshot_hash",
                "resolved_values",
                "generated_at",
                "effective_from",
                "validation_report",
                "consumer_acknowledgement",
            )
        ),
    )


@pytest.mark.parametrize(
    ("failing_model", "operation"),
    [
        (RuntimeConfigValueModel, "value"),
        (RuntimeConfigRevisionModel, "revision"),
        (RuntimeConfigSnapshotModel, "snapshot"),
    ],
    ids=["value-insert-failure", "revision-insert-failure", "snapshot-insert-failure"],
)
def test_activation_rolls_back_predecessor_and_all_rows_on_late_insert_failure(
    monkeypatch: pytest.MonkeyPatch,
    failing_model: type[object],
    operation: str,
) -> None:
    """A failure after predecessor locking leaves no partial successor state."""

    previous = _profile()
    RuntimeConfigProfileRepository().save(previous)
    RuntimeConfigValueRepository().save(_value(previous.profile_id))
    RuntimeConfigRevisionRepository().save(_revision(previous))
    RuntimeConfigSnapshotRepository().save(_snapshot(previous))
    before_graph = _graph_fingerprint()
    profile, values, revision, snapshot = _candidate(previous, value=2)
    previous_snapshot = RuntimeConfigSnapshotRepository().get_latest(previous.profile_key)
    assert previous_snapshot is not None

    def fail_create(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise RuntimeError(f"injected {operation} insert failure")

    manager = failing_model._default_manager  # type: ignore[attr-defined]
    monkeypatch.setattr(manager, "create", fail_create)

    with pytest.raises(RuntimeError, match=f"injected {operation}"):
        RuntimeConfigActivationUnitOfWork().activate(
            profile=profile,
            values=values,
            revision=revision,
            snapshot=snapshot,
            expected_previous_profile=previous,
            expected_previous_snapshot=previous_snapshot,
        )

    assert _graph_fingerprint() == before_graph


def test_profile_value_and_snapshot_repositories_refuse_in_place_mutation() -> None:
    """All persisted identity-bearing rows remain append-only."""

    profile = _profile()
    profile_repository = RuntimeConfigProfileRepository()
    profile_repository.save(profile)
    with pytest.raises(ValueError, match="immutable"):
        profile_repository.save(replace(profile, change_reason="tampered"))

    value = _value(profile.profile_id)
    value_repository = RuntimeConfigValueRepository()
    value_repository.save(value)
    with pytest.raises(ValueError, match="immutable"):
        value_repository.save(replace(value, value_json=99))

    snapshot = _snapshot(profile)
    snapshot_repository = RuntimeConfigSnapshotRepository()
    snapshot_repository.save(snapshot)
    with pytest.raises(ValueError, match="immutable"):
        snapshot_repository.save(replace(snapshot, resolved_values={"aud05.value": 99}))


def test_activation_rejects_exact_predecessor_drift_before_any_write() -> None:
    """The locked predecessor must equal the caller's read-phase identity."""

    previous = _profile()
    RuntimeConfigProfileRepository().save(previous)
    profile, values, revision, snapshot = _candidate(previous, value=2)
    expected = replace(previous, content_hash="f" * 64)
    expected_snapshot = _snapshot(previous)

    with pytest.raises(ValueError, match="predecessor drifted"):
        RuntimeConfigActivationUnitOfWork().activate(
            profile=profile,
            values=values,
            revision=revision,
            snapshot=snapshot,
            expected_previous_profile=expected,
            expected_previous_snapshot=expected_snapshot,
        )

    stored = RuntimeConfigProfileModel._default_manager.get(profile_id=previous.profile_id)
    assert stored.status == RuntimeProfileStatus.ACTIVE.value
    assert not RuntimeConfigProfileModel._default_manager.filter(
        profile_id=profile.profile_id
    ).exists()


def test_bootstrap_refuses_a_second_active_profile_for_the_same_environment() -> None:
    """A no-predecessor bootstrap cannot create two active profiles in one environment."""

    first, first_values, first_revision, first_snapshot = _candidate(value=1)
    uow = RuntimeConfigActivationUnitOfWork()
    uow.activate(
        profile=first,
        values=first_values,
        revision=first_revision,
        snapshot=first_snapshot,
        expected_previous_profile=None,
        expected_previous_snapshot=None,
    )
    second, second_values, second_revision, second_snapshot = _candidate(
        profile_key="aud05-second", value=2
    )

    with pytest.raises(ValueError, match="predecessor drifted"):
        uow.activate(
            profile=second,
            values=second_values,
            revision=second_revision,
            snapshot=second_snapshot,
            expected_previous_profile=None,
            expected_previous_snapshot=None,
        )

    assert len(_active_rows()) == 1


def _require_aud05_postgresql() -> None:
    """Require the explicit local PostgreSQL evidence database for the race."""

    if connection.vendor != "postgresql":
        pytest.skip(
            f"AUD-05 concurrency requires PostgreSQL; active vendor is {connection.vendor!r}"
        )
    if os.environ.get("AGOM_AUD05_PG_CONCURRENCY_EVIDENCE", "").strip() != "1":
        pytest.fail("PostgreSQL AUD-05 concurrency requires explicit evidence opt-in")
    host = str(connection.settings_dict.get("HOST", "")).lower()
    database_name = str(connection.settings_dict.get("NAME", "")).lower()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("AUD-05 concurrency refuses a non-loopback PostgreSQL host")
    if not database_name.startswith("test_") or "aud05" not in database_name:
        pytest.fail("AUD-05 concurrency refuses a non-dedicated test database")
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        row = cursor.fetchone()
    if row is None or str(row[0]).lower() != database_name:
        pytest.fail("AUD-05 concurrency database identity mismatch")


@pytest.mark.parametrize("corruption", ["changed", "missing", "added"])
def test_activation_rechecks_locked_predecessor_value_hash(corruption: str) -> None:
    """Raw row drift after an application read cannot be blessed as a successor."""

    previous, previous_values, previous_revision, previous_snapshot = _candidate()
    uow = RuntimeConfigActivationUnitOfWork()
    uow.activate(
        profile=previous,
        values=previous_values,
        revision=previous_revision,
        snapshot=previous_snapshot,
        expected_previous_profile=None,
        expected_previous_snapshot=None,
    )
    if corruption == "changed":
        RuntimeConfigValueModel._default_manager.filter(profile_id=previous.profile_id).update(
            value_json=99
        )
    elif corruption == "missing":
        RuntimeConfigValueModel._default_manager.filter(profile_id=previous.profile_id).delete()
    else:
        RuntimeConfigValueModel._default_manager.create(
            profile_id=previous.profile_id, definition_key="aud05.unapproved", value_json=99
        )
    before = _graph_fingerprint()
    profile, values, revision, snapshot = _candidate(previous, value=2)

    with pytest.raises(ValueError, match="runtime profile full hash"):
        uow.activate(
            profile=profile,
            values=values,
            revision=revision,
            snapshot=snapshot,
            expected_previous_profile=previous,
            expected_previous_snapshot=previous_snapshot,
        )

    assert _graph_fingerprint() == before


@pytest.mark.parametrize(
    "corruption",
    ["profile_hash", "revision_hash", "revision_projection", "snapshot_projection", "before_hash"],
)
def test_activation_rejects_inconsistent_candidate_graph(corruption: str) -> None:
    """The final persistence boundary rejects mismatched candidate evidence."""

    profile, values, revision, snapshot = _candidate()
    if corruption == "profile_hash":
        profile = replace(profile, content_hash="0" * 64)
    elif corruption == "revision_hash":
        revision = replace(revision, after_hash="0" * 64)
    elif corruption == "revision_projection":
        revision = replace(revision, after_projection={"aud05.value": 9})
    elif corruption == "snapshot_projection":
        snapshot = _snapshot(profile, value=9)
        revision = replace(revision, after_projection=snapshot.resolved_values)
    else:
        revision = replace(revision, before_hash="unexpected-predecessor")
    before = _graph_fingerprint()

    with pytest.raises(
        ValueError, match="runtime (profile full hash|revision|snapshot public projection)"
    ):
        RuntimeConfigActivationUnitOfWork().activate(
            profile=profile,
            values=values,
            revision=revision,
            snapshot=snapshot,
            expected_previous_profile=None,
            expected_previous_snapshot=None,
        )

    assert _graph_fingerprint() == before


def test_active_reader_rejects_multiple_active_profiles() -> None:
    """Two active identities in one environment cannot be resolved by sorting."""

    repository = RuntimeConfigProfileRepository()
    repository.save(_profile(profile_key="first"))
    repository.save(_profile(profile_key="second"))

    with pytest.raises(RuntimeError, match="multiple active runtime profiles"):
        repository.get_active("production")


def test_snapshot_reader_rejects_multiple_snapshots_for_one_profile_version() -> None:
    """Different hashes do not make duplicate snapshots for a profile valid."""

    profile = _profile()
    repository = RuntimeConfigSnapshotRepository()
    repository.save(_snapshot(profile, value=1))
    repository.save(_snapshot(profile, value=2))

    with pytest.raises(RuntimeError, match="multiple runtime snapshots"):
        repository.get_latest(profile.profile_key)


def _race_activation(
    barrier: Barrier,
    profile: RuntimeConfigProfile,
    values: tuple[RuntimeConfigValue, ...],
    revision: RuntimeConfigRevision,
    snapshot: RuntimeConfigSnapshot,
    expected_previous_profile: RuntimeConfigProfile | None = None,
    expected_previous_snapshot: RuntimeConfigSnapshot | None = None,
) -> str:
    """Run one activation on a thread-owned Django connection."""

    close_old_connections()
    try:
        barrier.wait(timeout=15)
        RuntimeConfigActivationUnitOfWork().activate(
            profile=profile,
            values=values,
            revision=revision,
            snapshot=snapshot,
            expected_previous_profile=expected_previous_profile,
            expected_previous_snapshot=expected_previous_snapshot,
        )
        return f"winner:{profile.profile_id}"
    except ValueError as exc:
        return f"loser:{exc}"
    except Exception as exc:  # noqa: BLE001 - expose unexpected race failures
        return f"unexpected:{type(exc).__name__}:{exc}"
    finally:
        close_old_connections()


def test_postgresql_bootstrap_race_has_one_first_winner() -> None:
    """Two empty-state bootstraps cannot both publish an active profile."""

    _require_aud05_postgresql()
    barrier = Barrier(2)
    candidates = [
        _candidate(profile_key=profile_key, value=value)
        for profile_key, value in (("aud05-race-one", 1), ("aud05-race-two", 2))
    ]
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="aud05-uow") as executor:
        futures: list[Future[str]] = [
            executor.submit(_race_activation, barrier, profile, values, revision, snapshot)
            for profile, values, revision, snapshot in candidates
        ]
        outcomes = [future.result(timeout=30) for future in futures]

    assert sum(item.startswith("winner:") for item in outcomes) == 1
    assert outcomes.count("loser:runtime profile predecessor drifted") == 1
    assert all(not item.startswith("unexpected:") for item in outcomes)
    winner_id = next(
        item.removeprefix("winner:") for item in outcomes if item.startswith("winner:")
    )
    assert len(RuntimeConfigProfileModel._default_manager.all()) == 1
    assert len(RuntimeConfigValueModel._default_manager.all()) == 1
    assert len(RuntimeConfigRevisionModel._default_manager.all()) == 1
    assert len(RuntimeConfigSnapshotModel._default_manager.all()) == 1
    winner = RuntimeConfigProfileModel._default_manager.get(profile_id=winner_id)
    assert winner.status == RuntimeProfileStatus.ACTIVE.value
    assert winner.profile_key in {candidate[0].profile_key for candidate in candidates}
    loser = next(profile for profile, *_rest in candidates if profile.profile_id != winner_id)
    assert not RuntimeConfigProfileModel._default_manager.filter(
        profile_id=loser.profile_id
    ).exists()
    assert not RuntimeConfigValueModel._default_manager.filter(profile_id=loser.profile_id).exists()
    assert not RuntimeConfigRevisionModel._default_manager.filter(
        profile_id=loser.profile_id
    ).exists()
    assert not RuntimeConfigSnapshotModel._default_manager.filter(
        profile_id=loser.profile_id
    ).exists()
    assert len(_active_rows()) == 1


def test_postgresql_successor_race_has_one_first_winner() -> None:
    """Two corrections from one active predecessor publish one successor graph."""

    _require_aud05_postgresql()
    previous = _profile(profile_key="aud05-successor-race")
    RuntimeConfigProfileRepository().save(previous)
    RuntimeConfigValueRepository().save(_value(previous.profile_id))
    RuntimeConfigRevisionRepository().save(_revision(previous))
    RuntimeConfigSnapshotRepository().save(_snapshot(previous))
    previous_snapshot = RuntimeConfigSnapshotRepository().get_latest(previous.profile_key)
    assert previous_snapshot is not None
    candidates = [_candidate(previous, value=value) for value in (2, 3)]
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="aud05-uow") as executor:
        futures: list[Future[str]] = [
            executor.submit(
                _race_activation,
                barrier,
                profile,
                values,
                revision,
                snapshot,
                previous,
                previous_snapshot,
            )
            for profile, values, revision, snapshot in candidates
        ]
        outcomes = [future.result(timeout=30) for future in futures]

    assert sum(item.startswith("winner:") for item in outcomes) == 1
    assert outcomes.count("loser:runtime profile predecessor drifted") == 1
    assert all(not item.startswith("unexpected:") for item in outcomes)
    winner_id = next(
        item.removeprefix("winner:") for item in outcomes if item.startswith("winner:")
    )
    assert len(RuntimeConfigProfileModel._default_manager.all()) == 2
    assert len(RuntimeConfigValueModel._default_manager.all()) == 2
    assert len(RuntimeConfigRevisionModel._default_manager.all()) == 2
    assert len(RuntimeConfigSnapshotModel._default_manager.all()) == 2
    assert len(_active_rows()) == 1
    assert RuntimeConfigProfileModel._default_manager.get(profile_id=winner_id).status == (
        RuntimeProfileStatus.ACTIVE.value
    )
    loser = next(profile for profile, *_rest in candidates if profile.profile_id != winner_id)
    assert not RuntimeConfigProfileModel._default_manager.filter(
        profile_id=loser.profile_id
    ).exists()
    assert not RuntimeConfigValueModel._default_manager.filter(profile_id=loser.profile_id).exists()
    assert not RuntimeConfigRevisionModel._default_manager.filter(
        profile_id=loser.profile_id
    ).exists()
    assert not RuntimeConfigSnapshotModel._default_manager.filter(
        profile_id=loser.profile_id
    ).exists()
