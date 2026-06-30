"""Repository providers for macro application consumers."""

from __future__ import annotations


def get_macro_repository():
    """Return the configured macro repository implementation."""

    from apps.macro.infrastructure.providers import DjangoMacroRepository

    return DjangoMacroRepository()


def get_macro_read_repository():
    """Return the configured macro read repository implementation."""

    from apps.macro.infrastructure.providers import MacroIndicatorReadRepository

    return MacroIndicatorReadRepository()


def build_default_macro_adapter():
    """Build the default macro data adapter chain."""

    from apps.macro.infrastructure.adapters import create_default_adapter

    return create_default_adapter()


def build_akshare_macro_adapter():
    """Build the AKShare macro adapter."""

    from apps.macro.infrastructure.adapters import AKShareAdapter

    return AKShareAdapter()


def build_tushare_macro_adapter(*, token: str | None = None, http_url: str | None = None):
    """Build the Tushare macro adapter."""

    from apps.macro.infrastructure.adapters import TushareAdapter

    if token is None and http_url is None:
        return TushareAdapter()
    return TushareAdapter(token=token, http_url=http_url)
