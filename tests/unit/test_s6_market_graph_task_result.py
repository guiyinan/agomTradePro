"""Contract tests for evidence-qualified S6 market task results."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from typing import cast

import pytest

from apps.data_center.application import s6_market_graph_task_result as contract

_RUN_ID = "11111111-1111-4111-8111-111111111111"
_TARGET = "2026-10-09"
_DATASETS = (
    "equity.price.bar",
    "equity.quote.snapshot",
    "equity.valuation.fact",
)


def _block(dataset_key: str, publication_id: str) -> dict[str, object]:
    """Return one fully bound partial-publication block."""

    reasons = {
        "equity.price.bar": "price_full_day_suspension",
        "equity.quote.snapshot": "quote_full_day_suspension",
        "equity.valuation.fact": "valuation_source_data_unavailable",
    }
    value: dict[str, object] = {
        "asset_code": "600001.SH",
        "reason_code": reasons[dataset_key],
        "target_trade_date": _TARGET,
        "source": "tushare",
        "publication_run_id": _RUN_ID,
        "policy_version": f"p2:{dataset_key}:policy",
        "publication_id": publication_id,
    }
    if dataset_key != "equity.valuation.fact":
        value["evidence_source"] = "tushare.suspend_d"
    return value


def _publication(dataset_key: str, index: int, *, partial: bool) -> dict[str, object]:
    """Return one versioned current publication projection."""

    publication_id = f"00000000-0000-4000-8000-{index:012d}"
    missing = int(partial)
    member_count = 3 - missing
    return {
        "dataset_key": dataset_key,
        "publication_id": publication_id,
        "publication_key": "current",
        "policy_version": f"p2:{dataset_key}:policy",
        "selected_source": "tushare",
        "publication_hash": str(index) * 64,
        "member_count": member_count,
        "as_of": datetime(2026, 10, 9, 7, tzinfo=UTC),
        "published_at": datetime(2026, 10, 9, 8, tzinfo=UTC),
        "run_id": _RUN_ID,
        "state": "published",
        "must_not_use_for_decision": False,
        "coverage_requested_count": 3,
        "coverage_eligible_count": member_count,
        "coverage_selected_count": member_count,
        "coverage_missing_count": missing,
        "scope_blocks": [_block(dataset_key, publication_id)] if partial else [],
    }


def _graph(*, partial: bool) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Return matching publication headers and a normalized task result."""

    publications = [
        _publication(dataset, index, partial=partial and dataset != "equity.valuation.fact")
        for index, dataset in enumerate(_DATASETS, start=1)
    ]
    missing_codes = ["600001.SH"] if partial else []
    failed = len(missing_codes)
    summaries = [
        {
            "dataset_key": item["dataset_key"],
            "publication_id": item["publication_id"],
            "publication_hash": item["publication_hash"],
            "member_count": item["member_count"],
            "requested_asset_count": item["coverage_requested_count"],
            "covered_asset_count": item["coverage_selected_count"],
            "missing_asset_count": item["coverage_missing_count"],
            "outcome": "partial" if item["coverage_missing_count"] else "success",
            "scope_blocks": item["scope_blocks"],
            "policy_identity": item["policy_version"],
            "as_of": item["as_of"].isoformat(),
            "published_at": item["published_at"].isoformat(),
        }
        for item in publications
    ]
    ordered = sorted(publications, key=lambda item: str(item["dataset_key"]))
    flattened_blocks = [
        block for item in ordered for block in cast(list[dict[str, object]], item["scope_blocks"])
    ]
    quote_blocks = next(
        item["scope_blocks"]
        for item in publications
        if item["dataset_key"] == "equity.quote.snapshot"
    )
    result: dict[str, object] = {
        "outcome": "partial" if partial else "success",
        "success": True,
        "phase": "completed",
        "requested": 3,
        "succeeded": 3 - failed,
        "failed": failed,
        "stored": 5 if partial else 6,
        "count_unit": "valuation_asset",
        "stored_count_unit": "fact_row",
        "operation_requested": 7,
        "operation_succeeded": 7,
        "operation_failed": 0,
        "requested_asset_count": 3,
        "succeeded_asset_count": 3 - failed,
        "failed_asset_count": failed,
        "missing_asset_codes": missing_codes,
        "publication_updated": True,
        "published_members": sum(int(item["member_count"]) for item in publications),
        "must_not_use_for_decision": False,
        "target_trade_date": _TARGET,
        "run_id": _RUN_ID,
        "publication_run_id": _RUN_ID,
        "publication_ids": [item["publication_id"] for item in reversed(publications)],
        "datasets": summaries,
        "scope_blocks": flattened_blocks,
        "quote_scope_blocks": quote_blocks,
        "excluded_non_trading_codes": missing_codes,
    }
    return publications, result


