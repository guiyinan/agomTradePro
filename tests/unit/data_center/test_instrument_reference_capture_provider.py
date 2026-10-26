"""Counterexamples for route pinning and raw response capture side effects."""

from __future__ import annotations

import hashlib
import json
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest

from apps.data_center.application.instrument_reference_capture import (
    CaptureScopeProgressState,
    InstrumentReferenceCaptureLease,
    InstrumentReferenceCaptureScopeProgress,
)
from apps.data_center.application.provider_response_payload import (
    ProviderResponsePayloadReference,
    RetainProviderResponsePayloadUseCase,
)
from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.domain.instrument_reference_capture import (
    CaptureClaimEpoch,
    CaptureOwnerCapability,
    InstrumentReferenceCaptureContractError,
    InstrumentReferenceCaptureRequest,
)
from apps.data_center.domain.instrument_reference_snapshot import (
    InstrumentReferenceMappingContent,
    make_instrument_reference_mapping_record,
)
from apps.data_center.domain.instrument_reference_source import (
    InstrumentReferenceExchangeSuffixCrosswalk,
    InstrumentReferenceProviderContract,
)
from apps.data_center.domain.protocols import ProviderConfigRepositoryProtocol
from apps.data_center.domain.provider_response import (
    ProviderResponseCapture,
    ProviderResponseTransport,
)
from apps.data_center.domain.raw_landing import RawPayload
from apps.data_center.infrastructure import (
    instrument_reference_capture_persistence as persistence_module,
)
from apps.data_center.infrastructure import (
    tushare_client,
)
from apps.data_center.infrastructure.instrument_reference_capture_persistence import (
    DjangoInstrumentReferenceCapturePersistence,
)
from apps.data_center.infrastructure.instrument_reference_capture_provider import (
    CaptureResponseStageStore,
    TushareInstrumentReferenceCaptureProvider,
)
from apps.data_center.infrastructure.instrument_reference_capture_receipt import (
    scope_checkpoint_name,
)
from apps.data_center.infrastructure.tushare_client import TushareProviderResponseHandler
from shared.config.tushare import (
    TUSHARE_REQUEST_MODE_SDK_PATH,
    TUSHARE_REQUEST_MODE_UNIFIED_RELAY,
)

_NOW = datetime(2026, 10, 22, 2, 0, tzinfo=UTC)
_FIELDS = (
    "ts_code",
    "name",
    "exchange",
    "market",
    "list_status",
    "list_date",
    "delist_date",
)


def _request(route_id: str = "tushare.stock_basic") -> InstrumentReferenceCaptureRequest:
    """Build one request with explicit SSE scopes and no asset-type inference."""

    contract = InstrumentReferenceProviderContract(
        contract_id="fixture.stock-basic",
        contract_version="fixture-v1",
        provider_name="tushare",
        dataset_key="fixture.stock-basic",
        api_name="stock_basic",
        fields=_FIELDS,
        exchange_scope=("SSE",),
        list_status_scope=("L", "D"),
    )
    crosswalk = InstrumentReferenceExchangeSuffixCrosswalk(
        crosswalk_id="fixture.crosswalk",
        crosswalk_version="fixture-v1",
        exchange_suffix_pairs=(("SSE", "SH"),),
    )
    mapping = make_instrument_reference_mapping_record(
        InstrumentReferenceMappingContent(
            mapping_id="fixture.mapping",
            mapping_version="fixture-v1",
            source_crosswalk=crosswalk,
            exchange_rule_market_pairs=(("SSE", "FIXTURE_SSE"),),
            exchange_source_market_board_pairs=(("SSE", "fixture-market", "FIXTURE"),),
        ),
        mapping_record_id=UUID("c5d7a91a-17f2-43a2-8f55-0a74789be639"),
        recorded_at=_NOW,
    )
    return InstrumentReferenceCaptureRequest(
        capture_id=UUID("84c776c3-0db4-4aed-9d2c-62e18b917ed5"),
        provider_contract=contract,
        provider_route_id=route_id,
        provider_route_revision="fixture-route-rev-1",
        provider_configuration_id=17,
        mapping_record=mapping,
    )


