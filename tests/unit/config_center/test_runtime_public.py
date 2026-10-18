from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

import pytest

from apps.config_center.application import runtime_public
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

NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


def _profile(*, version: int = 1) -> RuntimeConfigProfile:
    return RuntimeConfigProfile(
        profile_id="profile-1",
        profile_key="data-center-development",
        environment="development",
        version=version,
        status=RuntimeProfileStatus.ACTIVE,
        content_hash="profile-hash",
        created_at=NOW,
        activated_at=NOW,
    )


def _snapshot(*, profile_id: str = "profile-1", version: int = 1) -> RuntimeConfigSnapshot:
    resolved_values = {"data_center.provider.failover_tolerance": 0.025}
    return RuntimeConfigSnapshot(
        snapshot_id="snapshot-1",
        profile_id=profile_id,
        profile_key="data-center-development",
        profile_version=version,
        snapshot_hash=hash_public_runtime_projection(resolved_values),
        resolved_values=resolved_values,
        generated_at=NOW,
    )


def _public_definition_repository() -> object:
    """Provide the definition seam required for public snapshot verification."""

    definition = RuntimeConfigDefinition(
        key="data_center.provider.failover_tolerance",
        namespace="data_center",
        owner_app="data_center",
        value_type=RuntimeValueType.PERCENTAGE,
    )

    class _Repository:
        def list_all(self) -> list[RuntimeConfigDefinition]:
            return [definition]

    return _Repository()


def test_active_runtime_value_requires_profile_snapshot_identity_match(monkeypatch) -> None:
    profile = _profile(version=2)
    snapshot = _snapshot(version=2)
    monkeypatch.setattr(runtime_public, "get_active_runtime_profile", lambda _environment: profile)
    monkeypatch.setattr(
        runtime_public,
        "get_runtime_definition_repository",
        _public_definition_repository,
    )
    monkeypatch.setattr(
        runtime_public,
        "get_latest_runtime_snapshot",
        lambda _profile_key: snapshot,
    )

    assert (
        runtime_public.get_active_runtime_value(
            environment="development",
            definition_key="data_center.provider.failover_tolerance",
        )
        == 0.025
    )


@pytest.mark.parametrize(
    ("snapshot_profile_id", "snapshot_version"),
    [("other-profile", 2), ("profile-1", 1)],
)
def test_active_runtime_value_fails_closed_for_stale_snapshot(
    monkeypatch,
    snapshot_profile_id: str,
    snapshot_version: int,
) -> None:
    profile = _profile(version=2)
    snapshot = _snapshot(profile_id=snapshot_profile_id, version=snapshot_version)
    monkeypatch.setattr(runtime_public, "get_active_runtime_profile", lambda _environment: profile)
    monkeypatch.setattr(
        runtime_public,
        "get_runtime_definition_repository",
        _public_definition_repository,
    )
    monkeypatch.setattr(
        runtime_public,
        "get_latest_runtime_snapshot",
        lambda _profile_key: snapshot,
    )

    assert (
        runtime_public.get_active_runtime_value(
            environment="development",
            definition_key="data_center.provider.failover_tolerance",
        )
        is None
    )


def test_active_runtime_value_rejects_blank_lookup_keys(monkeypatch) -> None:
    called = False

    def _unexpected_lookup(_environment: str) -> RuntimeConfigProfile:
        nonlocal called
        called = True
        return _profile()

    monkeypatch.setattr(runtime_public, "get_active_runtime_profile", _unexpected_lookup)

    assert runtime_public.get_active_runtime_value(environment="", definition_key="key") is None
    assert (
        runtime_public.get_active_runtime_value(environment="development", definition_key="")
        is None
    )
    assert called is False


def test_active_qlib_runtime_config_requires_complete_typed_snapshot(monkeypatch, tmp_path) -> None:
    provider_path = tmp_path / "cn_data"
    provider_path.mkdir()
    values = {
        "alpha.qlib.enabled": True,
        "alpha.qlib.provider_uri": str(provider_path),
        "alpha.qlib.region": "CN",
        "alpha.qlib.model_path": str(tmp_path / "models"),
        "alpha.qlib.default_universe": "csi300",
        "alpha.qlib.default_feature_set_id": "v1",
        "alpha.qlib.default_label_id": "return_5d",
        "alpha.qlib.train_queue_name": "qlib_train",
        "alpha.qlib.infer_queue_name": "qlib_infer",
        "alpha.qlib.allow_auto_activate": False,
    }
    monkeypatch.setattr(
        runtime_public,
        "get_active_runtime_value",
        lambda *, environment, definition_key: (
            values.get(definition_key) if environment == "development" else None
        ),
    )

    result = runtime_public.get_active_qlib_runtime_config("development")

    assert result is not None
    assert result["provider_uri"] == str(provider_path)
    assert result["is_configured"] is True


