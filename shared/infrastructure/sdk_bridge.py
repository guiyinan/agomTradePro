"""Shared bridges for optional third-party SDK imports."""

from __future__ import annotations

from importlib import import_module
from types import ModuleType


def get_akshare_module() -> ModuleType:
    """Import and return the AKShare module lazily."""

    return import_module("akshare")
