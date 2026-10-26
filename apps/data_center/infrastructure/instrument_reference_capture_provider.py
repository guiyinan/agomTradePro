"""Pure network adapter for exact, explicitly scoped Tushare stock-basic reads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, cast

from apps.data_center.application.provider_response_payload import (
    ProviderResponsePayloadReference,
    RetainProviderResponsePayloadUseCase,
)
from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.domain.instrument_reference_capture import (
    InstrumentReferenceCaptureContractError,
    InstrumentReferenceCaptureRequest,
    InstrumentReferenceCaptureScope,
)
from apps.data_center.domain.protocols import ProviderConfigRepositoryProtocol
from apps.data_center.domain.provider_response import (
    ProviderResponseCapture,
    canonical_provider_response_json,
    parse_provider_response_json,
)
from apps.data_center.domain.raw_landing import RawPayload
from apps.data_center.infrastructure.tushare_client import (
    TushareProviderResponseHandler,
    TushareResponseEvidence,
    create_tushare_pro_client,
    resolve_tushare_runtime_settings,
)
from apps.data_center.infrastructure.tushare_instrument_reference_source import (
    TushareStockBasicClientPort,
)

_STOCK_BASIC_ROUTE_ID = "tushare.stock_basic"


class _MemoryPayloadStore:
    """Hold a prepared response payload only until fenced persistence accepts it."""

    def __init__(self) -> None:
        """Start with an empty ephemeral response store."""

        self.payload: RawPayload | None = None

    def save(self, payload: RawPayload) -> RawPayload:
        """Return the exact payload without writing to a database or file."""

        if self.payload is not None and self.payload != payload:
            raise ValueError("capture_ephemeral_payload_conflict")
        self.payload = payload
        return payload


@dataclass(frozen=True, slots=True)
class PreparedCaptureResponse:
    """Bind one network response to its preflighted redaction inputs."""

    request_sha256: str
    scope: InstrumentReferenceCaptureScope
    response: ProviderResponseCapture
    reference: ProviderResponsePayloadReference
    raw_payload: RawPayload
    request_params: dict[str, object]
    sensitive_values: tuple[str, ...]


class CaptureResponseStageStore:
    """Share volatile capture evidence between the fetch and fenced writer ports."""

    def __init__(self) -> None:
        """Create an empty per-process stage keyed by response object identity."""

        self._responses: dict[tuple[str, str, str, int], PreparedCaptureResponse] = {}

    def put(self, item: PreparedCaptureResponse) -> None:
        """Keep one exact response for a request scope until durable readback."""

        key = _stage_key(item.request_sha256, item.scope, item.response)
        current = self._responses.get(key)
        if current is not None and current != item:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_RESPONSE_STAGE_CONFLICT"
            )
        self._responses[key] = item

    def get(
        self,
        request: InstrumentReferenceCaptureRequest,
        scope: InstrumentReferenceCaptureScope,
        response: ProviderResponseCapture,
    ) -> PreparedCaptureResponse | None:
        """Return a staged response only when its body and scope match exactly."""

        item = self._responses.get(_stage_key(request.request_sha256, scope, response))
        if item is None or item.response is not response:
            return None
        return item

    def get_prepared(
        self,
        request: InstrumentReferenceCaptureRequest,
        scope: InstrumentReferenceCaptureScope,
    ) -> PreparedCaptureResponse | None:
        """Return the exact prepared response for one immutable request scope."""

        prefix = _stage_prefix(request.request_sha256, scope)
        matches = [item for key, item in self._responses.items() if key[:3] == prefix]
        return matches[-1] if matches else None

    def get_by_evidence(
        self,
        request: InstrumentReferenceCaptureRequest,
        scope: InstrumentReferenceCaptureScope,
        evidence: TushareResponseEvidence,
    ) -> PreparedCaptureResponse | None:
        """Find the latest exact response staged for Tushare's attached evidence."""

        prefix = _stage_prefix(request.request_sha256, scope)
        matches = [
            item
            for key, item in self._responses.items()
            if key[:3] == prefix
            and item.reference == evidence.raw_payload_reference
            and item.reference.body_sha256 == evidence.body_sha256
            and item.reference.response_completed_at == evidence.response_completed_at
        ]
        return matches[-1] if matches else None

    def discard(
        self,
        request: InstrumentReferenceCaptureRequest,
        scope: InstrumentReferenceCaptureScope,
        response: ProviderResponseCapture,
    ) -> None:
        """Forget one response after its payload pointer committed or failed."""

        key = _stage_key(request.request_sha256, scope, response)
        item = self._responses.get(key)
        if item is not None and item.response is response:
            del self._responses[key]