class _ConfigRepository:
    """Return only the requested provider-configuration ID."""

    def __init__(self, config: ProviderConfig) -> None:
        """Set up one exact configuration row for the adapter call."""

        self.config = config
        self.requested_ids: list[int] = []

    def get_by_id(self, provider_id: int) -> ProviderConfig | None:
        """Record exact-ID lookup without using name or priority fallback."""

        self.requested_ids.append(provider_id)
        return self.config if self.config.id == provider_id else None

    def list_all(self) -> list[ProviderConfig]:
        """Satisfy the unused remainder of the public repository protocol."""

        return [self.config]

    def list_active(self) -> list[ProviderConfig]:
        """Satisfy the unused remainder of the public repository protocol."""

        return [self.config]

    def get_by_name(self, name: str) -> ProviderConfig | None:
        """Never resolve capture configuration by its display name."""

        del name
        return None

    def save(self, config: ProviderConfig) -> ProviderConfig:
        """Prevent tests from changing configured provider state."""

        raise AssertionError(config)

    def persist_credentials(
        self,
        provider_id: int,
        *,
        api_key: str | None,
        api_secret: str | None,
    ) -> str:
        """Prevent tests from writing provider credentials."""

        raise AssertionError((provider_id, api_key, api_secret))

    def delete(self, provider_id: int) -> None:
        """Prevent tests from deleting provider configuration."""

        raise AssertionError(provider_id)

    def get_active_by_type(self, source_type: str) -> list[ProviderConfig]:
        """Prevent fallback to priority-ordered provider selection."""

        raise AssertionError(source_type)


class _ResponseFrame:
    """Expose only the exact transport evidence expected from Tushare."""

    def __init__(self, evidence: object) -> None:
        """Attach one provider-response evidence record."""

        self.response_evidence = evidence


