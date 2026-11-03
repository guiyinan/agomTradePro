"""Contract tests for active runtime value identity and cutoff evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.config_center.application import runtime_public
from apps.config_center.application.runtime_value_evidence import (
    ActiveRuntimeValueEvidence,
    read_active_runtime_value_evidence,
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
from core.integration import config_center_runtime

_AS_OF = datetime(2026, 11, 3, 3, 0, tzinfo=UTC)
_ENVIRONMENT = "development"
_DEFINITION_KEY = "risk_center.simulated_portfolio_risk"
_VALUE: object = {"revision": "risk-policy-v1", "active": True}


def _runtime_records(
    *,
    profile_id: str = "risk-profile-1",
    version: int = 1,
    profile_key: str = "risk-center-development",
    value: object = _VALUE,
    effective_at: datetime = _AS_OF,
) -> tuple[RuntimeConfigProfile, RuntimeConfigSnapshot, tuple[RuntimeConfigValue, ...]]:
    """Build a complete active profile and public snapshot at the cutoff."""

    values = (
        RuntimeConfigValue(
            profile_id=profile_id,
            definition_key=_DEFINITION_KEY,
            value_json=value,
        ),
    )
    resolved = {_DEFINITION_KEY: value}
    profile = RuntimeConfigProfile(
        profile_id=profile_id,
        profile_key=profile_key,
        environment=_ENVIRONMENT,
        version=version,
        status=RuntimeProfileStatus.ACTIVE,
        content_hash=hash_runtime_profile_values(resolved),
        created_at=_AS_OF - timedelta(minutes=3),
        activated_at=effective_at,
    )
    snapshot = RuntimeConfigSnapshot(
        snapshot_id=f"snapshot-{version}",
        profile_id=profile_id,
        profile_key=profile_key,
        profile_version=version,
        snapshot_hash=hash_public_runtime_projection(resolved),
        resolved_values=resolved,
        generated_at=_AS_OF - timedelta(minutes=2),
        effective_from=effective_at,
    )
    return profile, snapshot, values


def _install_runtime(monkeypatch: pytest.MonkeyPatch) -> tuple[
    RuntimeConfigProfile,
    RuntimeConfigSnapshot,
    tuple[RuntimeConfigValue, ...],
]:
    """Install repository seams used by the existing public cutoff qualifier."""

    profile, snapshot, values = _runtime_records()
    definition = RuntimeConfigDefinition(
        key=_DEFINITION_KEY,
        namespace="risk_center",
        owner_app="risk_center",
        value_type=RuntimeValueType.TYPED_JSON,
    )

    class _DefinitionRepository:
        def list_all(self) -> list[RuntimeConfigDefinition]:
            return [definition]

    class _ValueRepository:
        def list_for_profile(self, profile_id: str) -> list[RuntimeConfigValue]:
            return [value for value in values if value.profile_id == profile_id]

    monkeypatch.setattr(runtime_public, "get_active_runtime_profile", lambda _env: profile)
    monkeypatch.setattr(
        runtime_public,
        "get_latest_runtime_snapshot",
        lambda _profile_key: snapshot,
    )
    monkeypatch.setattr(
        runtime_public,
        "get_runtime_definition_repository",
        lambda: _DefinitionRepository(),
    )
    monkeypatch.setattr(
        runtime_public,
        "get_runtime_value_repository",
        lambda: _ValueRepository(),
    )
    return profile, snapshot, values


def test_evidence_reuses_public_cutoff_qualification_and_returns_full_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One typed value carries the exact profile/snapshot identities and real clocks."""

    profile, snapshot, _values = _install_runtime(monkeypatch)

    evidence = read_active_runtime_value_evidence(
        environment=_ENVIRONMENT,
        definition_key=_DEFINITION_KEY,
        as_of=_AS_OF,
    )

    assert isinstance(evidence, ActiveRuntimeValueEvidence)
    assert evidence.value == _VALUE
    assert evidence.profile_id == profile.profile_id
    assert evidence.profile_key == profile.profile_key
    assert evidence.profile_version == profile.version
    assert evidence.profile_content_hash == profile.content_hash
    assert evidence.snapshot_id == snapshot.snapshot_id
    assert evidence.snapshot_hash == snapshot.snapshot_hash
    assert evidence.created_at == profile.created_at
    assert evidence.known_at == profile.created_at
    assert evidence.activated_at == profile.activated_at
    assert evidence.snapshot_generated_at == snapshot.generated_at
    assert evidence.effective_at == snapshot.effective_from
    assert evidence.as_of == _AS_OF
    assert isinstance(evidence.value, dict)
    evidence.value["active"] = False
    assert snapshot.resolved_values[_DEFINITION_KEY]["active"] is True


