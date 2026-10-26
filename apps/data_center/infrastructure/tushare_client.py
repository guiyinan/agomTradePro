"""Data Center-owned Tushare transport boundary.

Only this module may load the Tushare SDK or call the configured Tushare
relay.  The shared package no longer owns financial-provider transport.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial
from hashlib import sha256
from importlib import import_module
from typing import Any, Protocol, cast
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from apps.data_center.application.financial_response_artifact import (
    RetainedFinancialResponsePayload,
)
from apps.data_center.domain.egress_routing import EgressRequestContext
from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifactRef
from apps.data_center.domain.provider_response import ProviderResponseCapture
from apps.data_center.infrastructure.tushare_response_capture_support import (
    TushareProviderResponseHandler,
    TushareRelayAuthorizationError,
    TushareResponseEvidence,
    build_tushare_response_evidence,
    capture_direct_provider_response,
)
from core.exceptions import TushareError
from shared.config.secrets import get_secrets
from shared.config.tushare import (
    TUSHARE_REQUEST_MODE_REST_PATH,
    TUSHARE_REQUEST_MODE_SDK_PATH,
    TUSHARE_REQUEST_MODE_UNIFIED_RELAY,
    TushareRequestMode,
)

PandasDataFrame = Any
pd = cast(Any, import_module("pandas"))

FullMarketCacheKey = tuple[str, str, str, str]
FullMarketResponseCache = dict[FullMarketCacheKey, PandasDataFrame]

_FULL_MARKET_RESPONSE_CACHE: ContextVar[FullMarketResponseCache | None] = ContextVar(
    "tushare_full_market_response_cache",
    default=None,
)
_FULL_MARKET_RESPONSE_STATS: ContextVar[TushareFullMarketCacheStats | None] = ContextVar(
    "tushare_full_market_response_stats",
    default=None,
)


@dataclass(slots=True)
class TushareFullMarketCacheStats:
    """Count provider queries and operation-cache hits by Tushare endpoint."""

    provider_queries: dict[str, int] = field(default_factory=dict)
    cache_hits: dict[str, int] = field(default_factory=dict)

    def record_provider_query(self, api_name: str) -> None:
        """Record one call that reached the configured provider client."""

        self.provider_queries[api_name] = self.provider_queries.get(api_name, 0) + 1

    def record_cache_hit(self, api_name: str) -> None:
        """Record one full-market response served from the operation cache."""

        self.cache_hits[api_name] = self.cache_hits.get(api_name, 0) + 1


@contextmanager
def cache_tushare_full_market_trade_date_queries(
    stats: TushareFullMarketCacheStats,
) -> Iterator[None]:
    """Cache exact full-market daily tables for one explicitly bounded operation."""

    cache_token = _FULL_MARKET_RESPONSE_CACHE.set({})
    stats_token = _FULL_MARKET_RESPONSE_STATS.set(stats)
    try:
        yield
    finally:
        _FULL_MARKET_RESPONSE_STATS.reset(stats_token)
        _FULL_MARKET_RESPONSE_CACHE.reset(cache_token)


@dataclass(frozen=True)
class TushareRuntimeSettings:
    """Resolved runtime settings for Tushare."""

    token: str
    http_url: str | None = None
    request_mode: TushareRequestMode = TUSHARE_REQUEST_MODE_SDK_PATH


class _TushareDataApi(Protocol):
    """Private URL field exposed by Tushare's untyped DataApi client."""

    _DataApi__http_url: str


class TushareFinancialResponseHandler(Protocol):
    """Application supplied handler for the opt-in financial raw capture."""

    def __call__(
        self,
        *,
        request_id: UUID,
        context: EgressRequestContext,
        method: str,
        params: Mapping[str, object] | None,
        json_body: Mapping[str, object] | None,
        headers: Mapping[str, str] | None,
        api_name: str,
    ) -> RetainedFinancialResponsePayload:
        """Capture, retain, and return one payload/reference pair."""
        ...


@dataclass(frozen=True, slots=True)
class _RetainedFinancialFrame:
    """Expose a dataframe-compatible view with its immutable response reference."""

    frame: Any
    artifact_reference: FinancialResponseArtifactRef

    @property
    def empty(self) -> bool:
        """Return the wrapped dataframe's empty flag."""

        return bool(self.frame.empty)

    def to_dict(self, orient: str) -> list[dict[str, object]]:
        """Return provider rows through the wrapped dataframe conversion."""

        return cast(list[dict[str, object]], self.frame.to_dict(orient))


