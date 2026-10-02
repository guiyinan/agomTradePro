"""Pure validation and outcome helpers for the full-market Celery task."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence, Set

from apps.data_center.domain.entities import RawAuditReference
from shared.domain.task_outcomes import TaskBusinessOutcome

from .market_publication_refresh import MarketPublicationRefreshBlocked


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


def require_sync_raw_audit_reference(
    reference: RawAuditReference | None,
    *,
    run_id: str | None,
    ingested_run_id: str | None,
) -> RawAuditReference:
    """Require an exact raw-audit reference bound to its sync result."""

    if not isinstance(reference, RawAuditReference):
        raise MarketPublicationRefreshBlocked(
            "Market sync returned no exact RawAudit reference",
            code="CURRENT_RAW_AUDIT_REFERENCE_MISSING",
        )
    if reference.run_id != run_id or reference.ingested_run_id != ingested_run_id:
        raise MarketPublicationRefreshBlocked(
            "Market RawAudit reference does not match its sync result",
            code="CURRENT_RAW_AUDIT_REFERENCE_IDENTITY_INVALID",
        )
    return reference


def serialize_raw_audit_references(
    references: Mapping[str, RawAuditReference],
) -> list[dict[str, str]]:
    """Return deterministic JSON-ready exact RawAudit reference values."""

    return [
        {
            "raw_audit_id": reference.raw_audit_id,
            "version": reference.version,
            "content_hash": reference.content_hash,
            "run_id": reference.run_id,
            "ingested_run_id": reference.ingested_run_id,
        }
        for _raw_audit_id, reference in sorted(references.items())
    ]


def apply_full_market_authority_block(
    result: dict[str, object],
    *,
    reason_code: str,
) -> dict[str, object]:
    """Preserve completed writes when late authority loss blocks publication."""

    stored = result.get("stored")
    has_stored_facts = isinstance(stored, int) and not isinstance(stored, bool) and stored > 0
    return {
        **result,
        "outcome": (
            TaskBusinessOutcome.PARTIAL.value
            if has_stored_facts
            else TaskBusinessOutcome.BLOCKED.value
        ),
        "success": False,
        "must_not_use_for_decision": True,
        "blocked_reason": reason_code,
        "error_code": reason_code,
        "publication_updated": False,
        "published_members": 0,
    }


def task_attempt_identity_failure() -> dict[str, object]:
    """Return the stable zero-write outcome when Task Monitor identity is absent."""

    return {
        "outcome": TaskBusinessOutcome.BLOCKED.value,
        "success": False,
        "requested": 0,
        "succeeded": 0,
        "failed": 0,
        "stored": 0,
        "count_unit": "sync_operation",
        "stored_count_unit": "fact_row",
        "phase": "task_attempt_identity",
        "blocked_reason": "current_task_attempt_identity_unavailable",
        "error_code": "CURRENT_TASK_ATTEMPT_IDENTITY_UNAVAILABLE",
        "errors": ["CURRENT_TASK_ATTEMPT_IDENTITY_UNAVAILABLE"],
        "publication_updated": False,
        "published_members": 0,
        "must_not_use_for_decision": True,
    }


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


def quote_session_prefetch_failure(
    *,
    asset_count: int,
    batch_count: int,
    target_trade_date: str,
    publication_run_id: str,
    quote_source: str,
    valuation_source: str,
    market_universe: Mapping[str, object],
    valuation_requested_count: int,
    valuation_succeeded_count: int,
    valuation_missing_codes: Sequence[str],
    valuation_stored_count: int,
    valuation_coverage_ratio: float,
    valuation_policy_identity: str | None,
    error_code: str,
) -> dict[str, object]:
    """Shape a pre-write quote response failure while preserving seed-write evidence."""

    if (
        isinstance(asset_count, bool)
        or not isinstance(asset_count, int)
        or asset_count < 0
        or isinstance(batch_count, bool)
        or not isinstance(batch_count, int)
        or batch_count < 0
        or not isinstance(error_code, str)
        or not error_code.strip()
    ):
        raise ValueError("quote prefetch failure evidence is invalid")
    failed_operations = batch_count * 2 + 2 if asset_count else 0
    outcome = (
        TaskBusinessOutcome.PARTIAL.value
        if valuation_stored_count > 0
        else TaskBusinessOutcome.FAILED.value
    )
    missing_codes = tuple(valuation_missing_codes)
    return {
        "outcome": outcome,
        "success": outcome == TaskBusinessOutcome.PARTIAL.value,
        "must_not_use_for_decision": True,
        "blocked_reason": error_code,
        "error_code": error_code,
        "errors": [error_code],
        "phase": "quote",
        "phase_results": [
            {
                "phase": "valuation_seed",
                "requested": valuation_requested_count,
                "succeeded": valuation_succeeded_count,
                "failed": len(missing_codes),
                "stored": valuation_stored_count,
                "count_unit": "valuation_asset",
                "stored_count_unit": "fact_row",
            },
            {
                "phase": "quote_prefetch",
                "requested": int(bool(asset_count)),
                "succeeded": 0,
                "failed": int(bool(asset_count)),
                "stored": 0,
                "count_unit": "provider_request",
                "stored_count_unit": "fact_row",
            },
            {
                "phase": "quote",
                "requested": asset_count,
                "succeeded": 0,
                "failed": asset_count,
                "stored": 0,
                "count_unit": "quote_asset",
                "stored_count_unit": "fact_row",
            },
            {
                "phase": "publication",
                "requested": int(bool(asset_count)),
                "succeeded": 0,
                "failed": int(bool(asset_count)),
                "stored": 0,
                "count_unit": "sync_operation",
                "stored_count_unit": "publication_member",
            },
        ],
        "requested": asset_count,
        "succeeded": 0,
        "failed": asset_count,
        "stored": valuation_stored_count,
        "count_unit": "quote_asset",
        "stored_count_unit": "fact_row",
        "operation_requested": failed_operations,
        "operation_succeeded": 0,
        "operation_failed": failed_operations,
        "operation_count_unit": "sync_operation",
        "target_trade_date": target_trade_date,
        "publication_run_id": publication_run_id,
        "publication_updated": False,
        "published_members": 0,
        "asset_count": asset_count,
        "quote_source": quote_source,
        "valuation_source": valuation_source,
        "market_universe": dict(market_universe),
        "valuation_seed_stored": valuation_stored_count,
        "valuation_coverage_ratio": valuation_coverage_ratio,
        "valuation_policy_identity": valuation_policy_identity,
        "missing_asset_codes": list(missing_codes),
        "excluded_non_trading_count": 0,
        "excluded_non_trading_codes": [],
    }


def quote_session_scope_empty_failure(
    *,
    requested_codes: Set[str],
    valuation_missing_codes: Sequence[str],
    valuation_stored_count: int,
    excluded_codes: Sequence[str],
    target_trade_date: str,
    publication_run_id: str,
    quote_source: str,
    valuation_source: str,
    market_universe: Mapping[str, object],
    valuation_coverage_ratio: float,
    valuation_policy_identity: str | None,
) -> dict[str, object]:
    """Block when every frozen asset is explicitly excluded as suspended."""

    excluded = tuple(sorted({str(code or "").strip().upper() for code in excluded_codes}))
    valuation_missing = tuple(
        sorted({str(code or "").strip().upper() for code in valuation_missing_codes})
    )
    missing = tuple(sorted(set(excluded).union(valuation_missing)))
    return {
        "outcome": TaskBusinessOutcome.BLOCKED.value,
        "success": False,
        "blocked_reason": "quote_full_day_suspension",
        "error_code": "CURRENT_QUOTE_SESSION_SCOPE_EMPTY",
        "errors": ["CURRENT_QUOTE_SESSION_SCOPE_EMPTY"],
        "requested": len(requested_codes),
        "succeeded": 0,
        "failed": len(missing),
        "stored": valuation_stored_count,
        "count_unit": "valuation_asset",
        "stored_count_unit": "fact_row",
        "operation_requested": 1,
        "operation_succeeded": 0,
        "operation_failed": 1,
        "publication_updated": False,
        "published_members": 0,
        "publication_run_id": publication_run_id,
        "target_trade_date": target_trade_date,
        "quote_source": quote_source,
        "valuation_source": valuation_source,
        "market_universe": dict(market_universe),
        "valuation_seed_stored": valuation_stored_count,
        "valuation_coverage_ratio": valuation_coverage_ratio,
        "valuation_policy_identity": valuation_policy_identity,
        "requested_asset_count": len(requested_codes),
        "succeeded_asset_count": 0,
        "failed_asset_count": len(missing),
        "missing_asset_codes": list(missing),
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
    quote_stored_rows: int = 0,
    excluded_codes: Sequence[str] = (),
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
        elif phase_result.get("phase") == "quote":
            phase_result["stored"] = quote_stored_rows
    datasets = publication_evidence.get("datasets")
    dataset_evidence = (
        [item for item in datasets if isinstance(item, Mapping)]
        if isinstance(datasets, list)
        else []
    )
    scope_blocks_by_dataset: dict[str, list[dict[str, object]]] = {}
    for dataset in dataset_evidence:
        dataset_key = dataset.get("dataset_key")
        raw_scope_blocks = dataset.get("scope_blocks")
        if not isinstance(dataset_key, str) or not isinstance(raw_scope_blocks, list):
            continue
        scoped = [dict(item) for item in raw_scope_blocks if isinstance(item, Mapping)]
        if scoped:
            scope_blocks_by_dataset[dataset_key] = scoped
    scope_blocks = [
        block
        for dataset_key in sorted(scope_blocks_by_dataset)
        for block in scope_blocks_by_dataset[dataset_key]
    ]
    quote_scope_blocks = scope_blocks_by_dataset.get("equity.quote.snapshot", [])
    excluded = tuple(
        sorted(
            {str(code or "").strip().upper() for code in excluded_codes if str(code or "").strip()}
        )
    )
    valuation_missing = tuple(
        sorted(
            {str(code or "").strip().upper() for code in missing_codes if str(code or "").strip()}
        )
    )
    combined_missing = tuple(sorted(set(valuation_missing).union(excluded)))
    effective_succeeded = set(succeeded_codes).difference(excluded)
    raw_audit_reference_failed_after_write = (
        result.get("error_code")
        in {
            "CURRENT_RAW_AUDIT_REFERENCE_MISSING",
            "CURRENT_RAW_AUDIT_REFERENCE_IDENTITY_INVALID",
            "CURRENT_RAW_AUDIT_REFERENCE_DUPLICATE",
        }
        and stored_row_count > 0
    )
    business_outcome = (
        TaskBusinessOutcome.PARTIAL.value
        if raw_audit_reference_failed_after_write
        or (combined_missing and result.get("publication_updated"))
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
        "excluded_non_trading_count": len(excluded),
        "excluded_non_trading_codes": list(excluded),
        "quote_eligible_asset_count": len(requested_codes) - len(excluded),
        "quote_selected_asset_count": len(requested_codes) - len(excluded),
        "suspension_evidence_source": "tushare.suspend_d" if excluded else None,
        "scope_notice": (
            "目标交易日全天停牌证券无当日行情，其他证券已按有效范围发布。" if excluded else ""
        ),
        "outcome": business_outcome,
        "success": business_outcome
        in {
            TaskBusinessOutcome.SUCCESS.value,
            TaskBusinessOutcome.PARTIAL.value,
            TaskBusinessOutcome.NOOP.value,
        },
        "requested": len(requested_codes),
        "succeeded": len(effective_succeeded),
        "failed": len(combined_missing),
        "stored": stored_row_count,
        "count_unit": "valuation_asset",
        "stored_count_unit": "fact_row",
        "operation_requested": result.get("requested"),
        "operation_succeeded": result.get("succeeded"),
        "operation_failed": result.get("failed"),
        "requested_asset_count": len(requested_codes),
        "succeeded_asset_count": len(effective_succeeded),
        "failed_asset_count": len(combined_missing),
        "missing_asset_codes": list(combined_missing),
        "scope_blocks": scope_blocks,
        "quote_scope_blocks": quote_scope_blocks,
        "valuation_coverage_ratio": coverage_ratio,
        "valuation_policy_identity": policy_identity,
    }
