from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

import pytest

from apps.audit.application.system_audit_authority_provider import (
    SystemAuditAuthorityBundleSelector,
)
from apps.config_center.domain.runtime_config import (
    RuntimeConfigProfile,
    RuntimeConfigSnapshot,
    RuntimeProfileStatus,
)
from core.integration import system_audit_runtime_config as runtime_config_module
from core.integration.system_audit_runtime_config import (
    SystemAuditRuntimeConfigBinding,
    SystemAuditRuntimeConfigurationUnavailable,
    load_system_audit_runtime_config,
)

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
SELECTOR: dict[str, object] = {
    "actor_source_id": "actor-source-41",
    "actor_source_version": "v3",
    "actor_content_hash": "a" * 64,
    "scope_source_id": "scope-authority-41",
    "scope_source_version": "v4",
    "scope_content_hash": "b" * 64,
}


def _values(
    *,
    mode: object = "shadow",
    outbox_enabled: object = True,
    selector: object = SELECTOR,
) -> dict[str, object]:
    return {
        "audit.system_event.mode": mode,
        "audit.system_event.outbox_enabled": outbox_enabled,
        "audit.system_event.authority_selector": selector,
        "unrelated.runtime.value": "preserved-in-snapshot-hash",
    }


def _profile(
    *,
    environment: str = "production",
    status: RuntimeProfileStatus = RuntimeProfileStatus.ACTIVE,
    profile_id: str = "profile-audit-production",
    profile_key: str = "audit-production",
    version: int = 7,
) -> RuntimeConfigProfile:
    return RuntimeConfigProfile(
        profile_id=profile_id,
        profile_key=profile_key,
        environment=environment,
        version=version,
        status=status,
        content_hash="active-profile-content",
        created_at=NOW,
        activated_at=NOW if status is RuntimeProfileStatus.ACTIVE else None,
    )


def _snapshot(
    profile: RuntimeConfigProfile,
    *,
    values: dict[str, object] | None = None,
    snapshot_id: str = "snapshot-audit-production-v7",
    profile_id: str | None = None,
    profile_key: str | None = None,
    profile_version: int | None = None,
    snapshot_hash: str | None = None,
) -> RuntimeConfigSnapshot:
    resolved = _values() if values is None else values
    return RuntimeConfigSnapshot(
        snapshot_id=snapshot_id,
        profile_id=profile.profile_id if profile_id is None else profile_id,
        profile_key=profile.profile_key if profile_key is None else profile_key,
        profile_version=profile.version if profile_version is None else profile_version,
        snapshot_hash=(
            RuntimeConfigSnapshot.hash_values(resolved) if snapshot_hash is None else snapshot_hash
        ),
        resolved_values=resolved,
        generated_at=NOW,
    )


def _install_lookups(
    monkeypatch: pytest.MonkeyPatch,
    *,
    profile: object,
    snapshot: object,
) -> tuple[list[str], list[str]]:
    profile_calls: list[str] = []
    snapshot_calls: list[str] = []

    def get_profile(environment: str) -> object:
        profile_calls.append(environment)
        return profile

    def get_snapshot(profile_key: str) -> object:
        snapshot_calls.append(profile_key)
        return snapshot

    monkeypatch.setattr(runtime_config_module, "get_active_runtime_profile", get_profile)
    monkeypatch.setattr(runtime_config_module, "get_latest_runtime_snapshot", get_snapshot)
    return profile_calls, snapshot_calls


def _assert_reason(reason_code: str, action: object) -> None:
    if not callable(action):
        raise TypeError("action must be callable")
    with pytest.raises(SystemAuditRuntimeConfigurationUnavailable) as error:
        action()
    assert error.value.reason_code == reason_code


def test_valid_binding_uses_one_snapshot_and_has_deterministic_issuer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = _profile()
    snapshot = _snapshot(profile)
    profile_calls, snapshot_calls = _install_lookups(
        monkeypatch,
        profile=profile,
        snapshot=snapshot,
    )

    first = load_system_audit_runtime_config(environment="production")
    second = load_system_audit_runtime_config(environment="production")

    assert profile_calls == ["production", "production"]
    assert snapshot_calls == [profile.profile_key, profile.profile_key]
    assert first == second
    assert first.mode == "shadow"
    assert first.outbox_enabled is True
    assert first.authority_selector == SystemAuditAuthorityBundleSelector(
        actor_source_id="actor-source-41",
        actor_source_version="v3",
        actor_content_hash="a" * 64,
        scope_source_id="scope-authority-41",
        scope_source_version="v4",
        scope_content_hash="b" * 64,
    )
    assert (
        first.snapshot_id,
        first.snapshot_hash,
        first.profile_id,
        first.profile_key,
        first.profile_version,
        first.environment,
    ) == (
        snapshot.snapshot_id,
        snapshot.snapshot_hash,
        profile.profile_id,
        profile.profile_key,
        profile.version,
        profile.environment,
    )
    assert first.issuer_id.startswith("audit-config:")
    assert len(first.issuer_id) == len("audit-config:") + 64


def test_missing_profile_stops_before_snapshot_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    profile_calls, snapshot_calls = _install_lookups(
        monkeypatch,
        profile=None,
        snapshot=object(),
    )

    _assert_reason(
        "profile_unavailable",
        lambda: load_system_audit_runtime_config(environment="production"),
    )

    assert profile_calls == ["production"]
    assert snapshot_calls == []


def test_missing_snapshot_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = _profile()
    _install_lookups(monkeypatch, profile=profile, snapshot=None)

    _assert_reason(
        "snapshot_unavailable",
        lambda: load_system_audit_runtime_config(environment="production"),
    )