def test_active_domain_runtime_config_requires_complete_typed_snapshot(monkeypatch) -> None:
    values: dict[str, object] = {
        "alpha.runtime.fixed_provider": "",
        "alpha.runtime.pool_mode": "strict_valuation",
        "config_center.market.color_convention": "cn_a_share",
        "config_center.market.benchmark_code_map": {"equity_default_index": "000300.SH"},
        "config_center.market.asset_proxy_code_map": {"A_SHARE_GROWTH": "000300.SH"},
    }
    monkeypatch.setattr(
        runtime_public,
        "get_active_runtime_value",
        lambda *, environment, definition_key: (
            values.get(definition_key) if environment == "development" else None
        ),
    )

    result = runtime_public.get_active_domain_runtime_config("development")

    assert result == {
        "alpha_fixed_provider": "",
        "alpha_pool_mode": "strict_valuation",
        "market_color_convention": "cn_a_share",
        "benchmark_code_map": {"equity_default_index": "000300.SH"},
        "asset_proxy_code_map": {"A_SHARE_GROWTH": "000300.SH"},
    }

    values.pop("config_center.market.asset_proxy_code_map")
    assert runtime_public.get_active_domain_runtime_config("development") is None


def test_active_alpha_and_market_runtime_projections_are_independently_complete(
    monkeypatch,
) -> None:
    """A missing market key must not erase a complete canonical Alpha profile."""

    values: dict[str, object] = {
        "alpha.runtime.fixed_provider": "qlib",
        "alpha.runtime.pool_mode": "market",
        "config_center.market.color_convention": "us_market",
        "config_center.market.benchmark_code_map": {"equity": "000300.SH"},
        "config_center.market.asset_proxy_code_map": {"growth": "510300.SH"},
    }
    monkeypatch.setattr(
        runtime_public,
        "get_active_runtime_value",
        lambda *, environment, definition_key: (
            values.get(definition_key) if environment == "development" else None
        ),
    )

    assert runtime_public.get_active_alpha_runtime_config("development") == {
        "alpha_fixed_provider": "qlib",
        "alpha_pool_mode": "market",
    }
    assert runtime_public.get_active_market_runtime_config("development") == {
        "market_color_convention": "us_market",
        "benchmark_code_map": {"equity": "000300.SH"},
        "asset_proxy_code_map": {"growth": "510300.SH"},
    }

    values.pop("config_center.market.asset_proxy_code_map")
    assert runtime_public.get_active_alpha_runtime_config("development") == {
        "alpha_fixed_provider": "qlib",
        "alpha_pool_mode": "market",
    }
    assert runtime_public.get_active_market_runtime_config("development") is None
    assert runtime_public.get_active_domain_runtime_config("development") is None


def test_active_backup_delivery_config_requires_policy_and_secret_refs(monkeypatch) -> None:
    values: dict[str, object] = {
        "backup.enabled": True,
        "backup.recipient_email": "owner@example.test",
        "backup.app_base_url": "https://example.test",
        "backup.mail_from_email": "noreply@example.test",
        "backup.smtp_host": "smtp.example.test",
        "backup.smtp_port": 587,
        "backup.smtp_username": "mailer",
        "backup.smtp_use_tls": True,
        "backup.smtp_use_ssl": False,
        "backup.interval_days": 7,
        "backup.link_ttl_days": 2,
        "backup.password_hint": "vault-a",
        "backup.archive_password": "config_center.backup.archive_password",
        "backup.smtp_password": "config_center.backup.smtp_password",
    }
    monkeypatch.setattr(
        runtime_public,
        "get_active_runtime_value",
        lambda *, environment, definition_key: (
            values.get(definition_key) if environment == "development" else None
        ),
    )

    result = runtime_public.get_active_backup_delivery_config("development")

    assert result is not None
    assert result["backup_smtp_port"] == 587
    assert result["backup_archive_password_ref"] == "config_center.backup.archive_password"

    values.pop("backup.smtp_password")
    assert runtime_public.get_active_backup_delivery_config("development") is None