class _TushareClientFactory(Protocol):
    """Typed boundary for the existing Tushare client constructor."""

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
        """Construct a client with response capture enabled for one dataset."""


class TushareInstrumentReferenceCaptureProvider:
    """Fetch exact stock-basic response bytes without durable side effects."""

    def __init__(
        self,
        provider_configs: ProviderConfigRepositoryProtocol,
        response_stages: CaptureResponseStageStore,
        *,
        client_factory: _TushareClientFactory | None = None,
    ) -> None:
        """Inject exact-ID provider config lookup, volatile staging and transport."""

        self._provider_configs = provider_configs
        self._response_stages = response_stages
        self._client_factory = client_factory or create_tushare_pro_client

    def fetch_scope(
        self,
        request: InstrumentReferenceCaptureRequest,
        scope: InstrumentReferenceCaptureScope,
    ) -> ProviderResponseCapture:
        """Call one exact route/configuration/scope and return same-call bytes."""

        self._validate_request_route(request, scope)
        config = self._provider_configs.get_by_id(request.provider_configuration_id)
        if (
            type(config) is not ProviderConfig
            or type(config.id) is not int
            or config.id != request.provider_configuration_id
            or config.source_type != "tushare"
            or config.is_active is not True
            or not config.api_key.strip()
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_PROVIDER_CONFIGURATION_INVALID"
            )
        endpoint = config.http_url or config.api_endpoint or None
        raw_request_mode = (config.extra_config or {}).get("tushare_request_mode")
        if raw_request_mode is not None and not isinstance(raw_request_mode, str):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_PROVIDER_CONFIGURATION_INVALID"
            )
        request_mode = (
            raw_request_mode.strip()
            if isinstance(raw_request_mode, str) and raw_request_mode.strip()
            else None
        )
        settings = resolve_tushare_runtime_settings(
            token=config.api_key,
            http_url=endpoint,
            request_mode=request_mode,
        )
        memory_store = _MemoryPayloadStore()
        staged_responses: list[ProviderResponseCapture] = []

        def retain_ephemerally(
            response: ProviderResponseCapture,
            *,
            provider_name: str,
            dataset_key: str,
            api_name: str,
            request_params: object,
            sensitive_values: tuple[str, ...],
        ) -> ProviderResponsePayloadReference:
            """Validate exact request scope and prepare redaction without I/O."""

            contract = request.provider_contract
            normalized_params = _json_object(request_params)
            if (
                provider_name != contract.provider_name
                or dataset_key != contract.dataset_key
                or api_name != contract.api_name
                or not _request_params_match_scope(normalized_params, request, scope)
            ):
                raise InstrumentReferenceCaptureContractError(
                    "INSTRUMENT_REFERENCE_CAPTURE_ROUTE_BINDING_INVALID"
                )
            reference = RetainProviderResponsePayloadUseCase(memory_store).execute(
                response,
                provider_name=provider_name,
                dataset_key=dataset_key,
                api_name=api_name,
                request_params=normalized_params,
                sensitive_values=sensitive_values,
                run_id=str(request.identity.run_id),
            )
            payload = memory_store.payload
            if (
                payload is None
                or reference.original_body_retained is not True
                or not reference.verifies(payload)
            ):
                raise InstrumentReferenceCaptureContractError(
                    "INSTRUMENT_REFERENCE_CAPTURE_ORIGINAL_RESPONSE_UNAVAILABLE"
                )
            self._response_stages.put(
                PreparedCaptureResponse(
                    request_sha256=request.request_sha256,
                    scope=scope,
                    response=response,
                    reference=reference,
                    raw_payload=payload,
                    request_params=normalized_params,
                    sensitive_values=sensitive_values,
                )
            )
            staged_responses.append(response)
            return reference

        client = self._client_factory(
            token=settings.token,
            http_url=settings.http_url,
            request_mode=settings.request_mode,
            provider_id=config.id,
            dataset_key=request.provider_contract.dataset_key,
            provider_response_handler=cast(TushareProviderResponseHandler, retain_ephemerally),
        )
        transferred_to_persistence = False
        try:
            response_frame = cast(TushareStockBasicClientPort, client).stock_basic(
                exchange=scope.exchange,
                list_status=scope.list_status,
                fields=request.provider_contract.fields_csv,
            )
            evidence = getattr(response_frame, "response_evidence", None)
            if not isinstance(evidence, TushareResponseEvidence):
                raise InstrumentReferenceCaptureContractError(
                    "INSTRUMENT_REFERENCE_CAPTURE_RESPONSE_EVIDENCE_MISSING"
                )
            staged = self._response_stages.get_by_evidence(request, scope, evidence)
            if (
                staged is None
                or staged.reference != evidence.raw_payload_reference
                or staged.reference.body_sha256 != evidence.body_sha256
                or staged.reference.response_completed_at != evidence.response_completed_at
                or staged.reference.provider_name != request.provider_contract.provider_name
                or staged.reference.dataset_key != request.provider_contract.dataset_key
            ):
                raise InstrumentReferenceCaptureContractError(
                    "INSTRUMENT_REFERENCE_CAPTURE_RESPONSE_EVIDENCE_MISMATCH"
                )
            transferred_to_persistence = True
            return staged.response
        finally:
            if not transferred_to_persistence:
                for response in staged_responses:
                    self._response_stages.discard(request, scope, response)

    @staticmethod
    def _validate_request_route(
        request: InstrumentReferenceCaptureRequest,
        scope: InstrumentReferenceCaptureScope,
    ) -> None:
        """Pin the supported endpoint and explicit ordinary stock-basic scope."""

        if (
            type(request) is not InstrumentReferenceCaptureRequest
            or type(scope) is not InstrumentReferenceCaptureScope
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_ROUTE_BINDING_INVALID"
            )
        contract = request.provider_contract
        if (
            scope not in request.scopes
            or request.provider_route_id != _STOCK_BASIC_ROUTE_ID
            or contract.provider_name != "tushare"
            or contract.api_name != "stock_basic"
            or request.provider_configuration_id < 1
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_ROUTE_BINDING_INVALID"
            )


