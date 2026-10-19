from __future__ import annotations

from collections.abc import Mapping

import pytest

from apps.equity.application.published_pool_summary import (
    PublishedStockContextReader,
    build_published_stock_pool_summary,
)


def _gate(dataset: str, outcome: str) -> dict[str, object]:
    """Build one complete global gate for a narrow summary test."""

    partial = outcome == "partial"
    return {
        "dataset_key": dataset,
        "publication_key": "current",
        "publication_id": f"publication-{dataset}",
        "policy_identity": "policy-v1",
        "policy_version": "policy-v1",
        "selected_source": "canonical-provider",
        "publication_run_id": f"run-{dataset}",
        "publication_outcome": outcome,
        "coverage_requested_count": 2,
        "coverage_eligible_count": 1 if partial else 2,
        "coverage_selected_count": 1 if partial else 2,
        "coverage_missing_count": 1 if partial else 0,
        "must_not_use_for_decision": False,
        "blocked_reason": None,
        "private_artifact_location": "private://publication-evidence",
        "encryption_key_ref": "private-kms-key",
    }


def _asset_gate(
    global_gate: Mapping[str, object],
    dataset: str,
    blocked: bool,
) -> dict[str, object]:
    """Build a matching per-asset gate for one dataset."""

    gate = dict(global_gate)
    gate["dataset_key"] = dataset
    gate["must_not_use_for_decision"] = blocked
    gate["blocked_reason"] = "valuation_source_data_unavailable" if blocked else None
    return gate


def _context(
    code: str,
    financial_global: Mapping[str, object],
    valuation_global: Mapping[str, object],
    *,
    valuation_blocked: bool,
    reason: str = "valuation_source_data_unavailable",
) -> dict[str, object]:
    """Build a canonical Application context row with one optional local block."""

    valuation_gate = _asset_gate(valuation_global, "equity.valuation.fact", valuation_blocked)
    if valuation_blocked:
        valuation_gate["blocked_reason"] = reason
        valuation_gate["scope_block"] = {
            "asset_code": code,
            "reason_code": reason,
            "target_trade_date": "2026-10-16",
            "publication_id": valuation_global["publication_id"],
            "source": valuation_global["selected_source"],
            "publication_run_id": valuation_global["publication_run_id"],
            "policy_version": valuation_global["policy_version"],
        }
    return {
        "requested_code": code,
        "asset_code": code,
        "name": code,
        "sector": "银行" if code == "000001.SZ" else "制造",
        "publication_gates": {
            "financial": _asset_gate(financial_global, "equity.financial.fact", False),
            "valuation": valuation_gate,
        },
        "must_not_use_for_decision": valuation_blocked,
        "blocked_reason": reason if valuation_blocked else None,
        "roe": 12.5 if code == "000001.SZ" else 10.0,
        "pe": None if valuation_blocked else (7.2 if code == "000001.SZ" else 10.8),
        "pb": None if valuation_blocked else 0.8,
        "revenue_growth": 8.0,
        "profit_growth": 6.0,
        "source_times": {
            "financial": {
                "roe": {
                    "period_end": "2026-06-30",
                    "available_at": None,
                    "fetched_at": "2026-07-20T08:00:05+00:00",
                    "announced_at": None,
                    "source_time_witness": None,
                }
            },
            "valuation": {
                "val_date": "2026-10-16",
                "observed_at": None if valuation_blocked else "2026-10-16T07:00:00+00:00",
                "available_at": None,
                "fetched_at": None if valuation_blocked else "2026-10-16T07:00:05+00:00",
            },
        },
    }


def _reader_for(
    rows: dict[str, dict[str, object]],
) -> PublishedStockContextReader:
    """Return a reader that records the stable call shape without external I/O."""

    def read(
        stock_codes: list[str],
        *,
        publication_key: str,
        include_price: bool,
    ) -> dict[str, dict[str, object]]:
        assert publication_key == "current"
        assert include_price is False
        return {code: rows[code] for code in stock_codes}

    return read


def test_summary_keeps_supported_local_valuation_gap_in_requested_coverage() -> None:
    """A supported valuation gap preserves row order and complete-metric means."""

    financial = _gate("equity.financial.fact", "success")
    valuation = _gate("equity.valuation.fact", "partial")
    rows = {
        "000001.SZ": _context("000001.SZ", financial, valuation, valuation_blocked=True),
        "000002.SZ": _context("000002.SZ", financial, valuation, valuation_blocked=False),
    }

    result = build_published_stock_pool_summary(
        ["000001.SZ", "000002.SZ"],
        publication_key="current",
        publication_gates={
            "equity.financial.fact": financial,
            "equity.valuation.fact": valuation,
        },
        context_reader=_reader_for(rows),
    )
    payload = result.to_payload()

    assert result.status == "partial"
    assert result.outcome == "partial"
    assert result.must_not_use_for_decision is True
    assert result.blocked_reason is None
    assert result.restriction_message is not None
    assert "当前结果不可用于决策" in result.restriction_message
    assert payload["requested_count"] == payload["count"] == 2
    assert payload["blocked_count"] == 1
    assert [row["code"] for row in payload["stocks"]] == ["000001.SZ", "000002.SZ"]
    assert payload["avg_roe"] == pytest.approx(11.25)
    assert payload["avg_pe"] is None
    assert payload["aggregate_coverage"] == {
        "avg_roe": {"known_count": 2, "requested_count": 2},
        "avg_pe": {"known_count": 1, "requested_count": 2},
    }
    blocked, healthy = payload["stocks"]
    assert blocked["status_label"] == "估值资料受限"
    assert "仅供观察" in blocked["restriction_message"]
    assert blocked["pe"] is None
    assert blocked["source_times"]["valuation"]["available_at"] is None
    assert healthy["status_label"] == "资料已发布"
    assert "private_artifact_location" not in payload["publication_gates"]["equity.financial.fact"]
    assert "encryption_key_ref" not in payload["publication_gates"]["equity.valuation.fact"]


