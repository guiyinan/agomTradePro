"""Pure unit tests for the equity research snapshot application use case."""

from collections.abc import Mapping
from dataclasses import replace

import pytest

from apps.equity.application.research_snapshot import (
    EquityResearchSnapshotRequest,
    EquityResearchSnapshotResult,
    EquityResearchSnapshotUseCase,
    ReadPayload,
)


def _verified_quote_payload(asset_code: str) -> dict[str, object]:
    return {
        "asset_code": asset_code,
        "snapshot_at": "2026-10-27T09:30:00+08:00",
        "current_price": 12.34,
        "publication_id": "quote-publication-001",
        "must_not_use_for_decision": False,
    }


def _verified_price_history_payload(asset_code: str) -> dict[str, object]:
    return {
        "rows": [
            {
                "asset_code": asset_code,
                "timestamp": "2026-10-27",
                "close": 12.30,
            }
        ],
        "publication_id": "price-publication-001",
        "must_not_use_for_decision": False,
    }


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
        return self._payload("latest_quote", _verified_quote_payload(stock_code))

    def get_price_history(self, stock_code: str, *, limit: int) -> ReadPayload:
        self.calls.append(("price_history", stock_code, limit))
        return self._payload("price_history", _verified_price_history_payload(stock_code))

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
    assert result.to_payload()["outcome"] == "success"
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
    assert payload["outcome"] == "partial"
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
    assert payload["outcome"] == "blocked"
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
    assert payload["outcome"] == "blocked"
    assert payload["sections"] == {}
    assert payload["reliability"]["block_reason_code"] == "equity_identity_unresolved"
    assert reader.calls == [("identity", "不存在", None)]
    assert payload["capabilities"]["market_research"]["status"] == "blocked"
    assert payload["capabilities"]["plan_calculation"] == {
        "status": "not_evaluated",
        "reason_codes": ["account_context_required"],
        "evidence_sections": [],
    }


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


def test_unknown_owner_status_is_conservatively_blocked_without_rewriting_status() -> None:
    reader = FakeResearchSnapshotReader()
    result = EquityResearchSnapshotUseCase(reader).execute(
        EquityResearchSnapshotRequest("002156.SZ")
    )
    unknown_status = replace(result, status="unknown")

    payload = unknown_status.to_payload()

    assert payload["status"] == "unknown"
    assert payload["outcome"] == "blocked"


@pytest.mark.parametrize("owner_status", ["fresh", "partial"])
def test_restricted_fresh_or_partial_state_cannot_publish_success(owner_status: str) -> None:
    reader = FakeResearchSnapshotReader()
    result = EquityResearchSnapshotUseCase(reader).execute(
        EquityResearchSnapshotRequest("002156.SZ")
    )
    restricted = replace(
        result,
        status=owner_status,
        must_not_use_for_decision=True,
    )

    payload = restricted.to_payload()

    assert payload["status"] == owner_status
    assert payload["must_not_use_for_decision"] is True
    assert payload["outcome"] == "blocked"


def test_snapshot_payload_preserves_sections_source_times_and_reliability() -> None:
    reader = FakeResearchSnapshotReader()
    quote_payload: ReadPayload = {
        "results": [
            {
                "asset_code": "002156.SZ",
                "current_price": 12.34,
                "snapshot_at": "2026-10-17T09:30:00+08:00",
            }
        ],
        "observed_at": "2026-10-17T09:30:00+08:00",
        "available_at": "2026-10-17T09:30:01+08:00",
        "fetched_at": "2026-10-17T09:30:02+08:00",
    }
    reader.overrides["latest_quote"] = quote_payload

    payload = (
        EquityResearchSnapshotUseCase(reader)
        .execute(EquityResearchSnapshotRequest("002156.SZ"))
        .to_payload()
    )

    assert payload["status"] == "fresh"
    assert payload["outcome"] == "success"
    assert payload["sections"]["latest_quote"]["data"] == quote_payload
    assert payload["reliability"]["status"] == "fresh"
    assert payload["reliability"]["source"] == "agomtradepro_api"


