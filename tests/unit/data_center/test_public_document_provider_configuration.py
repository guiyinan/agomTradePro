"""Document-only configurations never become financial data providers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.data_center.application.dtos import ProviderResponse
from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.domain.enums import DataCapability
from apps.data_center.infrastructure.models import ProviderConfigModel
from apps.data_center.infrastructure.provider_registry import ProviderRegistry
from apps.data_center.interface import provider_api_views
from apps.data_center.interface.serializers import ProviderConfigSerializer
from tests.unit.data_center.test_source_registry import (
    _ProviderConfigRepository,
    _StubProvider,
)

DOCUMENT_TYPE = "public_document"


def configuration(source_type: str, identity: int = 7) -> ProviderConfig:
    return ProviderConfig(
        id=identity,
        name=f"synthetic-{identity}",
        source_type=source_type,
        is_active=True,
        priority=10,
        api_key="",
        api_secret="",
        http_url="",
        api_endpoint="",
        extra_config={},
        description="Synthetic configuration fixture",
    )


def test_document_source_is_an_explicit_model_and_input_choice() -> None:
    assert DOCUMENT_TYPE in dict(ProviderConfigModel.SOURCE_TYPE_CHOICES)
    serializer = ProviderConfigSerializer(
        data={
            "name": "Synthetic public documents",
            "source_type": DOCUMENT_TYPE,
            "is_active": False,
        }
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["source_type"] == DOCUMENT_TYPE


def test_document_only_configuration_never_invokes_financial_builder() -> None:
    builder = Mock(side_effect=AssertionError("Document configurations are not financial adapters"))
    registry = ProviderRegistry.from_repository(
        _ProviderConfigRepository([configuration(DOCUMENT_TYPE)]), builder=builder
    )
    builder.assert_not_called()
    assert registry.get_by_id(7) is None
    assert registry.get_provider(DataCapability.MACRO) is None


def test_mixed_configuration_builds_and_routes_only_real_financial_provider() -> None:
    document = configuration(DOCUMENT_TYPE)
    market = configuration("akshare", 8)
    provider = _StubProvider(market.name, [DataCapability.MACRO])
    builder = Mock(return_value=provider)
    registry = ProviderRegistry.from_repository(
        _ProviderConfigRepository([document, market]), builder=builder
    )
    builder.assert_called_once_with(market)
    assert registry.get_by_id(document.id) is None
    assert registry.get_by_id(market.id) is provider
    assert registry.get_provider(DataCapability.MACRO) is provider


def test_only_document_configuration_retires_previous_market_routes() -> None:
    builder = Mock(side_effect=AssertionError("No financial configuration is active"))
    registry = ProviderRegistry(builder=builder)
    registry.register(_StubProvider("old-market", [DataCapability.MACRO]), priority=10)
    registry.refresh_from_repository(_ProviderConfigRepository([configuration(DOCUMENT_TYPE)]))
    builder.assert_not_called()
    assert registry.get_provider(DataCapability.MACRO) is None


def test_document_entry_does_not_hide_all_financial_build_failures() -> None:
    registry = ProviderRegistry(builder=Mock(side_effect=ValueError("Synthetic adapter failure")))
    previous = _StubProvider("still-configured-market", [DataCapability.MACRO])
    registry.register(previous, priority=10)
    with pytest.raises(RuntimeError, match="No active Data Center provider"):
        registry.refresh_from_repository(
            _ProviderConfigRepository([configuration(DOCUMENT_TYPE), configuration("tushare", 8)])
        )
    assert registry.get_provider(DataCapability.MACRO) is previous


def test_unknown_type_is_not_silently_treated_as_document_only() -> None:
    registry = ProviderRegistry(builder=Mock(side_effect=ValueError("Unsupported source")))
    with pytest.raises(RuntimeError, match="No active Data Center provider"):
        registry.refresh_from_repository(
            _ProviderConfigRepository([configuration("public_document_typo")])
        )


def test_admin_create_document_configuration_has_json_201_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_case = Mock()
    use_case.create.return_value = ProviderResponse(
        id=7,
        name="Synthetic public documents",
        source_type=DOCUMENT_TYPE,
        is_active=False,
        priority=10,
        has_api_key=False,
        has_api_secret=False,
        http_url="",
        api_endpoint="",
        extra_config={},
        description="",
    )
    monkeypatch.setattr(
        provider_api_views, "make_manage_provider_config_use_case", lambda: use_case
    )
    refresh = Mock()
    monkeypatch.setattr(provider_api_views, "refresh_registry", refresh)
    request = APIRequestFactory().post(
        "/api/data-center/providers/",
        {"name": "Synthetic public documents", "source_type": DOCUMENT_TYPE, "is_active": False},
        format="json",
    )
    force_authenticate(request, user=SimpleNamespace(pk=7, is_authenticated=True, is_staff=True))
    response = provider_api_views.provider_list_create(request)
    response.render()
    assert response.status_code == 201
    assert response["Content-Type"].startswith("application/json")
    assert response.data["source_type"] == DOCUMENT_TYPE
    assert use_case.create.call_args.args[0].source_type == DOCUMENT_TYPE
    refresh.assert_called_once_with()


def test_nonstaff_cannot_create_document_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    factory = Mock()
    monkeypatch.setattr(provider_api_views, "make_manage_provider_config_use_case", factory)
    request = APIRequestFactory().post(
        "/api/data-center/providers/",
        {"name": "Synthetic", "source_type": DOCUMENT_TYPE},
        format="json",
    )
    force_authenticate(request, user=SimpleNamespace(pk=7, is_authenticated=True, is_staff=False))
    response = provider_api_views.provider_list_create(request)
    response.render()
    assert response.status_code == 403
    assert response["Content-Type"].startswith("application/json")
    factory.assert_not_called()