@pytest.mark.parametrize("partial", (False, True))
def test_contract_accepts_complete_and_evidence_qualified_dynamic_partial(partial: bool) -> None:
    """A dynamic partial passes only with a complete immutable evidence partition."""

    publications, result = _graph(partial=partial)

    contract.validate_market_graph_task_result(
        result,
        publications,
        target_trade_date=_TARGET,
        run_id=_RUN_ID,
    )


def test_contract_accepts_policy_bound_valuation_partial() -> None:
    """A valuation gap is counted only when its publication carries exact evidence."""

    publications, result = _graph(partial=False)
    valuation = publications[2]
    valuation["member_count"] = 2
    valuation["coverage_eligible_count"] = 2
    valuation["coverage_selected_count"] = 2
    valuation["coverage_missing_count"] = 1
    valuation["scope_blocks"] = [
        _block("equity.valuation.fact", cast(str, valuation["publication_id"]))
    ]
    summaries = cast(list[dict[str, object]], result["datasets"])
    summaries[2].update(
        {
            "member_count": 2,
            "covered_asset_count": 2,
            "missing_asset_count": 1,
            "outcome": "partial",
            "scope_blocks": valuation["scope_blocks"],
        }
    )
    result.update(
        {
            "outcome": "partial",
            "succeeded": 2,
            "failed": 1,
            "succeeded_asset_count": 2,
            "failed_asset_count": 1,
            "missing_asset_codes": ["600001.SH"],
            "published_members": 8,
            "scope_blocks": valuation["scope_blocks"],
        }
    )

    contract.validate_market_graph_task_result(
        result,
        publications,
        target_trade_date=_TARGET,
        run_id=_RUN_ID,
    )


