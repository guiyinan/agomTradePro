# ruff: noqa: F403, F405
"""Core-only read matrix for realtime."""

from .core_registry_support import *


@pytest.mark.parametrize(
    (
        "state",
        "results",
        "scope_available",
        "requested",
        "qualified",
        "unavailable",
        "rankable",
        "unrankable",
        "reason",
    ),
    [
        (
            "partial",
            [{"asset_code": "510300.SH", "current_price": 3.5, "change_pct": 1.2}],
            True,
            4,
            1,
            3,
            1,
            0,
            "monitored_cached_prices_incomplete",
        ),
        ("blocked", [], True, 0, 0, 0, 0, 0, "monitored_asset_scope_empty"),
        (
            "blocked",
            [],
            False,
            None,
            None,
            None,
            None,
            None,
            "monitored_price_scope_unavailable",
        ),
    ],
    ids=["partial", "resolved-empty", "unknown-scope"],
)
def test_realtime_top_movers_read_matrix_preserves_scope_contract(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
    state: str,
    results: list[dict[str, object]],
    scope_available: bool,
    requested: int | None,
    qualified: int | None,
    unavailable: int | None,
    rankable: int | None,
    unrankable: int | None,
    reason: str,
) -> None:
    """Verify the default core registry transports rich Top Movers evidence."""

    from agomtradepro import ServerError

    payload: dict[str, object] = {
        "results": results,
        "count": len(results),
        "source": "cached_monitored_prices",
        "scope": "all_monitored_assets",
        "scope_available": scope_available,
        "requested": requested,
        "qualified": qualified,
        "unavailable": unavailable,
        "rankable": rankable,
        "unrankable": unrankable,
        "outcome": state,
        "is_reliable": False,
        "is_stale": None,
        "must_not_use_for_decision": True,
        "blocked_reason": reason,
    }

    class _Realtime:
        @staticmethod
        def get_top_movers_payload(direction: str, limit: int) -> dict[str, object]:
            assert direction == "down"
            assert limit == 5
            if not scope_available:
                raise ServerError(status_code=503, response=payload)
            return payload

    monkeypatch.setattr(
        "agomtradepro.AgomTradeProClient",
        lambda: SimpleNamespace(realtime=_Realtime()),
    )
    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": "realtime.read.top_movers",
                "arguments": {"direction": "down", "limit": 5},
            },
        )
    )

    rendered = str(result)
    assert "realtime.read.top_movers" in rendered
    assert state in rendered
    assert reason in rendered
    assert "must_not_use_for_decision" in rendered
    assert "scope_available" in rendered
    assert "requested" in rendered
    assert "qualified" in rendered
    assert "unavailable" in rendered
    assert "rankable" in rendered
    assert "unrankable" in rendered
    assert "movers" in rendered
    assert "total_count" in rendered


@pytest.mark.parametrize(
    (
        "capability_key",
        "executor_ref",
        "legacy_tool_names",
        "arguments",
        "payload",
        "expected",
    ),
    [
        (
            "realtime.read.price",
            "get_realtime_price",
            ("get_realtime_price",),
            {"asset_code": "510300.SH"},
            {
                "asset_code": "510300.SH",
                "current_price": 4.25,
                "price_change_percent": 0.83,
                "updated_at": "2026-07-10T14:30:00+08:00",
                "source": "core-only-fallback",
            },
            "4.25",
        ),
        (
            "realtime.read.price_batch",
            "get_multiple_realtime_prices",
            ("get_multiple_realtime_prices",),
            {"asset_codes": ["510300.SH", "159915.SZ"]},
            {
                "prices": {
                    "510300.SH": {"current_price": 4.25},
                    "159915.SZ": {"current_price": 2.18},
                },
                "total_count": 2,
                "source": "core-only-fallback",
            },
            "159915.SZ",
        ),
        (
            "realtime.read.market_summary",
            "get_market_summary",
            ("get_market_summary",),
            {},
            {
                "success": True,
                "stats_available": False,
                "sh_index": 3200.5,
                "cyb_index": 2100.1,
                "source": "core-only-fallback",
            },
            "3200.5",
        ),
    ],
)
def test_agom_capability_call_reads_data_family_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
    capability_key,
    executor_ref,
    legacy_tool_names,
    arguments,
    payload,
    expected,
):
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        executor_ref,
        lambda **kwargs: payload,
    )
    assert all(legacy_tool_names)

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": capability_key,
                "arguments": arguments,
            },
        )
    )

    rendered = str(result)
    assert capability_key in rendered
    assert expected in rendered
    assert "core-only-fallback" in rendered