@dataclass(frozen=True, slots=True)
class _WitnessedProviderFrame:
    """Expose dataframe operations with exact non-financial transport evidence."""

    frame: Any
    response_evidence: TushareResponseEvidence

    @property
    def empty(self) -> bool:
        """Return the wrapped dataframe's empty flag."""

        return bool(self.frame.empty)

    def to_dict(self, orient: str) -> list[dict[str, object]]:
        """Return provider rows through the wrapped dataframe conversion."""

        return cast(list[dict[str, object]], self.frame.to_dict(orient))

    def __len__(self) -> int:
        """Preserve dataframe row-count semantics for completeness checks."""

        return int(len(self.frame))

    def __getitem__(self, key: object) -> Any:
        """Delegate column and mask selection to the wrapped dataframe."""

        return self.frame[key]

    def to_payload(self) -> dict[str, object]:
        """Serialize rows with immutable response evidence for cache handoff."""

        return {
            "rows": cast(list[dict[str, object]], self.frame.to_dict(orient="records")),
            "response_evidence": self.response_evidence.to_payload(),
        }

    def __getattr__(self, name: str) -> Any:
        """Delegate public dataframe operations while retaining response evidence."""

        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self.frame, name)


def _unwrap_retained_financial_payload(
    value: object,
) -> tuple[object, FinancialResponseArtifactRef | None]:
    """Separate an opt-in retained reference from the decoded provider payload."""

    if not isinstance(value, RetainedFinancialResponsePayload):
        return value, None
    return value.payload, value.reference


def _provider_frame(
    items: list[object],
    columns: list[str],
    artifact_reference: FinancialResponseArtifactRef | None,
    response_evidence: TushareResponseEvidence | None = None,
) -> PandasDataFrame:
    """Build the usual dataframe or its retained-financial wrapper."""

    frame = pd.DataFrame(items, columns=columns)
    if artifact_reference is None:
        return (
            _WitnessedProviderFrame(frame=frame, response_evidence=response_evidence)
            if response_evidence is not None
            else frame
        )
    return _RetainedFinancialFrame(frame=frame, artifact_reference=artifact_reference)


def _is_full_market_trade_date_query(api_name: str, params: Mapping[str, object]) -> bool:
    """Identify daily tables requested for one complete session rather than one symbol."""

    trade_date = params.get("trade_date")
    asset_code = params.get("ts_code")
    return (
        api_name in {"daily", "daily_basic"}
        and isinstance(trade_date, str)
        and re.fullmatch(r"[0-9]{8}", trade_date) is not None
        and not (isinstance(asset_code, str) and asset_code.strip())
    )


def _operation_cache_key(
    *,
    route_identity: str,
    api_name: str,
    fields: str,
    params: Mapping[str, object],
) -> FullMarketCacheKey | None:
    """Return a collision-free key for the exact session reads used by backfill."""

    if not _is_full_market_trade_date_query(api_name, params):
        return None
    if set(params) - {"trade_date", "ts_code"}:
        return None
    trade_date = cast(str, params["trade_date"])
    return route_identity, api_name, fields, trade_date


class _OperationCachedTushareClient:
    """Reuse immutable full-market responses inside one explicit operation scope."""

    def __init__(self, client: object, *, direct_route_identity: str) -> None:
        self._client = client
        self._direct_route_identity = direct_route_identity

    def query(self, api_name: str, fields: str = "", **params: object) -> PandasDataFrame:
        """Return a cached session table only when its current route is identical."""

        cache = _FULL_MARKET_RESPONSE_CACHE.get()
        stats = _FULL_MARKET_RESPONSE_STATS.get()
        if cache is None or stats is None:
            return cast(Any, self._client).query(api_name, fields=fields, **params)
        route_identity = self._route_identity(api_name)
        key = _operation_cache_key(
            route_identity=route_identity,
            api_name=api_name,
            fields=fields,
            params=params,
        )
        if key is None:
            return cast(Any, self._client).query(api_name, fields=fields, **params)
        cached = cache.get(key)
        if cached is not None:
            stats.record_cache_hit(api_name)
            return cached
        stats.record_provider_query(api_name)
        frame = cast(Any, self._client).query(api_name, fields=fields, **params)
        if self._route_identity(api_name) == route_identity:
            cache[key] = frame
        return frame

    def _route_identity(self, api_name: str) -> str:
        """Resolve the governed route used for one endpoint at call time."""

        resolver = getattr(self._client, "_operation_cache_route_identity", None)
        if callable(resolver):
            return cast(str, resolver(api_name))
        return self._direct_route_identity

    def __getattr__(self, api_name: str) -> Any:
        """Expose Tushare endpoint names through the standard dynamic API."""

        if api_name.startswith("_"):
            raise AttributeError(api_name)
        return partial(self.query, api_name)


