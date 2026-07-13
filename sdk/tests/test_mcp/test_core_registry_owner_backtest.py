# ruff: noqa: F403, F405
"""Split tests from test_core_registry.py: owner_backtest."""

from .core_registry_support import *


def test_backtest_core_only_fallbacks_use_canonical_sdk_methods(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    calls: list[tuple[str, object]] = []

    class _Backtest:
        def get_result(self, backtest_id):
            calls.append(("get_result", backtest_id))
            return SimpleNamespace(
                id=backtest_id,
                status="completed",
                total_return=0.12,
                annual_return=0.08,
                max_drawdown=-0.05,
                sharpe_ratio=1.4,
            )

        def list_backtests(self, **kwargs):
            calls.append(("list_backtests", kwargs))
            return [
                SimpleNamespace(
                    id=17,
                    status="completed",
                    total_return=0.12,
                    annual_return=0.08,
                    max_drawdown=-0.05,
                    sharpe_ratio=1.4,
                )
            ]

    class _Client:
        backtest = _Backtest()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _Client())

    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["get_backtest_result"](17) == {
        "id": 17,
        "status": "completed",
        "total_return": 0.12,
        "annual_return": 0.08,
        "max_drawdown": -0.05,
        "sharpe_ratio": 1.4,
    }
    assert server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["list_backtests"]("completed", 10) == {
        "backtests": [
            {
                "id": 17,
                "status": "completed",
                "total_return": 0.12,
                "annual_return": 0.08,
                "max_drawdown": -0.05,
                "sharpe_ratio": 1.4,
            }
        ],
        "total_count": 1,
    }
    assert calls == [
        ("get_result", 17),
        ("list_backtests", {"status": "completed", "limit": 10}),
    ]
