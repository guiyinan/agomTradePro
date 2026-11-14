"""App-neutral runtime snapshot evidence port contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

import pytest

from core.integration import config_center_runtime
from core.integration.config_center_runtime import (
    ActiveRuntimeSnapshotEvidence,
    RuntimeConfigProfileRead,
    RuntimeConfigSnapshotRead,
    RuntimeSnapshotEvidenceReadPort,
)

_AS_OF = datetime(2026, 11, 14, 2, 0, tzinfo=UTC)


@dataclass(frozen=True)
class _Profile:
    profile_id: str = "profile-1"
    profile_key: str = "market-development"
    environment: str = "development"
    version: int = 2
    status: str = "active"
    content_hash: str = "a" * 64
    created_at: datetime = datetime(2026, 11, 14, 1, 0, tzinfo=UTC)
    activated_at: datetime | None = datetime(2026, 11, 14, 1, 30, tzinfo=UTC)

    def __post_init__(self) -> None:
        """Satisfy the Config Center profile-read Protocol."""


@dataclass(frozen=True)
class _Snapshot:
    snapshot_id: str = "snapshot-1"
    profile_id: str = "profile-1"
    profile_key: str = "market-development"
    profile_version: int = 2
    snapshot_hash: str = "b" * 64
    resolved_values: Mapping[str, object] = field(
        default_factory=lambda: {"market.policy": {"enabled": True}}
    )
    generated_at: datetime = datetime(2026, 11, 14, 1, 40, tzinfo=UTC)
    effective_from: datetime | None = datetime(2026, 11, 14, 1, 30, tzinfo=UTC)

    def __post_init__(self) -> None:
        """Satisfy the Config Center snapshot-read Protocol."""


def _evidence(
    profile: RuntimeConfigProfileRead | None = None,
    snapshot: RuntimeConfigSnapshotRead | None = None,
) -> ActiveRuntimeSnapshotEvidence:
    """Build one typed app-neutral snapshot bundle for bridge tests."""

    return ActiveRuntimeSnapshotEvidence(
        environment="development",
        definition_keys=("market.policy",),
        profile=_Profile() if profile is None else profile,
        snapshot=_Snapshot() if snapshot is None else snapshot,
        as_of=_AS_OF,
    )


class _NewEvidenceProvider:
    """Expose only the optional bundle port, not the older Config Center API."""

    def __init__(self, result: ActiveRuntimeSnapshotEvidence | None) -> None:
        self.result = result
        self.calls: list[tuple[str, tuple[str, ...], datetime]] = []
        self.legacy_value_calls = 0

    def get_active_runtime_snapshot_evidence(
        self,
        *,
        environment: str,
        definition_keys: tuple[str, ...],
        as_of: datetime,
    ) -> ActiveRuntimeSnapshotEvidence | None:
        self.calls.append((environment, definition_keys, as_of))
        return self.result

    def get_active_runtime_value(
        self,
        *,
        environment: str,
        definition_key: str,
        as_of: datetime | None = None,
    ) -> object | None:
        self.legacy_value_calls += 1
        return {"enabled": True}


class _LegacyProvider:
    """Keep the historical read port usable without the new optional Protocol."""

    def __init__(self) -> None:
        self.value_calls = 0

    def get_active_runtime_value(
        self,
        *,
        environment: str,
        definition_key: str,
        as_of: datetime | None = None,
    ) -> object | None:
        self.value_calls += 1
        return {"enabled": True}

    def get_active_runtime_profile(self, environment: str) -> RuntimeConfigProfileRead | None:
        return _Profile()

    def get_latest_runtime_snapshot(self, profile_key: str) -> RuntimeConfigSnapshotRead | None:
        return _Snapshot()

    def get_active_runtime_secret_ref(self, *, environment: str, definition_key: str) -> str | None:
        return None

    def register_runtime_definitions(self, specifications: tuple[object, ...]) -> tuple[str, ...]:
        return ()

    def evaluate_storage_pressure(
        self, *, used_bytes: int, actual_capacity_bytes: int | None = None
    ) -> dict[str, object]:
        return {}

    def collect_storage_capacity_profile(
        self, *, environment: str, source: str
    ) -> dict[str, object]:
        return {}


def test_optional_snapshot_read_protocol_is_runtime_checkable() -> None:
    """An independent bundle provider need not implement the legacy port."""

    provider = _NewEvidenceProvider(_evidence())

    assert isinstance(provider, RuntimeSnapshotEvidenceReadPort)
    assert not isinstance(_LegacyProvider(), RuntimeSnapshotEvidenceReadPort)


@pytest.mark.parametrize("status", ("superseded", "draft", False))
def test_snapshot_dto_cannot_relabel_a_nonactive_profile(status) -> None:
    """Copying a profile may canonicalize an active enum but cannot activate another status."""
    with pytest.raises(ValueError):
        _evidence(profile=replace(_Profile(), status=status))


def test_snapshot_bridge_uses_fresh_bundle_and_has_no_legacy_fallback(monkeypatch) -> None:
    """The new bridge delegates once and missing bundle results stay unavailable."""

    provider = _NewEvidenceProvider(None)
    monkeypatch.setattr(config_center_runtime, "_provider", provider)

    result = config_center_runtime.get_active_runtime_snapshot_evidence(
        environment="development",
        definition_keys=("market.policy",),
        as_of=_AS_OF,
    )

    assert result is None
    assert provider.calls == [("development", ("market.policy",), _AS_OF)]
    assert provider.legacy_value_calls == 0


def test_runtime_value_evidence_projects_new_bundle_without_reasking_value_port(
    monkeypatch,
) -> None:
    """Existing typed single-key evidence can be projected from one full bundle."""

    provider = _NewEvidenceProvider(_evidence())
    monkeypatch.setattr(config_center_runtime, "_provider", provider)

    result = config_center_runtime.get_active_runtime_value_evidence(
        environment="development",
        definition_key="market.policy",
        as_of=_AS_OF,
    )

    assert result is not None
    assert result.value == {"enabled": True}
    assert result.profile_id == "profile-1"
    assert result.snapshot_id == "snapshot-1"
    assert result.as_of == _AS_OF
    assert provider.calls == [("development", ("market.policy",), _AS_OF)]
    assert provider.legacy_value_calls == 0


def test_capable_provider_returning_none_does_not_fall_back_to_legacy_value(
    monkeypatch,
) -> None:
    """An unavailable new evidence read cannot silently use the old scalar value port."""

    provider = _NewEvidenceProvider(None)
    monkeypatch.setattr(config_center_runtime, "_provider", provider)

    result = config_center_runtime.get_active_runtime_value_evidence(
        environment="development",
        definition_key="market.policy",
        as_of=_AS_OF,
    )

    assert result is None
    assert provider.legacy_value_calls == 0


def test_legacy_provider_without_bundle_keeps_the_existing_port_path(monkeypatch) -> None:
    """Only providers lacking the independent Protocol retain the old reader path."""

    provider = _LegacyProvider()
    monkeypatch.setattr(config_center_runtime, "_provider", provider)

    bundle = config_center_runtime.get_active_runtime_snapshot_evidence(
        environment="development",
        definition_keys=("market.policy",),
        as_of=_AS_OF,
    )
    value = config_center_runtime.get_active_runtime_value_evidence(
        environment="development",
        definition_key="market.policy",
        as_of=_AS_OF,
    )

    assert bundle is None
    assert value is not None
    assert value.value == {"enabled": True}
    assert provider.value_calls == 2


def test_snapshot_evidence_detaches_original_and_returned_nested_mappings() -> None:
    """Evidence consumers cannot mutate its source snapshot through shared dicts."""

    source = _Snapshot()
    evidence = _evidence(snapshot=source)
    first = evidence.snapshot.resolved_values
    assert isinstance(first["market.policy"], dict)
    first["market.policy"]["enabled"] = False
    source.resolved_values["market.policy"]["enabled"] = False

    assert evidence.snapshot.resolved_values == {"market.policy": {"enabled": True}}
