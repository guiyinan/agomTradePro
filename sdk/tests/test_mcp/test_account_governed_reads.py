"""Execution evidence for governed Account read fallbacks."""

from types import SimpleNamespace


def test_account_governed_read_fallbacks_use_formal_sdk(monkeypatch):
    import agomtradepro
    import agomtradepro_mcp.server as server_module

    calls: list[tuple[str, object]] = []

    account = SimpleNamespace(
        list_portfolio_records=lambda limit: (
            calls.append(("list_portfolio_records", limit)) or [{"id": 7, "name": "Core"}]
        ),
        get_portfolio_record=lambda portfolio_id: (
            calls.append(("get_portfolio_record", portfolio_id))
            or {"id": portfolio_id, "name": "Core"}
        ),
        list_position_records=lambda **kwargs: (
            calls.append(("list_position_records", kwargs))
            or [{"id": 11, "portfolio": 7, "asset_code": "510300.SH"}]
        ),
        list_transaction_records=lambda **kwargs: (
            calls.append(("list_transaction_records", kwargs))
            or [{"id": 21, "portfolio": 7, "asset_code": "510300.SH"}]
        ),
        list_capital_flow_records=lambda **kwargs: (
            calls.append(("list_capital_flow_records", kwargs))
            or [{"id": 31, "portfolio": 7, "flow_type": "deposit"}]
        ),
    )
    monkeypatch.setattr(
        agomtradepro,
        "AgomTradeProClient",
        lambda: SimpleNamespace(account=account),
    )

    catalog = server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["account_read_portfolio_catalog"](
        limit=25
    )
    detail = server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["account_read_portfolio_detail"](
        portfolio_id=7
    )
    positions = server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["account_read_position_records"](
        portfolio_id=7,
        include_closed=True,
        limit=20,
    )
    transactions = server_module.INTERNAL_LEGACY_TOOL_FALLBACKS["account_read_transaction_records"](
        portfolio_id=7,
        limit=30,
    )
    capital_flows = server_module.INTERNAL_LEGACY_TOOL_FALLBACKS[
        "account_read_capital_flow_records"
    ](
        portfolio_id=7,
        limit=40,
    )

    assert catalog["portfolios"][0]["id"] == 7
    assert detail["positions"][0]["id"] == 11
    assert positions["total_count"] == 1
    assert transactions["transactions"][0]["id"] == 21
    assert capital_flows["capital_flows"][0]["id"] == 31
    assert calls == [
        ("list_portfolio_records", 25),
        ("get_portfolio_record", 7),
        (
            "list_position_records",
            {"portfolio_id": 7, "include_closed": False, "limit": 200},
        ),
        (
            "list_position_records",
            {"portfolio_id": 7, "include_closed": True, "limit": 20},
        ),
        ("list_transaction_records", {"portfolio_id": 7, "limit": 30}),
        ("list_capital_flow_records", {"portfolio_id": 7, "limit": 40}),
    ]