def _empty_trade_date_error(api_name: str, trade_date: object) -> TushareError:
    """Build the stable retryable error for a successful but unavailable session table."""

    return TushareError(
        "目标交易日的行情数据尚未可用",
        code="TUSHARE_DATA_NOT_YET_AVAILABLE",
        details={"api_name": api_name, "trade_date": trade_date},
    )


def _validated_provider_table(
    data: dict[str, object],
    *,
    api_name: str,
    params: Mapping[str, object],
) -> tuple[list[str], list[object]]:
    """Validate one Tushare table envelope before constructing a dataframe."""

    if set(data) - {"fields", "items", "has_more"}:
        raise TushareError("Tushare table envelope is invalid", code="TUSHARE_INVALID_PAYLOAD")
    columns = data.get("fields")
    items = data.get("items")
    has_more = data.get("has_more", False)
    if (
        not isinstance(columns, list)
        or not all(isinstance(column, str) and column.strip() for column in columns)
        or len(set(columns)) != len(columns)
        or not isinstance(items, list)
        or type(has_more) is not bool
    ):
        raise TushareError("Tushare table shape is invalid", code="TUSHARE_INVALID_PAYLOAD")
    if has_more:
        raise TushareError("Tushare table is incomplete", code="MODEL_MARKET_INCOMPLETE_RESULT")
    if not all(isinstance(row, list) and len(row) == len(columns) for row in items):
        raise TushareError("Tushare table row shape is invalid", code="TUSHARE_INVALID_PAYLOAD")
    if (
        _is_full_market_trade_date_query(api_name, params)
        and columns
        and not {"ts_code", "trade_date"}.issubset(columns)
    ):
        raise TushareError(
            "Tushare session identity fields are missing", code="TUSHARE_INVALID_PAYLOAD"
        )
    if _is_full_market_trade_date_query(api_name, params) and not items:
        raise _empty_trade_date_error(api_name, params.get("trade_date"))
    return cast(list[str], columns), cast(list[object], items)


def resolve_tushare_runtime_settings(
    token: str | None = None,
    http_url: str | None = None,
    request_mode: str | None = None,
) -> TushareRuntimeSettings:
    """Resolve token, HTTP URL, and request mode from explicit or stored config."""

    secrets = None
    try:
        secrets = get_secrets().data_sources
    except OSError:
        secrets = None

    resolved_token = token if token is not None else (secrets.tushare_token if secrets else "")
    resolved_http_url = (
        http_url if http_url is not None else (secrets.tushare_http_url if secrets else None)
    )
    resolved_request_mode = (
        request_mode
        if request_mode is not None
        else getattr(secrets, "tushare_request_mode", TUSHARE_REQUEST_MODE_SDK_PATH)
    )
    normalized_token = resolved_token.strip()
    if len(normalized_token) > 10_000 or any(ord(char) < 32 for char in normalized_token):
        raise ValueError("Tushare token has invalid format")
    return TushareRuntimeSettings(
        token=normalized_token,
        http_url=_validated_http_url(resolved_http_url),
        request_mode=_validated_request_mode(resolved_request_mode),
    )


def _validated_request_mode(request_mode: str | None) -> TushareRequestMode:
    """Return one supported Tushare transport mode."""

    normalized = (request_mode or TUSHARE_REQUEST_MODE_SDK_PATH).strip().lower()
    if normalized == TUSHARE_REQUEST_MODE_SDK_PATH:
        return TUSHARE_REQUEST_MODE_SDK_PATH
    if normalized == TUSHARE_REQUEST_MODE_UNIFIED_RELAY:
        return TUSHARE_REQUEST_MODE_UNIFIED_RELAY
    if normalized == TUSHARE_REQUEST_MODE_REST_PATH:
        return TUSHARE_REQUEST_MODE_REST_PATH
    raise ValueError("Tushare request mode is unsupported")


def _validated_http_url(http_url: str | None) -> str | None:
    """Return one credential-free HTTP(S) endpoint URL."""

    normalized = (http_url or "").strip()
    if not normalized:
        return None
    if len(normalized) > 2048 or any(ord(char) < 32 for char in normalized):
        raise ValueError("Tushare HTTP URL has invalid format")
    parsed = urlsplit(normalized)
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("Tushare HTTP URL has invalid format") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Tushare HTTP URL has invalid format")
    return normalized


def configure_tushare_pro_client(pro: object, http_url: str | None) -> object:
    """Apply custom DataApi HTTP URL to an existing Tushare Pro client."""

    normalized_http_url = _validated_http_url(http_url)
    if normalized_http_url:
        cast(_TushareDataApi, pro)._DataApi__http_url = normalized_http_url
    return pro


