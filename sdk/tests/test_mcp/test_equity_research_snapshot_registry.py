"""Equity research snapshot MCP registry contract."""

from types import SimpleNamespace

from agomtradepro_mcp.registry import CapabilityRegistryLoader
from agomtradepro_mcp.registry.dispatcher import CapabilityDispatcher
from agomtradepro_mcp.registry.runtime_handlers.owners.equity import (
    GOVERNED_HANDLERS,
    _internal_handler_equity_read_research_snapshot,
)


def test_equity_research_snapshot_is_low_risk_read_without_confirmation() -> None:
    manifest = CapabilityRegistryLoader().build_registry().get("equity.read.research_snapshot")

    assert manifest is not None
    assert manifest.enabled is True
    assert manifest.owner_app == "equity"
    assert manifest.risk_level == "low"
    assert manifest.requires_confirmation is False
    assert manifest.input_schema["required"] == ["stock_code"]
    assert "全部" in manifest.description


def test_research_snapshot_is_a_single_sdk_call_and_preserves_envelope(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, int]]] = []
    snapshot = {
        "status": "blocked",
        "stock_code": "002156.SZ",
        "sections": {"financials": {"status": "stale"}},
        "reliability": {"block_reason_code": "canonical_publication_stale"},
        "must_not_use_for_decision": True,
    }

    def get_research_snapshot(stock_code: str, **limits: int) -> dict[str, object]:
        calls.append((stock_code, limits))
        return snapshot

    monkeypatch.setattr(
        "agomtradepro.AgomTradeProClient",
        lambda: SimpleNamespace(
            equity=SimpleNamespace(get_research_snapshot=get_research_snapshot)
        ),
    )

    result = _internal_handler_equity_read_research_snapshot(
        "通富微电",
        history_limit=120,
        financial_limit=8,
        valuation_limit=90,
        news_limit=12,
        capital_flow_limit=30,
    )

    assert result is snapshot
    assert calls == [
        (
            "通富微电",
            {
                "history_limit": 120,
                "financial_limit": 8,
                "valuation_limit": 90,
                "news_limit": 12,
                "capital_flow_limit": 30,
            },
        )
    ]


def test_research_snapshot_executes_through_core_native_handler(monkeypatch) -> None:
    """Prove core dispatcher wiring without importing the optional MCP server."""

    snapshot = {
        "status": "partial",
        "stock_code": "002156.SZ",
        "missing_optional_sections": ["news"],
        "must_not_use_for_decision": False,
    }
    monkeypatch.setattr(
        "agomtradepro.AgomTradeProClient",
        lambda: SimpleNamespace(
            equity=SimpleNamespace(get_research_snapshot=lambda *_args, **_kwargs: snapshot)
        ),
    )
    dispatcher = CapabilityDispatcher(
        registry=CapabilityRegistryLoader().build_registry(),
        legacy_tool_caller=lambda _name, _arguments: None,
        internal_handler_caller=lambda ref, arguments: GOVERNED_HANDLERS[ref](**arguments),
        audit_logger=SimpleNamespace(
            log_governed_capability_event=lambda **_kwargs: "test-audit-log"
        ),
        role_provider=lambda: "admin",
    )

    result = dispatcher.call(
        capability_key="equity.read.research_snapshot",
        arguments={"stock_code": "通富微电"},
    )

    assert result["status"] == "completed"
    assert result["result"] is snapshot
