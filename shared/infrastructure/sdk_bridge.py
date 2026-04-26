"""Shared bridges for optional third-party SDK imports."""

from __future__ import annotations


def get_akshare_module():
    """Import and return the AKShare module lazily."""

    import akshare as ak

    return ak