def _append_custom_endpoint_to_no_proxy(http_url: str | None) -> None:
    """Bypass process proxies for one validated custom Tushare endpoint host.

    The Tushare SDK delegates transport to ``requests``.  Some production
    environments inject HTTP(S) proxy variables, so the custom endpoint must
    be present in both conventional NO_PROXY spellings before the SDK module
    is imported.  The bypass is deliberately host-scoped instead of disabling
    proxy handling for unrelated outbound services in the process.
    """

    normalized_http_url = _validated_http_url(http_url)
    if not normalized_http_url:
        return
    hostname = urlsplit(normalized_http_url).hostname
    if not hostname:
        return
    for variable_name in ("NO_PROXY", "no_proxy"):
        current_entries = [
            entry.strip() for entry in os.environ.get(variable_name, "").split(",") if entry.strip()
        ]
        normalized_entries = {entry.casefold() for entry in current_entries}
        if "*" in normalized_entries or hostname.casefold() in normalized_entries:
            continue
        os.environ[variable_name] = ",".join([*current_entries, hostname])


def _create_requests_session() -> Any:
    """Create a requests session without importing requests at module load."""

    requests_module = cast(Any, import_module("requests"))
    return requests_module.Session()


class _UnifiedRelayClient:
    """Tushare-compatible client for a single-URL authenticated relay."""

    def __init__(
        self,
        *,
        token: str,
        http_url: str,
        timeout_seconds: int = 30,
        provider_id: int | None = None,
        deployment_region: str = "unknown",
        dataset_key: str = "",
        financial_response_handler: TushareFinancialResponseHandler | None = None,
        provider_response_handler: TushareProviderResponseHandler | None = None,
        capture_provider_responses: bool = False,
    ) -> None:
        self._token = token
        self._http_url = http_url
        self._timeout_seconds = timeout_seconds
        self._provider_id = provider_id
        self._deployment_region = deployment_region.strip() or "unknown"
        self._dataset_key = dataset_key.strip()
        self._financial_response_handler = financial_response_handler
        self._provider_response_handler = provider_response_handler
        self._capture_provider_responses = capture_provider_responses
        self._session = _create_requests_session()
        self._session.headers.update({"X-API-Key": token})
        self._session.trust_env = False
        self._session.proxies = {"http": "", "https": ""}

    def query(
        self,
        api_name: str,
        fields: str = "",
        **params: object,
    ) -> PandasDataFrame:
        """Call one relay API and return the standard Tushare dataframe shape."""

        normalized_api_name = api_name.strip()
        if (
            not normalized_api_name
            or len(normalized_api_name) > 128
            or any(ord(character) < 33 for character in normalized_api_name)
        ):
            raise ValueError("Tushare API name has invalid format")
        self._reject_unsupported_financial_capture(api_name)

        request_body: dict[str, object] = {
            "api_name": normalized_api_name,
            "token": self._token,
            "params": params,
            "fields": fields,
        }
        target_url = self._http_url
        response_evidence: TushareResponseEvidence | None = None
        provider_capture: ProviderResponseCapture | None = None
        if self._should_use_egress(target_url, api_name=api_name):
            payload = self._request_through_egress(
                target_url,
                method="POST",
                api_name=api_name,
                json_body=request_body,
            )
        elif self._requires_financial_response_capture(api_name):
            raise TushareError(
                "Financial raw capture requires an explicit egress route",
                code="TUSHARE_FINANCIAL_ARTIFACT_ROUTE_REQUIRED",
            )
        else:
            if self._provider_response_capture_enabled(api_name):
                provider_capture = self._request_direct_provider_response(
                    target_url,
                    method="POST",
                    json_body=request_body,
                )
                payload = provider_capture.payload
            else:
                response = self._session.post(
                    target_url,
                    json=request_body,
                    timeout=self._timeout_seconds,
                )
                if response.status_code in {401, 403}:
                    raise TushareRelayAuthorizationError(
                        f"Tushare relay authorization failed with HTTP {response.status_code}"
                    )
                if response.status_code >= 400:
                    raise TushareError(
                        "Tushare relay returned an HTTP error",
                        code=f"TUSHARE_HTTP_{response.status_code}",
                    )
                response.raise_for_status()
                body = bytes(response.content)
                response_evidence = TushareResponseEvidence(
                    body_sha256=sha256(body).hexdigest(),
                    response_completed_at=datetime.now(UTC),
                )
                payload = response.json()
        if isinstance(payload, ProviderResponseCapture):
            provider_capture = payload
            payload = provider_capture.payload
        payload, artifact_reference = _unwrap_retained_financial_payload(payload)
        if not isinstance(payload, dict):
            raise TushareError(
                "Tushare relay returned an invalid payload",
                code="TUSHARE_INVALID_PAYLOAD",
            )
        if _validated_provider_code(payload) != 0:
            raise TushareError(
                "Tushare relay rejected the request",
                code="TUSHARE_PROVIDER_REJECTED",
            )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise TushareError(
                "Tushare relay response is missing data",
                code="TUSHARE_INVALID_PAYLOAD",
            )
        columns, items = _validated_provider_table(data, api_name=api_name, params=params)
        if self._provider_response_capture_enabled(api_name):
            if provider_capture is None:
                raise TushareError(
                    "Tushare response bytes were unavailable for opt-in retention",
                    code="TUSHARE_PROVIDER_RESPONSE_CAPTURE_UNAVAILABLE",
                )
            response_evidence = build_tushare_response_evidence(
                provider_capture,
                handler=self._provider_response_handler,
                token=self._token,
                target_url=self._operation_cache_target_url(api_name),
                headers=cast(Mapping[str, str], self._session.headers),
                dataset_key=self._dataset_key,
                api_name=api_name,
                request_params={"fields": fields, "params": params},
            )
        return _provider_frame(
            items,
            columns,
            artifact_reference,
            response_evidence=response_evidence,
        )

    def _should_use_egress(self, target_url: str, *, api_name: str) -> bool:
        """Use the Data Center transport only when an explicit rule matches."""

        if self._provider_id is None:
            return False
        from apps.data_center.application.egress_service import preview_route
        from apps.data_center.domain.egress_routing import EgressRequestContext

        context = EgressRequestContext(
            provider_id=self._provider_id,
            dataset_key=self._dataset_key or f"tushare.{api_name}",
            target_url=target_url,
            deployment_region=self._deployment_region,
        )
        return preview_route(context).rule_id is not None

    def _operation_cache_route_identity(self, api_name: str) -> str:
        """Return a stable identity for the live route used by one endpoint."""

        target_url = self._operation_cache_target_url(api_name)
        token_digest = sha256(self._token.encode("utf-8")).hexdigest()
        if self._provider_id is None:
            return f"direct:{target_url}:{token_digest}"
        from apps.data_center.application.egress_service import preview_route

        context = EgressRequestContext(
            provider_id=self._provider_id,
            dataset_key=self._dataset_key or f"tushare.{api_name}",
            target_url=target_url,
            deployment_region=self._deployment_region,
        )
        route = preview_route(context)
        route_key = f"rule:{route.rule_id}" if route.rule_id is not None else "direct"
        return f"{route_key}:{target_url}:{token_digest}"

    def _operation_cache_target_url(self, api_name: str) -> str:
        """Return the physical endpoint addressed by one logical API call."""

        return self._http_url

    def _request_through_egress(
        self,
        target_url: str,
        *,
        method: str,
        api_name: str,
        params: dict[str, object] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> object:
        """Send one provider request through the routed Data Center port."""

        from apps.data_center.application.egress_service import (
            execute_provider_request,
            execute_provider_response_request,
        )
        from apps.data_center.domain.egress_routing import EgressRequestContext

        if self._provider_id is None:  # pragma: no cover - guarded by caller
            raise RuntimeError("egress provider id is required")
        context = EgressRequestContext(
            provider_id=self._provider_id,
            dataset_key=self._dataset_key or f"tushare.{api_name}",
            target_url=target_url,
            deployment_region=self._deployment_region,
        )
        handler = self._financial_response_handler
        if handler is not None and api_name == "fina_indicator":
            return handler(
                request_id=uuid4(),
                context=context,
                method=method,
                params=params,
                json_body=json_body,
                headers={"X-API-Key": self._token},
                api_name=api_name,
            )
        if self._provider_response_capture_enabled(api_name):
            return execute_provider_response_request(
                context,
                method=method,
                params=params,
                json_body=json_body,
                headers={
                    "X-API-Key": self._token,
                    "Accept-Encoding": "identity",
                },
                max_attempts=2,
            )
        payload = execute_provider_request(
            context,
            method=method,
            params=params,
            json_body=json_body,
            headers={"X-API-Key": self._token},
            max_attempts=2,
        )
        return payload

    def _request_direct_provider_response(
        self,
        target_url: str,
        *,
        method: str,
        params: Mapping[str, object] | None = None,
        json_body: Mapping[str, object] | None = None,
    ) -> ProviderResponseCapture:
        """Capture a direct HTTP response without reserializing parsed rows."""
        return capture_direct_provider_response(
            self._session,
            target_url,
            method=method,
            params=params,
            json_body=json_body,
            timeout_seconds=self._timeout_seconds,
        )

    def _provider_response_capture_enabled(self, api_name: str) -> bool:
        """Return whether an opt-in non-financial handler owns this endpoint."""

        return (
            self._provider_response_handler is not None or self._capture_provider_responses
        ) and api_name != "fina_indicator"

    def _reject_unsupported_financial_capture(self, api_name: str) -> None:
        """Prevent generic raw-payload capture from masquerading as financial evidence."""

        if (
            api_name == "fina_indicator"
            and self._provider_response_handler is not None
            and self._financial_response_handler is None
        ):
            raise TushareError(
                "Financial responses require the dedicated financial capture path",
                code="TUSHARE_PROVIDER_RESPONSE_CAPTURE_UNSUPPORTED_API",
            )

    def _requires_financial_response_capture(self, api_name: str) -> bool:
        """Return whether this client must refuse an unrouted financial read."""

        return self._financial_response_handler is not None and api_name == "fina_indicator"

    def __getattr__(self, api_name: str) -> Any:
        """Expose Tushare endpoint names through the standard dynamic API."""

        if api_name.startswith("_"):
            raise AttributeError(api_name)
        return partial(self.query, api_name)


class _RestPathClient(_UnifiedRelayClient):
    """Read Tushare-shaped data from authenticated GET resource endpoints."""

    def query(self, api_name: str, fields: str = "", **params: object) -> PandasDataFrame:
        """Fetch a complete table, rejecting redirects and declared truncation."""
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,127}", api_name):
            raise ValueError("Tushare API name has invalid format")
        self._reject_unsupported_financial_capture(api_name)
        query_params = dict(params)
        if fields:
            query_params["fields"] = fields
        target_url = self._http_url.rstrip("/") + "/" + api_name.replace("_", "-")
        provider_capture: ProviderResponseCapture | None = None
        response_evidence: TushareResponseEvidence | None = None
        if self._should_use_egress(target_url, api_name=api_name):
            payload = self._request_through_egress(
                target_url,
                method="GET",
                api_name=api_name,
                params=query_params,
            )
        elif self._requires_financial_response_capture(api_name):
            raise TushareError(
                "Financial raw capture requires an explicit egress route",
                code="TUSHARE_FINANCIAL_ARTIFACT_ROUTE_REQUIRED",
            )
        else:
            if self._provider_response_capture_enabled(api_name):
                provider_capture = self._request_direct_provider_response(
                    target_url,
                    method="GET",
                    params=query_params,
                )
                payload = provider_capture.payload
            else:
                response = self._session.get(
                    target_url,
                    params=query_params,
                    timeout=self._timeout_seconds,
                    allow_redirects=False,
                )
                if response.status_code in {401, 403}:
                    raise TushareRelayAuthorizationError(
                        f"Tushare relay authorization failed with HTTP {response.status_code}"
                    )
                if response.status_code >= 400:
                    raise TushareError(
                        "Tushare resource returned an HTTP error",
                        code=f"TUSHARE_HTTP_{response.status_code}",
                    )
                if 300 <= response.status_code < 400:
                    raise TushareError(
                        "Tushare resource redirect rejected", code="TUSHARE_REDIRECT_BLOCKED"
                    )
                response.raise_for_status()
                payload = response.json()
        if isinstance(payload, ProviderResponseCapture):
            provider_capture = payload
            payload = provider_capture.payload
        payload, artifact_reference = _unwrap_retained_financial_payload(payload)
        if not isinstance(payload, dict):
            raise TushareError(
                "Tushare resource response is invalid",
                code="TUSHARE_INVALID_PAYLOAD",
            )
        if _validated_provider_code(payload) != 0:
            raise TushareError(
                "Tushare resource request rejected",
                code="TUSHARE_PROVIDER_REJECTED",
            )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise TushareError(
                "Tushare resource response is missing data",
                code="TUSHARE_INVALID_PAYLOAD",
            )
        columns, items = _validated_provider_table(data, api_name=api_name, params=params)
        if self._provider_response_capture_enabled(api_name):
            if provider_capture is None:
                raise TushareError(
                    "Tushare response bytes were unavailable for opt-in retention",
                    code="TUSHARE_PROVIDER_RESPONSE_CAPTURE_UNAVAILABLE",
                )
            response_evidence = build_tushare_response_evidence(
                provider_capture,
                handler=self._provider_response_handler,
                token=self._token,
                target_url=self._operation_cache_target_url(api_name),
                headers=cast(Mapping[str, str], self._session.headers),
                dataset_key=self._dataset_key,
                api_name=api_name,
                request_params=query_params,
            )
        return _provider_frame(
            items,
            columns,
            artifact_reference,
            response_evidence=response_evidence,
        )

    def _operation_cache_target_url(self, api_name: str) -> str:
        """Return the REST resource endpoint addressed by one API call."""

        return self._http_url.rstrip("/") + "/" + api_name.replace("_", "-")