def _financial_publication_payload(
    *,
    publication_outcome: str,
    selected_count: int,
    missing_count: int,
    freshness_status: str = "fresh",
    must_not_use_for_decision: bool = False,
    blocked_reason: str = "",
) -> dict[str, object]:
    """Build the existing published-financial payload with coherent four-target coverage."""

    rows: list[dict[str, object]] = [
        {
            "asset_code": "002156.SZ",
            "period_end": "2026-06-30",
            "period_type": "quarterly",
            "metric_code": f"metric_{index}",
            "value": 100.0 + index,
            "unit": "CNY",
            "source": "unit-test-source",
            "report_date": None,
            "available_at": None,
            "fetched_at": "2026-10-18T08:00:00+00:00",
            "extra": {},
            "source_evidence": None,
            "decision_evidence": None,
        }
        for index in range(selected_count)
    ]
    return {
        "rows": rows,
        "publication_id": "financial-publication-001",
        "dataset_key": "equity.financial.fact",
        "publication_key": "current",
        "publication_hash": "a" * 64,
        "published_at": "2026-10-18T08:05:00+00:00",
        "as_of": "2026-10-18T08:00:00+00:00",
        "must_not_use_for_decision": must_not_use_for_decision,
        "blocked_reason": blocked_reason,
        "policy_identity": "financial-policy-v1",
        "policy_version": "financial-policy-v1",
        "selected_source": "unit-test-source",
        "publication_run_id": "financial-run-001",
        "coverage_requested_count": 4,
        "coverage_eligible_count": 4,
        "coverage_selected_count": selected_count,
        "coverage_missing_count": missing_count,
        "publication_outcome": publication_outcome,
        "freshness_status": freshness_status,
        "freshness_scope": "asset",
        "asset_code": "002156.SZ",
    }


def test_partial_financial_publication_preserves_coverage_and_is_usable_partial() -> None:
    reader = FakeResearchSnapshotReader()
    financial_payload = _financial_publication_payload(
        publication_outcome="partial",
        selected_count=3,
        missing_count=1,
    )
    reader.overrides["financials"] = financial_payload

    payload = (
        EquityResearchSnapshotUseCase(reader)
        .execute(EquityResearchSnapshotRequest("002156.SZ"))
        .to_payload()
    )
    sections = payload["sections"]
    assert isinstance(sections, dict)
    financials = sections["financials"]
    assert isinstance(financials, dict)

    assert payload["status"] == "partial"
    assert payload["outcome"] == "partial"
    assert payload["must_not_use_for_decision"] is False
    assert payload["missing_optional_sections"] == []
    assert payload["reliability"]["status"] == "partial"
    assert financials["status"] == "partial"
    assert financials["required"] is True
    assert financials["must_not_use_for_decision"] is False
    assert financials["data"] == financial_payload
    assert financials["block_reason_code"] == ""


@pytest.mark.parametrize(
    ("freshness_status", "must_not_use_for_decision", "blocked_reason", "expected_reason"),
    [
        ("stale", False, "", "section_freshness_stale"),
        ("fresh", True, "financial_publication_blocked", "financial_publication_blocked"),
    ],
)
def test_financial_publication_blockers_take_precedence_over_partial_outcome(
    freshness_status: str,
    must_not_use_for_decision: bool,
    blocked_reason: str,
    expected_reason: str,
) -> None:
    reader = FakeResearchSnapshotReader()
    financial_payload = _financial_publication_payload(
        publication_outcome="partial",
        selected_count=3,
        missing_count=1,
        freshness_status=freshness_status,
        must_not_use_for_decision=must_not_use_for_decision,
        blocked_reason=blocked_reason,
    )
    reader.overrides["financials"] = financial_payload

    payload = (
        EquityResearchSnapshotUseCase(reader)
        .execute(EquityResearchSnapshotRequest("002156.SZ"))
        .to_payload()
    )
    sections = payload["sections"]
    assert isinstance(sections, dict)
    financials = sections["financials"]
    assert isinstance(financials, dict)

    assert payload["status"] == "blocked"
    assert payload["outcome"] == "blocked"
    assert payload["must_not_use_for_decision"] is True
    assert payload["reliability"]["block_reason_code"] == "equity_core_evidence_incomplete"
    assert financials["status"] == "blocked"
    assert financials["must_not_use_for_decision"] is True
    assert financials["block_reason_code"] == expected_reason
    assert financials["data"] == financial_payload


