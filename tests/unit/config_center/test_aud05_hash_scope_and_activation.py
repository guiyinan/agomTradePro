"""Focused AUD-05 regressions for public snapshot integrity and successors."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from io import StringIO
from uuid import uuid4

import pytest
from django.core.management import CommandError

from apps.config_center.application import runtime_public
from apps.config_center.application.runtime_config import RuntimeConfigService
from apps.config_center.domain.runtime_config import (
    RuntimeConfigCriticality,
    RuntimeConfigDefinition,
    RuntimeConfigProfile,
    RuntimeConfigSnapshot,
    RuntimeConfigValue,
    RuntimeProfileStatus,
    RuntimeValueType,
    hash_public_runtime_projection,
    hash_runtime_profile_values,
)
from apps.config_center.infrastructure.runtime_config_repositories import _same_snapshot
from apps.config_center.management.commands import activate_runtime_profile_corrective

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


class _Definitions:
    def __init__(self) -> None:
        self.items = [
            RuntimeConfigDefinition(
                key="audit.mode",
                namespace="audit",
                owner_app="audit",
                value_type=RuntimeValueType.STRING,
                criticality=RuntimeConfigCriticality.CRITICAL,
            ),
            RuntimeConfigDefinition(
                key="provider.key",
                namespace="provider",
                owner_app="data_center",
                value_type=RuntimeValueType.STRING,
                secret=True,
            ),
        ]

    def list_all(self) -> list[RuntimeConfigDefinition]:
        return self.items

    def get(self, key: str) -> RuntimeConfigDefinition | None:
        return next((item for item in self.items if item.key == key), None)


class _Profiles:
    def __init__(self) -> None:
        self.saved: list[RuntimeConfigProfile] = []

    def save(self, profile: RuntimeConfigProfile) -> RuntimeConfigProfile:
        self.saved.append(profile)
        return profile

    def get(self, profile_id: str) -> RuntimeConfigProfile | None:
        return next((item for item in self.saved if item.profile_id == profile_id), None)

    def get_active(self, environment: str) -> RuntimeConfigProfile | None:
        return next(
            (
                item
                for item in reversed(self.saved)
                if item.environment == environment and item.status is RuntimeProfileStatus.ACTIVE
            ),
            None,
        )


class _Values:
    def __init__(self) -> None:
        self.saved: list[RuntimeConfigValue] = []

    def save(self, value: RuntimeConfigValue) -> RuntimeConfigValue:
        self.saved.append(value)
        return value

    def list_for_profile(self, profile_id: str) -> list[RuntimeConfigValue]:
        return [item for item in self.saved if item.profile_id == profile_id]


class _Revisions:
    def __init__(self) -> None:
        self.saved = []

    def save(self, revision):  # type: ignore[no-untyped-def]
        self.saved.append(revision)
        return revision


class _Snapshots:
    def __init__(self) -> None:
        self.saved = []

    def save(self, snapshot):  # type: ignore[no-untyped-def]
        self.saved.append(snapshot)
        return snapshot

    def get_latest(self, profile_key: str):  # type: ignore[no-untyped-def]
        return next(
            (item for item in reversed(self.saved) if item.profile_key == profile_key),
            None,
        )


class _Activation:
    """Explicit in-memory atomic adapter used only by these application tests."""

    def __init__(self, profiles, values, revisions, snapshots) -> None:  # type: ignore[no-untyped-def]
        self.profiles = profiles
        self.values = values
        self.revisions = revisions
        self.snapshots = snapshots

    def activate(
        self,
        *,
        profile,
        values,
        revision,
        snapshot,
        expected_previous_profile,
        expected_previous_snapshot,
    ):  # type: ignore[no-untyped-def]
        del expected_previous_profile, expected_previous_snapshot
        saved_profile = self.profiles.save(profile)
        for value in values:
            self.values.save(value)
        self.revisions.save(revision)
        saved_snapshot = self.snapshots.save(snapshot)
        return saved_profile, saved_snapshot


def _service() -> tuple[RuntimeConfigService, _Profiles, _Values, _Revisions, _Snapshots]:
    profiles, values, revisions, snapshots = _Profiles(), _Values(), _Revisions(), _Snapshots()
    service = RuntimeConfigService(
        _Definitions(),
        profiles,
        values,
        revisions,
        snapshots,
        _Activation(profiles, values, revisions, snapshots),
    )
    return service, profiles, values, revisions, snapshots


def _profile(*, profile_id: str | None = None, version: int = 14) -> RuntimeConfigProfile:
    return RuntimeConfigProfile(
        profile_id=profile_id or str(uuid4()),
        profile_key="production",
        environment="production",
        version=version,
        created_at=NOW,
    )


def _values(
    profile_id: str, *, secret_ref: str = "secret://provider/v14"
) -> tuple[RuntimeConfigValue, ...]:
    return (
        RuntimeConfigValue(
            profile_id=profile_id,
            definition_key="audit.mode",
            value_json="off",
        ),
        RuntimeConfigValue(
            profile_id=profile_id,
            definition_key="provider.key",
            secret_ref=secret_ref,
        ),
    )


def test_aud05_reproduces_full_profile_vs_public_snapshot_hash_mismatch_without_secret_values() -> (
    None
):
    service, _profiles, _values_repo, revisions, _snapshots = _service()
    profile = _profile()

    saved_profile, snapshot = service.activate(
        profile,
        _values(profile.profile_id),
        actor="aud05-test",
        reason="reproduce v14 hash scope",
    )

    full_values = {"audit.mode": "off", "provider.key": "secret://provider/v14"}
    assert saved_profile.content_hash == hash_runtime_profile_values(full_values)
    assert snapshot.resolved_values == {"audit.mode": "off"}
    assert snapshot.snapshot_hash == hash_public_runtime_projection(snapshot.resolved_values)
    assert saved_profile.content_hash != snapshot.snapshot_hash
    assert "secret://" not in str(snapshot)
    assert "secret://" not in str(revisions.saved[0].after_projection)


def test_public_getter_rejects_snapshot_hash_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = RuntimeConfigProfile(
        profile_id="profile-aud05",
        profile_key="production",
        environment="production",
        version=17,
        status=RuntimeProfileStatus.ACTIVE,
        content_hash="full-profile-hash",
        created_at=NOW,
        activated_at=NOW,
    )
    snapshot = RuntimeConfigSnapshot(
        snapshot_id="snapshot-aud05",
        profile_id=profile.profile_id,
        profile_key=profile.profile_key,
        profile_version=profile.version,
        snapshot_hash="0" * 64,
        resolved_values={"audit.mode": "off"},
        generated_at=NOW,
    )
    monkeypatch.setattr(runtime_public, "get_active_runtime_profile", lambda _environment: profile)
    monkeypatch.setattr(
        runtime_public,
        "get_runtime_definition_repository",
        lambda: _Definitions(),
    )
    monkeypatch.setattr(
        runtime_public,
        "get_latest_runtime_snapshot",
        lambda _profile_key: snapshot,
    )

    assert (
        runtime_public.get_active_runtime_value(
            environment="production",
            definition_key="audit.mode",
        )
        is None
    )


def test_public_getter_rejects_secret_bearing_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = RuntimeConfigProfile(
        profile_id="profile-secret-bearing",
        profile_key="production",
        environment="production",
        version=17,
        status=RuntimeProfileStatus.ACTIVE,
        content_hash="full-profile-hash",
        created_at=NOW,
        activated_at=NOW,
    )
    snapshot = RuntimeConfigSnapshot(
        snapshot_id="snapshot-secret-bearing",
        profile_id=profile.profile_id,
        profile_key=profile.profile_key,
        profile_version=profile.version,
        snapshot_hash=hash_public_runtime_projection({"audit.mode": "off"}),
        resolved_values={
            "audit.mode": "off",
            "provider.key": "secret://provider/v17",
        },
        generated_at=NOW,
    )
    monkeypatch.setattr(runtime_public, "get_active_runtime_profile", lambda _environment: profile)
    monkeypatch.setattr(
        runtime_public,
        "get_runtime_definition_repository",
        lambda: _Definitions(),
    )
    monkeypatch.setattr(
        runtime_public,
        "get_latest_runtime_snapshot",
        lambda _profile_key: snapshot,
    )

    assert (
        runtime_public.get_active_runtime_value(
            environment="production",
            definition_key="provider.key",
        )
        is None
    )


def test_corrective_preview_is_read_only_and_binds_approved_hashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = RuntimeConfigProfile(
        profile_id="approved-profile",
        profile_key="production",
        environment="production",
        version=14,
        status=RuntimeProfileStatus.ACTIVE,
        content_hash="approved-full-hash",
        created_at=NOW,
        activated_at=NOW,
    )
    snapshot_values = {"audit.mode": "off"}
    snapshot = RuntimeConfigSnapshot(
        snapshot_id="approved-snapshot",
        profile_id=profile.profile_id,
        profile_key=profile.profile_key,
        profile_version=profile.version,
        snapshot_hash=hash_public_runtime_projection(snapshot_values),
        resolved_values=snapshot_values,
        generated_at=NOW,
    )
    values = _Values()
    values.saved.extend(_values(profile.profile_id))
    monkeypatch.setattr(runtime_public, "get_active_runtime_profile", lambda _environment: profile)
    monkeypatch.setattr(runtime_public, "get_runtime_value_repository", lambda: values)
    monkeypatch.setattr(
        runtime_public,
        "get_latest_runtime_snapshot",
        lambda _profile_key: snapshot,
    )
    monkeypatch.setattr(
        runtime_public,
        "reconcile_runtime_definitions",
        lambda: pytest.fail("dry-run must not reconcile definitions"),
    )
    monkeypatch.setattr(
        runtime_public,
        "preview_runtime_profile",
        lambda _profile, _values: {
            "after_hash": "candidate-full-hash",
            "changed_keys": ("audit.mode",),
            "valid": True,
            "errors": (),
        },
    )

    preview = runtime_public.preview_runtime_profile_patch(
        environment="production",
        patch={"audit.mode": "on"},
        actor="aud05-test",
        reason="preview corrective successor",
        expected_active_profile_id=profile.profile_id,
        expected_active_profile_version=profile.version,
        expected_active_profile_hash=profile.content_hash,
        expected_active_snapshot_hash=snapshot.snapshot_hash,
    )

    assert preview["before_profile_id"] == profile.profile_id
    assert preview["before_profile_version"] == profile.version
    assert preview["after_profile_version"] == profile.version + 1


def test_snapshot_binding_rejects_payload_drift_with_same_header() -> None:
    expected = RuntimeConfigSnapshot(
        snapshot_id="bound-snapshot",
        profile_id="bound-profile",
        profile_key="production",
        profile_version=14,
        snapshot_hash=hash_public_runtime_projection({"audit.mode": "off"}),
        resolved_values={"audit.mode": "off"},
        generated_at=NOW,
    )
    actual = replace(expected, resolved_values={"audit.mode": "on"})

    assert _same_snapshot(actual, expected) is False


def test_hash_bound_execute_does_not_reconcile_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = replace(
        _profile(version=14),
        status=RuntimeProfileStatus.ACTIVE,
        content_hash="approved-full-hash",
        activated_at=NOW,
    )
    snapshot_values = {"audit.mode": "off"}
    snapshot = RuntimeConfigSnapshot(
        snapshot_id="approved-snapshot-execute",
        profile_id=profile.profile_id,
        profile_key=profile.profile_key,
        profile_version=profile.version,
        snapshot_hash=hash_public_runtime_projection(snapshot_values),
        resolved_values=snapshot_values,
        generated_at=NOW,
    )
    values = _Values()
    values.saved.extend(_values(profile.profile_id))
    captured: dict[str, object] = {}

    class _Service:
        def activate(self, candidate, candidate_values, **kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return candidate, snapshot

    monkeypatch.setattr(runtime_public, "get_active_runtime_profile", lambda _environment: profile)
    monkeypatch.setattr(runtime_public, "get_runtime_value_repository", lambda: values)
    monkeypatch.setattr(
        runtime_public,
        "get_latest_runtime_snapshot",
        lambda _profile_key: snapshot,
    )
    monkeypatch.setattr(runtime_public, "get_runtime_config_service", lambda: _Service())
    monkeypatch.setattr(
        runtime_public,
        "reconcile_runtime_definitions",
        lambda: pytest.fail("bound corrective execution must not reconcile definitions"),
    )

    candidate, returned_snapshot = runtime_public.activate_runtime_profile_patch(
        environment="production",
        patch={"audit.mode": "on"},
        actor="aud05-test",
        reason="bound corrective execution",
        expected_active_profile_id=profile.profile_id,
        expected_active_profile_version=profile.version,
        expected_active_profile_hash=profile.content_hash,
        expected_active_snapshot_hash=snapshot.snapshot_hash,
    )

    assert candidate.based_on_profile == profile.profile_id
    assert returned_snapshot is snapshot
    assert captured["expected_previous_snapshot"] is snapshot
    assert captured["legacy_correction"] == (
        profile.content_hash,
        snapshot.snapshot_hash,
    )


def test_corrective_command_dry_run_does_not_echo_secret_refs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    patch_file = tmp_path / "aud05-patch.json"
    secret_ref = "secret://provider/v17"
    patch_file.write_text(
        json.dumps(
            {
                "patch": {"audit.mode": "on"},
                "secret_ref_patch": {"provider.key": secret_ref},
            }
        ),
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    def _preview(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "after_profile_id": "candidate",
            "after_profile_version": 15,
            "secret_definition_keys": ("provider.key",),
            "valid": True,
            "errors": (),
        }

    monkeypatch.setattr(
        activate_runtime_profile_corrective,
        "preview_runtime_profile_patch",
        _preview,
    )
    command = activate_runtime_profile_corrective.Command()
    command.stdout = StringIO()
    command.handle(
        environment="production",
        patch_file=str(patch_file),
        actor="aud05-test",
        reason="dry-run",
        release_ref="",
        execute=False,
        expected_profile_id="",
        expected_profile_version=None,
        expected_profile_hash="",
        expected_snapshot_hash="",
    )

    output = command.stdout.getvalue()
    assert '"mode":"dry_run"' in output
    assert secret_ref not in output
    assert captured["secret_ref_patch"] == {"provider.key": secret_ref}


def test_corrective_command_requires_approved_hash_bindings() -> None:
    command = activate_runtime_profile_corrective.Command()
    command.stdout = StringIO()

    with pytest.raises(CommandError, match="approved predecessor bindings"):
        command.handle(
            environment="production",
            patch_file="missing.json",
            actor="aud05-test",
            reason="execute",
            release_ref="",
            execute=True,
            expected_profile_id="profile",
            expected_profile_version=14,
            expected_profile_hash="",
            expected_snapshot_hash=None,
        )


def test_corrective_activation_requires_exact_new_successor_and_rejects_in_place_or_v13() -> None:
    service, profiles, _values_repo, _revisions, _snapshots = _service()
    first = _profile(version=14)
    service.activate(
        first,
        _values(first.profile_id),
        actor="aud05-test",
        reason="seed v14",
    )

    with pytest.raises(ValueError, match="immutable"):
        service.activate(
            first,
            _values(first.profile_id, secret_ref="secret://provider/in-place"),
            actor="aud05-test",
            reason="attempt in-place v14 edit",
        )

    stale = _profile(version=13)
    with pytest.raises(ValueError, match="successor|predecessor"):
        service.activate(
            stale,
            _values(stale.profile_id, secret_ref="secret://provider/v13"),
            actor="aud05-test",
            reason="attempt superseded v13 fallback",
        )

    successor = _profile(version=15)
    successor = replace(successor, based_on_profile=first.profile_id)
    saved, _snapshot = service.activate(
        successor,
        _values(successor.profile_id, secret_ref="secret://provider/v17"),
        actor="aud05-test",
        reason="corrective successor",
    )
    assert saved.profile_id != first.profile_id
    assert saved.based_on_profile == first.profile_id
    assert saved.version == first.version + 1
    assert profiles.get_active("production") == saved


def test_hash_scope_correction_appends_successor_for_exact_legacy_snapshot() -> None:
    service, profiles, _values_repo, _revisions, snapshots = _service()
    first = _profile(version=14)
    saved_first, public_snapshot = service.activate(
        first,
        _values(first.profile_id),
        actor="aud05-test",
        reason="seed v14",
    )
    legacy_snapshot = replace(
        public_snapshot,
        snapshot_hash=hash_runtime_profile_values(
            {
                "audit.mode": "off",
                "provider.key": "secret://provider/v14",
            }
        ),
    )
    snapshots.saved[-1] = legacy_snapshot
    successor = replace(_profile(version=15), based_on_profile=saved_first.profile_id)
    successor_values = _values(successor.profile_id, secret_ref="secret://provider/v17")

    with pytest.raises(ValueError, match="snapshot is unavailable"):
        service.activate(
            successor,
            successor_values,
            actor="aud05-test",
            reason="reject unbound legacy correction",
        )

    repaired, repaired_snapshot = service.activate(
        successor,
        successor_values,
        actor="aud05-test",
        reason="append hash-scope correction",
        legacy_correction=(saved_first.content_hash, legacy_snapshot.snapshot_hash),
        expected_previous_snapshot=legacy_snapshot,
    )

    assert repaired.profile_id != saved_first.profile_id
    assert repaired.based_on_profile == saved_first.profile_id
    assert repaired_snapshot.snapshot_hash == hash_public_runtime_projection(
        repaired_snapshot.resolved_values
    )
    assert profiles.get_active("production") == repaired


def test_rollback_publishes_fresh_successor_profile_and_value_ids() -> None:
    service, profiles, values_repo, _revisions, _snapshots = _service()
    first = _profile(version=14)
    service.activate(
        first,
        _values(first.profile_id),
        actor="aud05-test",
        reason="seed v14",
    )
    rollback_source_values = _values("superseded-v13", secret_ref="secret://provider/v13")
    rollback_source = replace(
        _profile(profile_id="superseded-v13", version=13),
        status=RuntimeProfileStatus.SUPERSEDED,
        content_hash=hash_runtime_profile_values(
            {
                "audit.mode": "off",
                "provider.key": "secret://provider/v13",
            }
        ),
    )
    profiles.save(rollback_source)
    for value in rollback_source_values:
        values_repo.save(value)
    rolled_back, _snapshot = service.rollback(
        rollback_source,
        rollback_source_values,
        actor="aud05-test",
        reason="forward rollback successor",
    )

    assert rolled_back.profile_id not in {first.profile_id, rollback_source.profile_id}
    assert rolled_back.based_on_profile == first.profile_id
    assert rolled_back.version == 15
    assert values_repo.list_for_profile(rolled_back.profile_id)
    assert values_repo.list_for_profile(rollback_source.profile_id) == list(rollback_source_values)


def test_rollback_rejects_historical_source_scope_and_hash_drift() -> None:
    service, profiles, _values_repo, _revisions, _snapshots = _service()
    first = _profile(version=14)
    service.activate(
        first,
        _values(first.profile_id),
        actor="aud05-test",
        reason="seed v14",
    )
    source_hash = hash_runtime_profile_values(
        {
            "audit.mode": "off",
            "provider.key": "secret://provider/v13",
        }
    )
    wrong_scope = replace(
        _profile(profile_id="historical-source", version=13),
        profile_key="other-environment-profile",
        status=RuntimeProfileStatus.SUPERSEDED,
        content_hash=source_hash,
    )
    profiles.save(wrong_scope)
    with pytest.raises(ValueError, match="scope mismatch"):
        service.rollback(
            wrong_scope,
            _values(wrong_scope.profile_id, secret_ref="secret://provider/v13"),
            actor="aud05-test",
            reason="reject cross-scope rollback",
        )

    wrong_hash = replace(
        _profile(profile_id="historical-hash", version=13),
        status=RuntimeProfileStatus.SUPERSEDED,
        content_hash="f" * 64,
    )
    profiles.save(wrong_hash)
    with pytest.raises(ValueError, match="hash mismatch"):
        service.rollback(
            wrong_hash,
            _values(wrong_hash.profile_id, secret_ref="secret://provider/v13"),
            actor="aud05-test",
            reason="reject hash-drifted rollback",
        )