class _RoutedSdkClient(_UnifiedRelayClient):
    """Check live routing rules before each SDK-shaped provider query."""

    def __init__(
        self,
        *,
        sdk_client: object,
        token: str,
        http_url: str,
        provider_id: int,
        deployment_region: str,
        dataset_key: str,
        legacy_bypass_url: str | None = None,
        financial_response_handler: TushareFinancialResponseHandler | None = None,
        provider_response_handler: TushareProviderResponseHandler | None = None,
        capture_provider_responses: bool = False,
    ) -> None:
        super().__init__(
            token=token,
            http_url=http_url,
            provider_id=provider_id,
            deployment_region=deployment_region,
            dataset_key=dataset_key,
            financial_response_handler=financial_response_handler,
            provider_response_handler=provider_response_handler,
            capture_provider_responses=capture_provider_responses,
        )
        self._sdk_client = sdk_client
        self._legacy_bypass_url = legacy_bypass_url

    def query(self, api_name: str, fields: str = "", **params: object) -> PandasDataFrame:
        """Preserve the SDK URL/body contract while routing explicitly selected reads."""
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,127}", api_name):
            raise ValueError("Tushare API name has invalid format")
        self._reject_unsupported_financial_capture(api_name)
        # ``pro._DataApi__http_url`` is a single POST endpoint.  The official
        # SDK carries ``api_name`` in the JSON body and never appends it to the
        # configured URL.  Keep that wire contract when the request is routed
        # through the governed egress path as well.
        target_url = self._http_url
        if not self._should_use_egress(target_url, api_name=api_name):
            if self._requires_financial_response_capture(api_name):
                raise TushareError(
                    "Financial raw capture requires an explicit egress route",
                    code="TUSHARE_FINANCIAL_ARTIFACT_ROUTE_REQUIRED",
                )
            if self._legacy_bypass_url is not None:
                return super().query(api_name, fields=fields, **params)
            if self._provider_response_capture_enabled(api_name):
                raise TushareError(
                    "The native Tushare SDK does not expose exact response bytes",
                    code="TUSHARE_PROVIDER_RESPONSE_CAPTURE_UNAVAILABLE",
                )
            _append_custom_endpoint_to_no_proxy(self._legacy_bypass_url)
            frame = cast(Any, self._sdk_client).query(api_name, fields=fields, **params)
            if _is_full_market_trade_date_query(api_name, params) and (
                frame is None or bool(getattr(frame, "empty", False))
            ):
                raise _empty_trade_date_error(api_name, params.get("trade_date"))
            return frame
        payload = self._request_through_egress(
            target_url,
            method="POST",
            api_name=api_name,
            json_body={
                "api_name": api_name,
                "token": self._token,
                "params": params,
                "fields": fields,
            },
        )
        provider_capture: ProviderResponseCapture | None = None
        if isinstance(payload, ProviderResponseCapture):
            provider_capture = payload
            payload = provider_capture.payload
        payload, artifact_reference = _unwrap_retained_financial_payload(payload)
        if not isinstance(payload, dict):
            raise TushareError(
                "Tushare response payload is invalid", code="TUSHARE_INVALID_PAYLOAD"
            )
        if _validated_provider_code(payload) != 0:
            raise TushareError(
                "Tushare provider rejected the read", code="TUSHARE_PROVIDER_REJECTED"
            )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise TushareError("Tushare response is missing data", code="TUSHARE_INVALID_PAYLOAD")
        columns, items = _validated_provider_table(data, api_name=api_name, params=params)
        response_evidence: TushareResponseEvidence | None = None
        if self._provider_response_capture_enabled(api_name):
            if provider_capture is None:
                raise TushareError(
                    "Tushare response bytes were unavailable for opt-in retention",
                    code="TUSHARE_PROVIDER_RESPONSE_CAPTURE_UNAVAILABLE",
                )
            response_evidence = build_tushare_response_evidence(
                provider_capture,
                handler=self._provider_response_handler,
                token=self._token,
                target_url=self._operation_cache_target_url(api_name),
                headers=cast(Mapping[str, str], self._session.headers),
                dataset_key=self._dataset_key,
                api_name=api_name,
                request_params={"api_name": api_name, "fields": fields, "params": params},
            )
        return _provider_frame(
            items,
            columns,
            artifact_reference,
            response_evidence=response_evidence,
        )


