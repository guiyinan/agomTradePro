# ruff: noqa: F403, F405
"""Split tests from test_core_registry.py: owner_hedge."""

from .core_registry_support import *


def test_hedge_read_fallbacks_normalize_sdk_results(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro
    import agomtradepro_mcp.server as server_module

    hedge = SimpleNamespace(
        get_correlation_matrix=lambda asset_codes, window_days: {
            "asset_codes": asset_codes,
            "window_days": window_days,
            "matrix": {
                asset_codes[0]: {
                    asset_codes[0]: 1.0,
                    asset_codes[1]: -0.42,
                }
            },
        },
        get_all_pairs=lambda: [{"id": 2, "name": "股债对冲"}],
        get_pair_info=lambda pair_name: {
            "id": 2,
            "name": pair_name,
            "hedge_method": "beta",
        },
        get_alerts=lambda: [{"id": 9, "severity": "warning"}],
        get_portfolio_state=lambda pair_name: {
            "pair_name": pair_name,
            "hedge_effectiveness": 0.72,
        },
    )
    monkeypatch.setattr(
        agomtradepro,
        "AgomTradeProClient",
        lambda: SimpleNamespace(hedge=hedge),
    )

    matrix = server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["hedge_compute_correlation_matrix"](
        ["510300", "511260"],
        30,
    )
    pair_catalog = server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["hedge_read_pair_catalog"]()
    pair_detail = server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["hedge_read_pair_detail"]("股债对冲")
    alert_list = server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["hedge_read_alert_list"]()
    portfolio_state = server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["hedge_read_portfolio_state"](
        "股债对冲"
    )

    assert matrix["matrix"]["510300"]["511260"] == -0.42
    assert pair_catalog["total_count"] == 1
    assert pair_detail["pair"]["hedge_method"] == "beta"
    assert alert_list["query"] == {
        "days": 7,
        "is_resolved": False,
    }
    assert portfolio_state["state"]["hedge_effectiveness"] == 0.72
