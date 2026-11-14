"""Pure owner-side contracts for fresh, full-hash runtime snapshot evidence."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.config_center.application import runtime_public
from apps.config_center.application.runtime_snapshot_evidence import (
    read_active_runtime_snapshot_evidence,
)
from apps.config_center.domain.runtime_config import (
    RuntimeConfigDefinition,
    RuntimeConfigProfile,
    RuntimeConfigSnapshot,
    RuntimeConfigValue,
    RuntimeProfileStatus,
    RuntimeValueType,
    hash_public_runtime_projection,
    hash_runtime_profile_values,
)
from core.integration.config_center_runtime import ActiveRuntimeSnapshotEvidence

_AS_OF = datetime(2026, 11, 14, 2, 0, tzinfo=UTC)
_ENVIRONMENT = "development"
_POLICY_KEY = "market.simulated_disclosure_coverage_policy"
_SECRET_KEY = "market.provider_secret"
_SECRET_REF = "vault://runtime/provider-secret"
_POLICY: object = {"schema_version": "test.v1", "enabled": True}


class _RuntimeService:
    """Provide a deterministic sequence of current profile/snapshot reads."""

    def __init__(
        self,
        profiles: tuple[RuntimeConfigProfile | None, ...],
        snapshots: tuple[RuntimeConfigSnapshot | None, ...],
    ) -> None:
        self.profiles = profiles
        self.snapshots = snapshots
        self.profile_calls = 0
        self.snapshot_calls = 0

    def get_active_profile(self, environment: str) -> RuntimeConfigProfile | None:
        assert environment == _ENVIRONMENT
        index = min(self.profile_calls, len(self.profiles) - 1)
        self.profile_calls += 1
        return self.profiles[index]

    def get_latest_snapshot(self, profile_key: str) -> RuntimeConfigSnapshot | None:
        assert profile_key.startswith("market-")
        index = min(self.snapshot_calls, len(self.snapshots) - 1)
        self.snapshot_calls += 1
        return self.snapshots[index]


class _RuntimeValues:
    """Return complete immutable profile-value cohorts in read order."""

    def __init__(self, cohorts: tuple[tuple[RuntimeConfigValue, ...], ...]) -> None:
        self.cohorts = cohorts
        self.calls = 0

    def list_for_profile(self, profile_id: str) -> list[RuntimeConfigValue]:
        cohort = self.cohorts[min(self.calls, len(self.cohorts) - 1)]
        self.calls += 1
        assert all(value.profile_id == profile_id for value in cohort)
        return list(cohort)


class _RuntimeDefinitions:
    """Return the exact current definition catalog on every evidence pass."""

    def __init__(self, catalogs: tuple[tuple[RuntimeConfigDefinition, ...], ...]) -> None:
        self.catalogs = catalogs
        self.calls = 0

    def list_all(self) -> list[RuntimeConfigDefinition]:
        catalog = self.catalogs[min(self.calls, len(self.catalogs) - 1)]
        self.calls += 1
        return list(catalog)


def _records(
    *,
    profile_id: str = "market-profile-1",
    version: int = 1,
    snapshot_id: str = "market-snapshot-1",
    policy: object = _POLICY,
    secret_ref: str = _SECRET_REF,
    snapshot_policy: object | None = None,
    activated_at: datetime | None = None,
) -> tuple[
    RuntimeConfigProfile,
    RuntimeConfigSnapshot,
    tuple[RuntimeConfigValue, ...],
    tuple[RuntimeConfigDefinition, ...],
]:
    """Build a current public policy plus a secret reference in the full profile."""

    policy = deepcopy(policy)
    effective_at = _AS_OF - timedelta(minutes=2) if activated_at is None else activated_at
    values = (
        RuntimeConfigValue(
            profile_id=profile_id,
            definition_key=_POLICY_KEY,
            value_json=policy,
        ),
        RuntimeConfigValue(
            profile_id=profile_id,
            definition_key=_SECRET_KEY,
            value_json=None,
            secret_ref=secret_ref,
        ),
    )
    full_values = {_POLICY_KEY: policy, _SECRET_KEY: secret_ref}
    profile = RuntimeConfigProfile(
        profile_id=profile_id,
        profile_key="market-development",
        environment=_ENVIRONMENT,
        version=version,
        status=RuntimeProfileStatus.ACTIVE,
        content_hash=hash_runtime_profile_values(full_values),
        created_at=_AS_OF - timedelta(minutes=4),
        activated_at=effective_at,
    )
    public = {_POLICY_KEY: policy if snapshot_policy is None else snapshot_policy}
    snapshot = RuntimeConfigSnapshot(
        snapshot_id=snapshot_id,
        profile_id=profile_id,
        profile_key=profile.profile_key,
        profile_version=version,
        snapshot_hash=hash_public_runtime_projection(public),
        resolved_values=public,
        generated_at=_AS_OF - timedelta(minutes=1),
        effective_from=effective_at,
    )
    definitions = (
        RuntimeConfigDefinition(
            key=_POLICY_KEY,
            namespace="market",
            owner_app="simulated_trading",
            value_type=RuntimeValueType.TYPED_JSON,
        ),
        RuntimeConfigDefinition(
            key=_SECRET_KEY,
            namespace="market",
            owner_app="market_data",
            value_type=RuntimeValueType.STRING,
            secret=True,
        ),
    )
    return profile, snapshot, values, definitions


def _read(
    service: _RuntimeService,
    values: _RuntimeValues,
    definitions: _RuntimeDefinitions,
    *,
    definition_keys: tuple[str, ...] = (_POLICY_KEY,),
    as_of: datetime = _AS_OF,
) -> ActiveRuntimeSnapshotEvidence | None:
    """Call the owner reader with only application ports and an explicit cutoff."""

    return read_active_runtime_snapshot_evidence(
        runtime_config_service=service,
        value_repository=values,
        definition_repository=definitions,
        environment=_ENVIRONMENT,
        definition_keys=definition_keys,
        as_of=as_of,
    )


def _stable_ports() -> tuple[_RuntimeService, _RuntimeValues, _RuntimeDefinitions]:
    """Build a complete current repository set with two identical reads."""

    profile, snapshot, value_rows, definitions = _records()
    return (
        _RuntimeService((profile, profile), (snapshot, snapshot)),
        _RuntimeValues((value_rows, value_rows)),
        _RuntimeDefinitions((definitions, definitions)),
    )


def test_snapshot_evidence_binds_full_profile_and_public_snapshot_without_secrets() -> None:
    """Return the exact typed current objects only after both full hashes verify."""

    service, values, definitions = _stable_ports()

    evidence = _read(service, values, definitions)

    assert type(evidence) is ActiveRuntimeSnapshotEvidence
    assert evidence.environment == _ENVIRONMENT
    assert evidence.definition_keys == (_POLICY_KEY,)
    assert evidence.as_of == _AS_OF
    assert evidence.profile.profile_id == "market-profile-1"
    assert evidence.profile.content_hash == _records()[0].content_hash
    assert evidence.snapshot.snapshot_id == "market-snapshot-1"
    assert evidence.snapshot.resolved_values == {_POLICY_KEY: _POLICY}
    assert _SECRET_REF not in repr(evidence)
    assert service.profile_calls == service.snapshot_calls == 2
    assert values.calls == definitions.calls == 2


def test_runtime_public_snapshot_reader_uses_fresh_owner_repositories(monkeypatch) -> None:
    """The public Application facade assembles the same exact owner read path."""

    service, values, definitions = _stable_ports()
    monkeypatch.setattr(runtime_public, "get_runtime_config_service", lambda: service)
    monkeypatch.setattr(runtime_public, "get_runtime_value_repository", lambda: values)
    monkeypatch.setattr(
        runtime_public,
        "get_runtime_definition_repository",
        lambda: definitions,
    )

    evidence = runtime_public.get_active_runtime_snapshot_evidence(
        environment=_ENVIRONMENT,
        definition_keys=(_POLICY_KEY,),
        as_of=_AS_OF,
    )

    assert type(evidence) is ActiveRuntimeSnapshotEvidence
    assert evidence.snapshot.resolved_values == {_POLICY_KEY: _POLICY}
    assert service.profile_calls == service.snapshot_calls == 2
    assert values.calls == definitions.calls == 2


def test_runtime_snapshot_core_dto_accepts_real_profile_status_enum() -> None:
    """The bridge canonicalizes the actual str-enum Domain profile status."""

    profile, snapshot, _, _ = _records()

    evidence = ActiveRuntimeSnapshotEvidence(
        environment=_ENVIRONMENT,
        definition_keys=(_POLICY_KEY,),
        profile=profile,
        snapshot=snapshot,
        as_of=_AS_OF,
    )

    assert type(evidence.profile.status) is str
    assert evidence.profile.status == RuntimeProfileStatus.ACTIVE.value


def test_snapshot_evidence_is_fresh_on_every_call_and_detaches_mutable_values() -> None:
    """No runtime cache or source-object alias can mutate a returned evidence DTO."""

    profile, snapshot, value_rows, definition_rows = _records()
    service = _RuntimeService((profile,) * 4, (snapshot,) * 4)
    values = _RuntimeValues((value_rows,) * 4)
    definitions = _RuntimeDefinitions((definition_rows,) * 4)

    first = _read(service, values, definitions)
    assert first is not None
    original_public = first.snapshot.resolved_values
    assert isinstance(original_public[_POLICY_KEY], dict)
    original_public[_POLICY_KEY]["enabled"] = False
    assert first.snapshot.resolved_values[_POLICY_KEY]["enabled"] is True
    snapshot.resolved_values[_POLICY_KEY]["enabled"] = False
    assert first.snapshot.resolved_values[_POLICY_KEY]["enabled"] is True

    second_service, second_values, second_definitions = _stable_ports()
    second = _read(second_service, second_values, second_definitions)

    assert second is not None
    assert second is not first
    assert second.snapshot.resolved_values[_POLICY_KEY]["enabled"] is True
    assert service.profile_calls == service.snapshot_calls == 2
    assert values.calls == definitions.calls == 2
    assert second_service.profile_calls == second_service.snapshot_calls == 2
    assert second_values.calls == second_definitions.calls == 2


def test_same_profile_id_value_row_drift_fails_the_full_content_hash() -> None:
    """A same-ID persisted value edit cannot hide behind the original profile hash."""

    profile, snapshot, original_rows, definition_rows = _records()
    changed_rows = (
        replace(original_rows[0], value_json={"schema_version": "test.v1", "enabled": False}),
        original_rows[1],
    )
    service = _RuntimeService((profile, profile), (snapshot, snapshot))
    values = _RuntimeValues((original_rows, changed_rows))
    definitions = _RuntimeDefinitions((definition_rows, definition_rows))

    assert _read(service, values, definitions) is None


def test_same_snapshot_id_content_drift_fails_the_public_hash() -> None:
    """A mutable same-ID resolved snapshot cannot bypass its stored public hash."""

    profile, snapshot, value_rows, definition_rows = _records()
    changed_snapshot = replace(
        snapshot,
        resolved_values={_POLICY_KEY: {"schema_version": "test.v1", "enabled": False}},
    )
    service = _RuntimeService((profile, profile), (snapshot, changed_snapshot))
    values = _RuntimeValues((value_rows, value_rows))
    definitions = _RuntimeDefinitions((definition_rows, definition_rows))

    assert _read(service, values, definitions) is None


def test_same_value_successor_is_not_silently_accepted() -> None:
    """Republishing equal settings under a new profile/snapshot is visible drift."""

    first_profile, first_snapshot, first_rows, first_definitions = _records()
    next_profile, next_snapshot, next_rows, next_definitions = _records(
        profile_id="market-profile-2",
        version=2,
        snapshot_id="market-snapshot-2",
    )
    service = _RuntimeService(
        (first_profile, next_profile),
        (first_snapshot, next_snapshot),
    )
    values = _RuntimeValues((first_rows, next_rows))
    definitions = _RuntimeDefinitions((first_definitions, next_definitions))

    assert _read(service, values, definitions) is None


def test_provider_object_mutation_during_read_does_not_replace_first_pins() -> None:
    """A provider mutating same-ID objects mid-read cannot erase source drift."""

    profile, snapshot, value_rows, definition_rows = _records()

    class _MutatingRuntimeService(_RuntimeService):
        """Mutate the already-returned profile before returning its snapshot."""

        def get_latest_snapshot(self, profile_key: str) -> RuntimeConfigSnapshot | None:
            if self.snapshot_calls == 0:
                object.__setattr__(profile, "created_at", _AS_OF - timedelta(minutes=3))
            return super().get_latest_snapshot(profile_key)

    class _MutatingRuntimeValues(_RuntimeValues):
        """Mutate the same persisted snapshot during its first value read."""

        def list_for_profile(self, profile_id: str) -> list[RuntimeConfigValue]:
            if self.calls == 0:
                object.__setattr__(
                    snapshot,
                    "generated_at",
                    _AS_OF - timedelta(seconds=30),
                )
            return super().list_for_profile(profile_id)

    service = _MutatingRuntimeService((profile, profile), (snapshot, snapshot))
    values = _MutatingRuntimeValues((value_rows, value_rows))
    definitions = _RuntimeDefinitions((definition_rows, definition_rows))

    assert _read(service, values, definitions) is None


@pytest.mark.parametrize(
    "definition_keys,as_of",
    [
        ((_SECRET_KEY,), _AS_OF),
        ((_POLICY_KEY, _POLICY_KEY), _AS_OF),
        ((_POLICY_KEY,), datetime(2026, 11, 14, 2, 0)),
        ((_POLICY_KEY,), _AS_OF - timedelta(minutes=3)),
    ],
)
def test_snapshot_evidence_rejects_secret_duplicate_or_future_timing(
    definition_keys: tuple[str, ...],
    as_of: datetime,
) -> None:
    """The owner reader requires public unique keys and clocks known by the cutoff."""

    service, values, definitions = _stable_ports()

    assert (
        _read(
            service,
            values,
            definitions,
            definition_keys=definition_keys,
            as_of=as_of,
        )
        is None
    )


def test_snapshot_evidence_rejects_profile_snapshot_version_substitution() -> None:
    """A snapshot bound to a different profile version is never returned."""

    profile, snapshot, value_rows, definition_rows = _records()
    wrong_snapshot = replace(snapshot, profile_version=snapshot.profile_version + 1)
    service = _RuntimeService((profile, profile), (wrong_snapshot, wrong_snapshot))
    values = _RuntimeValues((value_rows, value_rows))
    definitions = _RuntimeDefinitions((definition_rows, definition_rows))

    assert _read(service, values, definitions) is None


def test_snapshot_evidence_rejects_noncanonical_environment() -> None:
    """Whitespace around an environment cannot select a different owner scope."""

    service, values, definitions = _stable_ports()

    evidence = read_active_runtime_snapshot_evidence(
        runtime_config_service=service,
        value_repository=values,
        definition_repository=definitions,
        environment=f" {_ENVIRONMENT}",
        definition_keys=(_POLICY_KEY,),
        as_of=_AS_OF,
    )

    assert evidence is None
    assert service.profile_calls == service.snapshot_calls == 0
    assert values.calls == definitions.calls == 0