def _validated_provider_code(payload: dict[str, object]) -> int:
    """Return an exact integer provider code or reject ambiguous JSON scalars."""

    provider_code = payload.get("code")
    if isinstance(provider_code, bool) or not isinstance(provider_code, int):
        raise TushareError(
            "Tushare response code is invalid",
            code="TUSHARE_INVALID_PAYLOAD",
        )
    return provider_code


def create_tushare_pro_client(
    token: str | None = None,
    http_url: str | None = None,
    request_mode: str | None = None,
    *,
    provider_id: int | None = None,
    deployment_region: str = "unknown",
    dataset_key: str = "",
    financial_response_handler: TushareFinancialResponseHandler | None = None,
    provider_response_handler: TushareProviderResponseHandler | None = None,
    capture_provider_responses: bool = False,
) -> object:
    """Create a configured Tushare Pro client inside the Data Center boundary."""

    settings = resolve_tushare_runtime_settings(
        token=token,
        http_url=http_url,
        request_mode=request_mode,
    )
    if not settings.token:
        raise ValueError("Tushare token 未配置")
    if (
        (provider_response_handler is not None or capture_provider_responses)
        and settings.request_mode == TUSHARE_REQUEST_MODE_SDK_PATH
        and provider_id is None
    ):
        raise TushareError(
            "The native Tushare SDK does not expose exact response bytes",
            code="TUSHARE_PROVIDER_RESPONSE_CAPTURE_UNAVAILABLE",
        )
    if settings.request_mode in {
        TUSHARE_REQUEST_MODE_UNIFIED_RELAY,
        TUSHARE_REQUEST_MODE_REST_PATH,
    }:
        if not settings.http_url:
            raise ValueError("Tushare unified relay URL 未配置")
        client_type = (
            _RestPathClient
            if settings.request_mode == TUSHARE_REQUEST_MODE_REST_PATH
            else _UnifiedRelayClient
        )
        client = client_type(
            token=settings.token,
            http_url=settings.http_url,
            provider_id=provider_id,
            deployment_region=deployment_region,
            dataset_key=dataset_key,
            financial_response_handler=financial_response_handler,
            provider_response_handler=provider_response_handler,
            capture_provider_responses=capture_provider_responses,
        )
        return _operation_cached_client(client, settings)

    if provider_id is None:
        _append_custom_endpoint_to_no_proxy(settings.http_url)
    try:
        ts = cast(Any, import_module("tushare"))
    except ImportError as exc:
        raise ImportError("请安装 tushare: pip install tushare") from exc
    pro = ts.pro_api(settings.token)
    configured = configure_tushare_pro_client(pro, settings.http_url)
    if provider_id is None:
        return _operation_cached_client(configured, settings)
    sdk_url = _validated_http_url(cast(_TushareDataApi, configured)._DataApi__http_url)
    if sdk_url is None:
        raise ValueError("Tushare SDK endpoint is unavailable")
    client = _RoutedSdkClient(
        sdk_client=configured,
        token=settings.token,
        http_url=sdk_url,
        legacy_bypass_url=settings.http_url,
        provider_id=provider_id,
        deployment_region=deployment_region,
        dataset_key=dataset_key,
        financial_response_handler=financial_response_handler,
        provider_response_handler=provider_response_handler,
        capture_provider_responses=capture_provider_responses,
    )
    return _operation_cached_client(client, settings)


def _operation_cached_client(client: object, settings: TushareRuntimeSettings) -> object:
    """Wrap a client only while an explicit full-market cache scope is active."""

    if _FULL_MARKET_RESPONSE_CACHE.get() is None:
        return client
    token_digest = sha256(settings.token.encode("utf-8")).hexdigest()
    target_url = settings.http_url or "official-sdk"
    return _OperationCachedTushareClient(
        client,
        direct_route_identity=f"direct:{target_url}:{token_digest}",
    )


__all__ = [
    "TushareFullMarketCacheStats",
    "TushareFinancialResponseHandler",
    "TushareRelayAuthorizationError",
    "TushareRuntimeSettings",
    "TushareResponseEvidence",
    "TushareProviderResponseHandler",
    "cache_tushare_full_market_trade_date_queries",
    "configure_tushare_pro_client",
    "create_tushare_pro_client",
    "resolve_tushare_runtime_settings",
]
