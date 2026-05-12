"""
Tushare client helpers.

集中处理 Tushare token/http_url 解析与 Pro client 初始化。
"""

from __future__ import annotations

from dataclasses import dataclass

from shared.config.secrets import get_secrets


@dataclass(frozen=True)
class TushareRuntimeSettings:
    """Resolved runtime settings for Tushare."""

    token: str
    http_url: str | None = None


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
        http_url
        if http_url is not None
        else (secrets.tushare_http_url if secrets else None)
    )
    return TushareRuntimeSettings(
        token=resolved_token.strip(),
        http_url=(resolved_http_url or "").strip() or None,
    )


def configure_tushare_pro_client(pro: object, http_url: str | None) -> object:
    """Apply custom DataApi HTTP URL to an existing Tushare Pro client."""
    normalized_http_url = (http_url or "").strip()
    if normalized_http_url:
        pro._DataApi__http_url = normalized_http_url
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