def test_global_readiness_block_takes_precedence_over_partial_financial_publication() -> None:
    reader = FakeResearchSnapshotReader()
    reader.readiness = {
        "status": "blocked",
        "must_not_use_for_decision": True,
        "block_reason_code": "strict_readiness_block",
    }
    financial_payload = _financial_publication_payload(
        publication_outcome="partial",
        selected_count=3,
        missing_count=1,
    )
    reader.overrides["financials"] = financial_payload

    payload = (
        EquityResearchSnapshotUseCase(reader)
        .execute(EquityResearchSnapshotRequest("002156.SZ"))
        .to_payload()
    )
    sections = payload["sections"]
    assert isinstance(sections, dict)
    financials = sections["financials"]
    assert isinstance(financials, dict)

    assert payload["status"] == "blocked"
    assert payload["outcome"] == "blocked"
    assert payload["must_not_use_for_decision"] is True
    assert payload["reliability"]["block_reason_code"] == "decision_readiness_blocked"
    assert financials["data"] == financial_payload


def test_complete_success_financial_publication_remains_fresh() -> None:
    reader = FakeResearchSnapshotReader()
    financial_payload = _financial_publication_payload(
        publication_outcome="success",
        selected_count=4,
        missing_count=0,
    )
    reader.overrides["financials"] = financial_payload

    payload = (
        EquityResearchSnapshotUseCase(reader)
        .execute(EquityResearchSnapshotRequest("002156.SZ"))
        .to_payload()
    )
    sections = payload["sections"]
    assert isinstance(sections, dict)
    financials = sections["financials"]
    assert isinstance(financials, dict)

    assert payload["status"] == "fresh"
    assert payload["outcome"] == "success"
    assert payload["must_not_use_for_decision"] is False
    assert payload["missing_optional_sections"] == []
    assert financials["status"] == "fresh"
    assert financials["data"] == financial_payload


def test_capabilities_distinguish_observation_from_uninvoked_analysis() -> None:
    payload = (
        EquityResearchSnapshotUseCase(FakeResearchSnapshotReader())
        .execute(EquityResearchSnapshotRequest("002156.SZ"))
        .to_payload()
    )
    capabilities = payload["capabilities"]

    assert capabilities == {
        "market_research": {
            "status": "observation_only",
            "reason_codes": ["published_market_evidence_observed"],
            "evidence_sections": ["latest_quote", "price_history"],
        },
        "technical_scoring": {
            "status": "not_evaluated",
            "reason_codes": ["technical_score_not_evaluated"],
            "evidence_sections": ["price_history"],
        },
        "financial_valuation": {
            "status": "not_evaluated",
            "reason_codes": ["valuation_calculation_not_evaluated"],
            "evidence_sections": ["price_history", "valuation", "financials"],
        },
        "plan_calculation": {
            "status": "not_evaluated",
            "reason_codes": ["account_context_required"],
            "evidence_sections": [],
        },
        "order_submission": {
            "status": "not_evaluated",
            "reason_codes": ["account_context_required"],
            "evidence_sections": [],
        },
    }
    assert payload["must_not_use_for_decision"] is False


