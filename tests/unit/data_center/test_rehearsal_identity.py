"""Provider rehearsal identity is derived from live non-secret configuration."""

import pytest

from apps.data_center.infrastructure import rehearsal_identity as identity
from apps.data_center.infrastructure.models import ProviderConfigModel
from apps.data_center.infrastructure.rehearsal_identity import RehearsalProviderIdentity


@pytest.mark.django_db
def test_configured_identity_binds_version_and_hashed_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ProviderConfigModel.objects.create(
        name="rehearsal-tushare",
        source_type="tushare",
        is_active=True,
        priority=1,
        http_url="http://relay.example:8020/",
        extra_config={"tushare_request_mode": "sdk_path"},
    )
    monkeypatch.setattr(identity.importlib.metadata, "version", lambda _name: "1.4.25")

    actual = identity.configured_rehearsal_identity(provider_id=provider.pk, role="quote")

    assert actual.version.startswith("tushare-1.4.25-cfg-")
    assert actual.endpoint_id.startswith("provider-config-")
    assert "relay.example" not in actual.endpoint_id


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("api_endpoint", "https://api-next.example/v2"),
        ("name", "renamed-provider"),
        ("priority", 9),
    ],
)
def test_runtime_config_change_rejects_frozen_identity(
    monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    provider = ProviderConfigModel.objects.create(
        name="frozen-tushare",
        source_type="tushare",
        is_active=True,
        priority=1,
        http_url="http://relay.example:8020/",
        api_endpoint="https://api.example/v1",
        extra_config={"tushare_request_mode": "sdk_path"},
    )
    monkeypatch.setattr(identity.importlib.metadata, "version", lambda _name: "1.4.25")
    frozen = (
        identity.configured_rehearsal_identity(provider_id=provider.pk, role="quote"),
        identity.configured_rehearsal_identity(provider_id=provider.pk, role="valuation"),
    )
    setattr(provider, field, value)
    provider.save(update_fields=[field])

    with pytest.raises(ValueError, match="REHEARSAL_PROVIDER_IDENTITY_MISMATCH"):
        identity.verify_configured_rehearsal_identities(frozen)


@pytest.mark.django_db
def test_request_mode_change_rejects_frozen_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ProviderConfigModel.objects.create(
        name="mode-tushare",
        source_type="tushare",
        is_active=True,
        priority=1,
        http_url="http://relay.example:8020/",
        extra_config={"tushare_request_mode": "sdk_path"},
    )
    monkeypatch.setattr(identity.importlib.metadata, "version", lambda _name: "1.4.25")
    frozen = (
        identity.configured_rehearsal_identity(provider_id=provider.pk, role="quote"),
        identity.configured_rehearsal_identity(provider_id=provider.pk, role="valuation"),
    )
    provider.extra_config = {"tushare_request_mode": "unified_relay"}
    provider.save(update_fields=["extra_config"])

    with pytest.raises(ValueError, match="REHEARSAL_PROVIDER_IDENTITY_MISMATCH"):
        identity.verify_configured_rehearsal_identities(frozen)


@pytest.mark.parametrize("field", ["version", "endpoint_id"])
def test_supplied_stale_identity_is_rejected(monkeypatch: pytest.MonkeyPatch, field: str) -> None:
    canonical = RehearsalProviderIdentity("quote", 2, "tushare", "v1", "endpoint-v1")
    other = RehearsalProviderIdentity("valuation", 2, "tushare", "v1", "endpoint-v1")
    monkeypatch.setattr(
        identity,
        "configured_rehearsal_identity",
        lambda **kwargs: canonical if kwargs["role"] == "quote" else other,
    )
    changed = {
        **canonical.__dict__,
        field: "stale-version" if field == "version" else "stale-endpoint",
    }
    supplied = (RehearsalProviderIdentity(**changed), other)

    with pytest.raises(ValueError, match="REHEARSAL_PROVIDER_IDENTITY_MISMATCH"):
        identity.verify_configured_rehearsal_identities(supplied)


def test_runner_level_recheck_detects_config_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    supplied = (
        RehearsalProviderIdentity("quote", 2, "tushare", "v1", "endpoint-v1"),
        RehearsalProviderIdentity("valuation", 2, "tushare", "v1", "endpoint-v1"),
    )

    def changing(*, provider_id: int, role: str) -> RehearsalProviderIdentity:
        nonlocal calls
        calls += 1
        selected = next(item for item in supplied if item.role == role)
        if calls > 2 and role == "quote":
            return RehearsalProviderIdentity(role, provider_id, "tushare", "v2", "endpoint-v2")
        return selected

    monkeypatch.setattr(identity, "configured_rehearsal_identity", changing)

    assert identity.verify_configured_rehearsal_identities(supplied) == supplied
    with pytest.raises(ValueError, match="REHEARSAL_PROVIDER_IDENTITY_MISMATCH"):
        identity.verify_configured_rehearsal_identities(supplied)