@pytest.mark.parametrize("stage", ["profile", "snapshot"])
def test_repository_exception_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    profile = _profile()

    def broken_profile(environment: str) -> RuntimeConfigProfile:
        del environment
        raise RuntimeError("postgres://audit:secret@example.test/audit")

    def broken_snapshot(profile_key: str) -> RuntimeConfigSnapshot:
        del profile_key
        raise RuntimeError("postgres://audit:secret@example.test/audit")

    monkeypatch.setattr(
        runtime_config_module,
        "get_active_runtime_profile",
        broken_profile if stage == "profile" else lambda environment: profile,
    )
    monkeypatch.setattr(
        runtime_config_module,
        "get_latest_runtime_snapshot",
        broken_snapshot,
    )

    _assert_reason(
        "runtime_configuration_unavailable",
        lambda: load_system_audit_runtime_config(environment="production"),
    )


@pytest.mark.parametrize("stage", ["profile", "snapshot"])
def test_profile_or_snapshot_type_substitution_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    profile = _profile()
    snapshot = _snapshot(profile)
    _install_lookups(
        monkeypatch,
        profile=object() if stage == "profile" else profile,
        snapshot=object() if stage == "snapshot" else snapshot,
    )

    _assert_reason(
        f"{stage}_unavailable",
        lambda: load_system_audit_runtime_config(environment="production"),
    )


@pytest.mark.parametrize(
    "profile",
    [
        _profile(status=RuntimeProfileStatus.DRAFT),
        _profile(environment="development"),
    ],
)
def test_nonactive_or_wrong_environment_profile_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    profile: RuntimeConfigProfile,
) -> None:
    _, snapshot_calls = _install_lookups(
        monkeypatch,
        profile=profile,
        snapshot=_snapshot(profile),
    )

    _assert_reason(
        "profile_unavailable",
        lambda: load_system_audit_runtime_config(environment="production"),
    )

    assert snapshot_calls == []


@pytest.mark.parametrize(
    ("snapshot_changes", "expected_reason"),
    [
        ({"profile_id": "other-profile"}, "snapshot_profile_mismatch"),
        ({"profile_key": "other-key"}, "snapshot_profile_mismatch"),
        ({"profile_version": 6}, "snapshot_profile_mismatch"),
        ({"snapshot_hash": "not-a-sha256"}, "snapshot_hash_invalid"),
        ({"snapshot_hash": "0" * 64}, "snapshot_hash_mismatch"),
    ],
)
def test_snapshot_identity_and_content_hash_are_exact(
    monkeypatch: pytest.MonkeyPatch,
    snapshot_changes: dict[str, object],
    expected_reason: str,
) -> None:
    profile = _profile()
    snapshot = _snapshot(
        profile,
        profile_id=cast(str | None, snapshot_changes.get("profile_id")),
        profile_key=cast(str | None, snapshot_changes.get("profile_key")),
        profile_version=cast(int | None, snapshot_changes.get("profile_version")),
        snapshot_hash=cast(str | None, snapshot_changes.get("snapshot_hash")),
    )
    _install_lookups(monkeypatch, profile=profile, snapshot=snapshot)

    _assert_reason(
        expected_reason,
        lambda: load_system_audit_runtime_config(environment="production"),
    )


@pytest.mark.parametrize(
    ("values", "expected_reason"),
    [
        (_values(mode="unknown"), "mode_invalid"),
        (_values(mode=1), "mode_invalid"),
        (_values(outbox_enabled=1), "outbox_enabled_invalid"),
        (_values(selector=[]), "authority_selector_invalid"),
        (
            _values(
                selector={
                    key: value for key, value in SELECTOR.items() if key != "scope_content_hash"
                }
            ),
            "authority_selector_invalid",
        ),
        (
            _values(selector={**SELECTOR, "unexpected": "value"}),
            "authority_selector_invalid",
        ),
        (_values(selector={1: "value"}), "authority_selector_invalid"),
        (
            _values(selector={**SELECTOR, "actor_source_id": 41}),
            "authority_selector_invalid",
        ),
        (
            _values(selector={**SELECTOR, "actor_content_hash": "bad-hash"}),
            "authority_selector_invalid",
        ),
    ],
)
def test_invalid_policy_or_selector_value_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    values: dict[str, object],
    expected_reason: str,
) -> None:
    profile = _profile()
    _install_lookups(monkeypatch, profile=profile, snapshot=_snapshot(profile, values=values))

    _assert_reason(
        expected_reason,
        lambda: load_system_audit_runtime_config(environment="production"),
    )


@pytest.mark.parametrize(
    "environment",
    ["", " production", "production ", "bad environment", "a" * 65, cast(str, 42)],
)
def test_invalid_environment_fails_before_lookup(
    monkeypatch: pytest.MonkeyPatch,
    environment: str,
) -> None:
    called = False

    def unexpected_lookup(value: str) -> None:
        nonlocal called
        del value
        called = True

    monkeypatch.setattr(runtime_config_module, "get_active_runtime_profile", unexpected_lookup)

    _assert_reason(
        "environment_invalid",
        lambda: load_system_audit_runtime_config(environment=environment),
    )

    assert called is False


def test_binding_revalidates_its_immutable_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = _profile()
    _install_lookups(monkeypatch, profile=profile, snapshot=_snapshot(profile))
    binding = load_system_audit_runtime_config(environment="production")

    with pytest.raises(ValueError, match="mode"):
        replace(binding, mode=cast(str, 1))
    with pytest.raises(ValueError, match="environment"):
        replace(binding, environment="bad environment")
    with pytest.raises(TypeError, match="selector"):
        replace(
            binding,
            authority_selector=cast(SystemAuditAuthorityBundleSelector, object()),
        )

    assert isinstance(binding, SystemAuditRuntimeConfigBinding)