def test_contract_does_not_double_count_price_only_scope_gap() -> None:
    """Price scope evidence is validated without changing valuation-denominated counts."""

    publications, result = _graph(partial=False)
    price = publications[0]
    price["member_count"] = 2
    price["coverage_eligible_count"] = 2
    price["coverage_selected_count"] = 2
    price["coverage_missing_count"] = 1
    price["scope_blocks"] = [_block("equity.price.bar", cast(str, price["publication_id"]))]
    summaries = cast(list[dict[str, object]], result["datasets"])
    summaries[0].update(
        {
            "member_count": 2,
            "covered_asset_count": 2,
            "missing_asset_count": 1,
            "outcome": "partial",
            "scope_blocks": price["scope_blocks"],
        }
    )
    result["published_members"] = 8
    result["scope_blocks"] = price["scope_blocks"]

    contract.validate_market_graph_task_result(
        result,
        publications,
        target_trade_date=_TARGET,
        run_id=_RUN_ID,
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "missing_scope_block",
        "missing_evidence_source",
        "unsupported_reason",
        "block_policy_drift",
        "missing_code_drift",
        "operation_failure",
        "decision_blocked",
        "wrong_outcome",
        "dataset_summary_drift",
        "target_date_drift",
        "run_drift",
    ),
)
def test_contract_rejects_unexplained_or_drifting_partial(mutation: str) -> None:
    """A partial cannot pass when any task, scope, policy, or graph binding differs."""

    publications, result = _graph(partial=True)
    publications = deepcopy(publications)
    result = deepcopy(result)
    if mutation == "missing_scope_block":
        publications[0]["scope_blocks"] = []
    elif mutation == "missing_evidence_source":
        blocks = cast(list[dict[str, object]], publications[0]["scope_blocks"])
        blocks[0]["evidence_source"] = ""
    elif mutation == "unsupported_reason":
        blocks = cast(list[dict[str, object]], publications[0]["scope_blocks"])
        blocks[0]["reason_code"] = "suspended"
    elif mutation == "block_policy_drift":
        blocks = cast(list[dict[str, object]], publications[0]["scope_blocks"])
        blocks[0]["policy_version"] = "old"
    elif mutation == "missing_code_drift":
        result["missing_asset_codes"] = ["600002.SH"]
    elif mutation == "operation_failure":
        result["operation_succeeded"] = 6
        result["operation_failed"] = 1
    elif mutation == "decision_blocked":
        result["must_not_use_for_decision"] = True
    elif mutation == "wrong_outcome":
        result["outcome"] = "success"
    elif mutation == "dataset_summary_drift":
        summaries = cast(list[dict[str, object]], result["datasets"])
        summaries[0]["publication_hash"] = "0" * 64
    elif mutation == "target_date_drift":
        result["target_trade_date"] = "2026-10-08"
    elif mutation == "run_drift":
        result["publication_run_id"] = "22222222-2222-4222-8222-222222222222"

    with pytest.raises(contract.MarketGraphTaskResultError):
        contract.validate_market_graph_task_result(
            result,
            publications,
            target_trade_date=_TARGET,
            run_id=_RUN_ID,
        )


def test_projection_is_bounded_and_does_not_copy_diagnostics_or_secrets() -> None:
    """The receipt retains required evidence without copying arbitrary task payloads."""

    _, result = _graph(partial=True)
    result["provider_response"] = "secret"
    result["errors"] = ["sensitive diagnostic"]

    projected = contract.project_market_graph_task_result(result)

    assert projected["outcome"] == "partial"
    assert projected["datasets"] == result["datasets"]
    assert "provider_response" not in projected
    assert "errors" not in projected


def test_contract_accepts_actual_task_monitor_projection_for_dynamic_partial() -> None:
    """A large result remains graph-verifiable after Task Monitor bounds it."""

    from apps.task_monitor.application.tasks import _serialize_task_result

    publications, result = _graph(partial=True)
    result["provider_diagnostics"] = ["sensitive" * 2_000]

    serialized = _serialize_task_result(result)
    projected = cast(dict[str, object], json.loads(serialized))

    assert projected["result_projection"] == "bounded_business_fields"
    assert "scope_blocks" not in projected
    assert projected["requested_asset_count"] == 3
    contract.validate_market_graph_task_result(
        projected,
        publications,
        target_trade_date=_TARGET,
        run_id=_RUN_ID,
    )


def test_contract_rejects_boolean_count_alias() -> None:
    """Boolean values cannot satisfy integer aliases through Python equality."""

    publications, result = _graph(partial=True)
    result["failed_asset_count"] = True

    with pytest.raises(contract.MarketGraphTaskResultError):
        contract.validate_market_graph_task_result(
            result,
            publications,
            target_trade_date=_TARGET,
            run_id=_RUN_ID,
        )


def test_contract_rejects_boolean_dataset_summary_count() -> None:
    """Dataset count summaries reject bool-as-int aliases."""

    publications, result = _graph(partial=True)
    summaries = cast(list[dict[str, object]], result["datasets"])
    summaries[0]["missing_asset_count"] = True

    with pytest.raises(contract.MarketGraphTaskResultError):
        contract.validate_market_graph_task_result(
            result,
            publications,
            target_trade_date=_TARGET,
            run_id=_RUN_ID,
        )
