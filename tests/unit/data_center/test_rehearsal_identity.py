"""Provider rehearsal identity is derived from live non-secret configuration."""

import pytest

from apps.data_center.infrastructure import rehearsal_identity as identity
from apps.data_center.infrastructure.financial_source_time_matchers import (
    akshare_notice_date_match_contract,
)
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
def test_akshare_valuation_identity_binds_actual_tencent_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ProviderConfigModel.objects.create(
        name="rehearsal-akshare",
        source_type="akshare",
        is_active=True,
        priority=2,
    )
    monkeypatch.setattr(identity.importlib.metadata, "version", lambda name: f"{name}-test")

    actual = identity.configured_rehearsal_identity(
        provider_id=provider.pk,
        role="valuation",
    )

    assert actual.source == "tencent"
    assert actual.version.startswith("tencent-quote-batch-v1-requests-")
    assert identity.rehearsal_identity_matches_adapter_source(
        actual,
        adapter_source="akshare",
    )
    with pytest.raises(ValueError, match="REHEARSAL_PROVIDER_IDENTITY_MISMATCH"):
        identity.configured_rehearsal_identity(provider_id=provider.pk, role="quote")


@pytest.mark.django_db
def test_akshare_financial_route_identity_binds_provider_and_notice_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The financial API route has its own frozen identity, separate from Tencent."""

    core_provider = ProviderConfigModel.objects.create(
        name="rehearsal-core-tushare",
        source_type="tushare",
        is_active=True,
        priority=1,
    )
    provider = ProviderConfigModel.objects.create(
        name="rehearsal-akshare-financial",
        source_type="akshare",
        is_active=True,
        priority=2,
        api_endpoint="https://financial.example/v1",
    )
    monkeypatch.setattr(identity.importlib.metadata, "version", lambda _name: "2.32.5")
    role = identity.akshare_financial_route_role(provider.pk)

    actual = identity.configured_akshare_financial_identity(provider_id=provider.pk)
    parsed = identity.parse_rehearsal_identities(
        [
            identity.configured_rehearsal_identity(
                provider_id=core_provider.pk,
                role="quote",
            ).__dict__,
            identity.configured_rehearsal_identity(
                provider_id=core_provider.pk,
                role="valuation",
            ).__dict__,
            actual.__dict__,
        ]
    )

    assert actual.role == role
    assert actual.source == "akshare_financial"
    contract = akshare_notice_date_match_contract()
    assert actual.version == (
        "akshare-financial-v1-requests-2.32.5-contract-" f"{contract.contract_sha256[:12]}"
    )
    assert actual.endpoint_id.startswith("akshare-financial-")
    assert identity.rehearsal_identity_matches_adapter_source(
        actual,
        adapter_source="akshare_financial",
    )
    assert not identity.rehearsal_identity_matches_adapter_source(
        actual,
        adapter_source="akshare",
    )
    assert identity.verify_configured_rehearsal_identities(parsed) == parsed

    provider.priority = 7
    provider.save(update_fields=["priority"])
    with pytest.raises(ValueError, match="REHEARSAL_PROVIDER_IDENTITY_MISMATCH"):
        identity.verify_configured_rehearsal_identities(parsed)


@pytest.mark.django_db
def test_frozen_identities_include_adaptive_model_market_failover_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = ProviderConfigModel.objects.create(
        name="primary-tushare",
        source_type="tushare",
        is_active=True,
        priority=1,
    )
    failover = ProviderConfigModel.objects.create(
        name="failover-akshare",
        source_type="akshare",
        is_active=True,
        priority=10,
    )
    monkeypatch.setattr(identity.importlib.metadata, "version", lambda name: f"{name}-test")
    route_role = identity.model_market_route_role(failover.pk)
    frozen = (
        identity.configured_rehearsal_identity(provider_id=primary.pk, role="quote"),
        identity.configured_rehearsal_identity(provider_id=primary.pk, role="valuation"),
        identity.configured_rehearsal_identity(provider_id=failover.pk, role=route_role),
    )

    assert identity.parse_rehearsal_identities([item.__dict__ for item in frozen]) == frozen
    assert frozen[2].source == "tencent"
    assert identity.rehearsal_identity_matches_adapter_source(frozen[2], adapter_source="akshare")
    assert identity.verify_configured_rehearsal_identities(frozen) == frozen


def test_route_identity_role_must_bind_its_provider_id() -> None:
    values = [
        RehearsalProviderIdentity("quote", 2, "tushare", "v1", "endpoint-v1").__dict__,
        RehearsalProviderIdentity("valuation", 2, "tushare", "v1", "endpoint-v1").__dict__,
        RehearsalProviderIdentity(
            "model_market_route:99", 3, "tencent", "v1", "endpoint-v2"
        ).__dict__,
    ]

    with pytest.raises(ValueError, match="REHEARSAL_PROVIDER_IDENTITY_INVALID"):
        identity.parse_rehearsal_identities(values)

    financial_values = [
        RehearsalProviderIdentity("quote", 2, "tushare", "v1", "endpoint-v1").__dict__,
        RehearsalProviderIdentity("valuation", 2, "tushare", "v1", "endpoint-v1").__dict__,
        RehearsalProviderIdentity(
            "akshare_financial_route:99",
            3,
            "akshare_financial",
            "v1",
            "endpoint-v2",
        ).__dict__,
    ]

    with pytest.raises(ValueError, match="REHEARSAL_PROVIDER_IDENTITY_INVALID"):
        identity.parse_rehearsal_identities(financial_values)


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