def _stage_key(
    request_sha256: str,
    scope: InstrumentReferenceCaptureScope,
    response: ProviderResponseCapture,
) -> tuple[str, str, str, int]:
    """Return the response-object slot within one immutable request scope."""

    return (*_stage_prefix(request_sha256, scope), id(response))


def _stage_prefix(
    request_sha256: str,
    scope: InstrumentReferenceCaptureScope,
) -> tuple[str, str, str]:
    """Return the request and explicit scope portion of a volatile stage key."""

    return request_sha256, scope.exchange, scope.list_status


def _json_object(value: object) -> dict[str, object]:
    """Copy only a strict JSON object across the third-party callback boundary."""

    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        try:
            parsed = parse_provider_response_json(
                canonical_provider_response_json(value).encode("utf-8")
            )
        except (RecursionError, TypeError, ValueError) as exc:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_REQUEST_PARAMS_INVALID"
            ) from exc
    else:
        parsed = parse_provider_response_json(
            canonical_provider_response_json(value).encode("utf-8")
        )
    if type(parsed) is not dict or any(type(key) is not str for key in parsed):
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_REQUEST_PARAMS_INVALID"
        )
    return cast(dict[str, object], parsed)


def _request_params_match_scope(
    value: dict[str, object],
    request: InstrumentReferenceCaptureRequest,
    scope: InstrumentReferenceCaptureScope,
) -> bool:
    """Accept only the exact Tushare SDK, relay, or REST request shape."""

    contract = request.provider_contract
    if set(value) == {"exchange", "list_status", "fields"}:
        return (
            value.get("exchange") == scope.exchange
            and value.get("list_status") == scope.list_status
            and value.get("fields") == contract.fields_csv
        )
    if set(value) not in (
        {"api_name", "fields", "params"},
        {"fields", "params"},
    ):
        return False
    api_name = value.get("api_name", contract.api_name)
    params = value.get("params")
    return (
        api_name == contract.api_name
        and value.get("fields") == contract.fields_csv
        and type(params) is dict
        and set(cast(dict[str, object], params)) == {"exchange", "list_status"}
        and cast(dict[str, object], params).get("exchange") == scope.exchange
        and cast(dict[str, object], params).get("list_status") == scope.list_status
    )


__all__ = [
    "CaptureResponseStageStore",
    "PreparedCaptureResponse",
    "TushareInstrumentReferenceCaptureProvider",
]