@pytest.mark.parametrize(
    "missing_key",
    ["alpha.qlib.provider_uri", "alpha.qlib.allow_auto_activate"],
)
def test_active_qlib_runtime_config_fails_closed_for_partial_or_wrong_snapshot(
    monkeypatch,
    missing_key: str,
) -> None:
    values: dict[str, object] = {
        "alpha.qlib.enabled": True,
        "alpha.qlib.provider_uri": "/missing/provider",
        "alpha.qlib.region": "CN",
        "alpha.qlib.model_path": "/missing/models",
        "alpha.qlib.default_universe": "csi300",
        "alpha.qlib.default_feature_set_id": "v1",
        "alpha.qlib.default_label_id": "return_5d",
        "alpha.qlib.train_queue_name": "qlib_train",
        "alpha.qlib.infer_queue_name": "qlib_infer",
        "alpha.qlib.allow_auto_activate": False,
    }
    values.pop(missing_key)
    if missing_key == "alpha.qlib.allow_auto_activate":
        values[missing_key] = "false"
    monkeypatch.setattr(
        runtime_public,
        "get_active_runtime_value",
        lambda *, environment, definition_key: values.get(definition_key),
    )

    assert runtime_public.get_active_qlib_runtime_config("development") is None


_TIMEZONE_DEFINITION_KEY = "config_center.market.exchange_timezone_map"
_NO_AS_OF = object()


def _timezone_runtime_records():
    values = (
        RuntimeConfigValue(
            profile_id="timezone-profile",
            definition_key=_TIMEZONE_DEFINITION_KEY,
            value_json={"SSE": "Etc/UTC"},
        ),
    )
    resolved_values = {value.definition_key: value.value_json for value in values}
    profile = RuntimeConfigProfile(
        profile_id="timezone-profile",
        profile_key="data-center-development",
        environment="development",
        version=3,
        status=RuntimeProfileStatus.ACTIVE,
        content_hash=hash_runtime_profile_values(resolved_values),
        created_at=NOW,
        activated_at=NOW,
    )
    snapshot = RuntimeConfigSnapshot(
        snapshot_id="timezone-snapshot",
        profile_id=profile.profile_id,
        profile_key=profile.profile_key,
        profile_version=profile.version,
        snapshot_hash=hash_public_runtime_projection(resolved_values),
        resolved_values=resolved_values,
        generated_at=NOW,
        effective_from=NOW,
    )
    return profile, snapshot, values


