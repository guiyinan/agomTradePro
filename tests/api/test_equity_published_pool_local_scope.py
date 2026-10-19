"""Consumer contracts for the publication-bound equity-pool read.

The positive exception is restricted to supported current valuation evidence;
these explicit reader fixtures do not qualify a production provider/publisher.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest


def _global_gate(dataset_key: str, publication_id: str) -> dict[str, object]:
    """Build a complete global publication gate for an API fixture."""

    partial = dataset_key == "equity.valuation.fact"
    return {
        "publication_id": publication_id,
        "dataset_key": dataset_key,
        "publication_key": "current",
        "published_at": "2026-10-18T08:00:00+00:00",
        "as_of": "2026-10-18T07:59:00+00:00",
        "policy_identity": "equity-policy-v2",
        "policy_version": "equity-policy-v2",
        "selected_source": "canonical-provider",
        "publication_run_id": f"run-{dataset_key}",
        "publication_outcome": "partial" if partial else "success",
        "coverage_requested_count": 2,
        "coverage_eligible_count": 1 if partial else 2,
        "coverage_selected_count": 1 if partial else 2,
        "coverage_missing_count": 1 if partial else 0,
        "must_not_use_for_decision": False,
        "freshness_status": "fresh",
    }


def _scope_block(
    asset_code: str,
    publication_id: str,
    *,
    dataset_key: str = "equity.valuation.fact",
    reason_code: str = "valuation_source_data_unavailable",
) -> dict[str, object]:
    """Build the explicit, publication-bound identity for one local block."""

    return {
        "asset_code": asset_code,
        "reason_code": reason_code,
        "target_trade_date": "2026-10-16",
        "publication_id": publication_id,
        "source": "canonical-provider",
        "publication_run_id": f"run-{dataset_key}",
        "policy_version": "equity-policy-v2",
    }


def _asset_gate(
    dataset_key: str,
    publication_id: str,
    asset_code: str,
    *,
    blocked: bool = False,
    scope_block: dict[str, object] | None = None,
    blocked_reason: str | None = None,
) -> dict[str, object]:
    """Return a per-asset gate; the canonical code comes from the master row."""

    gate = {
        **_global_gate(dataset_key, publication_id),
        "asset_code": asset_code,
        "must_not_use_for_decision": blocked,
        "blocked_reason": (blocked_reason or "asset_scope_block") if blocked else "",
    }
    if scope_block is not None:
        gate["scope_block"] = scope_block
    return gate


def _context(
    asset_code: str,
    financial_publication_id: str,
    valuation_publication_id: str,
    *,
    blocked_dataset: str | None = None,
    blocked_reason: str = "valuation_source_data_unavailable",
    scope_block: dict[str, object] | None = None,
    scope_block_dataset: str | None = None,
) -> dict[str, object]:
    """Build a post-Application row with only blocked dataset values omitted."""

    financial_blocked = blocked_dataset == "equity.financial.fact"
    valuation_blocked = blocked_dataset == "equity.valuation.fact"
    financial_scope_block = scope_block if scope_block_dataset == "equity.financial.fact" else None
    valuation_scope_block = scope_block if scope_block_dataset == "equity.valuation.fact" else None

    return {
        "requested_code": asset_code,
        "asset_code": asset_code,
        "name": f"名称-{asset_code}",
        "sector": "银行" if asset_code == "000001.SZ" else "制造",
        "publication_gates": {
            "financial": _asset_gate(
                "equity.financial.fact",
                financial_publication_id,
                asset_code,
                blocked=financial_blocked,
                scope_block=financial_scope_block,
                blocked_reason=blocked_reason,
            ),
            "valuation": _asset_gate(
                "equity.valuation.fact",
                valuation_publication_id,
                asset_code,
                blocked=valuation_blocked,
                scope_block=valuation_scope_block,
                blocked_reason=blocked_reason,
            ),
        },
        "must_not_use_for_decision": blocked_dataset is not None,
        "blocked_reason": blocked_reason if blocked_dataset is not None else None,
        "roe": None if financial_blocked else (10.0 if asset_code == "000002.SZ" else 12.5),
        "revenue_growth": None if financial_blocked else 8.0,
        "profit_growth": None if financial_blocked else 6.0,
        "pe": None if valuation_blocked else (7.2 if asset_code == "000001.SZ" else 10.8),
        "pb": None if valuation_blocked else 0.8,
        "source_times": {
            "financial": {},
            "valuation": {
                "val_date": "2026-10-16",
                "observed_at": None if valuation_blocked else "2026-10-16T07:00:00+00:00",
                "available_at": None,
                "fetched_at": None if valuation_blocked else "2026-10-16T07:00:05+00:00",
            },
        },
    }


@pytest.mark.django_db
def test_published_pool_keeps_verified_asset_scope_block_inside_full_requested_result(
    authenticated_client,
) -> None:
    """A bound local block must not discard healthy assets or shrink averages."""

    financial_id = "financial-publication-current"
    valuation_id = "valuation-publication-current"
    stock_codes = ["000001.SZ", "000002.SZ"]
    contexts = {
        "000001.SZ": _context(
            "000001.SZ",
            financial_id,
            valuation_id,
            blocked_dataset="equity.valuation.fact",
            scope_block=_scope_block("000001.SZ", valuation_id),
            scope_block_dataset="equity.valuation.fact",
        ),
        "000002.SZ": _context("000002.SZ", financial_id, valuation_id),
    }
    with (
        patch(
            "apps.equity.infrastructure.adapters.StockPoolRepositoryAdapter.get_current_pool",
            return_value=stock_codes,
        ),
        patch(
            "apps.equity.infrastructure.adapters.StockPoolRepositoryAdapter.get_latest_pool_info",
            return_value={"regime": "Recovery", "updated_at": "2026-10-18"},
        ),
        patch(
            "apps.equity.interface.pool_actions.get_decision_publication_gate",
            side_effect=[
                _global_gate("equity.financial.fact", financial_id),
                _global_gate("equity.valuation.fact", valuation_id),
            ],
        ),
        patch(
            "apps.equity.interface.pool_actions.get_published_stock_context_map",
            return_value=contexts,
        ),
        patch(
            "apps.equity.infrastructure.repositories.DjangoStockRepository.get_stock_info",
            side_effect=lambda code: SimpleNamespace(
                stock_code=code,
                name=f"名称-{code}",
                sector="银行" if code == "000001.SZ" else "制造",
            ),
        ),
        patch(
            "apps.equity.infrastructure.repositories.DjangoStockRepository.get_valuation_history",
            side_effect=AssertionError("published mode must not load unbound valuations"),
        ),
        patch(
            "apps.equity.infrastructure.repositories.DjangoStockRepository.get_latest_financial_data",
            side_effect=AssertionError("published mode must not load unbound financials"),
        ),
    ):
        response = authenticated_client.get("/api/equity/pool/?mode=published")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    payload = response.json()
    assert payload["success"] is True
    assert payload["outcome"] == "partial"
    assert payload["status"] == "partial"
    assert payload["must_not_use_for_decision"] is True
    assert payload["restriction_message"] is not None
    assert payload["blocked_reason"] is None
    assert payload["requested_count"] == payload["count"] == 2
    assert payload["blocked_count"] == 1
    assert [row["code"] for row in payload["stocks"]] == stock_codes
    assert sum(row["count"] for row in payload["sector_distribution"]) == 2

    blocked, healthy = payload["stocks"]
    assert blocked["status"] == "partial"
    assert blocked["status_label"] == "估值资料受限"
    assert blocked["restriction_message"] is not None
    assert blocked["must_not_use_for_decision"] is True
    assert blocked["blocked_datasets"] == ["equity.valuation.fact"]
    assert blocked["blocked_reason"] == "valuation_source_data_unavailable"
    assert blocked["publication_gates"]["valuation"]["scope_block"] == _scope_block(
        "000001.SZ", valuation_id
    )
    assert blocked["roe"] == pytest.approx(12.5)
    assert blocked["revenue_growth"] == pytest.approx(8.0)
    assert blocked["profit_growth"] == pytest.approx(6.0)
    assert blocked["pe"] is None
    assert blocked["pb"] is None
    assert healthy["status"] == "published"
    assert healthy["status_label"] == "资料已发布"
    assert healthy["restriction_message"] is None
    assert healthy["must_not_use_for_decision"] is False
    assert healthy["roe"] == pytest.approx(10.0)

    assert payload["avg_roe"] == pytest.approx(11.25)
    assert payload["avg_pe"] is None
    assert payload["aggregate_coverage"] == {
        "avg_roe": {"known_count": 2, "requested_count": 2},
        "avg_pe": {"known_count": 1, "requested_count": 2},
    }


@pytest.mark.parametrize(
    "invalid_scope",
    (
        "missing_block",
        "wrong_asset",
        "wrong_block_publication",
        "wrong_gate_publication",
        "wrong_gate_dataset",
        "wrong_gate_key",
        "wrong_block_source",
        "wrong_block_run",
        "wrong_block_policy",
        "wrong_gate_source",
        "wrong_gate_run",
        "wrong_gate_policy",
        "wrong_master_identity",
        "missing_context",
    ),
)
@pytest.mark.django_db
def test_unverifiable_scope_or_missing_context_stays_globally_blocked(
    authenticated_client,
    invalid_scope: str,
) -> None:
    """A bool flag or mismatched identity cannot authorize partial mode."""

    financial_id = "financial-publication-current"
    valuation_id = "valuation-publication-current"
    block = _scope_block("000001.SZ", valuation_id)
    row = _context(
        "000001.SZ",
        financial_id,
        valuation_id,
        blocked_dataset="equity.valuation.fact",
        blocked_reason="valuation_source_data_unavailable",
        scope_block=block,
        scope_block_dataset="equity.valuation.fact",
    )
    contexts = {
        "000001.SZ": row,
        "000002.SZ": _context("000002.SZ", financial_id, valuation_id),
    }
    if invalid_scope == "missing_block":
        row = _context(
            "000001.SZ",
            financial_id,
            valuation_id,
            blocked_dataset="equity.valuation.fact",
            scope_block_dataset="equity.valuation.fact",
        )
        contexts["000001.SZ"] = row
    elif invalid_scope == "wrong_asset":
        row["publication_gates"]["valuation"]["scope_block"] = _scope_block(
            "000002.SZ", valuation_id
        )
    elif invalid_scope == "wrong_block_publication":
        row["publication_gates"]["valuation"]["scope_block"] = _scope_block(
            "000001.SZ", "different-publication"
        )
    elif invalid_scope == "wrong_gate_publication":
        row["publication_gates"]["valuation"]["publication_id"] = "different-publication"
    elif invalid_scope == "wrong_gate_dataset":
        row["publication_gates"]["valuation"]["dataset_key"] = "equity.financial.fact"
    elif invalid_scope == "wrong_gate_key":
        row["publication_gates"]["valuation"]["publication_key"] = "other"
    elif invalid_scope == "wrong_block_source":
        row["publication_gates"]["valuation"]["scope_block"]["source"] = "other-source"
    elif invalid_scope == "wrong_block_run":
        row["publication_gates"]["valuation"]["scope_block"]["publication_run_id"] = "other-run"
    elif invalid_scope == "wrong_block_policy":
        row["publication_gates"]["valuation"]["scope_block"]["policy_version"] = "other-policy"
    elif invalid_scope == "wrong_gate_source":
        row["publication_gates"]["valuation"]["selected_source"] = "other-source"
    elif invalid_scope == "wrong_gate_run":
        row["publication_gates"]["valuation"]["publication_run_id"] = "other-run"
    elif invalid_scope == "wrong_gate_policy":
        row["publication_gates"]["valuation"]["policy_identity"] = "other-policy"
    elif invalid_scope == "wrong_master_identity":
        row["asset_code"] = "000002.SZ"
    elif invalid_scope == "missing_context":
        contexts.pop("000001.SZ")

    with (
        patch(
            "apps.equity.infrastructure.adapters.StockPoolRepositoryAdapter.get_current_pool",
            return_value=["000001.SZ", "000002.SZ"],
        ),
        patch(
            "apps.equity.infrastructure.adapters.StockPoolRepositoryAdapter.get_latest_pool_info",
            return_value={"regime": "Recovery", "updated_at": "2026-10-18"},
        ),
        patch(
            "apps.equity.interface.pool_actions.get_decision_publication_gate",
            side_effect=[
                _global_gate("equity.financial.fact", financial_id),
                _global_gate("equity.valuation.fact", valuation_id),
            ],
        ),
        patch(
            "apps.equity.interface.pool_actions.get_published_stock_context_map",
            return_value=contexts,
        ),
        patch(
            "apps.equity.infrastructure.repositories.DjangoStockRepository.get_stock_info",
            side_effect=AssertionError("invalid scope must stop before row projection"),
        ),
    ):
        response = authenticated_client.get("/api/equity/pool/?mode=published")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "blocked"
    assert payload["success"] is False
    assert payload["outcome"] == "blocked"
    assert payload["stocks"] == []
    assert payload["count"] == 0
    assert payload["must_not_use_for_decision"] is True


@pytest.mark.parametrize(
    ("dataset_key", "reason_code"),
    (
        ("equity.financial.fact", "financial_source_data_unavailable"),
        ("equity.valuation.fact", "unknown_future_scope_reason"),
        ("equity.valuation.fact", "publication_audit_integrity_failed"),
    ),
)
@pytest.mark.django_db
def test_unsupported_scope_reasons_remain_globally_blocked(
    authenticated_client,
    dataset_key: str,
    reason_code: str,
) -> None:
    """Matching strings do not authorize unsupported local-scope downgrades."""

    financial_id = "financial-publication-current"
    valuation_id = "valuation-publication-current"
    publication_id = financial_id if dataset_key == "equity.financial.fact" else valuation_id
    block = _scope_block(
        "000001.SZ",
        publication_id,
        dataset_key=dataset_key,
        reason_code=reason_code,
    )
    context = _context(
        "000001.SZ",
        financial_id,
        valuation_id,
        blocked_dataset=dataset_key,
        blocked_reason=reason_code,
        scope_block=block,
        scope_block_dataset=dataset_key,
    )
    contexts = {
        "000001.SZ": context,
        "000002.SZ": _context("000002.SZ", financial_id, valuation_id),
    }

    with (
        patch(
            "apps.equity.infrastructure.adapters.StockPoolRepositoryAdapter.get_current_pool",
            return_value=["000001.SZ", "000002.SZ"],
        ),
        patch(
            "apps.equity.infrastructure.adapters.StockPoolRepositoryAdapter.get_latest_pool_info",
            return_value={"regime": "Recovery", "updated_at": "2026-10-16"},
        ),
        patch(
            "apps.equity.interface.pool_actions.get_decision_publication_gate",
            side_effect=[
                _global_gate("equity.financial.fact", financial_id),
                _global_gate("equity.valuation.fact", valuation_id),
            ],
        ),
        patch(
            "apps.equity.interface.pool_actions.get_published_stock_context_map",
            return_value=contexts,
        ),
        patch(
            "apps.equity.infrastructure.repositories.DjangoStockRepository.get_stock_info",
            side_effect=AssertionError("unsupported scope reason must stop row projection"),
        ),
    ):
        response = authenticated_client.get("/api/equity/pool/?mode=published")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    payload = response.json()
    assert payload["status"] == "blocked"
    assert payload["success"] is False
    assert payload["outcome"] == "blocked"
    assert payload["must_not_use_for_decision"] is True
    assert payload["stocks"] == []
    assert payload["count"] == 0


@pytest.mark.parametrize("global_failure", ("wrong_dataset", "wrong_key", "audit_blocked"))
@pytest.mark.django_db
def test_global_identity_or_audit_failure_cannot_be_downgraded_by_local_block(
    authenticated_client,
    global_failure: str,
) -> None:
    """A local valuation exclusion cannot override the publication-level gate."""

    financial_id = "financial-publication-current"
    valuation_id = "valuation-publication-current"
    valuation_block = _scope_block("000001.SZ", valuation_id)
    contexts = {
        "000001.SZ": _context(
            "000001.SZ",
            financial_id,
            valuation_id,
            blocked_dataset="equity.valuation.fact",
            scope_block=valuation_block,
            scope_block_dataset="equity.valuation.fact",
        ),
        "000002.SZ": _context("000002.SZ", financial_id, valuation_id),
    }
    financial_gate = _global_gate("equity.financial.fact", financial_id)
    valuation_gate = _global_gate("equity.valuation.fact", valuation_id)
    if global_failure == "wrong_dataset":
        valuation_gate["dataset_key"] = "equity.financial.fact"
    elif global_failure == "wrong_key":
        valuation_gate["publication_key"] = "other"
    else:
        valuation_gate["must_not_use_for_decision"] = True
        valuation_gate["blocked_reason"] = "publication_audit_integrity_failed"

    with (
        patch(
            "apps.equity.infrastructure.adapters.StockPoolRepositoryAdapter.get_current_pool",
            return_value=["000001.SZ", "000002.SZ"],
        ),
        patch(
            "apps.equity.infrastructure.adapters.StockPoolRepositoryAdapter.get_latest_pool_info",
            return_value={"regime": "Recovery", "updated_at": "2026-10-16"},
        ),
        patch(
            "apps.equity.interface.pool_actions.get_decision_publication_gate",
            side_effect=[financial_gate, valuation_gate],
        ),
        patch(
            "apps.equity.interface.pool_actions.get_published_stock_context_map",
            return_value=contexts,
        ),
        patch(
            "apps.equity.infrastructure.repositories.DjangoStockRepository.get_stock_info",
            side_effect=AssertionError("global publication failure must stop row projection"),
        ),
    ):
        response = authenticated_client.get("/api/equity/pool/?mode=published")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    payload = response.json()
    assert payload["status"] == "blocked"
    assert payload["success"] is False
    assert payload["outcome"] == "blocked"
    assert payload["must_not_use_for_decision"] is True
    assert payload["stocks"] == []
    assert payload["count"] == 0


def _payload(
    dataset_key: str,
    publication_id: str,
    *,
    rows: list[dict[str, object]],
    scope_block: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build one raw Data Center public payload at the Application boundary."""

    partial_valuation = dataset_key == "equity.valuation.fact" and scope_block is not None
    payload: dict[str, object] = {
        "publication_id": publication_id,
        "dataset_key": dataset_key,
        "publication_key": "current",
        "policy_identity": "equity-policy-v2",
        "policy_version": "equity-policy-v2",
        "selected_source": "canonical-provider",
        "publication_run_id": f"run-{dataset_key}",
        "publication_outcome": "partial" if partial_valuation else "success",
        "coverage_requested_count": 2,
        "coverage_eligible_count": 1 if partial_valuation else 2,
        "coverage_selected_count": 1 if partial_valuation else 2,
        "coverage_missing_count": 1 if partial_valuation else 0,
        "must_not_use_for_decision": scope_block is not None,
        "blocked_reason": (str(scope_block["reason_code"]) if scope_block is not None else ""),
        "rows": rows,
    }
    if scope_block is not None:
        payload["scope_block"] = scope_block
    return payload


