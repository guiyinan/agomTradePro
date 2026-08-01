"""
Tushare client helpers.

集中处理 Tushare token/http_url 解析与 Pro client 初始化。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from importlib import import_module
from typing import Any, Protocol, cast
from urllib.parse import urlsplit

import requests

from shared.config.secrets import get_secrets
from shared.config.tushare import (
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


class TushareRelayAuthorizationError(RuntimeError):
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


class _UnifiedRelayClient:
    """Tushare-compatible client for a single-URL authenticated relay."""

    def __init__(self, *, token: str, http_url: str, timeout_seconds: int = 30) -> None:
        self._token = token
        self._http_url = http_url
        self._timeout_seconds = timeout_seconds
        self._session = requests.Session()
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

        response = self._session.post(
            self._http_url,
            json={
                "api_name": normalized_api_name,
                "token": self._token,
                "params": params,
                "fields": fields,
            },
            timeout=self._timeout_seconds,
        )
        if response.status_code in {401, 403}:
            raise TushareRelayAuthorizationError(
                f"Tushare relay authorization failed with HTTP {response.status_code}"
            )
        response.raise_for_status()
        payload: object = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Tushare relay returned an invalid payload")
        if payload.get("code") != 0:
            raise RuntimeError("Tushare relay rejected the request")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("Tushare relay response is missing data")
        columns = data.get("fields")
        items = data.get("items")
        if not isinstance(columns, list) or not all(isinstance(column, str) for column in columns):
            raise RuntimeError("Tushare relay response fields are invalid")
        if not isinstance(items, list):
            raise RuntimeError("Tushare relay response items are invalid")
        return pd.DataFrame(items, columns=columns)

    def __getattr__(self, api_name: str) -> Any:
        """Expose Tushare endpoint names through the standard dynamic API."""

        if api_name.startswith("_"):
            raise AttributeError(api_name)
        return partial(self.query, api_name)


def create_tushare_pro_client(
    token: str | None = None,
    http_url: str | None = None,
    request_mode: str | None = None,
) -> object:
    """Create a configured Tushare Pro client."""
    try:
        import tushare as ts
    except ImportError as exc:
        raise ImportError("请安装 tushare: pip install tushare") from exc

    settings = resolve_tushare_runtime_settings(
        token=token,
        http_url=http_url,
        request_mode=request_mode,
    )
    if not settings.token:
        raise ValueError("Tushare token 未配置")
    if settings.request_mode == TUSHARE_REQUEST_MODE_UNIFIED_RELAY:
        if not settings.http_url:
            raise ValueError("Tushare unified relay URL 未配置")
        return _UnifiedRelayClient(
            token=settings.token,
            http_url=settings.http_url,
        )

    pro = ts.pro_api(settings.token)
    return configure_tushare_pro_client(pro, settings.http_url)
