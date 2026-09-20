"""Regression checks for persisted full-profile integrity at public boundaries."""

from dataclasses import replace

import pytest

from apps.config_center.application import runtime_public
from apps.config_center.domain.runtime_config import (
    RuntimeConfigProfile,
    RuntimeConfigValue,
    verify_runtime_profile_values,
)
from tests.unit.config_center.test_aud05_hash_scope_and_activation import (
    _Definitions,
    _profile,
    _service,
    _values,
)


def _active_service(monkeypatch: pytest.MonkeyPatch):
    service, profiles, values, revisions, snapshots = _service()
    draft = _profile()
    profile, snapshot = service.activate(
        draft, _values(draft.profile_id), actor="review-test", reason="valid initial profile"
    )
    monkeypatch.setattr(runtime_public, "get_runtime_config_service", lambda: service)
    monkeypatch.setattr(runtime_public, "get_runtime_value_repository", lambda: values)
    monkeypatch.setattr(runtime_public, "get_runtime_definition_repository", _Definitions)
    monkeypatch.setattr(
        runtime_public, "reconcile_runtime_definitions", lambda: pytest.fail("unexpected write")
    )
    return service, profile, snapshot, profiles, values, revisions, snapshots


def _corrupt_values(values: list[RuntimeConfigValue], corruption: str) -> None:
    if corruption == "secret":
        values[-1] = replace(values[-1], secret_ref="secret://unapproved/reference")
    elif corruption == "public":
        values[0] = replace(values[0], value_json="changed-outside-activation")
    elif corruption == "missing":
        values.pop()
    elif corruption == "duplicate":
        values.append(values[-1])
    else:
        raise AssertionError(corruption)


@pytest.mark.parametrize("corruption", ["secret", "public", "missing", "duplicate"])
def test_secret_read_rejects_full_profile_value_drift(monkeypatch, corruption: str) -> None:
    _, _, _, _, values, _, _ = _active_service(monkeypatch)
    _corrupt_values(values.saved, corruption)

    assert (
        runtime_public.get_active_runtime_secret_ref(
            environment="production", definition_key="provider.key"
        )
        is None
    )


def test_secret_read_accepts_verified_full_profile(monkeypatch) -> None:
    _active_service(monkeypatch)

    assert (
        runtime_public.get_active_runtime_secret_ref(
            environment="production", definition_key="provider.key"
        )
        == "secret://provider/v14"
    )


def test_full_value_verification_rejects_foreign_profile_members(monkeypatch) -> None:
    _, profile, _, _, _, _, _ = _active_service(monkeypatch)

    with pytest.raises(ValueError, match="runtime profile value identity mismatch"):
        verify_runtime_profile_values(profile, _values("another-profile"))


def test_active_validation_reports_full_profile_hash_drift(monkeypatch) -> None:
    service, _, _, _, values, _, _ = _active_service(monkeypatch)
    _corrupt_values(values.saved, "secret")

    report = service.validate_active_profile("production")

    assert report["valid"] is False
    assert "runtime profile full hash does not match persisted values" in report["errors"]


@pytest.mark.parametrize("corruption", ["secret", "public", "missing", "duplicate"])
@pytest.mark.parametrize("execute", [False, True])
def test_patch_refuses_to_reseal_corrupt_predecessor(monkeypatch, corruption, execute) -> None:
    _, profile, snapshot, profiles, values, revisions, snapshots = _active_service(monkeypatch)
    _corrupt_values(values.saved, corruption)
    before = (
        list(profiles.saved),
        list(values.saved),
        list(revisions.saved),
        list(snapshots.saved),
    )
    operation = (
        runtime_public.activate_runtime_profile_patch
        if execute
        else runtime_public.preview_runtime_profile_patch
    )

    with pytest.raises(ValueError, match="runtime profile (values|value|full hash)"):
        operation(
            environment="production",
            patch={"audit.mode": "on"},
            actor="review-test",
            reason="corrective patch must not bless drift",
            expected_active_profile_id=profile.profile_id,
            expected_active_profile_version=profile.version,
            expected_active_profile_hash=profile.content_hash,
            expected_active_snapshot_hash=snapshot.snapshot_hash,
        )

    assert (profiles.saved, values.saved, revisions.saved, snapshots.saved) == before


def test_direct_activation_rejects_corrupt_predecessor_values(monkeypatch) -> None:
    service, profile, snapshot, profiles, values, revisions, snapshots = _active_service(
        monkeypatch
    )
    values.saved[-1] = replace(values.saved[-1], secret_ref="secret://unapproved/reference")
    successor = RuntimeConfigProfile(
        profile_id="new-profile",
        profile_key=profile.profile_key,
        environment=profile.environment,
        version=profile.version + 1,
        based_on_profile=profile.profile_id,
    )
    before = (
        list(profiles.saved),
        list(values.saved),
        list(revisions.saved),
        list(snapshots.saved),
    )

    with pytest.raises(ValueError, match="runtime profile full hash"):
        service.activate(
            successor,
            _values(successor.profile_id),
            actor="review-test",
            reason="direct caller must also verify predecessor",
            legacy_correction=(profile.content_hash, snapshot.snapshot_hash),
        )

    assert (profiles.saved, values.saved, revisions.saved, snapshots.saved) == before