def test_existing_result_construction_defaults_to_no_inferred_capabilities() -> None:
    result = EquityResearchSnapshotUseCase(FakeResearchSnapshotReader()).execute(
        EquityResearchSnapshotRequest("002156.SZ")
    )
    legacy_result = EquityResearchSnapshotResult(
        status=result.status,
        stock_code=result.stock_code,
        identity=result.identity,
        sections=result.sections,
        decision_readiness=result.decision_readiness,
        missing_optional_sections=result.missing_optional_sections,
        reliability=result.reliability,
        must_not_use_for_decision=result.must_not_use_for_decision,
    )

    assert legacy_result.to_payload()["capabilities"] == {}


def test_local_financial_evidence_gap_does_not_hide_verified_market_observation() -> None:
    reader = FakeResearchSnapshotReader()
    reader.overrides["financials"] = {"rows": []}

    payload = (
        EquityResearchSnapshotUseCase(reader)
        .execute(EquityResearchSnapshotRequest("002156.SZ"))
        .to_payload()
    )
    capabilities = payload["capabilities"]

    assert payload["must_not_use_for_decision"] is True
    assert capabilities["market_research"]["status"] == "observation_only"
    assert capabilities["financial_valuation"] == {
        "status": "blocked",
        "reason_codes": ["section_evidence_missing"],
        "evidence_sections": ["price_history", "valuation", "financials"],
    }


@pytest.mark.parametrize(
    "readiness",
    [
        {"status": "blocked", "must_not_use_for_decision": True},
        {"status": "ok"},
        {"status": "ok", "must_not_use_for_decision": 0},
        {"status": "ok", "must_not_use_for_decision": "False"},
    ],
)
def test_capability_requires_an_explicit_false_readiness_gate(
    readiness: dict[str, object],
) -> None:
    reader = FakeResearchSnapshotReader()
    reader.readiness = readiness

    payload = (
        EquityResearchSnapshotUseCase(reader)
        .execute(EquityResearchSnapshotRequest("002156.SZ"))
        .to_payload()
    )

    assert payload["must_not_use_for_decision"] is True
    assert payload["reliability"]["block_reason_code"] == "decision_readiness_blocked"
    assert payload["capabilities"]["market_research"] == {
        "status": "blocked",
        "reason_codes": ["decision_readiness_blocked"],
        "evidence_sections": ["latest_quote", "price_history"],
    }


def test_blocked_identity_with_code_cannot_publish_market_observation() -> None:
    reader = FakeResearchSnapshotReader()
    reader.overrides["identity"] = {
        "code": "002156.SZ",
        "name": "通富微电",
        "must_not_use_for_decision": True,
        "blocked_reason": "identity_scope_blocked",
    }

    payload = (
        EquityResearchSnapshotUseCase(reader)
        .execute(EquityResearchSnapshotRequest("002156.SZ"))
        .to_payload()
    )

    assert payload["must_not_use_for_decision"] is True
    assert payload["reliability"]["block_reason_code"] == "identity_scope_blocked"
    assert payload["capabilities"]["market_research"] == {
        "status": "blocked",
        "reason_codes": ["identity_scope_blocked"],
        "evidence_sections": ["latest_quote", "price_history"],
    }


