"""A-share universe provider resilience tests."""

from __future__ import annotations

import sys
from types import SimpleNamespace

from apps.data_center.infrastructure.a_share_universe_sync import (
    AkshareAshareCodeNameProvider,
)


def test_akshare_universe_provider_retries_transient_failure(monkeypatch) -> None:
    """A single transport-shaped failure must not defer the daily publication."""

    attempts = 0

    class _Frame:
        empty = False

        @staticmethod
        def to_dict(_orient: str) -> list[dict[str, str]]:
            return [{"code": "000001", "name": "平安银行"}]

    def load() -> _Frame:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ValueError("temporary provider response")
        return _Frame()

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(stock_info_a_code_name=load),
    )

    rows = AkshareAshareCodeNameProvider().load_code_names()

    assert attempts == 2
    assert rows == [{"code": "000001", "name": "平安银行"}]
