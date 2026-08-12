"""Pure unit tests for the equity research snapshot application use case."""

from collections.abc import Mapping

import pytest

from apps.equity.application.research_snapshot import (
    EquityResearchSnapshotRequest,
    EquityResearchSnapshotUseCase,
    ReadPayload,
)


class FakeResearchSnapshotReader:
    def __init__(self) -> None:
        self.readiness: ReadPayload = {"status": "ok", "must_not_use_for_decision": False}
        self.identity: ReadPayload = {
            "code": "002156.SZ",
            "name": "通富微电",
            "is_active": True,
        }
        self.overrides: dict[str, ReadPayload | Exception] = {}
        self.calls: list[tuple[str, str, int | bool | None]] = []

    def _payload(self, name: str, default: ReadPayload) -> ReadPayload:
        value = self.overrides.get(name, default)
        if isinstance(value, Exception):
            raise value
        return value

    def resolve_asset(self, stock_code: str) -> ReadPayload:
        self.calls.append(("identity", stock_code, None))
        return self._payload("identity", self.identity)

    def get_decision_readiness(self) -> ReadPayload:
        return self._payload("readiness", self.readiness)

    def get_latest_quotes(self, stock_code: str, *, strict_freshness: bool = True) -> ReadPayload:
        self.calls.append(("latest_quote", stock_code, strict_freshness))
        return self._payload("latest_quote", {"results": [{"asset_code": stock_code}]})

    def get_price_history(self, stock_code: str, *, limit: int) -> ReadPayload:
        self.calls.append(("price_history", stock_code, limit))
        return self._payload("price_history", {"results": [{"bar_date": "2026-07-31"}]})

    def get_valuations(self, stock_code: str, *, limit: int) -> ReadPayload:
        self.calls.append(("valuation", stock_code, limit))
        return self._payload("valuation", {"results": [{"trade_date": "2026-07-31"}]})

    def get_financials(self, stock_code: str, *, limit: int) -> ReadPayload:
        self.calls.append(("financials", stock_code, limit))
        return self._payload("financials", {"results": [{"period_end": "2026-03-31"}]})

    def get_news(self, stock_code: str, *, limit: int) -> ReadPayload:
        self.calls.append(("news", stock_code, limit))
        return self._payload("news", {"results": [{"headline": "news"}]})

    def get_capital_flows(self, stock_code: str, *, limit: int) -> ReadPayload:
        self.calls.append(("capital_flows", stock_code, limit))
        return self._payload("capital_flows", {"results": [{"net_inflow": 1.0}]})


def test_snapshot_resolves_name_and_forwards_all_bounded_limits() -> None:
    reader = FakeResearchSnapshotReader()
    result = EquityResearchSnapshotUseCase(reader).execute(
        EquityResearchSnapshotRequest(
            stock_code=" 通富微电 ",
            history_limit=101,
            financial_limit=11,
            valuation_limit=102,
            news_limit=12,
            capital_flow_limit=103,
        )
    )

    assert result.status == "fresh"
    assert result.stock_code == "002156.SZ"
    assert result.must_not_use_for_decision is False
    assert reader.calls == [
        ("identity", "通富微电", None),
        ("latest_quote", "002156.SZ", True),
        ("price_history", "002156.SZ", 101),
        ("valuation", "002156.SZ", 102),
        ("financials", "002156.SZ", 11),
        ("news", "002156.SZ", 12),
        ("capital_flows", "002156.SZ", 103),
    ]


def test_optional_gaps_are_partial_but_decision_usable() -> None:
    reader = FakeResearchSnapshotReader()
    reader.overrides.update({"news": {"results": []}, "capital_flows": {"rows": []}})

    payload = (
        EquityResearchSnapshotUseCase(reader)
        .execute(EquityResearchSnapshotRequest("通富微电"))
        .to_payload()
    )

    assert payload["status"] == "partial"
    assert payload["must_not_use_for_decision"] is False
    assert payload["missing_optional_sections"] == ["news", "capital_flows"]


@pytest.mark.parametrize(
    ("financial_payload", "reason"),
    [
        (
            {"rows": [], "must_not_use_for_decision": True, "blocked_reason": "pub_stale"},
            "pub_stale",
        ),
        ({"rows": [{"value": 1}], "freshness_status": "stale"}, "section_freshness_stale"),
        ({"rows": [{"value": 1}], "reliability": {"status": "stale"}}, "section_status_stale"),
        (
            {"rows": [], "publication_id": "empty", "freshness_status": "fresh"},
            "section_evidence_missing",
        ),
    ],
)
def test_core_section_fail_closed_for_publication_freshness_and_empty_evidence(
    financial_payload: Mapping[str, object], reason: str
) -> None:
    reader = FakeResearchSnapshotReader()
    reader.overrides["financials"] = financial_payload

    payload = (
        EquityResearchSnapshotUseCase(reader)
        .execute(EquityResearchSnapshotRequest("通富微电"))
        .to_payload()
    )
    sections = payload["sections"]

    assert payload["status"] == "blocked"
    assert payload["must_not_use_for_decision"] is True
    assert isinstance(sections, dict)
    assert sections["financials"]["block_reason_code"] == reason
    assert payload["reliability"]["block_reason_code"] == "equity_core_evidence_incomplete"


def test_global_readiness_block_takes_precedence() -> None:
    reader = FakeResearchSnapshotReader()
    reader.readiness = {"status": "blocked", "must_not_use_for_decision": True}

    result = EquityResearchSnapshotUseCase(reader).execute(
        EquityResearchSnapshotRequest("002156.SZ")
    )

    assert result.status == "blocked"
    assert result.reliability["block_reason_code"] == "decision_readiness_blocked"


def test_unresolved_identity_stops_before_section_reads() -> None:
    reader = FakeResearchSnapshotReader()
    reader.identity = None

    payload = (
        EquityResearchSnapshotUseCase(reader)
        .execute(EquityResearchSnapshotRequest("不存在"))
        .to_payload()
    )

    assert payload["stock_code"] is None
    assert payload["status"] == "missing"
    assert payload["sections"] == {}
    assert payload["reliability"]["block_reason_code"] == "equity_identity_unresolved"
    assert reader.calls == [("identity", "不存在", None)]


def test_required_upstream_exception_is_a_stable_block() -> None:
    reader = FakeResearchSnapshotReader()
    reader.overrides["valuation"] = RuntimeError("provider secret")

    payload = (
        EquityResearchSnapshotUseCase(reader)
        .execute(EquityResearchSnapshotRequest("002156.SZ"))
        .to_payload()
    )
    sections = payload["sections"]

    assert isinstance(sections, dict)
    assert sections["valuation"] == {
        "status": "failed",
        "required": True,
        "data": None,
        "must_not_use_for_decision": True,
        "block_reason_code": "upstream_read_failed",
    }


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("history_limit", 0),
        ("financial_limit", 101),
        ("valuation_limit", True),
        ("news_limit", 0),
        ("capital_flow_limit", 1001),
    ],
)
def test_request_rejects_invalid_limits(field_name: str, value: int | bool) -> None:
    kwargs = {field_name: value}
    with pytest.raises(ValueError):
        EquityResearchSnapshotRequest(stock_code="002156.SZ", **kwargs)
