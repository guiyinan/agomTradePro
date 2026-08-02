"""Data Center-owned optional provider SDK imports."""

from __future__ import annotations

from importlib import import_module
from types import ModuleType


def get_akshare_module() -> ModuleType:
    """Import AKShare lazily at the Data Center infrastructure boundary."""

    return import_module("akshare")

__all__ = ["get_akshare_module"]