def _install_timezone_runtime(monkeypatch, profile, snapshot, values=None):
    selected_values = values
    if selected_values is None:
        _, _, selected_values = _timezone_runtime_records()
    profile_reads: list[str] = []
    snapshot_reads: list[str] = []
    value_reads: list[str] = []

    definition = RuntimeConfigDefinition(
        key=_TIMEZONE_DEFINITION_KEY,
        namespace="config_center",
        owner_app="config_center",
        value_type=RuntimeValueType.TYPED_JSON,
    )

    class _DefinitionRepository:
        def list_all(self) -> list[RuntimeConfigDefinition]:
            return [definition]

    class _ValueRepository:
        def list_for_profile(self, profile_id: str) -> list[RuntimeConfigValue]:
            value_reads.append(profile_id)
            return [value for value in selected_values if value.profile_id == profile_id]

    def _active_profile(environment: str) -> RuntimeConfigProfile:
        profile_reads.append(environment)
        return profile

    def _latest_snapshot(profile_key: str) -> RuntimeConfigSnapshot:
        snapshot_reads.append(profile_key)
        return snapshot

    monkeypatch.setattr(runtime_public, "get_active_runtime_profile", _active_profile)
    monkeypatch.setattr(
        runtime_public,
        "get_latest_runtime_snapshot",
        _latest_snapshot,
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
    return profile_reads, snapshot_reads, value_reads


def _read_timezone_value(*, as_of: object = _NO_AS_OF) -> object | None:
    getter = runtime_public.get_active_runtime_value
    parameters = inspect.signature(getter).parameters
    assert "as_of" in parameters, "feature missing: runtime cutoff keyword"
    assert parameters["as_of"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["as_of"].default is None
    if as_of is _NO_AS_OF:
        return getter(
            environment="development",
            definition_key=_TIMEZONE_DEFINITION_KEY,
        )
    assert as_of is None or isinstance(as_of, datetime)
    return getter(
        environment="development",
        definition_key=_TIMEZONE_DEFINITION_KEY,
        as_of=as_of,
    )


def test_timezone_runtime_value_is_available_at_exact_activation_cutoff(monkeypatch) -> None:
    profile, snapshot, values = _timezone_runtime_records()
    reads = _install_timezone_runtime(monkeypatch, profile, snapshot, values)

    assert _read_timezone_value(as_of=NOW) == {"SSE": "Etc/UTC"}
    assert reads == (
        ["development"],
        [profile.profile_key],
        [profile.profile_id],
    )


@pytest.mark.parametrize(
    ("field_owner", "field_name", "replacement"),
    [
        ("profile", "activated_at", None),
        ("profile", "activated_at", NOW.replace(tzinfo=None)),
        ("snapshot", "generated_at", NOW.replace(tzinfo=None)),
        ("snapshot", "generated_at", None),
        ("snapshot", "effective_from", None),
        ("snapshot", "effective_from", NOW.replace(tzinfo=None)),
    ],
)
def test_timezone_runtime_value_fails_closed_for_missing_or_naive_clocks(
    monkeypatch,
    field_owner: str,
    field_name: str,
    replacement: object,
) -> None:
    profile, snapshot, values = _timezone_runtime_records()
    target = profile if field_owner == "profile" else snapshot
    object.__setattr__(target, field_name, replacement)
    _install_timezone_runtime(monkeypatch, profile, snapshot, values)

    assert _read_timezone_value(as_of=NOW) is None


@pytest.mark.parametrize("future_clock", ["activated_at", "generated_at", "effective_from"])
def test_timezone_runtime_value_rejects_current_profile_newer_than_cutoff(
    monkeypatch,
    future_clock: str,
) -> None:
    profile, snapshot, values = _timezone_runtime_records()
    future = NOW + timedelta(microseconds=1)
    if future_clock == "activated_at":
        object.__setattr__(profile, "activated_at", future)
        object.__setattr__(snapshot, "effective_from", future)
    elif future_clock == "generated_at":
        object.__setattr__(snapshot, "generated_at", future)
    else:
        object.__setattr__(profile, "activated_at", future)
        object.__setattr__(snapshot, "effective_from", future)
    reads = _install_timezone_runtime(monkeypatch, profile, snapshot, values)

    assert _read_timezone_value(as_of=NOW) is None
    assert reads[0] == ["development"]
    assert reads[1] == [profile.profile_key]
    assert reads[2] == [profile.profile_id]


@pytest.mark.parametrize(
    ("field_owner", "field_name", "replacement"),
    [
        ("profile", "status", RuntimeProfileStatus.SUPERSEDED),
        ("profile", "environment", "production"),
        ("profile", "content_hash", "0" * 64),
        ("snapshot", "profile_id", "another-profile"),
        ("snapshot", "profile_key", "another-profile-key"),
        ("snapshot", "profile_version", 2),
        ("snapshot", "snapshot_hash", "0" * 64),
        ("snapshot", "effective_from", NOW + timedelta(microseconds=1)),
        ("snapshot", "effective_from", NOW - timedelta(microseconds=1)),
    ],
)
def test_timezone_runtime_value_fails_closed_for_identity_hash_or_clock_mismatch(
    monkeypatch,
    field_owner: str,
    field_name: str,
    replacement: object,
) -> None:
    profile, snapshot, values = _timezone_runtime_records()
    target = profile if field_owner == "profile" else snapshot
    object.__setattr__(target, field_name, replacement)
    _install_timezone_runtime(monkeypatch, profile, snapshot, values)

    assert _read_timezone_value(as_of=NOW) is None


def test_timezone_runtime_value_rejects_tampered_full_profile_values(monkeypatch) -> None:
    profile, snapshot, values = _timezone_runtime_records()
    tampered_values = (
        RuntimeConfigValue(
            profile_id=profile.profile_id,
            definition_key=_TIMEZONE_DEFINITION_KEY,
            value_json={"SSE": "Asia/Shanghai"},
        ),
    )
    _install_timezone_runtime(monkeypatch, profile, snapshot, tampered_values)

    assert _read_timezone_value(as_of=NOW) is None


def test_timezone_runtime_value_rejects_snapshot_with_valid_hash_but_profile_value_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject a self-consistent snapshot that disagrees with persisted profile values."""

    profile, snapshot, values = _timezone_runtime_records()
    tampered_snapshot_values = {_TIMEZONE_DEFINITION_KEY: {"SSE": "Asia/Shanghai"}}
    object.__setattr__(snapshot, "resolved_values", tampered_snapshot_values)
    object.__setattr__(
        snapshot,
        "snapshot_hash",
        hash_public_runtime_projection(tampered_snapshot_values),
    )
    _install_timezone_runtime(monkeypatch, profile, snapshot, values)

    assert _read_timezone_value(as_of=NOW) is None


@pytest.mark.parametrize(
    "created_at",
    [None, NOW.replace(tzinfo=None), NOW + timedelta(microseconds=1)],
)
def test_timezone_runtime_value_rejects_missing_naive_or_future_profile_creation(
    monkeypatch: pytest.MonkeyPatch,
    created_at: object,
) -> None:
    """A profile not yet created by the cutoff cannot supply a runtime value."""

    profile, snapshot, values = _timezone_runtime_records()
    object.__setattr__(profile, "created_at", created_at)
    _install_timezone_runtime(monkeypatch, profile, snapshot, values)

    assert _read_timezone_value(as_of=NOW) is None


def test_timezone_runtime_value_rejects_naive_cutoff(monkeypatch) -> None:
    profile, snapshot, values = _timezone_runtime_records()
    _install_timezone_runtime(monkeypatch, profile, snapshot, values)

    assert _read_timezone_value(as_of=NOW.replace(tzinfo=None)) is None


def test_legacy_runtime_getter_and_explicit_none_keep_current_semantics(monkeypatch) -> None:
    profile, snapshot, values = _timezone_runtime_records()
    _install_timezone_runtime(monkeypatch, profile, snapshot, values)

    without_cutoff = _read_timezone_value()
    with_none = _read_timezone_value(as_of=None)

    assert without_cutoff == with_none == {"SSE": "Etc/UTC"}


def test_existing_market_projection_does_not_require_timezone_map(monkeypatch) -> None:
    values: dict[str, object] = {
        "config_center.market.color_convention": "cn_a_share",
        "config_center.market.benchmark_code_map": {"equity_default_index": "000300.SH"},
        "config_center.market.asset_proxy_code_map": {"A_SHARE_GROWTH": "000300.SH"},
    }
    monkeypatch.setattr(
        runtime_public,
        "get_active_runtime_value",
        lambda *, environment, definition_key: (
            values.get(definition_key) if environment == "development" else None
        ),
    )

    assert runtime_public.get_active_market_runtime_config("development") == {
        "market_color_convention": "cn_a_share",
        "benchmark_code_map": {"equity_default_index": "000300.SH"},
        "asset_proxy_code_map": {"A_SHARE_GROWTH": "000300.SH"},
    }


def test_timezone_runtime_value_blocks_when_optional_map_is_absent(monkeypatch) -> None:
    empty_values: dict[str, object] = {}
    profile = RuntimeConfigProfile(
        profile_id="timezone-profile",
        profile_key="data-center-development",
        environment="development",
        version=3,
        status=RuntimeProfileStatus.ACTIVE,
        content_hash=hash_runtime_profile_values(empty_values),
        created_at=NOW,
        activated_at=NOW,
    )
    snapshot = RuntimeConfigSnapshot(
        snapshot_id="timezone-snapshot",
        profile_id=profile.profile_id,
        profile_key=profile.profile_key,
        profile_version=profile.version,
        snapshot_hash=hash_public_runtime_projection(empty_values),
        resolved_values=empty_values,
        generated_at=NOW,
        effective_from=NOW,
    )
    _install_timezone_runtime(monkeypatch, profile, snapshot, values=())

    assert _read_timezone_value(as_of=NOW) is None
