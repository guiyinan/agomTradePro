"""Focused contract tests for the TUI research snapshot presentation helper."""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime, timedelta
from typing import cast

from apps.data_center.domain.entities import (
    CapitalFlowFact,
    FinancialFact,
    QuoteSnapshot,
    ValuationFact,
)
from apps.data_center.domain.enums import FinancialPeriodType
from apps.data_center.domain.financial_source_evidence import (
    FinancialFactSourceEvidence,
)
from apps.equity.application.research_snapshot import (
    EquityResearchSection,
    EquityResearchSnapshotResult,
)
from apps.terminal.application.tui_research_snapshot_result import (
    TuiResearchProfessionalTarget,
    build_tui_research_snapshot_view,
    project_tui_research_snapshot_result,
)


def _real_fact_rows() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    observed_at = datetime(2026, 10, 17, 9, 30, tzinfo=UTC)
    fetched_at = observed_at + timedelta(minutes=2)
    quote = QuoteSnapshot(
        asset_code="600000.SH",
        snapshot_at=observed_at,
        current_price=12.34,
        source="quote-source",
        fetched_at=fetched_at,
    ).to_dict()
    valuation = ValuationFact(
        asset_code="600000.SH",
        val_date=date(2026, 10, 16),
        pe_ttm=12.3,
        pb=0.0,
        source="valuation-source",
        observed_at=observed_at - timedelta(days=1),
        available_at=observed_at - timedelta(hours=12),
        fetched_at=observed_at - timedelta(hours=11),
    ).to_dict()
    financial = FinancialFact(
        asset_code="600000.SH",
        period_end=date(2026, 6, 30),
        period_type=FinancialPeriodType.SEMI_ANNUAL,
        metric_code="revenue",
        value=0.0,
        unit="CNY",
        source="financial-source",
        report_date=date(2026, 8, 20),
        available_at=datetime(2026, 8, 21, tzinfo=UTC),
        fetched_at=datetime(2026, 8, 21, 0, 1, tzinfo=UTC),
        source_evidence=FinancialFactSourceEvidence(
            announced_at=datetime(2026, 8, 20, tzinfo=UTC),
            source_record_id="fixture:600000.SH:2026-06-30:revenue",
            raw_payload_hash="a" * 64,
        ),
    ).to_dict()
    capital_flow = CapitalFlowFact(
        asset_code="600000.SH",
        flow_date=date(2026, 10, 16),
        main_net=0.0,
        source="flow-source",
        fetched_at=observed_at - timedelta(hours=10),
    ).to_dict()
    return quote, valuation, financial, capital_flow


def _base_snapshot(
    *,
    status: str = "fresh",
    must_not_use: bool | None = False,
) -> dict[str, object]:
    quote, valuation, financial, capital_flow = _real_fact_rows()
    section_data = (
        ("latest_quote", True, {"rows": [quote]}),
        ("valuation", True, {"rows": [valuation]}),
        ("financials", True, {"rows": [financial]}),
        ("capital_flows", False, {"rows": [capital_flow]}),
    )
    sections = {
        key: EquityResearchSection(
            status="fresh",
            required=required,
            data=data,
            must_not_use_for_decision=False,
            block_reason_code="",
        )
        for key, required, data in section_data
    }
    identity = EquityResearchSection(
        status="fresh",
        required=True,
        data={
            "asset_type": "stock",
            "code": "600000.SH",
            "name": "示例股份",
            "currency": "CNY",
        },
        must_not_use_for_decision=False,
        block_reason_code="",
    )
    owner_must_not_use = bool(must_not_use)
    result = EquityResearchSnapshotResult(
        status=status,
        stock_code="600000.SH",
        identity=identity,
        sections=sections,
        decision_readiness={
            "status": status,
            "must_not_use_for_decision": owner_must_not_use,
        },
        missing_optional_sections=(),
        reliability={
            "source": "research-source",
            "status": status,
            "reliability": "verified",
        },
        must_not_use_for_decision=owner_must_not_use,
    )
    return cast(dict[str, object], result.to_payload())


