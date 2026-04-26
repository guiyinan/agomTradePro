"""Repository providers for macro application consumers."""

from __future__ import annotations

from apps.macro.infrastructure.providers import (
    DjangoMacroRepository,
    MacroIndicatorReadRepository,
)


def get_macro_repository() -> DjangoMacroRepository:
    """Return the configured macro repository implementation."""

    return DjangoMacroRepository()


def get_macro_read_repository() -> MacroIndicatorReadRepository:
    """Return the configured macro read repository implementation."""

    return MacroIndicatorReadRepository()
