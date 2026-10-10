"""Validate and project the normalized task result for an S6 market graph."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import cast
from uuid import UUID

CORE_MARKET_DATASETS = frozenset(
    {
        "equity.price.bar",
        "equity.quote.snapshot",
        "equity.valuation.fact",
    }
)
_EXPECTED_SCOPE_REASONS = {
    "equity.price.bar": "price_full_day_suspension",
    "equity.quote.snapshot": "quote_full_day_suspension",
    "equity.valuation.fact": "valuation_source_data_unavailable",
}
_TASK_RESULT_FIELDS = (
    "result_projection",
    "outcome",
    "success",
    "phase",
    "requested",
    "succeeded",
    "failed",
    "stored",
    "count_unit",
    "stored_count_unit",
    "operation_requested",
    "operation_succeeded",
    "operation_failed",
    "requested_asset_count",
    "succeeded_asset_count",
    "failed_asset_count",
    "missing_asset_codes",
    "publication_updated",
    "published_members",
    "must_not_use_for_decision",
    "target_trade_date",
    "run_id",
    "publication_run_id",
    "publication_ids",
    "datasets",
    "scope_blocks",
    "quote_scope_blocks",
    "excluded_non_trading_codes",
)


class MarketGraphTaskResultError(ValueError):
    """The task result does not exactly describe a usable current graph."""


def _integer(value: object, *, positive: bool = False) -> int:
    """Return a strict integer or reject booleans and invalid bounds."""

    if not isinstance(value, int) or isinstance(value, bool):
        raise MarketGraphTaskResultError("task result count is invalid")
    if value < 0 or (positive and value == 0):
        raise MarketGraphTaskResultError("task result count is invalid")
    return value


def _canonical_date(value: object) -> str:
    """Return one canonical ISO date string."""

    if not isinstance(value, str):
        raise MarketGraphTaskResultError("task result date is invalid")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise MarketGraphTaskResultError("task result date is invalid") from exc
    if parsed.isoformat() != value:
        raise MarketGraphTaskResultError("task result date is invalid")
    return value


def _canonical_timestamp(value: object) -> str:
    """Return an aware timestamp in its canonical serialized form."""

    if isinstance(value, datetime):
        parsed = value
        text = value.isoformat()
    elif isinstance(value, str):
        text = value
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise MarketGraphTaskResultError("publication timestamp is invalid") from exc
    else:
        raise MarketGraphTaskResultError("publication timestamp is invalid")
    if parsed.tzinfo is None or parsed.utcoffset() is None or parsed.isoformat() != text:
        raise MarketGraphTaskResultError("publication timestamp is invalid")
    return text


def _identifier(value: object) -> str:
    """Return a non-empty string or UUID identity."""

    if isinstance(value, UUID):
        return str(value)
    if not isinstance(value, str) or not value or value != value.strip():
        raise MarketGraphTaskResultError("publication identity is invalid")
    return value


def _asset_codes(value: object) -> tuple[str, ...]:
    """Return a canonical, sorted, unique asset-code tuple."""

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise MarketGraphTaskResultError("task result asset codes are invalid")
    codes: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item or item != item.strip().upper():
            raise MarketGraphTaskResultError("task result asset codes are invalid")
        codes.append(item)
    if tuple(sorted(set(codes))) != tuple(codes):
        raise MarketGraphTaskResultError("task result asset codes are invalid")
    return tuple(codes)


def _scope_block(
    value: object,
    *,
    dataset_key: str,
    target_trade_date: str,
    selected_source: str,
    run_id: str,
    policy_version: str,
    publication_id: str,
) -> dict[str, object]:
    """Validate and project one current-publication scope block."""

    if not isinstance(value, Mapping):
        raise MarketGraphTaskResultError("publication scope block is invalid")
    allowed = {
        "asset_code",
        "reason_code",
        "target_trade_date",
        "source",
        "publication_run_id",
        "policy_version",
        "publication_id",
        "evidence_source",
    }
    if any(not isinstance(key, str) or key not in allowed for key in value):
        raise MarketGraphTaskResultError("publication scope block is invalid")
    asset_code = value.get("asset_code")
    expected_reason = _EXPECTED_SCOPE_REASONS[dataset_key]
    if (
        not isinstance(asset_code, str)
        or not asset_code
        or asset_code != asset_code.strip().upper()
        or value.get("reason_code") != expected_reason
        or value.get("target_trade_date") != target_trade_date
        or value.get("source") != selected_source
        or value.get("publication_run_id") != run_id
        or value.get("policy_version") != policy_version
        or value.get("publication_id") != publication_id
    ):
        raise MarketGraphTaskResultError("publication scope block is invalid")
    evidence_source = value.get("evidence_source", "")
    if not isinstance(evidence_source, str) or evidence_source != evidence_source.strip():
        raise MarketGraphTaskResultError("publication scope block is invalid")
    if dataset_key in {"equity.price.bar", "equity.quote.snapshot"} and not evidence_source:
        raise MarketGraphTaskResultError("market suspension evidence is missing")
    projected: dict[str, object] = {
        "asset_code": asset_code,
        "reason_code": expected_reason,
        "target_trade_date": target_trade_date,
        "source": selected_source,
        "publication_run_id": run_id,
        "policy_version": policy_version,
        "publication_id": publication_id,
    }
    if evidence_source:
        projected["evidence_source"] = evidence_source
    return projected


def _publication_projection(
    publication: Mapping[str, object], *, target_trade_date: str, run_id: str
) -> dict[str, object]:
    """Validate one publication header and its complete missing-scope evidence."""

    dataset_key = publication.get("dataset_key")
    if not isinstance(dataset_key, str) or dataset_key not in CORE_MARKET_DATASETS:
        raise MarketGraphTaskResultError("publication dataset is invalid")
    publication_id = _identifier(publication.get("publication_id"))
    publication_hash = _identifier(publication.get("publication_hash"))
    policy_version = _identifier(publication.get("policy_version"))
    selected_source = _identifier(publication.get("selected_source"))
    if (
        publication.get("publication_key") != "current"
        or publication.get("state") != "published"
        or publication.get("must_not_use_for_decision") is not False
        or _identifier(publication.get("run_id")) != run_id
    ):
        raise MarketGraphTaskResultError("publication state is invalid")
    member_count = _integer(publication.get("member_count"), positive=True)
    requested = _integer(publication.get("coverage_requested_count"), positive=True)
    eligible = _integer(publication.get("coverage_eligible_count"))
    selected = _integer(publication.get("coverage_selected_count"))
    missing = _integer(publication.get("coverage_missing_count"))
    if selected != eligible or selected != member_count or selected + missing != requested:
        raise MarketGraphTaskResultError("publication coverage partition is invalid")
    raw_blocks = publication.get("scope_blocks")
    if not isinstance(raw_blocks, Sequence) or isinstance(raw_blocks, (str, bytes, bytearray)):
        raise MarketGraphTaskResultError("publication scope blocks are invalid")
    blocks = [
        _scope_block(
            item,
            dataset_key=dataset_key,
            target_trade_date=target_trade_date,
            selected_source=selected_source,
            run_id=run_id,
            policy_version=policy_version,
            publication_id=publication_id,
        )
        for item in raw_blocks
    ]
    block_codes = tuple(cast(str, item["asset_code"]) for item in blocks)
    if len(blocks) != missing or tuple(sorted(set(block_codes))) != block_codes:
        raise MarketGraphTaskResultError("publication scope blocks are invalid")
    return {
        "dataset_key": dataset_key,
        "publication_id": publication_id,
        "publication_hash": publication_hash,
        "policy_identity": policy_version,
        "selected_source": selected_source,
        "member_count": member_count,
        "requested_asset_count": requested,
        "covered_asset_count": selected,
        "missing_asset_count": missing,
        "outcome": "partial" if missing else "success",
        "scope_blocks": blocks,
        "as_of": _canonical_timestamp(publication.get("as_of")),
        "published_at": _canonical_timestamp(publication.get("published_at")),
    }


def validate_market_graph_task_result(
    result: Mapping[str, object],
    publications: Sequence[Mapping[str, object]],
    *,
    target_trade_date: str,
    run_id: str,
) -> None:
    """Require task statistics to exactly describe an evidenced current graph.

    A partial result is accepted only when every missing asset is explained by
    the immutable publication graph.  This function does not decide policy
    eligibility; callers must first validate each publication against the
    active policy and immutable member evidence.
    """

    target_text = _canonical_date(target_trade_date)
    bounded_projection = result.get("result_projection") == "bounded_business_fields"
    if result.get("result_projection") not in {None, "bounded_business_fields"}:
        raise MarketGraphTaskResultError("task result projection is invalid")
    if result.get("target_trade_date") != target_text:
        raise MarketGraphTaskResultError("task result target date differs")
    run_text = _identifier(run_id)
    if result.get("run_id") != run_text or result.get("publication_run_id") != run_text:
        raise MarketGraphTaskResultError("task result run identity differs")
    if (
        result.get("success") is not True
        or result.get("phase") != "completed"
        or result.get("publication_updated") is not True
        or result.get("must_not_use_for_decision") is not False
        or result.get("count_unit") != "valuation_asset"
        or result.get("stored_count_unit") != "fact_row"
    ):
        raise MarketGraphTaskResultError("task result is not decision usable")

    requested = _integer(result.get("requested"), positive=True)
    succeeded = _integer(result.get("succeeded"))
    failed = _integer(result.get("failed"))
    _integer(result.get("stored"), positive=True)
    operation_requested = _integer(result.get("operation_requested"), positive=True)
    operation_succeeded = _integer(result.get("operation_succeeded"))
    operation_failed = _integer(result.get("operation_failed"))
    if operation_succeeded != operation_requested or operation_failed != 0:
        raise MarketGraphTaskResultError("task operation result is incomplete")
    if (
        _integer(result.get("requested_asset_count"), positive=True) != requested
        or _integer(result.get("succeeded_asset_count")) != succeeded
        or _integer(result.get("failed_asset_count")) != failed
    ):
        raise MarketGraphTaskResultError("task asset counts differ")

    publication_by_dataset: dict[str, dict[str, object]] = {}
    for publication in publications:
        projected = _publication_projection(
            publication,
            target_trade_date=target_text,
            run_id=run_text,
        )
        dataset_key = cast(str, projected["dataset_key"])
        if dataset_key in publication_by_dataset:
            raise MarketGraphTaskResultError("publication dataset is duplicated")
        publication_by_dataset[dataset_key] = projected
    if set(publication_by_dataset) != CORE_MARKET_DATASETS:
        raise MarketGraphTaskResultError("publication dataset set is incomplete")
    if any(item["requested_asset_count"] != requested for item in publication_by_dataset.values()):
        raise MarketGraphTaskResultError("publication denominators differ")

    quote_blocks = cast(
        list[dict[str, object]],
        publication_by_dataset["equity.quote.snapshot"]["scope_blocks"],
    )
    valuation_blocks = cast(
        list[dict[str, object]],
        publication_by_dataset["equity.valuation.fact"]["scope_blocks"],
    )
    failed_codes = tuple(
        sorted({cast(str, block["asset_code"]) for block in (*quote_blocks, *valuation_blocks)})
    )
    if (
        succeeded + failed != requested
        or failed != len(failed_codes)
        or succeeded != requested - len(failed_codes)
    ):
        raise MarketGraphTaskResultError("task missing-scope partition differs")
    if not bounded_projection and (
        _asset_codes(result.get("missing_asset_codes")) != failed_codes
        or result.get("excluded_non_trading_codes")
        != [cast(str, item["asset_code"]) for item in quote_blocks]
        or result.get("quote_scope_blocks") != quote_blocks
    ):
        raise MarketGraphTaskResultError("task missing-scope partition differs")
    expected_outcome = "partial" if failed else "success"
    if result.get("outcome") != expected_outcome:
        raise MarketGraphTaskResultError("task outcome differs from missing scope")

    ordered_publications = [publication_by_dataset[key] for key in sorted(CORE_MARKET_DATASETS)]
    publication_ids = [cast(str, item["publication_id"]) for item in ordered_publications]
    raw_publication_ids = result.get("publication_ids")
    if (
        not isinstance(raw_publication_ids, Sequence)
        or isinstance(raw_publication_ids, (str, bytes, bytearray))
        or len(raw_publication_ids) != len(publication_ids)
        or {item for item in raw_publication_ids if isinstance(item, str)} != set(publication_ids)
        or _integer(result.get("published_members"), positive=True)
        != sum(cast(int, item["member_count"]) for item in ordered_publications)
    ):
        raise MarketGraphTaskResultError("task publication summary differs")
    if not bounded_projection and result.get("scope_blocks") != [
        block
        for item in ordered_publications
        for block in cast(list[dict[str, object]], item["scope_blocks"])
    ]:
        raise MarketGraphTaskResultError("task publication summary differs")
    raw_datasets = result.get("datasets")
    if not isinstance(raw_datasets, Sequence) or isinstance(raw_datasets, (str, bytes, bytearray)):
        raise MarketGraphTaskResultError("task dataset summaries are invalid")
    summaries: dict[str, Mapping[str, object]] = {}
    for item in raw_datasets:
        if not isinstance(item, Mapping) or not isinstance(item.get("dataset_key"), str):
            raise MarketGraphTaskResultError("task dataset summaries are invalid")
        dataset_key = cast(str, item["dataset_key"])
        if dataset_key in summaries:
            raise MarketGraphTaskResultError("task dataset summaries are duplicated")
        summaries[dataset_key] = item
    if set(summaries) != CORE_MARKET_DATASETS:
        raise MarketGraphTaskResultError("task dataset summary set is incomplete")
    for dataset_key, publication in publication_by_dataset.items():
        summary = summaries[dataset_key]
        for count_field in (
            "member_count",
            "requested_asset_count",
            "covered_asset_count",
            "missing_asset_count",
        ):
            _integer(summary.get(count_field))
        fields = [
            "publication_id",
            "publication_hash",
            "member_count",
            "requested_asset_count",
            "covered_asset_count",
            "missing_asset_count",
            "outcome",
            "policy_identity",
            "as_of",
            "published_at",
        ]
        if not bounded_projection:
            fields.append("scope_blocks")
        for field in fields:
            if summary.get(field) != publication[field]:
                raise MarketGraphTaskResultError("task dataset summary differs")


def project_market_graph_task_result(result: Mapping[str, object]) -> dict[str, object]:
    """Return the bounded, non-secret Task Monitor evidence needed downstream."""

    return {field: result[field] for field in _TASK_RESULT_FIELDS if field in result}


__all__ = [
    "CORE_MARKET_DATASETS",
    "MarketGraphTaskResultError",
    "project_market_graph_task_result",
    "validate_market_graph_task_result",
]