@pytest.mark.parametrize(
    ("section_name", "payload_value", "expected_reason"),
    [
        (
            "latest_quote",
            {
                "asset_code": "002156.SZ",
                "current_price": 12.34,
                "publication_id": "quote-publication-001",
            },
            "market_publication_gate_unverified",
        ),
        (
            "latest_quote",
            {
                "asset_code": "002156.SZ",
                "current_price": 12.34,
                "must_not_use_for_decision": False,
            },
            "market_publication_id_missing",
        ),
        (
            "latest_quote",
            {
                "asset_code": "002156.SZ",
                "current_price": 12.34,
                "publication_id": "quote-publication-001",
                "must_not_use_for_decision": 0,
                "snapshot_at": "2026-10-27T09:30:00+08:00",
            },
            "market_publication_gate_unverified",
        ),
        (
            "latest_quote",
            {
                "asset_code": "002156.SZ",
                "current_price": 12.34,
                "publication_id": "quote-publication-001",
                "must_not_use_for_decision": "False",
                "snapshot_at": "2026-10-27T09:30:00+08:00",
            },
            "market_publication_gate_unverified",
        ),
        (
            "latest_quote",
            {
                "asset_code": "002156.SZ",
                "current_price": 12.34,
                "publication_id": "quote-publication-001",
                "must_not_use_for_decision": False,
            },
            "market_quote_snapshot_time_unverified",
        ),
        (
            "latest_quote",
            {
                "asset_code": "002156.SZ",
                "current_price": 12.34,
                "publication_id": "quote-publication-001",
                "must_not_use_for_decision": False,
                "snapshot_at": "2026-10-27T09:30:00",
            },
            "market_quote_snapshot_time_unverified",
        ),
        (
            "latest_quote",
            {
                "asset_code": "002156.SZ",
                "current_price": 12.34,
                "publication_id": "quote-publication-001",
                "must_not_use_for_decision": False,
                "snapshot_at": "malformed-time",
            },
            "market_quote_snapshot_time_unverified",
        ),
        (
            "latest_quote",
            {
                "asset_code": "002156.SZ",
                "current_price": 0,
                "publication_id": "quote-publication-001",
                "must_not_use_for_decision": False,
                "snapshot_at": "2026-10-27T09:30:00+08:00",
            },
            "market_quote_price_missing",
        ),
        (
            "latest_quote",
            {
                "current_price": 12.34,
                "publication_id": "quote-publication-001",
                "must_not_use_for_decision": False,
            },
            "market_asset_identity_mismatch",
        ),
        (
            "latest_quote",
            {
                "asset_code": "002156.SZ",
                "publication_id": "quote-publication-001",
                "must_not_use_for_decision": False,
                "snapshot_at": "2026-10-27T09:30:00+08:00",
            },
            "market_quote_price_missing",
        ),
        (
            "latest_quote",
            {
                "asset_code": "002156.SZ",
                "current_price": 12.34,
                "publication_id": "quote-publication-001",
                "must_not_use_for_decision": False,
            },
            "market_quote_snapshot_time_unverified",
        ),
        (
            "latest_quote",
            {
                "asset_code": "002156.SZ",
                "current_price": 12.34,
                "publication_id": "quote-publication-001",
                "must_not_use_for_decision": False,
                "snapshot_at": "2026-10-27T09:30:00",
            },
            "market_quote_snapshot_time_unverified",
        ),
        (
            "latest_quote",
            {
                "asset_code": "002156.SZ",
                "current_price": 12.34,
                "publication_id": "quote-publication-001",
                "must_not_use_for_decision": False,
                "snapshot_at": "malformed-time",
            },
            "market_quote_snapshot_time_unverified",
        ),
        (
            "latest_quote",
            {
                "asset_code": "002156.SZ ",
                "current_price": 12.34,
                "publication_id": "quote-publication-001",
                "must_not_use_for_decision": False,
                "snapshot_at": "2026-10-27T09:30:00+08:00",
            },
            "market_asset_identity_mismatch",
        ),
        (
            "price_history",
            {
                "rows": [
                    {
                        "asset_code": "002156.SZ",
                        "timestamp": "2026-10-27",
                        "close": 12.30,
                    }
                ],
                "publication_id": "price-publication-001",
            },
            "market_publication_gate_unverified",
        ),
        (
            "price_history",
            {
                "rows": [],
                "publication_id": "price-publication-001",
                "must_not_use_for_decision": False,
            },
            "section_evidence_missing",
        ),
        (
            "price_history",
            {
                "rows": [
                    {
                        "asset_code": "600000.SH",
                        "timestamp": "2026-10-27",
                        "close": 12.30,
                    }
                ],
                "publication_id": "price-publication-001",
                "must_not_use_for_decision": False,
            },
            "market_asset_identity_mismatch",
        ),
        (
            "price_history",
            {
                "rows": [
                    {
                        "asset_code": " 002156.SZ",
                        "timestamp": "2026-10-27",
                        "close": 12.30,
                    }
                ],
                "publication_id": "price-publication-001",
                "must_not_use_for_decision": False,
            },
            "market_asset_identity_mismatch",
        ),
        (
            "price_history",
            {
                "rows": [
                    {
                        "asset_code": "002156.SZ",
                        "timestamp": "2026-10-27",
                        "close": 12.30,
                    },
                    {
                        "asset_code": "600000.SH",
                        "timestamp": "2026-10-27",
                        "close": 12.20,
                    },
                ],
                "publication_id": "price-publication-001",
                "must_not_use_for_decision": False,
            },
            "market_asset_identity_mismatch",
        ),
        (
            "price_history",
            {
                "rows": [
                    {
                        "asset_code": "002156.SZ",
                        "timestamp": "2026-10-27",
                        "close": 12.30,
                        "must_not_use_for_decision": True,
                    }
                ],
                "publication_id": "price-publication-001",
                "must_not_use_for_decision": False,
            },
            "market_price_history_row_blocked",
        ),
        (
            "price_history",
            {
                "rows": [{"asset_code": "002156.SZ", "close": 12.30}],
                "publication_id": "price-publication-001",
                "must_not_use_for_decision": False,
            },
            "market_price_history_missing",
        ),
        (
            "price_history",
            {
                "rows": [
                    {
                        "asset_code": "002156.SZ",
                        "timestamp": "not-a-date",
                        "close": 12.30,
                    }
                ],
                "publication_id": "price-publication-001",
                "must_not_use_for_decision": False,
            },
            "market_price_history_missing",
        ),
        (
            "price_history",
            {
                "rows": [
                    {
                        "asset_code": "002156.SZ",
                        "timestamp": "2026-10-27",
                        "close": 0,
                    }
                ],
                "publication_id": "price-publication-001",
                "must_not_use_for_decision": False,
            },
            "market_price_history_missing",
        ),
    ],
)
def test_market_observation_fails_closed_without_publication_and_asset_price_evidence(
    section_name: str,
    payload_value: dict[str, object],
    expected_reason: str,
) -> None:
    reader = FakeResearchSnapshotReader()
    reader.overrides[section_name] = payload_value

    payload = (
        EquityResearchSnapshotUseCase(reader)
        .execute(EquityResearchSnapshotRequest("002156.SZ"))
        .to_payload()
    )

    assert payload["capabilities"]["market_research"] == {
        "status": "blocked",
        "reason_codes": [expected_reason],
        "evidence_sections": ["latest_quote", "price_history"],
    }


