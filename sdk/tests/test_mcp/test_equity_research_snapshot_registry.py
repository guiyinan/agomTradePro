"""Equity research snapshot MCP registry contract."""

from agomtradepro_mcp.registry import CapabilityRegistryLoader
from agomtradepro_mcp.registry.runtime_handlers.owners.equity import (
    _internal_handler_equity_read_research_snapshot,
)


def test_equity_research_snapshot_is_low_risk_read_without_confirmation() -> None:
    manifest = CapabilityRegistryLoader().build_registry().get("equity.read.research_snapshot")

    assert manifest is not None
    assert manifest.owner_app == "equity"
    assert manifest.risk_level == "low"
    assert manifest.requires_confirmation is False
    assert manifest.input_schema["required"] == ["stock_code"]
    assert "全部" in manifest.description


class _FakeDataCenter:
    def resolve_asset(self, value):
        assert value == "通富微电"
        return {"code": "002156.SZ", "name": "通富微电", "is_active": True}

    def get_latest_quotes(self, code, strict_freshness=True, *, mode=None):
        assert code == "002156.SZ"
        assert strict_freshness is True
        assert mode == "published"
        return {
            "results": [
                {
                    "asset_code": code,
                    "current_price": 56.73,
                    "snapshot_at": "2026-07-31T08:14:24+00:00",
                    "source": "tencent",
                }
            ],
            "must_not_use_for_decision": False,
        }

    def get_price_history(self, code, limit, *, mode=None):
        assert mode == "published"
        return {"results": [{"asset_code": code, "bar_date": "2026-07-31"}], "limit": limit}

    def get_valuations(self, code, limit, *, mode=None):
        assert mode == "published"
        return {"results": [{"asset_code": code, "trade_date": "2026-07-31"}], "limit": limit}

    def get_financials(self, code, limit, *, mode=None):
        assert mode == "published"
        return {"results": [{"asset_code": code, "period_end": "2026-03-31"}], "limit": limit}

    def get_news(self, code, limit, *, mode=None):
        assert mode == "published"
        return {"results": [], "asset_code": code, "limit": limit}

    def get_capital_flows(self, code, limit, *, mode=None):
        assert mode == "published"
        return {"results": [], "asset_code": code, "limit": limit}


class _FakeClient:
    def __init__(self, *, blocked=False):
        self.data_center = _FakeDataCenter()
        self.blocked = blocked

    def get(self, path):
        assert path == "/api/decision-ready/"
        return {
            "status": "blocked" if self.blocked else "ok",
            "must_not_use_for_decision": self.blocked,
        }


def test_research_snapshot_keeps_optional_gaps_visible_without_fabrication(monkeypatch) -> None:
    monkeypatch.setattr("agomtradepro.AgomTradeProClient", _FakeClient)

    result = _internal_handler_equity_read_research_snapshot("通富微电")

    assert result["stock_code"] == "002156.SZ"
    assert result["status"] == "partial"
    assert result["must_not_use_for_decision"] is False
    assert result["missing_optional_sections"] == ["news", "capital_flows"]
    assert result["sections"]["latest_quote"]["data"]["results"][0]["current_price"] == 56.73


def test_research_snapshot_obeys_global_decision_readiness(monkeypatch) -> None:
    monkeypatch.setattr(
        "agomtradepro.AgomTradeProClient",
        lambda: _FakeClient(blocked=True),
    )

    result = _internal_handler_equity_read_research_snapshot("通富微电")

    assert result["status"] == "blocked"
    assert result["must_not_use_for_decision"] is True
    assert result["reliability"]["block_reason_code"] == "decision_readiness_blocked"


def test_research_snapshot_does_not_treat_blocked_publication_metadata_as_evidence(
    monkeypatch,
) -> None:
    """Gate metadata must not make an empty/stale required section look complete."""

    class BlockedFinancialDataCenter(_FakeDataCenter):
        def get_financials(self, code, limit, *, mode=None):
            assert mode == "published"
            return {
                "rows": [],
                "publication_id": "pub-stale",
                "must_not_use_for_decision": True,
                "blocked_reason": "canonical_publication_stale",
            }

    class BlockedFinancialClient(_FakeClient):
        def __init__(self):
            super().__init__()
            self.data_center = BlockedFinancialDataCenter()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", BlockedFinancialClient)

    result = _internal_handler_equity_read_research_snapshot("通富微电")

    assert result["status"] == "blocked"
    assert result["must_not_use_for_decision"] is True
    assert result["sections"]["financials"]["status"] == "blocked"
    assert result["sections"]["financials"]["block_reason_code"] == ("canonical_publication_stale")


def test_research_snapshot_executes_through_core_native_handler(monkeypatch) -> None:
    """Prove core-only agom_capability_call wiring via INTERNAL_GOVERNED_HANDLERS."""

    import agomtradepro_mcp.server as server_module

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", _FakeClient)
    assert "equity_read_research_snapshot" in server_module.INTERNAL_GOVERNED_HANDLERS
    agom_capability_call = server_module.CORE_DISPATCHER.call

    result = agom_capability_call(
        capability_key="equity.read.research_snapshot",
        arguments={"stock_code": "通富微电"},
    )

    assert result["status"] == "completed"
    assert result["result"]["stock_code"] == "002156.SZ"