def test_published_context_map_keeps_scope_identity_and_raw_fact_clocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Application mapping retains local identity and fact timestamps including None."""

    from apps.equity.application import query_services

    financial_id = "financial-publication-current"
    valuation_id = "valuation-publication-current"
    source_available_at = "2026-07-20T08:00:00+00:00"
    source_fetched_at = "2026-07-20T08:00:05+00:00"
    valuation_observed_at = "2026-10-16T07:00:00+00:00"
    valuation_fetched_at = "2026-10-16T07:00:05+00:00"
    block = _scope_block("000001.SZ", valuation_id)

    class _StockMasterReader:
        """Return the canonical identity used by the publication read."""

        def get_stock_master_rows(self, codes: list[str]) -> dict[str, dict[str, str]]:
            return {
                code: {"asset_code": code, "name": code, "sector": "银行", "market": "SSE"}
                for code in codes
            }

    financial_rows = [
        {
            "asset_code": "000001.SZ",
            "period_end": "2026-06-30",
            "report_date": "2026-07-20",
            "metric_code": "roe",
            "value": 12.5,
            "available_at": None,
            "fetched_at": "2026-07-20T08:00:05+00:00",
            "source_evidence": {
                "announced_at": None,
                "source_record_id": None,
                "raw_payload_hash": None,
            },
            "decision_evidence": {
                "source_time_witness": {
                    "artifact_reference": {
                        "location": "private://response-artifact",
                        "encryption_key_ref": "private-key-ref",
                        "encryption_key_version": "private-key-version",
                    },
                    "financial_announced_date": "2026-07-20",
                    "source_timezone": "Asia/Shanghai",
                    "announced_at": "2026-07-20T00:00:00+08:00",
                    "available_at": "2026-07-21T00:00:00+08:00",
                    "availability_basis": "provider_date_next_session",
                    "source_time_precision": "day",
                    "source_native_row_id": "private-native-row-id",
                }
            },
        },
        {
            "asset_code": "000002.SZ",
            "period_end": "2026-06-30",
            "report_date": "2026-07-20",
            "metric_code": "roe",
            "value": 10.0,
            "available_at": source_available_at,
            "fetched_at": source_fetched_at,
            "source_evidence": {
                "announced_at": None,
                "source_record_id": None,
                "raw_payload_hash": None,
            },
            "decision_evidence": None,
        },
        {
            "asset_code": "000002.SZ",
            "period_end": "2026-06-30",
            "report_date": "2026-07-20",
            "metric_code": "debt_ratio",
            "value": 30.0,
            "available_at": None,
            "fetched_at": "2026-07-20T08:00:06+00:00",
            "source_evidence": {
                "announced_at": None,
                "source_record_id": None,
                "raw_payload_hash": None,
            },
            "decision_evidence": None,
        },
    ]
    valuation_rows = [
        {
            "asset_code": code,
            "val_date": "2026-10-16",
            "pe_ttm": pe,
            "pb": 0.8,
            "observed_at": valuation_observed_at,
            "available_at": None,
            "fetched_at": valuation_fetched_at,
        }
        for code, pe in (("000002.SZ", 10.8),)
    ]
    raw = {
        "000001.SZ": {
            "financial": _payload(
                "equity.financial.fact",
                financial_id,
                rows=[financial_rows[0]],
            ),
            "valuation": _payload(
                "equity.valuation.fact",
                valuation_id,
                rows=[],
                scope_block=block,
            ),
        },
        "000002.SZ": {
            "financial": _payload("equity.financial.fact", financial_id, rows=financial_rows),
            "valuation": _payload("equity.valuation.fact", valuation_id, rows=valuation_rows),
        },
    }
    monkeypatch.setattr(query_services, "get_equity_stock_repository", lambda: _StockMasterReader())
    monkeypatch.setattr(
        query_services,
        "get_published_equity_context_payloads",
        lambda codes, **_kwargs: {code: raw[code] for code in codes},
    )

    result: dict[str, dict[str, Any]] = query_services.get_published_stock_context_map(
        ["000001.SZ", "000002.SZ"],
        publication_key="current",
        include_price=False,
    )

    blocked_gate = result["000001.SZ"]["publication_gates"]["valuation"]
    assert blocked_gate["dataset_key"] == "equity.valuation.fact"
    assert blocked_gate["publication_key"] == "current"
    assert blocked_gate["publication_id"] == valuation_id
    assert blocked_gate["policy_identity"] == "equity-policy-v2"
    assert blocked_gate["selected_source"] == "canonical-provider"
    assert blocked_gate["publication_run_id"] == "run-equity.valuation.fact"
    assert blocked_gate["scope_block"] == block
    assert result["000001.SZ"]["must_not_use_for_decision"] is True
    assert result["000001.SZ"]["asset_code"] == "000001.SZ"
    assert result["000001.SZ"]["roe"] == pytest.approx(12.5)
    assert result["000001.SZ"].get("pe") is None

    financial_times = result["000002.SZ"]["source_times"]["financial"]
    assert financial_times["roe"]["period_end"] == "2026-06-30"
    assert financial_times["roe"]["available_at"] == source_available_at
    assert financial_times["roe"]["fetched_at"] == source_fetched_at
    assert financial_times["roe"]["announced_at"] is None
    assert financial_times["roe"]["source_time_witness"] is None
    assert financial_times["debt_ratio"]["available_at"] is None
    assert financial_times["debt_ratio"]["fetched_at"] == "2026-07-20T08:00:06+00:00"
    assert financial_times["debt_ratio"]["announced_at"] is None
    assert financial_times["debt_ratio"]["source_time_witness"] is None
    witness = result["000001.SZ"]["source_times"]["financial"]["roe"]["source_time_witness"]
    assert witness == {
        "financial_announced_date": "2026-07-20",
        "source_timezone": "Asia/Shanghai",
        "announced_at": "2026-07-20T00:00:00+08:00",
        "available_at": "2026-07-21T00:00:00+08:00",
        "availability_basis": "provider_date_next_session",
        "source_time_precision": "day",
    }
    assert "artifact_reference" not in witness
    assert "source_native_row_id" not in witness

    valuation_times = result["000002.SZ"]["source_times"]["valuation"]
    assert valuation_times["observed_at"] == valuation_observed_at
    assert valuation_times["available_at"] is None
    assert valuation_times["fetched_at"] == valuation_fetched_at


def test_missing_canonical_master_identity_cannot_use_requested_code_as_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A requested code fallback cannot authorize a publication-local row."""

    from apps.equity.application import query_services

    financial_id = "financial-publication-current"
    valuation_id = "valuation-publication-current"

    class _MissingStockMasterReader:
        """Represent a missing canonical AssetMaster result."""

        def get_stock_master_rows(self, codes: list[str]) -> dict[str, dict[str, str]]:
            assert codes == ["000001.SZ"]
            return {}

    raw = {
        "000001.SZ": {
            "financial": _payload(
                "equity.financial.fact",
                financial_id,
                rows=[
                    {
                        "asset_code": "000001.SZ",
                        "period_end": "2026-06-30",
                        "report_date": "2026-07-20",
                        "metric_code": "roe",
                        "value": 12.5,
                        "available_at": None,
                        "fetched_at": "2026-07-20T08:00:05+00:00",
                        "source_evidence": {
                            "announced_at": None,
                            "source_record_id": None,
                            "raw_payload_hash": None,
                        },
                        "decision_evidence": None,
                    }
                ],
            ),
            "valuation": _payload(
                "equity.valuation.fact",
                valuation_id,
                rows=[
                    {
                        "asset_code": "000001.SZ",
                        "val_date": "2026-10-16",
                        "pe_ttm": 7.2,
                        "pb": 0.8,
                        "observed_at": "2026-10-16T07:00:00+00:00",
                        "available_at": None,
                        "fetched_at": "2026-10-16T07:00:05+00:00",
                    }
                ],
            ),
        }
    }
    monkeypatch.setattr(
        query_services,
        "get_equity_stock_repository",
        lambda: _MissingStockMasterReader(),
    )
    monkeypatch.setattr(
        query_services,
        "get_published_equity_context_payloads",
        lambda codes, **_kwargs: {code: raw[code] for code in codes},
    )

    result: dict[str, dict[str, Any]] = query_services.get_published_stock_context_map(
        ["000001.SZ"],
        publication_key="current",
        include_price=False,
    )

    row = result.get("000001.SZ")
    assert row is None or row["must_not_use_for_decision"] is True
    if row is not None:
        assert row["blocked_reason"] is not None
        assert row["roe"] is None
        assert row["pe"] is None
