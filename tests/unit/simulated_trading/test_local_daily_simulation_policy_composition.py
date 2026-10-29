"""Active Config Center binding for the local daily simulation policy."""

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
from apps.simulated_trading import local_daily_simulation_policy_composition as composition

CUTOFF = datetime(2026, 10, 29, 7, tzinfo=UTC)
POLICY_KEY = "config_center.market.simulated_local_daily_simulation_policy"


def _policy_payload() -> dict[str, object]:
    """Return a complete explicit policy for the active runtime snapshot."""

    return {
        "schema_version": "local-daily-simulation-policy.v1",
        "purpose": "historical_daily_simulation",
        "policy_id": "local-daily-a-share",
        "version": "approved-1",
        "price_publication_key": "equity.price.bar.daily",
        "provider_configuration_id": 17,
        "provider_name": "tushare",
        "instrument_snapshot_id": "2c5e5a47-ef3a-4d03-8d13-a2e1054927b4",
        "currency": "CNY",
        "frequency": "1d",
        "adjustment": "none",
        "volume_unit": "shares",
        "participation_rate": "0.1250",
        "share_step": "100",
        "allowed_qmt_suspend_flags": [-1, 0],
        "currency_basis": "same_session_stock_basic_capture",
        "qmt_status_basis": "owner_authenticated_normalized_daily_status",
        "limit_price_basis": "same_provider_cny_listing_native",
    }


def _runtime_pair(
    payload: object,
) -> tuple[RuntimeConfigProfile, RuntimeConfigSnapshot]:
    values = {POLICY_KEY: payload}
    digest = hashlib.sha256(
        json.dumps(
            values,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    activated = CUTOFF - timedelta(hours=2)
    profile = RuntimeConfigProfile(
        profile_id="daily-simulation-profile",
        profile_key="development-profile",
        environment="development",
        version=4,
        status=RuntimeProfileStatus.ACTIVE,
        content_hash="a" * 64,
        created_at=activated - timedelta(hours=1),
        activated_at=activated,
    )
    snapshot = RuntimeConfigSnapshot(
        snapshot_id="daily-simulation-snapshot",
        profile_id=profile.profile_id,
        profile_key=profile.profile_key,
        profile_version=profile.version,
        snapshot_hash=digest,
        resolved_values=values,
        generated_at=activated,
        effective_from=activated,
    )
    return profile, snapshot


def _install_pair(
    monkeypatch: pytest.MonkeyPatch,
    profile: RuntimeConfigProfile,
    snapshot: RuntimeConfigSnapshot,
    value: object,
) -> list[datetime]:
    cutoffs: list[datetime] = []
    monkeypatch.setattr(composition, "get_active_runtime_profile", lambda environment: profile)
    monkeypatch.setattr(composition, "get_latest_runtime_snapshot", lambda key: snapshot)

    def read_value(*, environment: str, definition_key: str, as_of: datetime) -> object:
        assert environment == "development"
        assert definition_key == POLICY_KEY
        cutoffs.append(as_of)
        return value

    monkeypatch.setattr(composition, "get_active_runtime_value", read_value)
    return cutoffs


def test_runtime_reader_returns_policy_with_verified_active_profile_snapshot_and_cutoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _policy_payload()
    profile, snapshot = _runtime_pair(payload)
    cutoffs = _install_pair(monkeypatch, profile, snapshot, payload)

    binding = composition.ConfiguredLocalDailySimulationPolicyReader(
        runtime_environment="development"
    ).read_policy(as_of=CUTOFF)

    assert binding is not None
    assert binding.policy.to_payload() == payload
    assert binding.provenance.profile_id == profile.profile_id
    assert binding.provenance.profile_key == profile.profile_key
    assert binding.provenance.profile_version == profile.version
    assert binding.provenance.profile_content_hash == profile.content_hash
    assert binding.provenance.profile_activated_at == profile.activated_at
    assert binding.provenance.snapshot_id == snapshot.snapshot_id
    assert binding.provenance.snapshot_content_hash == snapshot.snapshot_hash
    assert binding.provenance.snapshot_effective_from == snapshot.effective_from
    assert binding.provenance.read_at == CUTOFF
    assert cutoffs == [CUTOFF]


@pytest.mark.parametrize(
    "defect",
    ["profile", "snapshot", "missing", "value_mismatch", "future", "effective", "digest"],
)
def test_runtime_reader_fails_closed_for_missing_or_inconsistent_policy_binding(
    monkeypatch: pytest.MonkeyPatch,
    defect: str,
) -> None:
    payload = _policy_payload()
    profile, snapshot = _runtime_pair(payload)
    _install_pair(monkeypatch, profile, snapshot, payload)
    if defect == "profile":
        monkeypatch.setattr(composition, "get_active_runtime_profile", lambda environment: None)
    elif defect == "snapshot":
        monkeypatch.setattr(composition, "get_latest_runtime_snapshot", lambda key: None)
    elif defect == "missing":
        monkeypatch.setattr(composition, "get_active_runtime_value", lambda **kwargs: None)
    elif defect == "value_mismatch":
        monkeypatch.setattr(composition, "get_active_runtime_value", lambda **kwargs: {})
    elif defect == "future":
        future = CUTOFF + timedelta(seconds=1)
        profile = replace(profile, activated_at=future)
        snapshot = replace(snapshot, effective_from=future, generated_at=future)
        _install_pair(monkeypatch, profile, snapshot, payload)
    elif defect == "effective":
        snapshot = replace(snapshot, effective_from=None)
        _install_pair(monkeypatch, profile, snapshot, payload)
    else:
        snapshot = replace(snapshot, snapshot_hash="b" * 64)
        _install_pair(monkeypatch, profile, snapshot, payload)

    assert (
        composition.ConfiguredLocalDailySimulationPolicyReader(
            runtime_environment="development"
        ).read_policy(as_of=CUTOFF)
        is None
    )


@pytest.mark.parametrize("drift", ["profile", "snapshot"])
def test_runtime_reader_rejects_profile_or_snapshot_drift_during_read(
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    payload = _policy_payload()
    profile, snapshot = _runtime_pair(payload)
    _install_pair(monkeypatch, profile, snapshot, payload)
    if drift == "profile":
        profiles = iter((profile, replace(profile, version=profile.version + 1)))
        monkeypatch.setattr(
            composition,
            "get_active_runtime_profile",
            lambda environment: next(profiles),
        )
    else:
        snapshots = iter((snapshot, replace(snapshot, snapshot_id="changed-snapshot")))
        monkeypatch.setattr(
            composition,
            "get_latest_runtime_snapshot",
            lambda key: next(snapshots),
        )

    assert (
        composition.ConfiguredLocalDailySimulationPolicyReader(
            runtime_environment="development"
        ).read_policy(as_of=CUTOFF)
        is None
    )


def test_reader_construction_does_not_read_or_activate_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("configuration reads occur only at the explicit policy cutoff")

    monkeypatch.setattr(composition, "get_active_runtime_profile", forbidden)
    monkeypatch.setattr(composition, "get_active_runtime_value", forbidden)
    assert composition.ConfiguredLocalDailySimulationPolicyReader(runtime_environment="development")


@pytest.mark.parametrize("environment", ["", "two words", None])
def test_reader_rejects_invalid_runtime_environment(environment: object) -> None:
    with pytest.raises(ValueError):
        composition.ConfiguredLocalDailySimulationPolicyReader(
            runtime_environment=environment  # type: ignore[arg-type]
        )