def _missing_snapshot() -> dict[str, object]:
    identity = EquityResearchSection(
        status="missing",
        required=True,
        data=None,
        must_not_use_for_decision=True,
        block_reason_code="equity_identity_unresolved",
    )
    result = EquityResearchSnapshotResult(
        status="missing",
        stock_code=None,
        identity=identity,
        sections={},
        decision_readiness={
            "status": "missing",
            "must_not_use_for_decision": True,
        },
        missing_optional_sections=(),
        reliability={
            "status": "missing",
            "source": "agomtradepro_api",
            "reliability": "unavailable",
            "must_not_use_for_decision": True,
            "block_reason_code": "equity_identity_unresolved",
            "block_reason": "无法从证券主数据唯一解析该名称或代码。",
        },
        must_not_use_for_decision=True,
    )
    return cast(dict[str, object], result.to_payload())


def _fields(view: dict[str, object]) -> dict[str, str]:
    raw_fields = cast(list[dict[str, str]], view["fields"])
    return {field["key"]: field["value"] for field in raw_fields}


class TuiResearchSnapshotTests(unittest.TestCase):
    def test_fresh_snapshot_uses_real_flat_facts_and_preserves_zero_values(self) -> None:
        view = build_tui_research_snapshot_view(_base_snapshot())
        self.assertEqual(view["outcome"], "success")
        self.assertLessEqual(len(view["fields"]), 10)
        fields = _fields(view)
        self.assertIn("价格：12.34", fields["latest_quote"])
        self.assertIn("币种：CNY", fields["latest_quote"])
        self.assertNotIn("可用时间", fields["latest_quote"])
        self.assertIn("PE(TTM)：12.3", fields["valuation"])
        self.assertIn("PB：0.0", fields["valuation"])
        self.assertIn("数值：0.0", fields["financials"])
        self.assertIn("单位：CNY", fields["financials"])

    def test_partial_blocked_and_unknown_keep_owner_status_and_outcome(self) -> None:
        cases = (
            ("partial", "partial", False),
            ("blocked", "blocked", True),
            ("unknown", "blocked", True),
        )
        for status, outcome, must_not_use in cases:
            with self.subTest(status=status):
                view = build_tui_research_snapshot_view(
                    _base_snapshot(
                        status=status,
                        must_not_use=must_not_use,
                    )
                )
                self.assertEqual(view["owner_status"], status)
                self.assertEqual(view["outcome"], outcome)

    def test_missing_owner_has_no_live_sections(self) -> None:
        view = build_tui_research_snapshot_view(_missing_snapshot())
        self.assertEqual(view["owner_status"], "missing")
        self.assertEqual(view["outcome"], "blocked")
        self.assertEqual(view["sections"], [])
        self.assertNotIn("latest_quote", _fields(view))

    def test_restricted_fresh_and_partial_owner_outcomes_are_copied(self) -> None:
        for status in ("fresh", "partial"):
            with self.subTest(status=status):
                snapshot = _base_snapshot(
                    status=status,
                    must_not_use=True,
                )
                view = build_tui_research_snapshot_view(snapshot)
                self.assertEqual(view["owner_status"], status)
                self.assertEqual(view["outcome"], "blocked")
                self.assertTrue(view["must_not_use_for_decision"])
                self.assertIn("禁止用于决策", _fields(view)["decision_restriction"])

    def test_source_clock_kinds_match_real_entity_serialization(self) -> None:
        view = build_tui_research_snapshot_view(_base_snapshot())
        sections = cast(list[dict[str, object]], view["sections"])
        quote = next(item for item in sections if item["key"] == "latest_quote")
        quote_times = cast(list[dict[str, str]], quote["source_times"])
        quote_kinds = {item["field"]: item["kind"] for item in quote_times}
        self.assertEqual(quote_kinds["snapshot_at"], "observation")
        self.assertEqual(quote_kinds["fetched_at"], "fetch")
        self.assertNotIn("available_at", quote_kinds)

        valuation = next(item for item in sections if item["key"] == "valuation")
        valuation_times = cast(
            list[dict[str, str]],
            valuation["source_times"],
        )
        valuation_kinds = {item["field"]: item["kind"] for item in valuation_times}
        self.assertEqual(valuation_kinds["observed_at"], "observation")
        self.assertEqual(valuation_kinds["available_at"], "availability")
        self.assertEqual(valuation_kinds["fetched_at"], "fetch")

    def test_financial_announcement_clock_uses_nested_source_evidence(self) -> None:
        view = build_tui_research_snapshot_view(_base_snapshot())
        sections = cast(list[dict[str, object]], view["sections"])
        financial = next(item for item in sections if item["key"] == "financials")
        times = cast(list[dict[str, str]], financial["source_times"])
        announced = [item for item in times if item["field"] == "announced_at"]
        rows = cast(list[dict[str, list[dict[str, str]]]], financial["rows"])
        self.assertEqual(
            next(cell["value"] for cell in rows[0]["fields"] if cell["key"] == "announced_at"),
            "2026-08-20T00:00:00+00:00",
        )
        self.assertEqual(
            announced,
            [
                {
                    "kind": "publication",
                    "field": "announced_at",
                    "origin": "record.source_evidence",
                    "label": "财务公告时间",
                    "value": "2026-08-20T00:00:00+00:00",
                }
            ],
        )
        self.assertIn(
            ("available_at", "record"),
            {(item["field"], item["origin"]) for item in times},
        )
        self.assertIn(
            ("fetched_at", "record"),
            {(item["field"], item["origin"]) for item in times},
        )

    def test_financial_announcement_clock_missing_or_null_is_omitted(self) -> None:
        for mode in ("missing", "null"):
            with self.subTest(mode=mode):
                snapshot = _base_snapshot()
                sections = cast(dict[str, object], snapshot["sections"])
                financial = cast(dict[str, object], sections["financials"])
                data = cast(dict[str, object], financial["data"])
                row = cast(dict[str, object], data["rows"][0])
                if mode == "missing":
                    row.pop("source_evidence")
                else:
                    evidence = cast(dict[str, object], row["source_evidence"])
                    evidence["announced_at"] = None
                view = build_tui_research_snapshot_view(snapshot)
                output_sections = cast(list[dict[str, object]], view["sections"])
                output_financial = next(
                    item for item in output_sections if item["key"] == "financials"
                )
                times = cast(list[dict[str, str]], output_financial["source_times"])
                self.assertNotIn(
                    "announced_at",
                    {item["field"] for item in times},
                )

    def test_news_record_publication_is_distinct_from_canonical_publication(self) -> None:
        snapshot = _base_snapshot()
        sections = cast(dict[str, object], snapshot["sections"])
        sections["news"] = {
            "status": "fresh",
            "required": False,
            "data": {
                "rows": [
                    {
                        "asset_code": "600000.SH",
                        "title": "[SYNTHETIC TEST] optional market-news record",
                        "summary": "Synthetic test evidence; no investment opinion.",
                        "published_at": "2026-10-17T13:13:16.255919+00:00",
                        "source": "synthetic-optional-consumer",
                        "fetched_at": "2026-10-17T13:15:27.023707+00:00",
                    }
                ],
                "published_at": "2026-10-17T13:15:27.034081+00:00",
                "observed_at": "2026-10-17T13:13:16.255919+00:00",
                "freshness_status": "fresh",
            },
            "must_not_use_for_decision": False,
            "block_reason_code": "",
        }
        view = build_tui_research_snapshot_view(snapshot)
        output_sections = cast(list[dict[str, object]], view["sections"])
        news = next(item for item in output_sections if item["key"] == "news")
        times = cast(list[dict[str, str]], news["source_times"])
        publication_times = [item for item in times if item["field"] == "published_at"]
        self.assertEqual(
            {(item["origin"], item["value"], item["label"]) for item in publication_times},
            {
                (
                    "data",
                    "2026-10-17T13:15:27.034081+00:00",
                    "新闻数据发布记录时间",
                ),
                (
                    "record",
                    "2026-10-17T13:13:16.255919+00:00",
                    "新闻发布时间",
                ),
            },
        )
        self.assertNotEqual(
            publication_times[0]["value"],
            publication_times[1]["value"],
        )
        self.assertIn(
            ("fetched_at", "record"),
            {(item["field"], item["origin"]) for item in times},
        )

    def test_non_news_record_publication_keeps_canonical_gate_label(self) -> None:
        snapshot = _base_snapshot()
        sections = cast(dict[str, object], snapshot["sections"])
        latest_quote = cast(dict[str, object], sections["latest_quote"])
        data = cast(dict[str, object], latest_quote["data"])
        canonical_published_at = "2026-10-17T13:04:20.748694+00:00"
        data["published_at"] = canonical_published_at
        row = cast(dict[str, object], data["rows"][0])
        row["published_at"] = canonical_published_at

        view = build_tui_research_snapshot_view(snapshot)
        output_sections = cast(list[dict[str, object]], view["sections"])
        output_quote = next(item for item in output_sections if item["key"] == "latest_quote")
        times = cast(list[dict[str, str]], output_quote["source_times"])
        publication_times = [item for item in times if item["field"] == "published_at"]
        self.assertEqual(
            {(item["origin"], item["label"]) for item in publication_times},
            {
                ("data", "行情数据发布记录时间"),
                ("record", "行情数据发布记录时间"),
            },
        )
        self.assertNotIn(
            "来源发布时间",
            {item["label"] for item in publication_times},
        )

    def test_missing_units_are_explicit_without_scaling(self) -> None:
        snapshot = _base_snapshot()
        sections = cast(dict[str, object], snapshot["sections"])
        financial = cast(dict[str, object], sections["financials"])
        financial_data = cast(dict[str, object], financial["data"])
        financial_row = cast(dict[str, object], financial_data["rows"][0])
        financial_row.pop("unit")

        view = build_tui_research_snapshot_view(snapshot)
        output_sections = cast(list[dict[str, object]], view["sections"])
        for key in ("valuation", "financials", "capital_flows"):
            with self.subTest(section=key):
                section = next(item for item in output_sections if item["key"] == key)
                rows = cast(list[dict[str, object]], section["rows"])
                cells = cast(list[dict[str, str]], rows[0]["fields"])
                self.assertIn(
                    {"key": "unit", "label": "单位", "value": "单位未提供"},
                    cells,
                )

    def test_curated_rows_are_bounded_with_honest_count_and_note(self) -> None:
        snapshot = _base_snapshot()
        sections = cast(dict[str, object], snapshot["sections"])
        quote = cast(dict[str, object], sections["latest_quote"])
        data = cast(dict[str, object], quote["data"])
        original = cast(dict[str, object], data["rows"][0])
        data["rows"] = [
            {
                **original,
                "current_price": 12.34 + index,
                "snapshot_at": f"2026-10-17T09:{30 + index:02d}:00+00:00",
            }
            for index in range(7)
        ]
        view = build_tui_research_snapshot_view(snapshot)
        output_sections = cast(list[dict[str, object]], view["sections"])
        output_quote = next(item for item in output_sections if item["key"] == "latest_quote")
        self.assertEqual(output_quote["item_count"], 7)
        self.assertEqual(len(cast(list[object], output_quote["rows"])), 6)
        note = cast(str, output_quote["truncation_note"])
        self.assertIn("实际返回 7 条", note)
        self.assertNotIn("equity.valuation-overview", note)

    def test_professional_target_is_optional_and_canonical(self) -> None:
        snapshot = _base_snapshot()
        target = cast(
            TuiResearchProfessionalTarget,
            {
                "screen_key": "research.asset-lab",
                "action_key": "equity.valuation-overview",
                "label": "打开专业研究",
            },
        )
        view = build_tui_research_snapshot_view(
            snapshot,
            professional_target=target,
        )
        steps = cast(list[dict[str, object]], view["next_steps"])
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["params"], {"stock_code": "600000.SH"})
        self.assertNotIn("return_context", steps[0])
        self.assertEqual(
            build_tui_research_snapshot_view(snapshot)["next_steps"],
            [],
        )

    def test_malformed_payload_is_tolerated_at_the_boundary(self) -> None:
        malformed = _base_snapshot()
        identity = cast(dict[str, object], malformed["identity"])
        identity["data"] = "not-a-mapping"
        malformed_view = build_tui_research_snapshot_view(malformed)
        self.assertEqual(malformed_view["owner_status"], "fresh")
        self.assertEqual(len(cast(list[object], malformed_view["sections"])), 4)

    def test_transport_error_or_malformed_owner_payload_uses_generic_projection(self) -> None:
        self.assertIsNone(
            project_tui_research_snapshot_result(
                {"detail": "owner unavailable"},
                503,
            )
        )
        self.assertIsNone(
            project_tui_research_snapshot_result(
                {"status": "fresh", "identity": {}, "sections": {}},
                200,
            )
        )

    def test_incomplete_success_envelope_cannot_become_a_research_view(self) -> None:
        payload: dict[str, object] = {
            "status": "fresh",
            "outcome": "success",
            "stock_code": "600000.SH",
            "identity": {},
            "sections": {},
            "must_not_use_for_decision": False,
        }
        self.assertIsNone(project_tui_research_snapshot_result(payload, 200))
        payload["identity"] = {
            "status": "fresh",
            "required": True,
            "data": {"code": "600000.SH"},
            "must_not_use_for_decision": False,
            "block_reason_code": "",
        }
        self.assertIsNone(project_tui_research_snapshot_result(payload, 200))
        payload["sections"] = {"financials": {"status": "fresh"}}
        self.assertIsNone(project_tui_research_snapshot_result(payload, 200))

    def test_unknown_restriction_keeps_code_deep_and_hides_it_from_main_copy(self) -> None:
        restricted = _base_snapshot()
        restricted_sections = cast(dict[str, object], restricted["sections"])
        restricted_sections["valuation"] = {
            "status": "blocked",
            "block_reason_code": "provider_specific_unknown",
            "data": {"rows": []},
        }
        restricted_view = build_tui_research_snapshot_view(restricted)
        output_sections = cast(list[dict[str, object]], restricted_view["sections"])
        valuation = next(item for item in output_sections if item["key"] == "valuation")
        self.assertEqual(valuation["block_reason_code"], "provider_specific_unknown")
        self.assertEqual(
            restricted_view["blocking_reason"],
            "数据暂时受限，请稍后重新读取；持续受限时请联系管理员。",
        )
        self.assertNotIn(
            "provider_specific_unknown",
            restricted_view["business_summary"],
        )

    def test_owner_reason_source_label_and_unrecomputed_outcome(self) -> None:
        snapshot = _base_snapshot(status="blocked", must_not_use=True)
        snapshot["reliability"] = {
            "status": "blocked",
            "source": "research-source",
            "must_not_use_for_decision": True,
        }
        sections = cast(dict[str, object], snapshot["sections"])
        valuation = cast(dict[str, object], sections["valuation"])
        valuation["status"] = "blocked"
        valuation["must_not_use_for_decision"] = True
        valuation["block_reason_code"] = "source_stale"
        valuation["data"] = {
            "freshness_status": "stale",
            "block_reason": "估值证据暂不可用。",
            "rows": [],
        }

        view = build_tui_research_snapshot_view(snapshot)
        output_sections = cast(list[dict[str, object]], view["sections"])
        output_valuation = next(item for item in output_sections if item["key"] == "valuation")
        self.assertEqual(output_valuation["owner_status"], "blocked")
        self.assertEqual(
            output_valuation["upstream_freshness_status"],
            "stale",
        )
        self.assertEqual(
            output_valuation["owner_reason"],
            "估值证据暂不可用。",
        )
        self.assertEqual(output_valuation["block_reason_code"], "source_stale")
        self.assertEqual(view["outcome"], "blocked")
        self.assertIn("估值证据暂不可用。", view["blocking_reason"])

    def test_top_reliability_reason_and_technical_source_are_separate(self) -> None:
        snapshot = _base_snapshot()
        snapshot["reliability"] = {
            "status": "fresh",
            "source": "agomtradepro_api",
            "must_not_use_for_decision": False,
            "block_reason_code": "decision_reliability_blocked",
            "block_reason": "系统研究汇总暂不可用于决策。",
        }
        view = build_tui_research_snapshot_view(snapshot)
        self.assertEqual(view["outcome"], "success")
        self.assertIn(
            "系统研究汇总暂不可用于决策。",
            view["blocking_reason"],
        )
        self.assertIn("来源：系统研究汇总", _fields(view)["reliability"])
        self.assertNotIn("agomtradepro_api", _fields(view)["reliability"])
        self.assertEqual(view["owner_reliability"]["source"], "agomtradepro_api")

    def test_stale_error_and_unavailable_sections_keep_readable_status(self) -> None:
        snapshot = _base_snapshot(status="blocked", must_not_use=True)
        sections = cast(dict[str, object], snapshot["sections"])
        for key, freshness_status in (
            ("latest_quote", "stale"),
            ("valuation", "error"),
            ("financials", "unavailable"),
        ):
            section = cast(dict[str, object], sections[key])
            section["status"] = "blocked"
            section["must_not_use_for_decision"] = True
            section["block_reason_code"] = f"section_{freshness_status}"
            section["data"] = {
                "freshness_status": freshness_status,
                "blocked_reason": f"上游状态为 {freshness_status}。",
                "rows": [],
            }

        view = build_tui_research_snapshot_view(snapshot)
        output_sections = cast(list[dict[str, object]], view["sections"])
        statuses = {item["key"]: item["owner_status"] for item in output_sections}
        self.assertEqual(statuses["latest_quote"], "blocked")
        self.assertEqual(statuses["valuation"], "blocked")
        self.assertEqual(statuses["financials"], "blocked")
        upstream_statuses = {
            item["key"]: item["upstream_freshness_status"]
            for item in output_sections
            if "upstream_freshness_status" in item
        }
        self.assertEqual(upstream_statuses["latest_quote"], "stale")
        self.assertEqual(upstream_statuses["valuation"], "error")
        self.assertEqual(upstream_statuses["financials"], "unavailable")
        self.assertIn("行情：上游数据过期", view["business_summary"])
        self.assertIn("估值：上游读取错误", view["business_summary"])
        self.assertIn("财务：上游暂不可用", view["business_summary"])
        self.assertEqual(view["outcome"], "blocked")

    def test_partial_financial_publication_shows_scope_counts_and_keeps_security_row(
        self,
    ) -> None:
        """Show publication-wide coverage beside the unchanged security facts."""
        snapshot = _base_snapshot()
        sections = cast(dict[str, object], snapshot["sections"])
        financial = cast(dict[str, object], sections["financials"])
        data = cast(dict[str, object], financial["data"])
        data.update(
            {
                "publication_outcome": "partial",
                "coverage_requested_count": 4,
                "coverage_eligible_count": 3,
                "coverage_selected_count": 2,
                "coverage_missing_count": 1,
                "observed_at": None,
                "available_at": None,
            }
        )
        rows = cast(list[dict[str, object]], data["rows"])
        rows[0]["observed_at"] = None
        rows[0]["available_at"] = None

        view = build_tui_research_snapshot_view(snapshot)
        output_sections = cast(list[dict[str, object]], view["sections"])
        output_financial = next(item for item in output_sections if item["key"] == "financials")
        coverage = "本次财务发布范围：部分返回；请求：4；符合条件：3；" "已选入：2；缺失：1。"
        self.assertEqual(view["owner_status"], "fresh")
        self.assertEqual(view["outcome"], "success")
        self.assertEqual(output_financial["owner_status"], "fresh")
        self.assertEqual(output_financial["item_count"], 1)
        restriction_message = cast(str, output_financial["restriction_message"])
        self.assertIn(coverage, restriction_message)
        self.assertIn(coverage, view["business_summary"])
        self.assertIn(coverage, _fields(view)["evidence_gaps"])

        output_rows = cast(list[dict[str, list[dict[str, str]]]], output_financial["rows"])
        self.assertEqual(len(output_rows), 1)
        cells = {cell["key"]: cell["value"] for cell in output_rows[0]["fields"]}
        self.assertEqual(cells["asset_code"], "600000.SH")
        self.assertEqual(cells["metric_code"], "revenue")
        self.assertEqual(cells["value"], "0.0")

        source_times = cast(list[dict[str, str]], output_financial["source_times"])
        source_time_fields = {item["field"] for item in source_times}
        self.assertNotIn("observed_at", source_time_fields)
        self.assertNotIn("available_at", source_time_fields)
        self.assertIn(
            ("fetched_at", "record"), {(item["field"], item["origin"]) for item in source_times}
        )

    def test_explicit_financial_block_keeps_priority_with_partial_coverage(self) -> None:
        """Coverage adds context without replacing an upstream blocking reason."""
        snapshot = _base_snapshot(status="blocked", must_not_use=True)
        sections = cast(dict[str, object], snapshot["sections"])
        financial = cast(dict[str, object], sections["financials"])
        financial["status"] = "blocked"
        financial["must_not_use_for_decision"] = True
        financial["block_reason_code"] = "publication_stale"
        data = cast(dict[str, object], financial["data"])
        blocking_reason = "发布证据已超过可用时限，当前分区受限。"
        data.update(
            {
                "publication_outcome": "partial",
                "coverage_requested_count": 4,
                "coverage_eligible_count": 3,
                "coverage_selected_count": 2,
                "coverage_missing_count": 1,
                "freshness_status": "stale",
                "blocked_reason": blocking_reason,
            }
        )

        view = build_tui_research_snapshot_view(snapshot)
        output_sections = cast(list[dict[str, object]], view["sections"])
        output_financial = next(item for item in output_sections if item["key"] == "financials")
        coverage = "本次财务发布范围：部分返回；请求：4；符合条件：3；" "已选入：2；缺失：1。"
        self.assertEqual(view["outcome"], "blocked")
        self.assertEqual(output_financial["owner_status"], "blocked")
        self.assertTrue(output_financial["must_not_use_for_decision"])
        self.assertEqual(view["blocking_reason"], blocking_reason)
        self.assertIn(blocking_reason, output_financial["restriction_message"])
        self.assertIn(coverage, output_financial["restriction_message"])
        self.assertIn(coverage, _fields(view)["evidence_gaps"])

    def test_successful_financial_publication_keeps_existing_presentation(self) -> None:
        """A successful full-scope payload adds no partial-coverage warning."""
        baseline = build_tui_research_snapshot_view(_base_snapshot())
        snapshot = _base_snapshot()
        sections = cast(dict[str, object], snapshot["sections"])
        financial = cast(dict[str, object], sections["financials"])
        data = cast(dict[str, object], financial["data"])
        data.update(
            {
                "publication_outcome": "success",
                "coverage_requested_count": 4,
                "coverage_eligible_count": 4,
                "coverage_selected_count": 4,
                "coverage_missing_count": 0,
            }
        )

        view = build_tui_research_snapshot_view(snapshot)
        output_sections = cast(list[dict[str, object]], view["sections"])
        output_financial = next(item for item in output_sections if item["key"] == "financials")
        baseline_sections = cast(list[dict[str, object]], baseline["sections"])
        baseline_financial = next(item for item in baseline_sections if item["key"] == "financials")
        self.assertEqual(view["business_summary"], baseline["business_summary"])
        self.assertEqual(_fields(view), _fields(baseline))
        self.assertEqual(
            output_financial["owner_status"],
            baseline_financial["owner_status"],
        )
        self.assertEqual(output_financial["rows"], baseline_financial["rows"])
        self.assertNotIn("财务发布范围", output_financial.get("restriction_message", ""))

    def test_partial_financial_coverage_never_coerces_unknown_counts_to_zero(self) -> None:
        """Boolean and missing counts remain explicitly unavailable in the notice."""
        invalid_counts = (
            ("coverage_requested_count", "请求", True),
            ("coverage_eligible_count", "符合条件", None),
            ("coverage_selected_count", "已选入", False),
            ("coverage_missing_count", "缺失", None),
        )
        valid_counts = {
            "coverage_requested_count": 4,
            "coverage_eligible_count": 3,
            "coverage_selected_count": 2,
            "coverage_missing_count": 1,
        }
        labels = {
            "coverage_requested_count": "请求",
            "coverage_eligible_count": "符合条件",
            "coverage_selected_count": "已选入",
            "coverage_missing_count": "缺失",
        }
        for field, label, invalid_value in invalid_counts:
            with self.subTest(field=field, value=invalid_value):
                snapshot = _base_snapshot()
                sections = cast(dict[str, object], snapshot["sections"])
                financial = cast(dict[str, object], sections["financials"])
                data = cast(dict[str, object], financial["data"])
                data.update({"publication_outcome": "partial", **valid_counts})
                data[field] = invalid_value

                view = build_tui_research_snapshot_view(snapshot)
                output_sections = cast(list[dict[str, object]], view["sections"])
                output_financial = next(
                    item for item in output_sections if item["key"] == "financials"
                )
                message = cast(str, output_financial["restriction_message"])
                self.assertIn("本次财务发布范围：部分返回", message)
                self.assertIn(f"{label}：未提供", message)
                self.assertNotIn(f"{label}：0", message)
                self.assertNotIn(f"{label}：是", message)
                self.assertNotIn(f"{label}：否", message)
                self.assertNotIn(f"{label}：None", message)
                for other_field, other_label in labels.items():
                    if other_field == field:
                        continue
                    self.assertIn(f"{other_label}：{valid_counts[other_field]}", message)


if __name__ == "__main__":
    unittest.main()