class _Client:
    """Invoke the supplied response callback with one exact stock-basic body."""

    def __init__(
        self,
        handler: TushareProviderResponseHandler,
        *,
        response_completed_at: datetime = _NOW,
        security_name: str = "Fixture security",
        failure: Exception | None = None,
        failure_after_callback: bool = False,
        mismatched_evidence: bool = False,
    ) -> None:
        """Keep the callback so tests can observe pre-persistence capture."""

        self.handler = handler
        self.response_completed_at = response_completed_at
        self.security_name = security_name
        self.failure = failure
        self.failure_after_callback = failure_after_callback
        self.mismatched_evidence = mismatched_evidence

    def stock_basic(self, *, exchange: str, list_status: str, fields: str) -> object:
        """Return a response frame after the exact requested response is staged."""

        if self.failure is not None and not self.failure_after_callback:
            raise self.failure
        body_value = {
            "code": 0,
            "data": {
                "fields": list(_FIELDS),
                "items": [
                    [
                        "600000.SH",
                        self.security_name,
                        exchange,
                        "fixture-market",
                        list_status,
                        "20200102",
                        "",
                    ]
                ],
            },
        }
        body = json.dumps(body_value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        response = ProviderResponseCapture(
            body=body,
            payload=body_value,
            body_sha256=hashlib.sha256(body).hexdigest(),
            body_size_bytes=len(body),
            response_completed_at=self.response_completed_at,
            status_code=200,
            content_type="application/json",
            transport=ProviderResponseTransport.DIRECT,
        )
        params = {"fields": fields, "params": {"exchange": exchange, "list_status": list_status}}
        reference = self.handler(
            response,
            provider_name="tushare",
            dataset_key="fixture.stock-basic",
            api_name="stock_basic",
            request_params=params,
            sensitive_values=("fixture-api-token",),
        )
        if self.failure is not None and self.failure_after_callback:
            raise self.failure
        from apps.data_center.infrastructure.tushare_client import TushareResponseEvidence

        return _ResponseFrame(
            TushareResponseEvidence(
                body_sha256=response.body_sha256,
                response_completed_at=response.response_completed_at,
                raw_payload_reference=None if self.mismatched_evidence else reference,
            )
        )


class _ClientFactory:
    """Create a fake endpoint client while asserting exact provider ID use."""

    def __init__(
        self,
        *,
        failure: Exception | None = None,
        failure_after_callback: bool = False,
        mismatched_evidence: bool = False,
        security_names: tuple[str, ...] = ("Fixture security",),
    ) -> None:
        """Set an optional provider failure and sequence of exact response rows."""

        self.failure = failure
        self.failure_after_callback = failure_after_callback
        self.mismatched_evidence = mismatched_evidence
        self.security_names = security_names
        self._next_response = 0
        self.calls: list[tuple[int | None, str]] = []
        self.client_parameters: list[tuple[str | None, str | None, str | None, int | None, str]] = (
            []
        )

    def __call__(
        self,
        token: str | None = None,
        http_url: str | None = None,
        request_mode: str | None = None,
        *,
        provider_id: int | None = None,
        dataset_key: str = "",
        provider_response_handler: TushareProviderResponseHandler | None = None,
    ) -> object:
        """Return a fake endpoint client for exact provider-route tests."""

        self.client_parameters.append((token, http_url, request_mode, provider_id, dataset_key))
        self.calls.append((provider_id, dataset_key))
        if token != "fixture-api-token" or provider_response_handler is None:
            raise AssertionError("provider token or capture callback was not bound")
        index = self._next_response
        self._next_response += 1
        response_index = min(index, len(self.security_names) - 1)
        return _Client(
            provider_response_handler,
            response_completed_at=_NOW + timedelta(seconds=index),
            security_name=self.security_names[response_index],
            failure=self.failure,
            failure_after_callback=self.failure_after_callback,
            mismatched_evidence=self.mismatched_evidence,
        )


def _patch_global_tushare_request_mode(monkeypatch: pytest.MonkeyPatch, request_mode: str) -> None:
    """Use fixture-only global settings without reading a secrets file."""

    data_sources = SimpleNamespace(
        tushare_token="global-fixture-token",
        tushare_http_url=None,
        tushare_request_mode=request_mode,
    )
    monkeypatch.setattr(
        tushare_client,
        "get_secrets",
        lambda: SimpleNamespace(data_sources=data_sources),
    )


def _provider(
    *,
    failure: Exception | None = None,
    security_names: tuple[str, ...] = ("Fixture security",),
    request_mode: str | int | None = None,
) -> tuple[
    TushareInstrumentReferenceCaptureProvider,
    _ConfigRepository,
    _ClientFactory,
    CaptureResponseStageStore,
]:
    """Compose one fake exact-ID provider without database or network access."""

    config = ProviderConfig(
        id=17,
        name="tushare display label",
        source_type="tushare",
        is_active=True,
        priority=999,
        api_key="fixture-api-token",
        api_secret="",
        http_url="",
        api_endpoint="",
        extra_config=({"tushare_request_mode": request_mode} if request_mode is not None else {}),
        description="fixture only",
    )
    repository = _ConfigRepository(config)
    factory = _ClientFactory(failure=failure, security_names=security_names)
    stages = CaptureResponseStageStore()
    provider = TushareInstrumentReferenceCaptureProvider(
        cast(ProviderConfigRepositoryProtocol, repository),
        stages,
        client_factory=factory,
    )
    return provider, repository, factory, stages


class _InMemoryRawPayloadRepository:
    """Persist exact RawPayload objects in memory for persistence-boundary tests."""

    unit_of_work_key = "django:default"

    def __init__(self) -> None:
        """Start with no payload rows."""

        self.payloads: dict[str, RawPayload] = {}

    def save(self, payload: RawPayload) -> RawPayload:
        """Preserve immutable identity and return an exact replay."""

        existing = self.payloads.get(payload.payload_id)
        if existing is not None and existing != payload:
            raise ValueError("raw payload immutable replay conflict")
        self.payloads[payload.payload_id] = payload
        return payload

    def get_by_id(self, payload_id: str) -> RawPayload | None:
        """Read one stored row by its content-derived UUID."""

        return self.payloads.get(payload_id)


class _CaptureClaims:
    """Return one exact request and keep its lease current for a unit test."""

    def __init__(self, request: InstrumentReferenceCaptureRequest) -> None:
        """Bind claim reads to one immutable request."""

        self.request = request

    def request_for_lease(
        self, lease: InstrumentReferenceCaptureLease
    ) -> InstrumentReferenceCaptureRequest:
        """Return only the request identified by the supplied lease."""

        assert lease.identity == self.request.identity
        assert lease.request_sha256 == self.request.request_sha256
        return self.request

    def is_current(self, lease: InstrumentReferenceCaptureLease) -> bool:
        """Report current only for the request bound above."""

        return (
            lease.identity == self.request.identity
            and lease.request_sha256 == self.request.request_sha256
        )


class _DefaultAliasStub:
    """Provide the unit-of-work identity required by persistence composition."""

    @property
    def unit_of_work_key(self) -> str:
        """Represent the default-alias transaction boundary."""

        return "django:default"


class _RunlessRetainer:
    """Model a regressed retainer that drops the supplied run identity."""

    def __init__(self, repository: _InMemoryRawPayloadRepository) -> None:
        """Use the real redaction/digest implementation with an in-memory store."""

        self._retainer = RetainProviderResponsePayloadUseCase(repository)
        self.received_run_ids: list[str | None] = []

    def execute(
        self,
        capture: ProviderResponseCapture,
        *,
        provider_name: str,
        dataset_key: str,
        api_name: str,
        request_params: dict[str, object],
        sensitive_values: tuple[str, ...],
        run_id: str | None = None,
    ) -> ProviderResponsePayloadReference:
        """Record the current identity but intentionally omit it from retention."""

        self.received_run_ids.append(run_id)
        return self._retainer.execute(
            capture,
            provider_name=provider_name,
            dataset_key=dataset_key,
            api_name=api_name,
            request_params=request_params,
            sensitive_values=sensitive_values,
        )


def _persistence_for_response_test(
    request: InstrumentReferenceCaptureRequest,
    stages: CaptureResponseStageStore,
    raw_payloads: _InMemoryRawPayloadRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    DjangoInstrumentReferenceCapturePersistence,
    InstrumentReferenceCaptureLease,
    list[tuple[str, str]],
]:
    """Compose the real persistence method with only DB read/write edges stubbed."""

    capability = CaptureOwnerCapability.generate()
    epoch = CaptureClaimEpoch.issue(1, request.request_sha256, None, capability)
    lease = InstrumentReferenceCaptureLease(
        identity=request.identity,
        request_sha256=request.request_sha256,
        epoch=epoch,
        owner_capability=capability,
    )
    persistence = DjangoInstrumentReferenceCapturePersistence(
        _CaptureClaims(request),
        _DefaultAliasStub(),
        raw_payloads,
        _DefaultAliasStub(),
        object(),
        stages,
    )
    checkpoints: list[tuple[str, str]] = []
    monkeypatch.setattr(persistence_module.transaction, "atomic", lambda **_kwargs: nullcontext())
    monkeypatch.setattr(
        persistence,
        "_read_scope_progress_locked",
        lambda selected_request, scope: InstrumentReferenceCaptureScopeProgress(
            request=selected_request,
            request_sha256=selected_request.request_sha256,
            provider_contract_hash=selected_request.provider_contract.content_hash,
            scope=scope,
            state=CaptureScopeProgressState.NOT_CAPTURED,
        ),
    )

    def record_checkpoint(
        _request: InstrumentReferenceCaptureRequest,
        checkpoint_name: str,
        checkpoint_value: str,
    ) -> None:
        """Capture a checkpoint write without opening a database connection."""

        checkpoints.append((checkpoint_name, checkpoint_value))

    monkeypatch.setattr(persistence, "_insert_checkpoint", record_checkpoint)
    return persistence, lease, checkpoints


def test_provider_uses_exact_configuration_id_and_stages_raw_response_in_memory() -> None:
    request = _request()
    provider, repository, factory, stages = _provider()

    response = provider.fetch_scope(request, request.scopes[0])

    staged = stages.get_prepared(request, request.scopes[0])
    assert repository.requested_ids == [request.provider_configuration_id]
    assert factory.calls == [
        (request.provider_configuration_id, request.provider_contract.dataset_key)
    ]
    assert staged is not None
    assert staged.response == response
    assert stages.get(request, request.scopes[0], response) is staged
    assert staged.reference.original_body_retained is True
    assert staged.raw_payload.fetched_at == _NOW
    assert staged.reference.run_id == str(request.identity.run_id)
    assert staged.raw_payload.run_id == str(request.identity.run_id)
    assert staged.raw_payload.batch_id == ""


def test_persistence_retain_response_persists_and_reads_back_current_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    scope = request.scopes[0]
    provider, _repository, _factory, stages = _provider()
    response = provider.fetch_scope(request, scope)
    raw_payloads = _InMemoryRawPayloadRepository()
    persistence, lease, checkpoints = _persistence_for_response_test(
        request,
        stages,
        raw_payloads,
        monkeypatch,
    )

    reference = persistence.retain_response(lease, scope, response)
    stored = raw_payloads.get_by_id(reference.payload_id)

    assert reference.run_id == str(request.identity.run_id)
    assert stored is not None
    assert stored.run_id == str(request.identity.run_id)
    assert reference.verifies(stored)
    assert checkpoints == [(scope_checkpoint_name(scope, "response"), reference.payload_id)]


def test_persistence_rejects_runless_readback_even_when_stage_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    scope = request.scopes[0]
    provider, _repository, _factory, provider_stages = _provider()
    response = provider.fetch_scope(request, scope)
    staged = provider_stages.get(request, scope, response)
    assert staged is not None

    raw_payloads = _InMemoryRawPayloadRepository()
    runless_reference = RetainProviderResponsePayloadUseCase(raw_payloads).execute(
        response,
        provider_name=request.provider_contract.provider_name,
        dataset_key=request.provider_contract.dataset_key,
        api_name=request.provider_contract.api_name,
        request_params=staged.request_params,
        sensitive_values=staged.sensitive_values,
    )
    runless_payload = raw_payloads.get_by_id(runless_reference.payload_id)
    assert runless_payload is not None
    assert runless_reference.run_id == runless_payload.run_id == ""

    runless_stages = CaptureResponseStageStore()
    runless_stages.put(replace(staged, reference=runless_reference, raw_payload=runless_payload))
    persistence, lease, checkpoints = _persistence_for_response_test(
        request,
        runless_stages,
        raw_payloads,
        monkeypatch,
    )
    runless_retainer = _RunlessRetainer(raw_payloads)
    persistence._retainer = runless_retainer

    with pytest.raises(InstrumentReferenceCaptureContractError) as caught:
        persistence.retain_response(lease, scope, response)

    assert caught.value.code == "INSTRUMENT_REFERENCE_CAPTURE_RESPONSE_READBACK_INVALID"
    assert runless_retainer.received_run_ids == [str(request.identity.run_id)]
    assert checkpoints == []


@pytest.mark.parametrize(
    ("global_mode", "selected_mode"),
    (
        (TUSHARE_REQUEST_MODE_SDK_PATH, TUSHARE_REQUEST_MODE_UNIFIED_RELAY),
        (TUSHARE_REQUEST_MODE_UNIFIED_RELAY, TUSHARE_REQUEST_MODE_SDK_PATH),
    ),
)
def test_selected_provider_mode_overrides_global_and_retains_response(
    monkeypatch: pytest.MonkeyPatch,
    global_mode: str,
    selected_mode: str,
) -> None:
    """Pass the selected row's transport mode to the client and retain its response."""

    _patch_global_tushare_request_mode(monkeypatch, global_mode)
    request = _request()
    provider, _repository, factory, stages = _provider(request_mode=selected_mode)

    response = provider.fetch_scope(request, request.scopes[0])

    assert factory.client_parameters == [
        (
            "fixture-api-token",
            None,
            selected_mode,
            request.provider_configuration_id,
            request.provider_contract.dataset_key,
        )
    ]
    staged = stages.get_prepared(request, request.scopes[0])
    assert staged is not None
    assert staged.response is response
    assert staged.reference.original_body_retained is True
    assert staged.reference.body_sha256 == response.body_sha256


@pytest.mark.parametrize("selected_mode", [None, "", "  "], ids=["missing", "empty", "whitespace"])
def test_missing_selected_mode_keeps_shared_global_resolver_fallback(
    monkeypatch: pytest.MonkeyPatch,
    selected_mode: str | None,
) -> None:
    """Keep legacy global fallback when the selected row has no mode."""

    _patch_global_tushare_request_mode(monkeypatch, TUSHARE_REQUEST_MODE_UNIFIED_RELAY)
    request = _request()
    provider, _repository, factory, stages = _provider(request_mode=selected_mode)

    response = provider.fetch_scope(request, request.scopes[0])

    assert factory.client_parameters == [
        (
            "fixture-api-token",
            None,
            TUSHARE_REQUEST_MODE_UNIFIED_RELAY,
            request.provider_configuration_id,
            request.provider_contract.dataset_key,
        )
    ]
    staged = stages.get_prepared(request, request.scopes[0])
    assert staged is not None
    assert staged.response is response
    assert staged.reference.original_body_retained is True
    assert staged.reference.body_sha256 == response.body_sha256


def test_non_string_selected_mode_fails_before_client_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject malformed explicit mode data rather than treating it as absent."""

    _patch_global_tushare_request_mode(monkeypatch, TUSHARE_REQUEST_MODE_SDK_PATH)
    request = _request()
    provider, _repository, factory, stages = _provider(request_mode=17)

    with pytest.raises(InstrumentReferenceCaptureContractError) as caught:
        provider.fetch_scope(request, request.scopes[0])

    assert caught.value.code == "INSTRUMENT_REFERENCE_CAPTURE_PROVIDER_CONFIGURATION_INVALID"
    assert factory.calls == []
    assert factory.client_parameters == []
    assert stages.get_prepared(request, request.scopes[0]) is None


def test_unsupported_selected_mode_fails_before_client_factory_despite_valid_global(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject an explicit invalid mode rather than silently using global mode."""

    _patch_global_tushare_request_mode(monkeypatch, TUSHARE_REQUEST_MODE_SDK_PATH)
    request = _request()
    provider, _repository, factory, stages = _provider(request_mode="unsupported-mode")

    with pytest.raises(ValueError, match="Tushare request mode is unsupported"):
        provider.fetch_scope(request, request.scopes[0])

    assert factory.calls == []
    assert factory.client_parameters == []
    assert stages.get_prepared(request, request.scopes[0]) is None


def test_wrong_logical_route_fails_before_config_or_provider_lookup() -> None:
    request = _request()
    wrong_route = replace(request, provider_route_id="tushare.other_api")
    provider, repository, factory, stages = _provider()

    with pytest.raises(InstrumentReferenceCaptureContractError) as caught:
        provider.fetch_scope(wrong_route, wrong_route.scopes[0])

    assert caught.value.code == "INSTRUMENT_REFERENCE_CAPTURE_ROUTE_BINDING_INVALID"
    assert repository.requested_ids == []
    assert factory.calls == []
    assert stages.get_prepared(wrong_route, wrong_route.scopes[0]) is None


def test_raw_transport_failure_is_propagated_without_durable_capture() -> None:
    request = _request()
    provider, _repository, factory, stages = _provider(
        failure=RuntimeError("fixture raw response failure")
    )

    with pytest.raises(RuntimeError, match="fixture raw response failure"):
        provider.fetch_scope(request, request.scopes[0])

    assert factory.calls == [
        (request.provider_configuration_id, request.provider_contract.dataset_key)
    ]
    assert stages.get_prepared(request, request.scopes[0]) is None


@pytest.mark.parametrize("failure_mode", ("after_callback", "evidence_mismatch"))
def test_failed_fetch_discards_only_its_own_staged_response(failure_mode: str) -> None:
    """Clear the failed response while retaining another attempt's exact object."""

    request = _request()
    scope = request.scopes[0]
    provider, _repository, factory, stages = _provider(
        security_names=("Earlier response", "Failed response")
    )
    earlier_response = provider.fetch_scope(request, scope)

    if failure_mode == "after_callback":
        factory.failure = RuntimeError("fixture failure after capture callback")
        factory.failure_after_callback = True
        with pytest.raises(RuntimeError, match="fixture failure after capture callback"):
            provider.fetch_scope(request, scope)
    else:
        factory.mismatched_evidence = True
        with pytest.raises(InstrumentReferenceCaptureContractError) as caught:
            provider.fetch_scope(request, scope)
        assert caught.value.code == "INSTRUMENT_REFERENCE_CAPTURE_RESPONSE_EVIDENCE_MISMATCH"

    earlier_stage = stages.get(request, scope, earlier_response)
    assert earlier_stage is not None
    assert earlier_stage.response is earlier_response
    assert stages.get_prepared(request, scope) is earlier_stage


def test_provider_configuration_id_mismatch_does_not_fall_back_to_name_or_priority() -> None:
    request = _request()
    config = ProviderConfig(
        id=18,
        name="same provider display label",
        source_type="tushare",
        is_active=True,
        priority=0,
        api_key="fixture-api-token",
        api_secret="",
        http_url="",
        api_endpoint="",
        extra_config={},
        description="mismatch fixture",
    )
    repository = _ConfigRepository(config)
    factory = _ClientFactory()
    stages = CaptureResponseStageStore()
    provider = TushareInstrumentReferenceCaptureProvider(
        cast(ProviderConfigRepositoryProtocol, repository),
        stages,
        client_factory=factory,
    )

    with pytest.raises(InstrumentReferenceCaptureContractError) as caught:
        provider.fetch_scope(request, request.scopes[0])

    assert caught.value.code == "INSTRUMENT_REFERENCE_CAPTURE_PROVIDER_CONFIGURATION_INVALID"
    assert repository.requested_ids == [request.provider_configuration_id]
    assert factory.calls == []
    assert stages.get_prepared(request, request.scopes[0]) is None


def test_reused_provider_instance_keeps_old_and_new_response_stages_separate() -> None:
    """Allow a resumed epoch to stage fresh bytes before stale-response cleanup."""

    request = _request()
    scope = request.scopes[0]
    provider, _repository, _factory, stages = _provider(
        security_names=("First response", "Resumed response")
    )

    old_response = provider.fetch_scope(request, scope)
    resumed_response = provider.fetch_scope(request, scope)

    assert old_response is not resumed_response
    assert old_response.body_sha256 != resumed_response.body_sha256
    assert stages.get(request, scope, old_response) is not None
    assert stages.get(request, scope, resumed_response) is not None
    stages.discard(request, scope, old_response)
    assert stages.get(request, scope, old_response) is None
    assert stages.get(request, scope, resumed_response) is not None
    prepared = stages.get_prepared(request, scope)
    assert prepared is not None
    assert prepared.response is resumed_response


def test_invalid_request_route_argument_fails_closed_before_attribute_access() -> None:
    """Map an untyped request to a capture contract error rather than AttributeError."""

    request = _request()
    provider, _repository, _factory, _stages = _provider()

    with pytest.raises(InstrumentReferenceCaptureContractError) as caught:
        provider.fetch_scope(cast(InstrumentReferenceCaptureRequest, object()), request.scopes[0])

    assert caught.value.code == "INSTRUMENT_REFERENCE_CAPTURE_ROUTE_BINDING_INVALID"


def test_explicit_null_selected_mode_keeps_shared_global_resolver_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit legacy JSON null retains the shared mode fallback."""
    _patch_global_tushare_request_mode(monkeypatch, TUSHARE_REQUEST_MODE_UNIFIED_RELAY)
    request = _request()
    provider, repository, factory, stages = _provider()
    repository.config = replace(repository.config, extra_config={"tushare_request_mode": None})
    response = provider.fetch_scope(request, request.scopes[0])
    assert factory.client_parameters[0][2] == TUSHARE_REQUEST_MODE_UNIFIED_RELAY
    staged = stages.get_prepared(request, request.scopes[0])
    assert staged is not None
    assert staged.response is response
    assert staged.reference.original_body_retained is True
    assert staged.reference.body_sha256 == response.body_sha256
