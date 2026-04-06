"""Bridges legacy modules to external SDK imports within data_center only."""

from __future__ import annotations


def get_akshare_module():
    import akshare as ak

    return ak
