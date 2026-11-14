"""An actual current configuration snapshot is evidence, never a model default."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from apps.simulated_trading import corporate_action_configuration_composition as configuration
from core.exceptions import BusinessLogicError
from core.integration import config_center_runtime as runtime
from tests.unit.simulated_trading.test_initial_position_mark_composition import (
    CUTOFF,
    POLICY_KEY,
    _runtime_pair,
)


def _install(monkeypatch):
    profile, snapshot = _runtime_pair()
    monkeypatch.setattr(configuration.timezone, "now", lambda: CUTOFF)
    port = SimpleNamespace(
        get_active_runtime_profile=lambda environment: profile,
        get_latest_runtime_snapshot=lambda key: snapshot,
        get_active_runtime_value=lambda **kwargs: snapshot.resolved_values.get(
            kwargs["definition_key"]
        ),
    )
    monkeypatch.setattr(runtime, "_provider", port)
    monkeypatch.setattr(
        configuration,
        "get_latest_runtime_snapshot",
        lambda key: runtime._provider.get_latest_runtime_snapshot(key),
    )
    return profile, snapshot


def test_current_configuration_keeps_original_profile_and_snapshot_and_immutable_value(monkeypatch):
    profile, snapshot = _install(monkeypatch)
    proof = configuration.read_corporate_action_configuration(
        definition_key=POLICY_KEY, environment="development", as_of=CUTOFF
    )
    assert proof.profile_id == profile.profile_id
    assert proof.profile_content_sha256 == profile.content_hash
    assert proof.snapshot_id == snapshot.snapshot_id
    assert proof.snapshot_sha256 == snapshot.snapshot_hash
    assert proof.known_at == snapshot.generated_at
    assert proof.checked_at == CUTOFF
    assert json.loads(proof.value_json) == snapshot.resolved_values[POLICY_KEY]
    original = proof.value_json
    snapshot.resolved_values.clear()
    assert proof.value_json == original


@pytest.mark.parametrize(
    "defect",
    [
        "missing",
        "digest",
        "future",
        "effective",
        "changed_profile",
        "changed_value",
        "wrong_environment",
    ],
)
def test_configuration_rejects_missing_conflicting_or_unknown_current_snapshot(monkeypatch, defect):
    profile, snapshot = _install(monkeypatch)
    if defect == "missing":
        monkeypatch.setattr(runtime._provider, "get_active_runtime_value", lambda **kwargs: None)
    elif defect == "digest":
        monkeypatch.setattr(
            runtime._provider,
            "get_latest_runtime_snapshot",
            lambda key: replace(snapshot, snapshot_hash="f" * 64),
        )
    elif defect == "future":
        from datetime import timedelta

        monkeypatch.setattr(configuration.timezone, "now", lambda: CUTOFF - timedelta(seconds=1))
    elif defect == "effective":
        monkeypatch.setattr(
            runtime._provider,
            "get_latest_runtime_snapshot",
            lambda key: replace(snapshot, effective_from=None),
        )
    elif defect == "changed_profile":
        calls = iter((profile, replace(profile, version=3), replace(profile, version=3)))
        monkeypatch.setattr(
            runtime._provider, "get_active_runtime_profile", lambda environment: next(calls)
        )
    elif defect == "changed_value":
        monkeypatch.setattr(
            runtime._provider, "get_active_runtime_value", lambda **kwargs: {"invented": True}
        )
    else:
        monkeypatch.setattr(
            runtime._provider,
            "get_active_runtime_profile",
            lambda environment: replace(profile, environment="production"),
        )
    with pytest.raises(BusinessLogicError):
        configuration.read_corporate_action_configuration(
            definition_key=POLICY_KEY, environment="development", as_of=CUTOFF
        )