def test_partial_financial_gate_blocks_before_context_read() -> None:
    """The valuation-only local exception cannot downgrade finance gaps."""

    financial = _gate("equity.financial.fact", "partial")
    valuation = _gate("equity.valuation.fact", "success")

    def unexpected_read(
        stock_codes: list[str],
        *,
        publication_key: str,
        include_price: bool,
    ) -> dict[str, dict[str, object]]:
        raise AssertionError("untrusted global gates must block before the fact read")

    result = build_published_stock_pool_summary(
        ["000001.SZ", "000002.SZ"],
        publication_key="current",
        publication_gates={
            "equity.financial.fact": financial,
            "equity.valuation.fact": valuation,
        },
        context_reader=unexpected_read,
    )

    assert result.success is False
    assert result.status == "blocked"
    assert result.outcome == "blocked"
    assert result.stocks == ()
    assert result.count == 0
    assert result.blocked_count is None
    assert result.to_payload()["blocked_count"] is None
    assert result.must_not_use_for_decision is True


def test_summary_preserves_requested_order_and_duplicate_entries() -> None:
    """Summary rows and denominators retain every supplied pool entry."""

    financial = _gate("equity.financial.fact", "success")
    valuation = _gate("equity.valuation.fact", "success")
    rows = {
        "000001.SZ": _context("000001.SZ", financial, valuation, valuation_blocked=False),
        "000002.SZ": _context("000002.SZ", financial, valuation, valuation_blocked=False),
    }

    result = build_published_stock_pool_summary(
        ["000002.SZ", "000001.SZ", "000002.SZ"],
        publication_key="current",
        publication_gates={
            "equity.financial.fact": financial,
            "equity.valuation.fact": valuation,
        },
        context_reader=_reader_for(rows),
    )
    payload = result.to_payload()

    assert result.status == "published"
    assert result.outcome == "success"
    assert payload["requested_count"] == payload["count"] == 3
    assert payload["blocked_count"] == 0
    assert [row["code"] for row in payload["stocks"]] == [
        "000002.SZ",
        "000001.SZ",
        "000002.SZ",
    ]
    assert payload["aggregate_coverage"]["avg_pe"] == {
        "known_count": 3,
        "requested_count": 3,
    }


def test_missing_financial_members_alongside_local_valuation_block_stays_global() -> None:
    """The valuation exception cannot hide a second dataset's missing member rows."""

    financial = _gate("equity.financial.fact", "success")
    valuation = _gate("equity.valuation.fact", "partial")
    row = _context("000001.SZ", financial, valuation, valuation_blocked=True)
    row["missing_datasets"] = ["financial", "valuation"]
    row["roe"] = None
    result = build_published_stock_pool_summary(
        ["000001.SZ"],
        publication_key="current",
        publication_gates={"equity.financial.fact": financial, "equity.valuation.fact": valuation},
        context_reader=_reader_for({"000001.SZ": row}),
    )
    assert result.outcome == "blocked"
    assert result.blocked_reason == "canonical_publication_members_missing"
    assert result.count == 0
    assert result.blocked_count is None


def test_partial_valuation_without_selected_members_blocks_before_context_read() -> None:
    """An empty selected set cannot satisfy the supported valuation partial contract."""

    financial = _gate("equity.financial.fact", "success")
    valuation = _gate("equity.valuation.fact", "partial")
    valuation.update(coverage_eligible_count=0, coverage_selected_count=0, coverage_missing_count=2)

    def unexpected_read(
        stock_codes: list[str],
        *,
        publication_key: str,
        include_price: bool,
    ) -> dict[str, dict[str, object]]:
        raise AssertionError("empty selected members must block before reading contexts")

    result = build_published_stock_pool_summary(
        ["000001.SZ"],
        publication_key="current",
        publication_gates={"equity.financial.fact": financial, "equity.valuation.fact": valuation},
        context_reader=unexpected_read,
    )
    assert result.outcome == "blocked"
    assert result.must_not_use_for_decision is True
    assert result.count == 0
    assert result.blocked_count is None


def test_summary_keeps_verified_master_alias_and_uses_canonical_scope_identity() -> None:
    """A persisted six-digit request can use its resolved canonical master identity."""

    financial = _gate("equity.financial.fact", "success")
    valuation = _gate("equity.valuation.fact", "partial")
    row = _context("000001.SZ", financial, valuation, valuation_blocked=True)
    row["requested_code"] = "000001"
    result = build_published_stock_pool_summary(
        ["000001"],
        publication_key="current",
        publication_gates={"equity.financial.fact": financial, "equity.valuation.fact": valuation},
        context_reader=_reader_for({"000001": row}),
    )
    assert result.outcome == "partial"
    assert result.stocks[0].code == "000001"
    assert result.stocks[0].asset_code == "000001.SZ"
    assert result.stocks[0].pe is None
    row["requested_code"] = "000002"
    rejected = build_published_stock_pool_summary(
        ["000001"],
        publication_key="current",
        publication_gates={"equity.financial.fact": financial, "equity.valuation.fact": valuation},
        context_reader=_reader_for({"000001": row}),
    )
    assert rejected.outcome == "blocked"
    assert rejected.stocks == ()