def test_unknown_required_section_block_prevents_local_market_observation() -> None:
    reader = FakeResearchSnapshotReader()
    reader.overrides["financials"] = {
        "rows": [{"asset_code": "002156.SZ", "value": 1}],
        "must_not_use_for_decision": True,
        "blocked_reason": "scope_mismatch",
    }

    payload = (
        EquityResearchSnapshotUseCase(reader)
        .execute(EquityResearchSnapshotRequest("002156.SZ"))
        .to_payload()
    )

    assert payload["must_not_use_for_decision"] is True
    assert payload["capabilities"]["market_research"] == {
        "status": "blocked",
        "reason_codes": ["scope_mismatch"],
        "evidence_sections": ["latest_quote", "price_history"],
    }


@pytest.mark.parametrize("section", ["identity", "financials"])
@pytest.mark.parametrize("invalid_gate", [0, None, ""])
def test_present_malformed_section_gate_cannot_authorize_market_observation(
    section: str, invalid_gate: object
) -> None:
    reader = FakeResearchSnapshotReader()
    reader.overrides[section] = {
        "code": "002156.SZ",
        "rows": [{"value": 1}],
        "must_not_use_for_decision": invalid_gate,
    }
    payload = (
        EquityResearchSnapshotUseCase(reader)
        .execute(EquityResearchSnapshotRequest("002156.SZ"))
        .to_payload()
    )
    assert payload["must_not_use_for_decision"] is True
    assert payload["capabilities"]["market_research"]["status"] == "blocked"
