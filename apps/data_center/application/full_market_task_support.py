"""Pure validation and outcome helpers for the full-market Celery task."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence, Set

from shared.domain.task_outcomes import TaskBusinessOutcome


def asset_code_scope_sha256(asset_codes: Sequence[str]) -> str:
    """Return the canonical digest for one frozen asset-code scope."""

    return hashlib.sha256(
        json.dumps(
            sorted(asset_codes),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def valuation_partial_policy_allows(
    *,
    dataset_key: str | None,
    allow_partial: bool,
    uses_versioned_evidence: bool,
    coverage_ratio: float,
    minimum_coverage_ratio: float,
) -> bool:
    """Apply the versioned valuation partial-publication policy without defaults."""

    return (
        dataset_key == "equity.valuation.fact"
        and allow_partial
        and uses_versioned_evidence
        and coverage_ratio >= minimum_coverage_ratio
    )


def exact_provider_batch_count(
    *,
    requested_asset_codes: Sequence[str],
    stored_count: object,
    returned_asset_codes: object,
    succeeded_asset_codes: object | None = None,
) -> int:
    """Return the stored count only when every requested identity is exact."""

    if isinstance(stored_count, bool) or not isinstance(stored_count, int):
        raise ValueError("provider batch stored_count must be an integer")
    if isinstance(returned_asset_codes, (str, bytes)) or not isinstance(
        returned_asset_codes, Sequence
    ):
        raise ValueError("provider batch asset identities are unavailable")
    requested = tuple(str(code or "").strip().upper() for code in requested_asset_codes)
    returned = tuple(str(code or "").strip().upper() for code in returned_asset_codes)
    succeeded = returned
    if succeeded_asset_codes is not None:
        if isinstance(succeeded_asset_codes, (str, bytes)) or not isinstance(
            succeeded_asset_codes, Sequence
        ):
            raise ValueError("provider batch succeeded identities are unavailable")
        succeeded = tuple(str(code or "").strip().upper() for code in succeeded_asset_codes)
    if (
        any(not code for code in (*requested, *returned, *succeeded))
        or len(set(requested)) != len(requested)
        or len(set(returned)) != len(returned)
        or len(set(succeeded)) != len(succeeded)
        or stored_count != len(requested)
        or len(returned) != len(requested)
        or len(succeeded) != len(requested)
        or set(returned) != set(requested)
        or set(succeeded) != set(requested)
    ):
        raise ValueError("provider batch asset identities are incomplete")
    return stored_count


def full_market_input_failure(reason: str) -> dict[str, object]:
    """Publish a stable zero-write failure before any market fetch."""

    return {
        "outcome": "failed",
        "success": False,
        "requested": 0,
        "succeeded": 0,
        "failed": 0,
        "stored": 0,
        "blocked_reason": reason,
    }


def full_market_soft_timeout_failure(
    *,
    requested_operations: int,
    completed_operations: int,
    stored_rows: int,
    target_trade_date: str,
    phase: str,
    asset_count: int,
    publication_run_id: str,
    quote_source: str,
    valuation_source: str,
    market_universe: Mapping[str, object],
    valuation_seed_stored: int,
    excluded_non_trading_codes: Sequence[str],
) -> dict[str, object]:
    """Return a durable business result when the worker reaches its soft deadline."""

    excluded = tuple(excluded_non_trading_codes)
    return {
        "outcome": TaskBusinessOutcome.FAILED.value,
        "success": False,
        "requested": requested_operations,
        "succeeded": completed_operations,
        "failed": 1,
        "stored": stored_rows,
        "count_unit": "sync_operation",
        "stored_count_unit": "fact_row",
        "target_trade_date": target_trade_date,
        "phase": phase,
        "asset_count": asset_count,
        "published_members": 0,
        "publication_updated": False,
        "publication_run_id": publication_run_id,
        "error_code": "MARKET_REFRESH_SOFT_TIME_LIMIT_EXCEEDED",
        "blocked_reason": "market_refresh_soft_time_limit_exceeded",
        "errors": ["MARKET_REFRESH_SOFT_TIME_LIMIT_EXCEEDED"],
        "must_not_use_for_decision": True,
        "quote_source": quote_source,
        "valuation_source": valuation_source,
        "market_universe": dict(market_universe),
        "valuation_seed_stored": valuation_seed_stored,
        "excluded_non_trading_count": len(excluded),
        "excluded_non_trading_codes": list(excluded),
    }


def valuation_scope_incomplete_failure(
    *,
    requested_codes: Set[str],
    succeeded_codes: Set[str],
    missing_codes: Sequence[str],
    unexpected_returned_codes: Sequence[str],
    stored_count: int,
    publication_run_id: str,
    target_trade_date: str,
    market_universe: Mapping[str, object],
    coverage_ratio: float,
    policy_identity: str | None,
) -> dict[str, object]:
    """Return asset-denominated evidence for a policy-rejected valuation gap."""

    return {
        **full_market_input_failure("valuation_scope_incomplete"),
        "outcome": TaskBusinessOutcome.BLOCKED.value,
        "success": False,
        "must_not_use_for_decision": True,
        "blocked_reason": "current_valuation_scope_incomplete",
        "error_code": "CURRENT_VALUATION_SCOPE_INCOMPLETE",
        "errors": ["CURRENT_VALUATION_SCOPE_INCOMPLETE"],
        "requested": len(requested_codes),
        "succeeded": len(succeeded_codes),
        "failed": len(missing_codes),
        "stored": stored_count,
        "count_unit": "valuation_asset",
        "stored_count_unit": "fact_row",
        "operation_requested": 1,
        "operation_succeeded": 0,
        "operation_failed": 1,
        "publication_updated": False,
        "published_members": 0,
        "publication_run_id": publication_run_id,
        "target_trade_date": target_trade_date,
        "market_universe": dict(market_universe),
        "requested_asset_count": len(requested_codes),
        "succeeded_asset_count": len(succeeded_codes),
        "failed_asset_count": len(missing_codes),
        "missing_asset_codes": list(missing_codes),
        "unexpected_returned_asset_codes": list(unexpected_returned_codes),
        "excluded_non_trading_count": 0,
        "excluded_non_trading_codes": [],
        "valuation_seed_stored": stored_count,
        "valuation_coverage_ratio": coverage_ratio,
        "valuation_policy_identity": policy_identity,
    }


def finalize_full_market_result(
    *,
    result: Mapping[str, object],
    price_evidence: Mapping[str, object],
    publication_evidence: Mapping[str, object],
    publication_run_id: str,
    quote_source: str,
    valuation_source: str,
    market_universe: Mapping[str, object],
    valuation_seed_stored: int,
    stored_row_count: int,
    requested_codes: Set[str],
    succeeded_codes: Set[str],
    missing_codes: Sequence[str],
    coverage_ratio: float,
    policy_identity: str | None,
) -> dict[str, object]:
    """Project operation results into the stable asset-denominated task contract."""

    phase_results = (
        [dict(item) for item in raw_phase_results if isinstance(item, Mapping)]
        if isinstance((raw_phase_results := result.get("phase_results")), list)
        else []
    )
    for phase_result in phase_results:
        if phase_result.get("phase") == "valuation":
            phase_result["stored"] = valuation_seed_stored
    datasets = publication_evidence.get("datasets")
    valuation_evidence = (
        next(
            (
                item
                for item in datasets
                if isinstance(item, Mapping) and item.get("dataset_key") == "equity.valuation.fact"
            ),
            None,
        )
        if isinstance(datasets, list)
        else None
    )
    raw_scope_blocks = (
        valuation_evidence.get("scope_blocks") if isinstance(valuation_evidence, Mapping) else None
    )
    scope_blocks = (
        [dict(item) for item in raw_scope_blocks if isinstance(item, Mapping)]
        if missing_codes and isinstance(raw_scope_blocks, list)
        else []
    )
    business_outcome = (
        TaskBusinessOutcome.PARTIAL.value
        if missing_codes and result.get("publication_updated")
        else str(result.get("outcome") or TaskBusinessOutcome.FAILED.value)
    )
    return {
        **result,
        "phase_results": phase_results,
        **price_evidence,
        **publication_evidence,
        "publication_run_id": publication_run_id,
        "quote_source": quote_source,
        "valuation_source": valuation_source,
        "market_universe": dict(market_universe),
        "valuation_seed_stored": valuation_seed_stored,
        "excluded_non_trading_count": 0,
        "excluded_non_trading_codes": [],
        "outcome": business_outcome,
        "success": business_outcome == TaskBusinessOutcome.SUCCESS.value,
        "requested": len(requested_codes),
        "succeeded": len(succeeded_codes),
        "failed": len(missing_codes),
        "stored": stored_row_count,
        "count_unit": "valuation_asset",
        "stored_count_unit": "fact_row",
        "operation_requested": result.get("requested"),
        "operation_succeeded": result.get("succeeded"),
        "operation_failed": result.get("failed"),
        "requested_asset_count": len(requested_codes),
        "succeeded_asset_count": len(succeeded_codes),
        "failed_asset_count": len(missing_codes),
        "missing_asset_codes": list(missing_codes),
        "scope_blocks": scope_blocks,
        "valuation_coverage_ratio": coverage_ratio,
        "valuation_policy_identity": policy_identity,
    }
