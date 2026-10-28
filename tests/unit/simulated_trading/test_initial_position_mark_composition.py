"""Runtime provenance and explicit composition for initial position marks."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.config_center.domain.runtime_config import (
    RuntimeConfigProfile,
    RuntimeConfigSnapshot,
    RuntimeProfileStatus,
)
from apps.simulated_trading import initial_position_mark_composition as composition

CUTOFF = datetime(2026, 10, 28, 8, tzinfo=UTC)
POLICY_KEY = "config_center.market.simulated_initial_position_mark_policy"


def _policy_payload() -> dict[str, object]:
    return {
        "schema_version": "simulated-initial-position-mark-policy.v1",
        "purpose": "apply_time_initial_position_mark",
        "policy_id": "local-close-mark",
        "version": "approved-1",
        "publication_key": "simulated-initial-mark",
        "source": "tushare",
        "frequency": "1d",
        "adjustment": "none",
        "supported_asset_types": ["stock"],
        "freshness_window_seconds": 86400,
    }


def _runtime_pair() -> tuple[RuntimeConfigProfile, RuntimeConfigSnapshot]:
    values = {POLICY_KEY: _policy_payload()}
    snapshot_hash = hashlib.sha256(
        json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    activated = CUTOFF - timedelta(hours=2)
    return (
        RuntimeConfigProfile(
            profile_id="mark-profile",
            profile_key="development-profile",
            environment="development",
            version=2,
            status=RuntimeProfileStatus.ACTIVE,
            content_hash="a" * 64,
            created_at=activated - timedelta(hours=1),
            activated_at=activated,
        ),
        RuntimeConfigSnapshot(
            snapshot_id="mark-snapshot",
            profile_id="mark-profile",
            profile_key="development-profile",
            profile_version=2,
            snapshot_hash=snapshot_hash,
            resolved_values=values,
            generated_at=activated,
            effective_from=activated,
        ),
    )


def _install_pair(
    monkeypatch: pytest.MonkeyPatch,
    profile: RuntimeConfigProfile,
    snapshot: RuntimeConfigSnapshot,
) -> list[datetime]:
    cutoffs: list[datetime] = []
    monkeypatch.setattr(composition, "get_active_runtime_profile", lambda environment: profile)
    monkeypatch.setattr(composition, "get_latest_runtime_snapshot", lambda key: snapshot)

    def value(*, environment: str, definition_key: str, as_of: datetime) -> object:
        assert environment == "development"
        assert definition_key == POLICY_KEY
        cutoffs.append(as_of)
        return _policy_payload()

    monkeypatch.setattr(composition, "get_active_runtime_value", value)
    return cutoffs


def test_runtime_policy_retains_actual_profile_and_snapshot_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile, snapshot = _runtime_pair()
    cutoffs = _install_pair(monkeypatch, profile, snapshot)
    binding = composition.ConfiguredInitialPositionMarkPolicyReader(
        runtime_environment="development"
    ).read_policy(as_of=CUTOFF)
    assert binding is not None
    assert binding.provenance.profile_id == profile.profile_id
    assert binding.provenance.profile_version == 2
    assert binding.provenance.profile_content_hash == profile.content_hash
    assert binding.provenance.profile_activated_at == profile.activated_at
    assert binding.provenance.snapshot_id == snapshot.snapshot_id
    assert binding.provenance.snapshot_content_hash == snapshot.snapshot_hash
    assert binding.provenance.snapshot_effective_from == snapshot.effective_from
    assert binding.provenance.read_at == CUTOFF
    assert binding.policy.freshness_window_seconds == 86400
    assert cutoffs == [CUTOFF]


@pytest.mark.parametrize(
    "defect", ["profile", "snapshot", "value", "value_mismatch", "future", "effective", "digest"]
)
def test_runtime_policy_rejects_missing_or_inconsistent_activation(
    monkeypatch: pytest.MonkeyPatch,
    defect: str,
) -> None:
    profile, snapshot = _runtime_pair()
    if defect == "future":
        profile = replace(profile, activated_at=CUTOFF + timedelta(seconds=1))
        snapshot = replace(
            snapshot,
            effective_from=profile.activated_at,
            generated_at=CUTOFF + timedelta(seconds=1),
        )
    elif defect == "effective":
        snapshot = replace(snapshot, effective_from=None)
    elif defect == "digest":
        snapshot = replace(snapshot, snapshot_hash="b" * 64)
    _install_pair(monkeypatch, profile, snapshot)
    if defect == "profile":
        monkeypatch.setattr(composition, "get_active_runtime_profile", lambda environment: None)
    elif defect == "snapshot":
        monkeypatch.setattr(composition, "get_latest_runtime_snapshot", lambda key: None)
    elif defect == "value":
        monkeypatch.setattr(composition, "get_active_runtime_value", lambda **kwargs: None)
    elif defect == "value_mismatch":
        monkeypatch.setattr(composition, "get_active_runtime_value", lambda **kwargs: {})
    assert (
        composition.ConfiguredInitialPositionMarkPolicyReader(
            runtime_environment="development"
        ).read_policy(as_of=CUTOFF)
        is None
    )


def test_runtime_policy_rejects_profile_change_during_value_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile, snapshot = _runtime_pair()
    _install_pair(monkeypatch, profile, snapshot)
    profiles = iter((profile, replace(profile, version=3)))
    monkeypatch.setattr(
        composition, "get_active_runtime_profile", lambda environment: next(profiles)
    )
    assert (
        composition.ConfiguredInitialPositionMarkPolicyReader(
            runtime_environment="development"
        ).read_policy(as_of=CUTOFF)
        is None
    )


def test_building_reader_does_not_read_or_activate_runtime_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("configuration must only be read at the caller cutoff")

    monkeypatch.setattr(composition, "get_active_runtime_profile", forbidden)
    monkeypatch.setattr(composition, "get_active_runtime_value", forbidden)
    reader = composition.build_published_initial_position_mark_reader(
        runtime_environment="development", calendar_dataset_key="cn.exchange.calendar"
    )
    assert reader is not None


def test_runtime_policy_rejects_snapshot_change_during_value_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile, snapshot = _runtime_pair()
    _install_pair(monkeypatch, profile, snapshot)
    snapshots = iter((snapshot, replace(snapshot, snapshot_id="replacement")))
    monkeypatch.setattr(composition, "get_latest_runtime_snapshot", lambda key: next(snapshots))
    assert (
        composition.ConfiguredInitialPositionMarkPolicyReader(
            runtime_environment="development"
        ).read_policy(as_of=CUTOFF)
        is None
    )