def test_evidence_passes_exact_cutoff_to_existing_public_qualifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The evidence adapter delegates eligibility instead of implementing a looser clock rule."""

    profile, snapshot, _values = _install_runtime(monkeypatch)
    cutoffs: list[datetime] = []

    def _qualified_value(
        *,
        environment: str,
        definition_key: str,
        as_of: datetime | None = None,
    ) -> object | None:
        assert environment == _ENVIRONMENT
        assert definition_key == _DEFINITION_KEY
        assert as_of is not None
        cutoffs.append(as_of)
        return snapshot.resolved_values[definition_key]

    monkeypatch.setattr(runtime_public, "get_active_runtime_value", _qualified_value)

    evidence = read_active_runtime_value_evidence(
        environment=_ENVIRONMENT,
        definition_key=_DEFINITION_KEY,
        as_of=_AS_OF,
    )

    assert evidence is not None
    assert evidence.profile_id == profile.profile_id
    assert cutoffs == [_AS_OF, _AS_OF]


def test_registered_neutral_bridge_uses_config_center_public_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The neutral getter is wired to the same public provider as AppConfig.ready."""

    profile, snapshot, _values = _install_runtime(monkeypatch)
    cutoffs: list[datetime] = []

    def _qualified_value(
        *,
        environment: str,
        definition_key: str,
        as_of: datetime | None = None,
    ) -> object | None:
        assert environment == _ENVIRONMENT
        assert definition_key == _DEFINITION_KEY
        assert as_of is not None
        cutoffs.append(as_of)
        return snapshot.resolved_values[definition_key]

    monkeypatch.setattr(runtime_public, "get_active_runtime_value", _qualified_value)
    monkeypatch.setattr(config_center_runtime, "_provider", None)
    config_center_runtime.configure_config_center_runtime_port(runtime_public)

    evidence = config_center_runtime.get_active_runtime_value_evidence(
        environment=_ENVIRONMENT,
        definition_key=_DEFINITION_KEY,
        as_of=_AS_OF,
    )

    assert evidence is not None
    assert evidence.profile_id == profile.profile_id
    assert evidence.snapshot_id == snapshot.snapshot_id
    assert evidence.value == _VALUE
    assert cutoffs == [_AS_OF, _AS_OF]


def test_evidence_fails_closed_when_profile_version_changes_between_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A current profile and a different snapshot can never be combined as one record."""

    first_profile, first_snapshot, _first_values = _runtime_records()
    second_profile, second_snapshot, _second_values = _runtime_records(
        profile_id="risk-profile-2",
        version=2,
        profile_key="risk-center-development-v2",
    )
    profiles = iter((first_profile, second_profile, second_profile))
    values = iter((_VALUE, _VALUE))
    snapshots = {
        first_profile.profile_key: first_snapshot,
        second_profile.profile_key: second_snapshot,
    }
    monkeypatch.setattr(
        runtime_public,
        "get_active_runtime_profile",
        lambda _env: next(profiles),
    )
    monkeypatch.setattr(
        runtime_public,
        "get_latest_runtime_snapshot",
        lambda profile_key: snapshots[profile_key],
    )
    monkeypatch.setattr(
        runtime_public,
        "get_active_runtime_value",
        lambda **_kwargs: next(values),
    )

    assert (
        read_active_runtime_value_evidence(
            environment=_ENVIRONMENT,
            definition_key=_DEFINITION_KEY,
            as_of=_AS_OF,
        )
        is None
    )


def test_evidence_never_falls_back_to_a_superseded_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An inactive old revision cannot be returned as current runtime evidence."""

    profile, _snapshot, _values = _install_runtime(monkeypatch)
    superseded = replace(profile, status=RuntimeProfileStatus.SUPERSEDED)
    monkeypatch.setattr(
        runtime_public,
        "get_active_runtime_profile",
        lambda _environment: superseded,
    )

    evidence = read_active_runtime_value_evidence(
        environment=_ENVIRONMENT,
        definition_key=_DEFINITION_KEY,
        as_of=_AS_OF,
    )

    assert evidence is None


def test_evidence_fails_closed_when_snapshot_identity_changes_under_same_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A repeated profile version cannot hide a regenerated snapshot identity."""

    profile, first_snapshot, _values = _runtime_records()
    second_snapshot = RuntimeConfigSnapshot(
        snapshot_id="snapshot-regenerated",
        profile_id=first_snapshot.profile_id,
        profile_key=first_snapshot.profile_key,
        profile_version=first_snapshot.profile_version,
        snapshot_hash=first_snapshot.snapshot_hash,
        resolved_values=first_snapshot.resolved_values,
        generated_at=first_snapshot.generated_at,
        effective_from=first_snapshot.effective_from,
    )
    profiles = iter((profile, profile, profile))
    snapshots = iter((first_snapshot, second_snapshot, second_snapshot))
    monkeypatch.setattr(
        runtime_public,
        "get_active_runtime_profile",
        lambda _env: next(profiles),
    )
    monkeypatch.setattr(
        runtime_public,
        "get_latest_runtime_snapshot",
        lambda _profile_key: next(snapshots),
    )
    monkeypatch.setattr(
        runtime_public,
        "get_active_runtime_value",
        lambda **_kwargs: _VALUE,
    )

    assert (
        read_active_runtime_value_evidence(
            environment=_ENVIRONMENT,
            definition_key=_DEFINITION_KEY,
            as_of=_AS_OF,
        )
        is None
    )


@pytest.mark.parametrize(
    "as_of",
    [datetime(2026, 11, 3, 3, 0), _AS_OF - timedelta(seconds=1)],
)
def test_evidence_fails_closed_when_the_existing_value_getter_rejects_cutoff(
    monkeypatch: pytest.MonkeyPatch,
    as_of: datetime,
) -> None:
    """Naive or too-new cutoffs cannot yield an evidence record."""

    _install_runtime(monkeypatch)

    result = read_active_runtime_value_evidence(
        environment=_ENVIRONMENT,
        definition_key=_DEFINITION_KEY,
        as_of=as_of,
    )

    assert result is None
