"""Data Center-owned Tushare transport boundary.

Only this module may load the Tushare SDK or call the configured Tushare
relay.  The shared package no longer owns financial-provider transport.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import partial
from importlib import import_module
from typing import Any, Protocol, cast
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from apps.data_center.domain.egress_routing import EgressRequestContext
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
    ) -> object:
        """Capture, retain, and return one financial response payload."""
        ...


class TushareRelayAuthorizationError(PermissionError):
    """Raised when the configured relay rejects its API credential."""


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
    ) -> None:
        self._token = token
        self._http_url = http_url
        self._timeout_seconds = timeout_seconds
        self._provider_id = provider_id
        self._deployment_region = deployment_region.strip() or "unknown"
        self._dataset_key = dataset_key.strip()
        self._financial_response_handler = financial_response_handler
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

        request_body: dict[str, object] = {
            "api_name": normalized_api_name,
            "token": self._token,
            "params": params,
            "fields": fields,
        }
        target_url = self._http_url
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
            payload = response.json()
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
        columns = data.get("fields")
        items = data.get("items")
        if not isinstance(columns, list) or not all(isinstance(column, str) for column in columns):
            raise TushareError(
                "Tushare relay response fields are invalid",
                code="TUSHARE_INVALID_PAYLOAD",
            )
        if not isinstance(items, list):
            raise TushareError(
                "Tushare relay response items are invalid",
                code="TUSHARE_INVALID_PAYLOAD",
            )
        return pd.DataFrame(items, columns=columns)

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

        from apps.data_center.application.egress_service import execute_provider_request
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
        payload = execute_provider_request(
            context,
            method=method,
            params=params,
            json_body=json_body,
            headers={"X-API-Key": self._token},
            max_attempts=2,
        )
        return payload

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
        query_params = dict(params)
        if fields:
            query_params["fields"] = fields
        target_url = self._http_url.rstrip("/") + "/" + api_name.replace("_", "-")
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
        if data.get("has_more"):
            raise TushareError(
                "Tushare resource result is incomplete; narrow the requested range",
                code="MODEL_MARKET_INCOMPLETE_RESULT",
            )
        columns, items = data.get("fields"), data.get("items")
        if (
            not isinstance(columns, list)
            or not all(isinstance(column, str) for column in columns)
            or len(set(columns)) != len(columns)
            or not isinstance(items, list)
            or not all(isinstance(row, list) and len(row) == len(columns) for row in items)
        ):
            raise TushareError(
                "Tushare resource table shape is invalid",
                code="TUSHARE_INVALID_PAYLOAD",
            )
        return pd.DataFrame(items, columns=columns)


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
    ) -> None:
        super().__init__(
            token=token,
            http_url=http_url,
            provider_id=provider_id,
            deployment_region=deployment_region,
            dataset_key=dataset_key,
            financial_response_handler=financial_response_handler,
        )
        self._sdk_client = sdk_client
        self._legacy_bypass_url = legacy_bypass_url

    def query(self, api_name: str, fields: str = "", **params: object) -> PandasDataFrame:
        """Preserve the SDK URL/body contract while routing explicitly selected reads."""
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,127}", api_name):
            raise ValueError("Tushare API name has invalid format")
        target_url = self._http_url.rstrip("/") + "/" + api_name
        if not self._should_use_egress(target_url, api_name=api_name):
            if self._requires_financial_response_capture(api_name):
                raise TushareError(
                    "Financial raw capture requires an explicit egress route",
                    code="TUSHARE_FINANCIAL_ARTIFACT_ROUTE_REQUIRED",
                )
            _append_custom_endpoint_to_no_proxy(self._legacy_bypass_url)
            return cast(Any, self._sdk_client).query(api_name, fields=fields, **params)
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
        columns, items = data.get("fields"), data.get("items")
        if (
            not isinstance(columns, list)
            or not all(isinstance(column, str) for column in columns)
            or len(set(columns)) != len(columns)
            or not isinstance(items, list)
            or not all(isinstance(row, list) and len(row) == len(columns) for row in items)
        ):
            raise TushareError("Tushare table shape is invalid", code="TUSHARE_INVALID_PAYLOAD")
        return pd.DataFrame(items, columns=columns)


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
) -> object:
    """Create a configured Tushare Pro client inside the Data Center boundary."""

    settings = resolve_tushare_runtime_settings(
        token=token,
        http_url=http_url,
        request_mode=request_mode,
    )
    if not settings.token:
        raise ValueError("Tushare token 未配置")
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
        return client_type(
            token=settings.token,
            http_url=settings.http_url,
            provider_id=provider_id,
            deployment_region=deployment_region,
            dataset_key=dataset_key,
            financial_response_handler=financial_response_handler,
        )

    if provider_id is None:
        _append_custom_endpoint_to_no_proxy(settings.http_url)
    try:
        ts = cast(Any, import_module("tushare"))
    except ImportError as exc:
        raise ImportError("请安装 tushare: pip install tushare") from exc
    pro = ts.pro_api(settings.token)
    configured = configure_tushare_pro_client(pro, settings.http_url)
    if provider_id is None:
        return configured
    sdk_url = _validated_http_url(cast(_TushareDataApi, configured)._DataApi__http_url)
    if sdk_url is None:
        raise ValueError("Tushare SDK endpoint is unavailable")
    return _RoutedSdkClient(
        sdk_client=configured,
        token=settings.token,
        http_url=sdk_url,
        legacy_bypass_url=settings.http_url,
        provider_id=provider_id,
        deployment_region=deployment_region,
        dataset_key=dataset_key,
        financial_response_handler=financial_response_handler,
    )


__all__ = [
    "TushareFinancialResponseHandler",
    "TushareRelayAuthorizationError",
    "TushareRuntimeSettings",
    "configure_tushare_pro_client",
    "create_tushare_pro_client",
    "resolve_tushare_runtime_settings",
]
