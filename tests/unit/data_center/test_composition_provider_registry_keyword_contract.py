"""Runtime contracts for provider-registry injection in composition factories."""

import pytest

import apps.data_center.application.interface_services as interface_services
import apps.data_center.composition as composition
import apps.data_center.infrastructure.model_market_wiring as model_market_wiring
import core.integration.data_center_audit as data_center_audit
from apps.data_center.application.current_valuation_sync import (
    SyncCurrentValuationBatchUseCase,
)
from apps.data_center.application.sync_macro_use_cases import SyncMacroUseCase
from apps.data_center.application.sync_market_use_cases import SyncPriceUseCase


def _new_object(*_args: object, **_kwargs: object) -> object:
    return object()


class _AuditWriter:
    database_alias = "default"


def _audit_writers(**_kwargs: object) -> tuple[_AuditWriter, ...]:
    return tuple(_AuditWriter() for _ in range(8))


def _stub_external_sync_ports(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub audit and transaction adapters while retaining actual use cases."""
    monkeypatch.setattr(composition, "DjangoSyncExecutionIdentityIssuer", _new_object)
    monkeypatch.setattr(composition, "DjangoDataCenterSyncUnitOfWork", _new_object)
    monkeypatch.setattr(
        data_center_audit,
        "get_data_reliability_audit_writers",
        _audit_writers,
    )


def test_macro_factory_uses_the_use_case_registry_parameter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_external_sync_ports(monkeypatch)

    result = composition.make_system_audited_sync_macro_use_case(
        provider_repository=object(),
        provider_registry=object(),
        environment="test",
    )

    assert isinstance(result, SyncMacroUseCase)


def test_price_factory_uses_the_use_case_registry_parameter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_external_sync_ports(monkeypatch)

    result = composition.make_system_audited_sync_price_use_case(
        provider_repository=object(),
        provider_registry=object(),
        environment="test",
    )

    assert isinstance(result, SyncPriceUseCase)


def test_current_valuation_factory_uses_the_use_case_registry_parameter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_external_sync_ports(monkeypatch)

    result = composition.make_system_audited_sync_current_valuation_batch_use_case(
        provider_repository=object(),
        provider_registry=object(),
        environment="test",
    )

    assert isinstance(result, SyncCurrentValuationBatchUseCase)


def test_model_market_factory_passes_registry_to_price_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_external_sync_ports(monkeypatch)
    registry = object()
    repository = object()
    settings: dict[str, object] = {"status": "test"}
    service = object()
    captured: dict[str, object] = {}

    def build_model_market_service(
        received_registry: object,
        received_repository: object,
        received_settings: dict[str, object],
        *,
        history_fetch_audit: object | None = None,
    ) -> object:
        captured["registry"] = received_registry
        captured["repository"] = received_repository
        captured["settings"] = received_settings
        captured["history_fetch_audit"] = history_fetch_audit
        return service

    monkeypatch.setattr(composition, "get_provider_registry", lambda: registry)
    monkeypatch.setattr(composition, "ProviderConfigRepository", _new_object)
    monkeypatch.setattr(composition, "get_price_bar_repository", lambda: repository)
    monkeypatch.setattr(
        interface_services,
        "load_provider_settings_payload",
        lambda: settings,
    )
    monkeypatch.setattr(
        model_market_wiring,
        "build_model_market_service",
        build_model_market_service,
    )

    result = composition.build_model_market_data_service()

    assert result is service
    assert captured["registry"] is registry
    assert captured["repository"] is repository
    assert captured["settings"] is settings
    assert isinstance(captured["history_fetch_audit"], SyncPriceUseCase)
