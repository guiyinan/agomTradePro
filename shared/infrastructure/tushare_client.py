"""
Tushare client helpers.

集中处理 Tushare token/http_url 解析与 Pro client 初始化。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, cast
from urllib.parse import urlsplit

from shared.config.secrets import get_secrets


@dataclass(frozen=True)
class TushareRuntimeSettings:
    """Resolved runtime settings for Tushare."""

    token: str
    http_url: str | None = None


class _TushareDataApi(Protocol):
    """Private URL field exposed by Tushare's untyped DataApi client."""

    _DataApi__http_url: str


def resolve_tushare_runtime_settings(
    token: str | None = None,
    http_url: str | None = None,
) -> TushareRuntimeSettings:
    """Resolve token/http_url from explicit args or configured secrets."""
    secrets = None
    try:
        secrets = get_secrets().data_sources
    except OSError:
        secrets = None

    resolved_token = token if token is not None else (secrets.tushare_token if secrets else "")
    resolved_http_url = (
        http_url if http_url is not None else (secrets.tushare_http_url if secrets else None)
    )
    normalized_token = resolved_token.strip()
    if len(normalized_token) > 10_000 or any(ord(char) < 32 for char in normalized_token):
        raise ValueError("Tushare token has invalid format")
    return TushareRuntimeSettings(
        token=normalized_token,
        http_url=_validated_http_url(resolved_http_url),
    )


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


def create_tushare_pro_client(
    token: str | None = None,
    http_url: str | None = None,
) -> object:
    """Create a configured Tushare Pro client."""
    try:
        import tushare as ts
    except ImportError as exc:
        raise ImportError("请安装 tushare: pip install tushare") from exc

    settings = resolve_tushare_runtime_settings(token=token, http_url=http_url)
    if not settings.token:
        raise ValueError("Tushare token 未配置")

    pro = ts.pro_api(settings.token)
    return configure_tushare_pro_client(pro, settings.http_url)
