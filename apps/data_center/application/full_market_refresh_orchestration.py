"""Application orchestration for the full-market publication refresh."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Protocol, cast
from uuid import uuid4

from celery.exceptions import SoftTimeLimitExceeded
from django.utils import timezone

from apps.data_center.domain.entities import RawAuditReference
from apps.data_center.domain.market_time import cn_market_date_from_observation
from apps.data_center.domain.model_market_data import ModelMarketDataPort
from apps.data_center.domain.protocols import PublicationPolicyRepositoryProtocol
from apps.data_center.domain.target_date_universe import TargetDateAssetUniverseScope
from core.exceptions import DataFetchError
from core.integration import data_center_audit as audit_integration
from core.integration.data_center_audit import SystemAuditReaderContext
from core.integration.task_monitor_runtime import TaskProgress, TaskProgressPhase
from shared.domain.task_outcomes import TaskBusinessOutcome

from . import full_market_task_support as market_task
from .current_publication_rebuild import (
    CoreCurrentPublicationRebuildUseCase,
    CurrentPublicationScopeExclusion,
)
from .current_valuation_sync import SyncCurrentValuationBatchUseCase
from .data02_task_authority import Data02AuthorityLatch
from .dtos import SyncQuoteRequest
from .market_publication_refresh import (
    MarketPricePreparationResult,
    MarketPublicationRefreshBlocked,
    MarketPublicationRefreshPorts,
)
from .quote_session_prefetch import QuoteSessionMissingAssetVerifier
from .sync_market_use_cases import SyncQuoteUseCase

logger = logging.getLogger(__name__)


class _Data02TaskAuthorityPreflight(Protocol):
    """Type the authority preflight dependency used by the refresh orchestrator."""

    def __call__(
        self,
        *,
        as_of: datetime,
        minimum_window: timedelta,
        expected_actor: str = "",
    ) -> tuple[SystemAuditReaderContext | None, dict[str, object] | None]: ...


class _PublicationRebuildFactory(Protocol):
    """Build a current-publication use case for the fixed refresh datasets."""

    def __call__(
        self,
        *,
        created_by: str,
        dataset_keys: tuple[str, ...],
    ) -> CoreCurrentPublicationRebuildUseCase: ...


class _MarketPublicationsRefresh(Protocol):
    """Run the generic coordinator over this refresh's bounded callbacks."""

    def __call__(
        self,
        *,
        as_of_date: date,
        batch_size: int,
        ports: MarketPublicationRefreshPorts,
    ) -> dict[str, object]: ...


class _TargetDateUniverseScopeResolver(Protocol):
    """Resolve current active A-shares against persisted target-date listing evidence."""

    def __call__(self, target_date: date) -> TargetDateAssetUniverseScope: ...


def _require_sync_raw_audit_reference(
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


def _serialize_raw_audit_references(
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


@dataclass(frozen=True, slots=True)
class FullMarketRefreshDependencies:
    """Application-owned collaborators used by the Celery task adapter."""

    authority_window: timedelta
    preflight_data02_authority: _Data02TaskAuthorityPreflight
    authority_latch_factory: Callable[[SystemAuditReaderContext], Data02AuthorityLatch]
    data02_authority_failure: Callable[[str], dict[str, object]]
    get_active_provider_id_by_source: Callable[[str], int | None]
    make_quote_sync_use_case: Callable[[], SyncQuoteUseCase]
    make_valuation_sync_use_case: Callable[[], SyncCurrentValuationBatchUseCase]
    make_publication_rebuild_use_case: _PublicationRebuildFactory
    latest_closed_market_session: Callable[[datetime], date | None]
    sync_active_universe: Callable[[], dict[str, object]]
    target_date_universe_scope: _TargetDateUniverseScopeResolver
    publication_policy_repository: Callable[[], PublicationPolicyRepositoryProtocol]
    record_progress: Callable[[TaskProgress], bool]
    model_market_data_port: Callable[[], ModelMarketDataPort]
    refresh_market_price_inputs: Callable[
        [ModelMarketDataPort, list[str], date], MarketPricePreparationResult
    ]
    refresh_market_publications: _MarketPublicationsRefresh


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


def run_full_market_publication_refresh(
    source: str | None = None,
    batch_size: int = 100,
    quote_source: str = "tushare",
    valuation_source: str = "akshare",
    *,
    dependencies: FullMarketRefreshDependencies,
) -> dict[str, object]:
    """Orchestrate a bounded full-market fact refresh and atomic publication."""

    allowed_sources = {"akshare", "tushare"}
    if source is not None and (type(source) is not str or source not in allowed_sources):
        return market_task.full_market_input_failure("unsupported_market_source")
    if type(quote_source) is not str or quote_source not in allowed_sources:
        return market_task.full_market_input_failure("unsupported_quote_source")
    if type(valuation_source) is not str or valuation_source not in allowed_sources:
        return market_task.full_market_input_failure("unsupported_valuation_source")
    selected_quote_source = source or quote_source
    selected_valuation_source = source or valuation_source
    if (
        isinstance(batch_size, bool)
        or not isinstance(batch_size, int)
        or not 1 <= batch_size <= 200
    ):
        return market_task.full_market_input_failure("invalid_batch_size")
    started_at = datetime.now(UTC)
    authority, authority_failure = dependencies.preflight_data02_authority(
        as_of=started_at,
        minimum_window=dependencies.authority_window,
    )
    if authority_failure is not None:
        return authority_failure
    if authority is None:  # pragma: no cover - narrowed by the failure branch
        raise RuntimeError("authority preflight returned no context")
    quote_provider_id = dependencies.get_active_provider_id_by_source(selected_quote_source)
    valuation_provider_id = dependencies.get_active_provider_id_by_source(selected_valuation_source)
    if quote_provider_id is None:
        return market_task.full_market_input_failure("quote_provider_unavailable")
    if valuation_provider_id is None:
        return market_task.full_market_input_failure("valuation_provider_unavailable")
    try:
        quotes = dependencies.make_quote_sync_use_case()
    except audit_integration.SystemAuditCompositionUnavailable as exc:
        return {
            **market_task.full_market_input_failure(f"system_audit_{exc.reason_code}"),
            "outcome": "blocked",
            "must_not_use_for_decision": True,
        }
    valuations = dependencies.make_valuation_sync_use_case()
    publications = dependencies.make_publication_rebuild_use_case(
        created_by=f"celery.full_market_refresh:{authority.actor_id}",
        dataset_keys=("equity.quote.snapshot", "equity.valuation.fact", "equity.price.bar"),
    )
    target_date = dependencies.latest_closed_market_session(timezone.now())
    if target_date is None:
        return {
            "outcome": "blocked",
            "success": False,
            "requested": 0,
            "succeeded": 0,
            "failed": 0,
            "stored": 0,
            "blocked_reason": "market_calendar_unavailable",
        }

    price_evidence: dict[str, object] = {}
    price_audit_references: dict[str, RawAuditReference] = {}
    quote_audit_references: dict[str, RawAuditReference] = {}
    valuation_audit_references: dict[str, RawAuditReference] = {}
    publication_evidence: dict[str, object] = {}
    publication_run_id = str(uuid4())
    completed_operation_count = 0
    stored_row_count = 0
    current_phase = "universe"
    authority_latch = dependencies.authority_latch_factory(authority)
    progress_phases: dict[str, TaskProgressPhase] = {}

    def publish_progress(phase_result: TaskProgressPhase) -> None:
        """Publish aggregate phase evidence without exposing asset identities."""

        progress_phases[phase_result.phase] = phase_result
        dependencies.record_progress(
            TaskProgress(
                phase=phase_result.phase,
                requested=phase_result.requested,
                succeeded=phase_result.succeeded,
                failed=phase_result.failed,
                stored=phase_result.stored,
                count_unit=phase_result.count_unit,
                stored_count_unit=phase_result.stored_count_unit,
                phase_results=tuple(progress_phases.values()),
            )
        )

    # Universe refresh can spend most of its time in provider-backed per-asset
    # upserts. Until the provider reports a real universe size, report only
    # the one in-flight sync operation rather than inventing a security count.
    publish_progress(
        TaskProgressPhase(
            phase="universe",
            requested=1,
            succeeded=0,
            failed=0,
            stored=None,
            count_unit="sync_operation",
        )
    )

    if not authority_latch.allows_next_write(as_of=datetime.now(UTC)):
        return dependencies.data02_authority_failure(authority_latch.reason_code)
    try:
        universe_report = dependencies.sync_active_universe()
    except (DataFetchError, OSError, RuntimeError, ValueError) as exc:
        logger.warning(
            "Full-market universe refresh failed: %s",
            type(exc).__name__,
        )
        publish_progress(
            TaskProgressPhase(
                phase="universe",
                requested=1,
                succeeded=0,
                failed=1,
                stored=None,
                count_unit="sync_operation",
            )
        )
        universe_error = (
            exc
            if isinstance(exc, DataFetchError) and exc.code.startswith("A_SHARE_UNIVERSE_")
            else None
        )
        error_code = (
            universe_error.code if universe_error is not None else "MARKET_UNIVERSE_REFRESH_FAILED"
        )
        return {
            **market_task.full_market_input_failure(type(exc).__name__),
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "must_not_use_for_decision": True,
            "blocked_reason": error_code.lower(),
            "error_code": error_code,
            "errors": [error_code],
            **(
                {"market_universe_error": universe_error.details}
                if universe_error is not None
                else {}
            ),
        }
    universe_active_count = universe_report.get("active_count")
    if (
        isinstance(universe_active_count, bool)
        or not isinstance(universe_active_count, int)
        or universe_active_count <= 0
    ):
        publish_progress(
            TaskProgressPhase(
                phase="universe",
                requested=1,
                succeeded=0,
                failed=1,
                stored=None,
                count_unit="sync_operation",
            )
        )
        return {
            **market_task.full_market_input_failure("market_universe_empty"),
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "must_not_use_for_decision": True,
            "blocked_reason": "market_universe_refresh_failed",
            "error_code": "MARKET_UNIVERSE_REFRESH_FAILED",
            "errors": ["MARKET_UNIVERSE_REFRESH_FAILED"],
        }
    publish_progress(
        TaskProgressPhase(
            phase="universe",
            requested=1,
            succeeded=1,
            failed=0,
            stored=universe_active_count,
            count_unit="sync_operation",
            stored_count_unit="universe_asset",
        )
    )

    current_phase = "scope"
    publish_progress(
        TaskProgressPhase(
            phase="scope",
            requested=1,
            succeeded=0,
            failed=0,
            stored=None,
            count_unit="scope_validation",
        )
    )
    try:
        target_date_scope = dependencies.target_date_universe_scope(target_date)
        candidate_codes = tuple(target_date_scope.candidate_codes)
        normalized_active_codes = tuple(str(code or "").strip().upper() for code in candidate_codes)
        normalized_requested_codes = tuple(
            str(code or "").strip().upper() for code in target_date_scope.requested_codes
        )
        excluded_not_yet_listed = tuple(target_date_scope.excluded_not_yet_listed)
        unknown_listing_date_codes = tuple(target_date_scope.unknown_listing_date_codes)
        excluded_codes = tuple(item.asset_code for item in excluded_not_yet_listed)
        if target_date_scope.target_date != target_date:
            raise ValueError("target-date universe scope is bound to another trade date")
        target_date_scope_evidence: dict[str, object] = {
            "scope_policy": "exclude_only_verified_list_date_after_target",
            "target_trade_date": target_date.isoformat(),
            "candidate_asset_count": len(normalized_active_codes),
            "candidate_asset_codes_sha256": market_task.asset_code_scope_sha256(
                normalized_active_codes
            ),
            "requested_asset_count": len(normalized_requested_codes),
            "requested_asset_codes_sha256": market_task.asset_code_scope_sha256(
                normalized_requested_codes
            ),
            "excluded_not_yet_listed_count": len(excluded_not_yet_listed),
            "excluded_not_yet_listed_codes": list(excluded_codes),
            "excluded_not_yet_listed_evidence": [
                {
                    "asset_code": item.asset_code,
                    "list_date": item.list_date.isoformat(),
                    "reason_code": item.reason_code,
                    "evidence_source": item.evidence_source,
                }
                for item in excluded_not_yet_listed
            ],
            "unknown_listing_date_count": len(unknown_listing_date_codes),
            "unknown_listing_date_codes_sha256": market_task.asset_code_scope_sha256(
                unknown_listing_date_codes
            ),
            "unknown_listing_date_codes_sample": list(unknown_listing_date_codes[:20]),
        }
        universe_report = {
            **universe_report,
            "target_date_scope": target_date_scope_evidence,
        }
    except Exception as exc:
        logger.warning(
            "Full-market target-date universe scope failed: %s",
            type(exc).__name__,
        )
        publish_progress(
            TaskProgressPhase(
                phase="scope",
                requested=1,
                succeeded=0,
                failed=1,
                stored=None,
                count_unit="scope_validation",
            )
        )
        return {
            **market_task.full_market_input_failure("market_universe_scope_unavailable"),
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "must_not_use_for_decision": True,
            "blocked_reason": "market_universe_scope_unavailable",
            "error_code": "MARKET_UNIVERSE_SCOPE_UNAVAILABLE",
            "errors": ["MARKET_UNIVERSE_SCOPE_UNAVAILABLE"],
            "market_universe": universe_report,
        }
    frozen_universe_sha256 = market_task.asset_code_scope_sha256(normalized_active_codes)
    reported_universe_sha256 = universe_report.get("active_codes_sha256")
    if (
        any(not code for code in normalized_active_codes)
        or len(set(normalized_active_codes)) != len(normalized_active_codes)
        or universe_active_count != len(normalized_active_codes)
        or reported_universe_sha256 != frozen_universe_sha256
        or any(not code for code in normalized_requested_codes)
        or len(set(normalized_requested_codes)) != len(normalized_requested_codes)
        or not set(normalized_requested_codes).issubset(set(normalized_active_codes))
        or len(set(excluded_codes)) != len(excluded_codes)
        or set(normalized_requested_codes).intersection(excluded_codes)
        or set(normalized_requested_codes).union(excluded_codes) != set(normalized_active_codes)
        or any(code not in set(normalized_active_codes) for code in unknown_listing_date_codes)
        or len(set(unknown_listing_date_codes)) != len(unknown_listing_date_codes)
    ):
        publish_progress(
            TaskProgressPhase(
                phase="scope",
                requested=1,
                succeeded=0,
                failed=1,
                stored=None,
                count_unit="scope_validation",
            )
        )
        return {
            **market_task.full_market_input_failure("market_universe_scope_invalid"),
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "must_not_use_for_decision": True,
            "blocked_reason": "market_universe_scope_invalid",
            "error_code": "MARKET_UNIVERSE_SCOPE_INVALID",
            "errors": ["MARKET_UNIVERSE_SCOPE_INVALID"],
            "publication_updated": False,
            "published_members": 0,
            "requested_asset_count": len(normalized_requested_codes),
            "frozen_universe_sha256": frozen_universe_sha256,
            "reported_universe_sha256": reported_universe_sha256,
            "market_universe": universe_report,
        }
    publish_progress(
        TaskProgressPhase(
            phase="scope",
            requested=1,
            succeeded=1,
            failed=0,
            stored=len(normalized_requested_codes),
            count_unit="scope_validation",
            stored_count_unit="universe_asset",
        )
    )
    if not normalized_requested_codes:
        return {
            **market_task.full_market_input_failure("market_universe_scope_empty"),
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "must_not_use_for_decision": True,
            "blocked_reason": "market_universe_scope_empty",
            "error_code": "MARKET_UNIVERSE_SCOPE_EMPTY",
            "errors": ["MARKET_UNIVERSE_SCOPE_EMPTY"],
            "requested_asset_count": 0,
            "market_universe": universe_report,
        }
    if not authority_latch.allows_next_write(as_of=datetime.now(UTC)):
        return dependencies.data02_authority_failure(authority_latch.reason_code)
    publish_progress(
        TaskProgressPhase(
            phase="valuation",
            requested=len(normalized_requested_codes),
            succeeded=None,
            failed=None,
            stored=None,
            count_unit="valuation_asset",
            stored_count_unit="fact_row",
        )
    )
    try:
        valuation_seed = valuations.execute(
            provider_id=valuation_provider_id,
            asset_codes=list(normalized_requested_codes),
            as_of_date=target_date,
            require_exact_asset_codes=False,
        )
    except (DataFetchError, OSError, RuntimeError, ValueError) as exc:
        logger.warning(
            "Full-market valuation scope refresh failed: %s",
            type(exc).__name__,
        )
        return {
            **market_task.full_market_input_failure(type(exc).__name__),
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "must_not_use_for_decision": True,
            "blocked_reason": "current_valuation_scope_unavailable",
            "error_code": "CURRENT_VALUATION_SCOPE_UNAVAILABLE",
            "errors": ["CURRENT_VALUATION_SCOPE_UNAVAILABLE"],
        }
    requested_codes = set(normalized_requested_codes)
    returned_codes = tuple(
        str(code or "").strip().upper() for code in valuation_seed.returned_asset_codes
    )
    succeeded_codes = tuple(
        str(code or "").strip().upper() for code in valuation_seed.succeeded_asset_codes
    )
    if (
        not requested_codes
        or any(not code for code in (*returned_codes, *succeeded_codes))
        or len(set(returned_codes)) != len(returned_codes)
        or len(set(succeeded_codes)) != len(succeeded_codes)
        or not set(returned_codes).issubset(requested_codes)
        or not set(succeeded_codes).issubset(requested_codes)
        or not set(succeeded_codes).issubset(set(returned_codes))
        or valuation_seed.stored_count != len(set(succeeded_codes))
    ):
        return {
            **market_task.full_market_input_failure("valuation_scope_identity_invalid"),
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "must_not_use_for_decision": True,
            "blocked_reason": "current_valuation_scope_invalid",
            "error_code": "CURRENT_VALUATION_SCOPE_INVALID",
            "errors": ["CURRENT_VALUATION_SCOPE_INVALID"],
        }
    succeeded_code_set = set(succeeded_codes)
    returned_code_set = set(returned_codes)
    missing_codes = sorted(requested_codes - succeeded_code_set)
    unexpected_returned_codes = sorted(returned_code_set - requested_codes)
    valuation_coverage_ratio = len(succeeded_code_set) / len(requested_codes)
    try:
        valuation_reference = _require_sync_raw_audit_reference(
            valuation_seed.raw_audit_reference,
            run_id=valuation_seed.run_id,
            ingested_run_id=valuation_seed.ingested_run_id,
        )
    except MarketPublicationRefreshBlocked as exc:
        error_code = exc.code
        return {
            **market_task.full_market_input_failure("current_raw_audit_reference_unavailable"),
            "outcome": (
                TaskBusinessOutcome.PARTIAL.value
                if valuation_seed.stored_count > 0
                else TaskBusinessOutcome.BLOCKED.value
            ),
            "success": False,
            "must_not_use_for_decision": True,
            "blocked_reason": "current_raw_audit_reference_unavailable",
            "error_code": error_code,
            "errors": [error_code],
            "phase": "valuation",
            "requested": len(requested_codes),
            "succeeded": len(succeeded_code_set),
            "failed": len(missing_codes),
            "stored": valuation_seed.stored_count,
            "count_unit": "valuation_asset",
            "stored_count_unit": "fact_row",
            "operation_requested": 1,
            "operation_succeeded": 0,
            "operation_failed": 1,
            "publication_updated": False,
            "published_members": 0,
            "publication_run_id": publication_run_id,
            "target_trade_date": target_date.isoformat(),
            "quote_source": selected_quote_source,
            "valuation_source": selected_valuation_source,
            "market_universe": universe_report,
            "valuation_seed_stored": valuation_seed.stored_count,
            "requested_asset_count": len(requested_codes),
            "succeeded_asset_count": len(succeeded_code_set),
            "failed_asset_count": len(missing_codes),
            "missing_asset_codes": missing_codes,
            "raw_audit_references_by_dataset": {
                "equity.quote.snapshot": [],
                "equity.valuation.fact": [],
                "equity.price.bar": [],
            },
        }
    valuation_audit_references[valuation_reference.raw_audit_id] = valuation_reference
    publish_progress(
        TaskProgressPhase(
            phase="valuation",
            requested=len(requested_codes),
            succeeded=len(succeeded_code_set),
            failed=len(missing_codes),
            stored=valuation_seed.stored_count,
            count_unit="valuation_asset",
            stored_count_unit="fact_row",
        )
    )
    valuation_policy = (
        dependencies.publication_policy_repository().get_active("equity.valuation.fact")
        if missing_codes
        else None
    )
    valuation_partial_allowed = (
        valuation_policy is not None
        and market_task.valuation_partial_policy_allows(
            dataset_key=valuation_policy.dataset.value,
            allow_partial=valuation_policy.allow_partial,
            uses_versioned_evidence=valuation_policy.uses_versioned_evidence,
            coverage_ratio=valuation_coverage_ratio,
            minimum_coverage_ratio=valuation_policy.minimum_coverage_ratio,
        )
    )
    if getattr(valuation_seed, "status", "success") not in {"success", "partial"} or (
        (succeeded_code_set != requested_codes or returned_code_set != requested_codes)
        and not valuation_partial_allowed
    ):
        return market_task.valuation_scope_incomplete_failure(
            requested_codes=requested_codes,
            succeeded_codes=succeeded_code_set,
            missing_codes=missing_codes,
            unexpected_returned_codes=unexpected_returned_codes,
            stored_count=valuation_seed.stored_count,
            publication_run_id=publication_run_id,
            target_trade_date=target_date.isoformat(),
            market_universe=universe_report,
            coverage_ratio=valuation_coverage_ratio,
            policy_identity=(valuation_policy.identity if valuation_policy is not None else None),
        )
    full_scope_codes = sorted(requested_codes)
    tradable_codes = list(full_scope_codes)
    excluded_non_trading_codes: list[str] = []
    stored_row_count = valuation_seed.stored_count

    def verify_quote_suspensions(
        missing_asset_codes: tuple[str, ...], missing_target_date: date
    ) -> tuple[str, ...]:
        """Prove provider-missing quote rows are full-day target-date suspensions."""

        missing = tuple(sorted(set(missing_asset_codes)))
        if missing_target_date != target_date or not missing:
            raise DataFetchError(
                "Quote suspension verification scope is invalid",
                code="CURRENT_QUOTE_SESSION_SUSPENSION_UNVERIFIED",
            )
        preparation = dependencies.refresh_market_price_inputs(
            dependencies.model_market_data_port(), list(missing), missing_target_date
        )
        normalized_verified = tuple(
            sorted(str(code or "").strip().upper() for code in preparation.suspended_codes)
        )
        price_audit_references.update(
            {reference.raw_audit_id: reference for reference in preparation.raw_audit_references}
        )
        if (
            any(not code for code in normalized_verified)
            or len(normalized_verified) != len(set(normalized_verified))
            or set(normalized_verified) != set(missing)
        ):
            raise DataFetchError(
                "Quote suspension evidence does not cover every provider-missing asset",
                code="CURRENT_QUOTE_SESSION_SUSPENSION_UNVERIFIED",
                details={
                    "missing_codes": list(missing),
                    "verified_codes": list(normalized_verified),
                    "target_trade_date": missing_target_date.isoformat(),
                },
            )
        return normalized_verified

    batches = (len(tradable_codes) + batch_size - 1) // batch_size
    requested_operations = batches * 2 + 1
    current_phase = "quote"
    publish_progress(
        TaskProgressPhase(
            phase="quote_prefetch",
            requested=1,
            succeeded=0,
            failed=None,
            stored=0,
            count_unit="provider_request",
            stored_count_unit="fact_row",
        )
    )
    try:
        prepared_quote_session = quotes.prepare_session(
            provider_id=quote_provider_id,
            asset_codes=tuple(tradable_codes),
            target_trade_date=target_date,
            missing_asset_verifier=cast(
                QuoteSessionMissingAssetVerifier,
                verify_quote_suspensions,
            ),
        )
    except SoftTimeLimitExceeded:
        return market_task.full_market_soft_timeout_failure(
            requested_operations=requested_operations,
            completed_operations=completed_operation_count,
            stored_rows=stored_row_count,
            target_trade_date=target_date.isoformat(),
            phase=current_phase,
            asset_count=len(tradable_codes),
            publication_run_id=publication_run_id,
            quote_source=selected_quote_source,
            valuation_source=selected_valuation_source,
            market_universe=universe_report,
            valuation_seed_stored=valuation_seed.stored_count,
            excluded_non_trading_codes=excluded_non_trading_codes,
        )
    except (DataFetchError, OSError, RuntimeError, ValueError) as exc:
        provider_error_code = getattr(exc, "code", None)
        error_code = (
            provider_error_code
            if isinstance(provider_error_code, str) and provider_error_code
            else type(exc).__name__
        )
        publish_progress(
            TaskProgressPhase(
                phase="quote_prefetch",
                requested=1,
                succeeded=0,
                failed=1,
                stored=0,
                count_unit="provider_request",
                stored_count_unit="fact_row",
            )
        )
        return market_task.quote_session_prefetch_failure(
            asset_count=len(tradable_codes),
            batch_count=batches,
            target_trade_date=target_date.isoformat(),
            publication_run_id=publication_run_id,
            quote_source=selected_quote_source,
            valuation_source=selected_valuation_source,
            market_universe=universe_report,
            valuation_requested_count=len(requested_codes),
            valuation_succeeded_count=len(succeeded_code_set),
            valuation_missing_codes=missing_codes,
            valuation_stored_count=valuation_seed.stored_count,
            valuation_coverage_ratio=valuation_coverage_ratio,
            valuation_policy_identity=(
                valuation_policy.identity if valuation_policy is not None else None
            ),
            error_code=error_code,
        )
    prepared_universe_codes = tuple(
        str(code or "").strip().upper()
        for code in getattr(prepared_quote_session, "universe_codes", full_scope_codes)
    )
    available_codes = tuple(
        sorted(
            str(code or "").strip().upper()
            for code in getattr(prepared_quote_session, "available_codes", tradable_codes)
        )
    )
    eligible_codes = tuple(
        sorted(
            str(code or "").strip().upper()
            for code in getattr(prepared_quote_session, "eligible_codes", available_codes)
        )
    )
    excluded_codes = tuple(
        sorted(
            str(code or "").strip().upper()
            for code in getattr(prepared_quote_session, "excluded_codes", ())
        )
    )
    if (
        tuple(full_scope_codes) != prepared_universe_codes
        or any(not code for code in (*available_codes, *eligible_codes, *excluded_codes))
        or len(available_codes) != len(set(available_codes))
        or len(eligible_codes) != len(set(eligible_codes))
        or len(excluded_codes) != len(set(excluded_codes))
        or eligible_codes != available_codes
        or set(eligible_codes).intersection(excluded_codes)
        or set(available_codes).union(excluded_codes) != set(full_scope_codes)
    ):
        raise DataFetchError(
            "Prepared quote session scope is not a complete frozen partition",
            code="CURRENT_QUOTE_SESSION_SCOPE_INVALID",
        )
    tradable_codes = list(eligible_codes)
    excluded_non_trading_codes = list(excluded_codes)
    batches = (len(tradable_codes) + batch_size - 1) // batch_size
    requested_operations = batches * 2 + 1
    publish_progress(
        TaskProgressPhase(
            phase="quote_prefetch",
            requested=1,
            succeeded=1,
            failed=0,
            stored=0,
            count_unit="provider_request",
            stored_count_unit="fact_row",
        )
    )
    if not tradable_codes:
        return market_task.quote_session_scope_empty_failure(
            requested_codes=requested_codes,
            valuation_missing_codes=missing_codes,
            valuation_stored_count=valuation_seed.stored_count,
            excluded_codes=excluded_non_trading_codes,
            target_trade_date=target_date.isoformat(),
            publication_run_id=publication_run_id,
            quote_source=selected_quote_source,
            valuation_source=selected_valuation_source,
            market_universe=universe_report,
            valuation_coverage_ratio=valuation_coverage_ratio,
            valuation_policy_identity=(
                valuation_policy.identity if valuation_policy is not None else None
            ),
        )
    quote_batches_succeeded = 0
    quote_stored_rows = 0

    def sync_quote_batch(codes: list[str]) -> int:
        nonlocal completed_operation_count, current_phase
        nonlocal quote_batches_succeeded, quote_stored_rows, stored_row_count
        current_phase = "quote"
        publish_progress(
            TaskProgressPhase(
                phase="quote",
                requested=batches,
                succeeded=quote_batches_succeeded,
                failed=None,
                stored=quote_stored_rows,
                count_unit="sync_operation",
                stored_count_unit="fact_row",
            )
        )
        if not authority_latch.allows_next_write(as_of=datetime.now(UTC)):
            raise MarketPublicationRefreshBlocked(code=authority_latch.reason_code)
        result = quotes.execute_prefetched_session_batch(
            SyncQuoteRequest(quote_provider_id, codes, True, target_date),
            prepared_quote_session,
        )
        stored_count = market_task.exact_provider_batch_count(
            requested_asset_codes=codes,
            stored_count=result.stored_count,
            returned_asset_codes=result.stored_asset_codes,
        )
        quote_stored_rows += stored_count
        stored_row_count += stored_count
        quote_reference = _require_sync_raw_audit_reference(
            result.raw_audit_reference,
            run_id=result.run_id,
            ingested_run_id=result.ingested_run_id,
        )
        if quote_reference.raw_audit_id in quote_audit_references:
            raise MarketPublicationRefreshBlocked(
                "Market quote batches returned a duplicate RawAudit reference",
                code="CURRENT_RAW_AUDIT_REFERENCE_DUPLICATE",
            )
        quote_audit_references[quote_reference.raw_audit_id] = quote_reference
        completed_operation_count += 1
        quote_batches_succeeded += 1
        publish_progress(
            TaskProgressPhase(
                phase="quote",
                requested=batches,
                succeeded=quote_batches_succeeded,
                failed=0,
                stored=quote_stored_rows,
                count_unit="sync_operation",
                stored_count_unit="fact_row",
            )
        )
        return stored_count

    def sync_valuation_batch(codes: list[str], day: date) -> int:
        nonlocal completed_operation_count, current_phase
        current_phase = "valuation"
        if day != target_date or not set(codes).issubset(requested_codes):
            raise ValueError("prefetched valuation scope changed before publication")
        completed_operation_count += 1
        publish_progress(
            TaskProgressPhase(
                phase="valuation",
                requested=len(requested_codes),
                succeeded=len(succeeded_code_set),
                failed=len(missing_codes),
                stored=valuation_seed.stored_count,
                count_unit="valuation_asset",
                stored_count_unit="fact_row",
            )
        )
        # The valuation rows were persisted by the full-scope seed above.
        # Returning the requested batch size tells the generic coordinator
        # that this phase validated the frozen prefetch; actual stored rows
        # remain the seed's durable count in the final business result.
        return len(codes)

    def publish_complete_session(codes: list[str]) -> int:
        nonlocal current_phase
        current_phase = "publication"
        publish_progress(
            TaskProgressPhase(
                phase="publication",
                requested=1,
                succeeded=0,
                failed=None,
                stored=None,
                count_unit="sync_operation",
                stored_count_unit="publication_member",
            )
        )
        if not authority_latch.allows_next_write(as_of=datetime.now(UTC)):
            raise MarketPublicationRefreshBlocked(code=authority_latch.reason_code)
        publication_scope_codes = list(full_scope_codes)
        publication_scope_exclusions = {
            "equity.quote.snapshot": tuple(
                CurrentPublicationScopeExclusion(
                    asset_code=code,
                    reason_code="quote_full_day_suspension",
                    target_trade_date=target_date,
                    evidence_source="tushare.suspend_d",
                )
                for code in excluded_non_trading_codes
            ),
        }
        required_observation_dates = {
            "equity.quote.snapshot": target_date,
            "equity.valuation.fact": target_date,
        }
        preview = publications.preview(
            asset_codes=publication_scope_codes,
            scope_exclusions_by_dataset=publication_scope_exclusions,
            required_observation_dates=required_observation_dates,
        )
        snapshots = {dataset.dataset_key: dataset for dataset in preview.datasets}
        quote_preview = snapshots.get("equity.quote.snapshot")
        valuation_preview = snapshots.get("equity.valuation.fact")
        quote_preview_allowed = quote_preview is not None and (
            quote_preview.ready
            or (
                bool(excluded_non_trading_codes)
                and set(getattr(quote_preview, "missing_asset_codes", ()))
                == set(excluded_non_trading_codes)
                and not getattr(quote_preview, "unexpected_asset_codes", ())
                and getattr(quote_preview, "covered_asset_count", -1) == len(tradable_codes)
            )
        )
        valuation_preview_allowed = valuation_preview is not None and (
            valuation_preview.ready
            or (
                valuation_partial_allowed
                and set(valuation_preview.missing_asset_codes) == set(missing_codes)
                and not valuation_preview.unexpected_asset_codes
                and valuation_preview.covered_asset_count == len(succeeded_code_set)
            )
        )
        current_snapshots = tuple(
            item for item in (quote_preview, valuation_preview) if item is not None
        )
        if (
            len(current_snapshots) != 2
            or quote_preview is None
            or not quote_preview_allowed
            or not valuation_preview_allowed
            or any(
                dataset.oldest_observed_at is None
                or cn_market_date_from_observation(dataset.oldest_observed_at) != target_date
                or dataset.newest_observed_at is None
                or cn_market_date_from_observation(dataset.newest_observed_at) != target_date
                for dataset in current_snapshots
            )
        ):
            raise ValueError("Market publication observations do not match the completed session")
        price_preparation = dependencies.refresh_market_price_inputs(
            dependencies.model_market_data_port(), publication_scope_codes, target_date
        )
        price_audit_references.update(
            {
                reference.raw_audit_id: reference
                for reference in price_preparation.raw_audit_references
            }
        )
        suspended_codes = tuple(
            sorted(set(excluded_non_trading_codes).union(price_preparation.suspended_codes))
        )
        price_evidence.update(
            price_scope_verified=len(publication_scope_codes),
            price_target_date=target_date.isoformat(),
            suspended_codes=list(suspended_codes),
            raw_audit_references=[
                {
                    "raw_audit_id": reference.raw_audit_id,
                    "version": reference.version,
                    "content_hash": reference.content_hash,
                    "run_id": reference.run_id,
                    "ingested_run_id": reference.ingested_run_id,
                }
                for _raw_audit_id, reference in sorted(price_audit_references.items())
            ],
        )
        publication_result = publications.execute(
            asset_codes=publication_scope_codes,
            run_id=publication_run_id,
            scope_exclusions_by_dataset=publication_scope_exclusions,
            required_observation_dates=required_observation_dates,
        )
        publication_evidence.update(publication_result.to_dict())
        publish_progress(
            TaskProgressPhase(
                phase="publication",
                requested=1,
                succeeded=1,
                failed=0,
                stored=publication_result.published_count,
                count_unit="sync_operation",
                stored_count_unit="publication_member",
            )
        )
        return publication_result.published_count

    try:
        result = dependencies.refresh_market_publications(
            as_of_date=target_date,
            batch_size=batch_size,
            ports=MarketPublicationRefreshPorts(
                list_codes=lambda: tradable_codes,
                sync_quotes=sync_quote_batch,
                sync_valuations=sync_valuation_batch,
                publish=publish_complete_session,
            ),
        )
    except SoftTimeLimitExceeded:
        return market_task.full_market_soft_timeout_failure(
            requested_operations=requested_operations,
            completed_operations=completed_operation_count,
            stored_rows=stored_row_count,
            target_trade_date=target_date.isoformat(),
            phase=current_phase,
            asset_count=len(tradable_codes),
            publication_run_id=publication_run_id,
            quote_source=selected_quote_source,
            valuation_source=selected_valuation_source,
            market_universe=universe_report,
            valuation_seed_stored=valuation_seed.stored_count,
            excluded_non_trading_codes=excluded_non_trading_codes,
        )
    price_evidence["raw_audit_references_by_dataset"] = {
        "equity.quote.snapshot": _serialize_raw_audit_references(quote_audit_references),
        "equity.valuation.fact": _serialize_raw_audit_references(valuation_audit_references),
        "equity.price.bar": _serialize_raw_audit_references(price_audit_references),
    }
    if not authority_latch.current:
        return apply_full_market_authority_block(
            result,
            reason_code=authority_latch.reason_code,
        )
    return market_task.finalize_full_market_result(
        result=result,
        price_evidence=price_evidence,
        publication_evidence=publication_evidence,
        publication_run_id=publication_run_id,
        quote_source=selected_quote_source,
        valuation_source=selected_valuation_source,
        market_universe=universe_report,
        valuation_seed_stored=valuation_seed.stored_count,
        stored_row_count=stored_row_count,
        quote_stored_rows=quote_stored_rows,
        requested_codes=requested_codes,
        succeeded_codes=succeeded_code_set,
        missing_codes=missing_codes,
        coverage_ratio=valuation_coverage_ratio,
        policy_identity=(valuation_policy.identity if valuation_policy is not None else None),
        excluded_codes=excluded_non_trading_codes,
    )
