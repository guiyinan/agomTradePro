"""Controlled, evidence-first AKShare financial slice synchronization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Protocol
from uuid import UUID

from apps.data_center.domain.entities import FinancialFact, ProviderConfig
from apps.data_center.domain.enums import DataCapability
from apps.data_center.domain.financial_source_evidence import (
    FINANCIAL_FACT_DATASET_KEY,
    FinancialFactDecisionEvidence,
)
from apps.data_center.domain.protocols import (
    FinancialFactRepositoryProtocol,
    ProviderConfigRepositoryProtocol,
    ProviderRegistryProtocol,
    UnifiedDataProviderProtocol,
)
from core.exceptions import DataFetchError, DataValidationError, InvalidInputError

from .sync_use_cases import with_verified_financial_transport_metadata


@dataclass(frozen=True, slots=True)
class FinancialAnnouncementSlice:
    """One explicit asset and announcement-date pair for a financial read."""

    asset_code: str
    announcement_date: date


@dataclass(frozen=True, slots=True)
class FinancialSliceSyncRequest:
    """An explicit, provider-pinned set of financial asset/date slices."""

    provider_id: int | None = None
    source: str = ""
    slices: tuple[FinancialAnnouncementSlice, ...] = ()
    period_limit: int = 8
    run_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class FinancialSliceSyncBudget:
    """Governed upper bounds for logical AKShare provider requests per invocation."""

    max_slices: int
    provider_requests_per_slice: int
    max_provider_requests: int
    max_period_rows_per_capture: int

    def __post_init__(self) -> None:
        """Reject inconsistent budgets instead of weakening a request gate."""

        values = (
            self.max_slices,
            self.provider_requests_per_slice,
            self.max_provider_requests,
            self.max_period_rows_per_capture,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in values
        ):
            raise ValueError("financial slice sync budget values must be positive integers")
        if self.provider_requests_per_slice != 2:
            raise ValueError("AKShare financial slices require two independent provider requests")
        if self.max_provider_requests != self.max_slices * self.provider_requests_per_slice:
            raise ValueError("financial slice sync request budget is inconsistent")


class FinancialSliceFetcherProtocol(Protocol):
    """Expose one exact captured AKShare asset/date fetch to the use case."""

    def fetch_financials_for_announcement_date(
        self,
        asset_code: str,
        announcement_date: date,
        periods: int,
        *,
        run_id: UUID | None = None,
    ) -> list[FinancialFact]:
        """Return typed facts only after retained-body witness validation."""

    @property
    def last_observed_provider_requests(self) -> int | None:
        """Return exact physical attempts for the most recent slice, if known."""


class FinancialSliceFetcherFactory(Protocol):
    """Build a pinned fetcher after owner approval and capture capability checks."""

    def __call__(
        self,
        config: ProviderConfig,
        provider: UnifiedDataProviderProtocol,
    ) -> FinancialSliceFetcherProtocol:
        """Return a no-fallback fetcher or raise before provider egress."""


class FinancialSliceEvidenceVerifier(Protocol):
    """Verify exact retained response and source-time artifacts for a fact."""

    def __call__(
        self,
        provider: ProviderConfig,
        evidence: FinancialFactDecisionEvidence,
        *,
        expected_run_id: UUID | None = None,
    ) -> bool:
        """Return whether the exact pair is still retained and audit-bound."""


FinancialSliceOutcome = Literal["success", "partial", "blocked", "failed", "noop"]


@dataclass(frozen=True, slots=True)
class FinancialSliceSyncResult:
    """Outcome and counts for one no-fallback AKShare slice-sync invocation.

    ``succeeded`` counts asset/date pairs whose provider data and evidence passed;
    ``stored`` is the actual count returned by the single atomic fact batch write.
    A partial provider result is never persisted because the entire batch is held
    until every requested pair has passed evidence validation.
    """

    outcome: FinancialSliceOutcome
    source: str
    provider_id: int | None
    provider_name: str | None
    requested: int
    succeeded: int
    failed: int
    stored: int
    planned_provider_requests: int
    atomic_fact_write_count: int = 0
    failure_reason: str | None = None
    observed_provider_requests: int | None = 0
    maximum_physical_provider_attempts: int | None = None

    def __post_init__(self) -> None:
        """Keep counters internally consistent and non-negative."""

        if min(self.requested, self.succeeded, self.failed, self.stored) < 0:
            raise ValueError("financial slice sync counters cannot be negative")
        if self.requested != self.succeeded + self.failed:
            raise ValueError("financial slice sync requested count must equal success plus failure")
        if (
            isinstance(self.planned_provider_requests, bool)
            or not isinstance(self.planned_provider_requests, int)
            or self.planned_provider_requests < 0
            or (
                self.maximum_physical_provider_attempts is not None
                and (
                    isinstance(self.maximum_physical_provider_attempts, bool)
                    or not isinstance(self.maximum_physical_provider_attempts, int)
                    or self.maximum_physical_provider_attempts < 0
                )
            )
            or isinstance(self.atomic_fact_write_count, bool)
            or not isinstance(self.atomic_fact_write_count, int)
            or self.atomic_fact_write_count not in {0, 1}
            or (
                self.observed_provider_requests is not None
                and (
                    isinstance(self.observed_provider_requests, bool)
                    or not isinstance(self.observed_provider_requests, int)
                    or self.observed_provider_requests < 0
                )
            )
        ):
            raise ValueError("financial slice provider request or atomic write count is invalid")

    def to_dict(self) -> dict[str, object]:
        """Return the stable business outcome contract."""

        return {
            "outcome": self.outcome,
            "source": self.source,
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "requested": self.requested,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "stored": self.stored,
            "planned_provider_requests": self.planned_provider_requests,
            "maximum_physical_provider_attempts": (
                self.maximum_physical_provider_attempts
                if self.maximum_physical_provider_attempts is not None
                else self.planned_provider_requests * 2
            ),
            "observed_provider_requests": self.observed_provider_requests,
            "atomic_fact_write_count": self.atomic_fact_write_count,
            "failure_reason": self.failure_reason,
        }


class SyncAkshareFinancialSlicesUseCase:
    """Synchronize only explicit, source-verified AKShare announcement slices."""

    _EXPECTED_SOURCE = "akshare"

    def __init__(
        self,
        *,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_registry: ProviderRegistryProtocol,
        fact_repo: FinancialFactRepositoryProtocol,
        fetcher_factory: FinancialSliceFetcherFactory,
        evidence_verifier: FinancialSliceEvidenceVerifier,
        request_budget: FinancialSliceSyncBudget | None,
        max_route_attempts: int = 2,
    ) -> None:
        """Inject provider routing, retained-evidence preflight, and atomic storage."""

        self._provider_repo = provider_repo
        self._provider_registry = provider_registry
        self._fact_repo = fact_repo
        self._fetcher_factory = fetcher_factory
        self._evidence_verifier = evidence_verifier
        self._request_budget = request_budget
        if type(max_route_attempts) is not int or max_route_attempts not in {1, 2}:
            raise ValueError("financial slice route attempts must be one or two")
        self._max_route_attempts = max_route_attempts

    def execute(self, request: FinancialSliceSyncRequest) -> FinancialSliceSyncResult:
        """Validate, fetch, verify, then atomically write one complete slice batch."""

        requested = len(request.slices) if isinstance(request.slices, (tuple, list)) else 0
        planned_requests = requested * 2
        invalid_reason = self._request_block_reason(request, requested, planned_requests)
        if invalid_reason is not None:
            return self._result(
                request,
                outcome="blocked",
                requested=requested,
                succeeded=0,
                stored=0,
                planned_requests=planned_requests,
                failure_reason=invalid_reason,
            )

        request_budget = self._request_budget
        if request_budget is None:
            return self._result(
                request,
                outcome="blocked",
                requested=requested,
                succeeded=0,
                stored=0,
                planned_requests=planned_requests,
                failure_reason="financial_sync_request_budget_unavailable",
            )

        provider_id = request.provider_id
        if provider_id is None:
            return self._result(
                request,
                outcome="blocked",
                requested=requested,
                succeeded=0,
                stored=0,
                planned_requests=planned_requests,
                failure_reason="explicit_provider_id_required",
            )
        try:
            config = self._provider_repo.get_by_id(provider_id)
        except (LookupError, OSError, RuntimeError, TypeError, ValueError):
            return self._result(
                request,
                outcome="failed",
                requested=requested,
                succeeded=0,
                stored=0,
                planned_requests=planned_requests,
                provider_id=provider_id,
                failure_reason="provider_config_lookup_failed",
            )
        if (
            config is None
            or config.id != provider_id
            or isinstance(config.id, bool)
            or config.id is None
            or config.id <= 0
            or config.source_type != self._EXPECTED_SOURCE
            or config.is_active is not True
        ):
            return self._result(
                request,
                outcome="blocked",
                requested=requested,
                succeeded=0,
                stored=0,
                planned_requests=planned_requests,
                failure_reason="exact_active_akshare_provider_required",
            )

        try:
            provider = self._provider_registry.get_by_id(provider_id)
        except (LookupError, RuntimeError, TypeError, ValueError):
            provider = None
        if provider is None:
            return self._result(
                request,
                outcome="blocked",
                requested=requested,
                succeeded=0,
                stored=0,
                planned_requests=planned_requests,
                provider_id=provider_id,
                provider_name=config.name,
                failure_reason="exact_akshare_financial_route_unavailable",
            )
        try:
            route_available = provider.supports(DataCapability.FINANCIAL)
        except (RuntimeError, TypeError, ValueError):
            route_available = False
        if not route_available:
            return self._result(
                request,
                outcome="blocked",
                requested=requested,
                succeeded=0,
                stored=0,
                planned_requests=planned_requests,
                provider_id=provider_id,
                provider_name=config.name,
                failure_reason="exact_akshare_financial_route_unavailable",
            )
        try:
            fetcher = self._fetcher_factory(config, provider)
        except (DataFetchError, InvalidInputError, OSError, RuntimeError, TypeError, ValueError):
            return self._result(
                request,
                outcome="blocked",
                requested=requested,
                succeeded=0,
                stored=0,
                planned_requests=planned_requests,
                provider_id=provider_id,
                provider_name=config.name,
                failure_reason="owner_approved_capture_capability_unavailable",
            )

        all_facts: list[FinancialFact] = []
        succeeded = 0
        observed_provider_requests: int | None = 0
        used_capture_ids: set[str] = set()
        for item in request.slices:
            try:
                if request.run_id is None:
                    facts = fetcher.fetch_financials_for_announcement_date(
                        item.asset_code,
                        item.announcement_date,
                        request.period_limit,
                    )
                else:
                    facts = fetcher.fetch_financials_for_announcement_date(
                        item.asset_code,
                        item.announcement_date,
                        request.period_limit,
                        run_id=request.run_id,
                    )
            except (
                DataFetchError,
                ConnectionError,
                OSError,
                RuntimeError,
                TimeoutError,
                TypeError,
                ValueError,
            ) as exc:
                observed_provider_requests = _accumulate_observed_provider_requests(
                    observed_provider_requests,
                    getattr(fetcher, "last_observed_provider_requests", None),
                )
                request_count_failure = self._provider_request_count_failure(
                    observed_provider_requests
                )
                provider_error_code = getattr(exc, "code", None)
                failure_reason = request_count_failure or (
                    "financial_provider_request_hard_limit_exceeded"
                    if provider_error_code == "FINANCIAL_PROVIDER_REQUEST_HARD_LIMIT_EXCEEDED"
                    else "akshare_provider_or_capture_failed"
                )
                return self._result(
                    request,
                    outcome="partial" if succeeded else "failed",
                    requested=requested,
                    succeeded=succeeded,
                    stored=0,
                    planned_requests=planned_requests,
                    provider_id=provider_id,
                    provider_name=config.name,
                    failure_reason=failure_reason,
                    observed_requests=observed_provider_requests,
                )

            observed_provider_requests = _accumulate_observed_provider_requests(
                observed_provider_requests,
                getattr(fetcher, "last_observed_provider_requests", None),
            )
            request_count_failure = self._provider_request_count_failure(observed_provider_requests)
            if request_count_failure is not None:
                return self._result(
                    request,
                    outcome="partial" if succeeded else "failed",
                    requested=requested,
                    succeeded=succeeded,
                    stored=0,
                    planned_requests=planned_requests,
                    provider_id=provider_id,
                    provider_name=config.name,
                    failure_reason=request_count_failure,
                    observed_requests=observed_provider_requests,
                )

            try:
                slice_is_valid = self._slice_facts_are_valid(
                    facts,
                    provider=config,
                    item=item,
                    period_limit=request.period_limit,
                    used_capture_ids=used_capture_ids,
                    run_id=request.run_id,
                )
            except (
                DataFetchError,
                DataValidationError,
                OSError,
                RuntimeError,
                TypeError,
                ValueError,
            ):
                slice_is_valid = False
            if not slice_is_valid:
                return self._result(
                    request,
                    outcome="partial" if succeeded else "blocked",
                    requested=requested,
                    succeeded=succeeded,
                    stored=0,
                    planned_requests=planned_requests,
                    provider_id=provider_id,
                    provider_name=config.name,
                    failure_reason="financial_source_evidence_incomplete_or_mismatched",
                    observed_requests=observed_provider_requests,
                )
            succeeded += 1
            all_facts.extend(facts)

        if not all_facts or self._has_duplicate_natural_keys(all_facts):
            return self._result(
                request,
                outcome="blocked",
                requested=requested,
                succeeded=succeeded,
                stored=0,
                planned_requests=planned_requests,
                provider_id=provider_id,
                provider_name=config.name,
                failure_reason="financial_slice_batch_empty_or_ambiguous",
                observed_requests=observed_provider_requests,
            )

        atomic_fact_write_count = 0
        try:
            facts_with_transport_metadata = [
                with_verified_financial_transport_metadata(fact) for fact in all_facts
            ]
            atomic_fact_write_count = 1
            if request.run_id is None:
                stored = self._fact_repo.bulk_upsert(facts_with_transport_metadata)
            else:
                stored = self._fact_repo.bulk_upsert(
                    facts_with_transport_metadata,
                    ingested_run_id=request.run_id,
                )
        except (
            DataValidationError,
            InvalidInputError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ):
            return self._result(
                request,
                outcome="failed",
                requested=requested,
                succeeded=succeeded,
                failed=requested - succeeded,
                stored=0,
                planned_requests=planned_requests,
                provider_id=provider_id,
                provider_name=config.name,
                atomic_fact_write_count=atomic_fact_write_count,
                failure_reason="financial_fact_atomic_batch_write_failed",
                observed_requests=observed_provider_requests,
            )
        if isinstance(stored, bool) or not isinstance(stored, int) or stored < 0:
            return self._result(
                request,
                outcome="failed",
                requested=requested,
                succeeded=succeeded,
                failed=requested - succeeded,
                stored=0,
                planned_requests=planned_requests,
                provider_id=provider_id,
                provider_name=config.name,
                atomic_fact_write_count=atomic_fact_write_count,
                failure_reason="financial_fact_repository_count_invalid",
                observed_requests=observed_provider_requests,
            )
        if stored > len(facts_with_transport_metadata):
            return self._result(
                request,
                outcome="failed",
                requested=requested,
                succeeded=succeeded,
                stored=0,
                planned_requests=planned_requests,
                provider_id=provider_id,
                provider_name=config.name,
                atomic_fact_write_count=atomic_fact_write_count,
                failure_reason="financial_fact_repository_count_invalid",
                observed_requests=observed_provider_requests,
            )
        return self._result(
            request,
            outcome="success" if stored > 0 else "noop",
            requested=requested,
            succeeded=succeeded,
            stored=stored,
            planned_requests=planned_requests,
            provider_id=provider_id,
            provider_name=config.name,
            atomic_fact_write_count=atomic_fact_write_count,
            failure_reason=None if stored > 0 else "financial_facts_already_current",
            observed_requests=observed_provider_requests,
        )

    def _request_block_reason(
        self,
        request: FinancialSliceSyncRequest,
        requested: int,
        planned_requests: int,
    ) -> str | None:
        """Validate explicit source, slice shape, page size, and hard request cap."""

        if request.source != self._EXPECTED_SOURCE:
            return "explicit_source_akshare_required"
        if not isinstance(request.slices, tuple) or requested == 0:
            return "explicit_asset_announcement_slices_required"
        if any(not isinstance(item, FinancialAnnouncementSlice) for item in request.slices):
            return "financial_announcement_slice_shape_invalid"
        if any(
            not _valid_slice(item)
            for item in request.slices
            if isinstance(item, FinancialAnnouncementSlice)
        ):
            return "financial_announcement_slice_dimensions_invalid"
        if len({(item.asset_code, item.announcement_date) for item in request.slices}) != requested:
            return "duplicate_financial_announcement_slice"
        if (
            request.provider_id is None
            or isinstance(request.provider_id, bool)
            or not isinstance(request.provider_id, int)
            or request.provider_id <= 0
        ):
            return "explicit_provider_id_required"
        budget = self._request_budget
        if budget is None:
            return "financial_sync_request_budget_unavailable"
        if (
            isinstance(request.period_limit, bool)
            or not isinstance(request.period_limit, int)
            or not 1 <= request.period_limit <= budget.max_period_rows_per_capture
        ):
            return "financial_period_limit_outside_governed_bound"
        if request.run_id is not None and not isinstance(request.run_id, UUID):
            return "financial_capacity_run_id_invalid"
        if requested > budget.max_slices or planned_requests > budget.max_provider_requests:
            return "financial_provider_request_scale_exceeds_governed_bound"
        if budget.provider_requests_per_slice != 2:
            return "financial_provider_request_model_mismatch"
        return None

    def _provider_request_count_failure(self, observed_requests: int | None) -> str | None:
        """Reject unknown or over-ceiling physical attempts before evidence or storage."""

        if observed_requests is None:
            return "financial_provider_request_count_unknown"
        if observed_requests > self._maximum_physical_provider_attempts:
            return "financial_provider_request_hard_limit_exceeded"
        return None

    @property
    def _maximum_physical_provider_attempts(self) -> int:
        """Return the logical invocation ceiling expanded by route attempts."""

        if self._request_budget is None:
            return 0
        return self._request_budget.max_provider_requests * self._max_route_attempts

    def _slice_facts_are_valid(
        self,
        facts: list[FinancialFact],
        *,
        provider: ProviderConfig,
        item: FinancialAnnouncementSlice,
        period_limit: int,
        used_capture_ids: set[str],
        run_id: UUID | None,
    ) -> bool:
        """Require every returned fact to bind to this exact dual-capture slice."""

        if not facts:
            return False
        slice_capture_ids: set[str] = set()
        expected_pair_ids: set[str] | None = None
        for fact in facts:
            source = fact.source_evidence
            decision = fact.decision_evidence
            if source is None or not source.is_complete or decision is None:
                return False
            witness = decision.source_time_witness
            reference = decision.artifact_reference
            scope = reference.evidence.request_scope
            response_scope = reference.evidence.response_scope
            if (
                fact.asset_code != item.asset_code
                or fact.source != self._EXPECTED_SOURCE
                or fact.available_at is None
                or fact.fetched_at.tzinfo is None
                or fact.fetched_at.utcoffset() is None
                or scope.provider_name != self._EXPECTED_SOURCE
                or scope.dataset_key != FINANCIAL_FACT_DATASET_KEY
                or scope.asset_code != item.asset_code
                or scope.period_limit != period_limit
                or response_scope.asset_codes != (item.asset_code,)
                or response_scope.row_count <= 0
                or response_scope.row_count > period_limit
                or fact.period_end not in response_scope.period_ends
                or decision.native_asset_code != fact.asset_code
                or decision.native_period_end != fact.period_end
                or source.raw_payload_hash != reference.evidence.body_sha256
                or source.source_record_id != decision.native_row_id
                or witness is None
                or witness.native_asset_code != item.asset_code
                or witness.native_period_end != fact.period_end
                or witness.financial_native_row_id != decision.native_row_id
                or witness.financial_announced_date != item.announcement_date
                or witness.artifact_reference.requested_asset_code != item.asset_code
                or witness.artifact_reference.requested_announcement_date != item.announcement_date
                or source.announced_at != witness.announced_at
                or fact.available_at != witness.available_at
                or not witness.available_at
                <= reference.evidence.response_completed_at
                <= fact.fetched_at
                or not self._verify_slice_evidence(provider, decision, run_id=run_id)
            ):
                return False
            pair_ids = {str(reference.capture_id), str(witness.artifact_reference.capture_id)}
            if (
                len(pair_ids) != 2
                or pair_ids & used_capture_ids
                or (expected_pair_ids is not None and pair_ids != expected_pair_ids)
            ):
                return False
            expected_pair_ids = pair_ids
            slice_capture_ids.update(pair_ids)
        if not slice_capture_ids:
            return False
        used_capture_ids.update(slice_capture_ids)
        return True

    def _verify_slice_evidence(
        self,
        provider: ProviderConfig,
        evidence: FinancialFactDecisionEvidence,
        *,
        run_id: UUID | None,
    ) -> bool:
        """Verify retained evidence and, for capacity runs, its exact run lineage."""

        if run_id is None:
            return self._evidence_verifier(provider, evidence)
        return self._evidence_verifier(
            provider,
            evidence,
            expected_run_id=run_id,
        )

    @staticmethod
    def _has_duplicate_natural_keys(facts: list[FinancialFact]) -> bool:
        """Return whether the batch contains repeated persisted fact identities."""

        keys = [
            (
                fact.asset_code,
                fact.period_end,
                fact.period_type,
                fact.metric_code,
                fact.source,
            )
            for fact in facts
        ]
        return len(set(keys)) != len(keys)

    def _result(
        self,
        request: FinancialSliceSyncRequest,
        *,
        outcome: FinancialSliceOutcome,
        requested: int,
        succeeded: int,
        stored: int,
        planned_requests: int,
        failure_reason: str | None = None,
        provider_id: int | None = None,
        provider_name: str | None = None,
        failed: int | None = None,
        atomic_fact_write_count: int = 0,
        observed_requests: int | None = 0,
    ) -> FinancialSliceSyncResult:
        """Build one immutable count contract from an execution decision."""

        final_failed = requested - succeeded if failed is None else failed
        return FinancialSliceSyncResult(
            outcome=outcome,
            source=request.source if isinstance(request.source, str) else "",
            provider_id=provider_id,
            provider_name=provider_name,
            requested=requested,
            succeeded=succeeded,
            failed=final_failed,
            stored=stored,
            planned_provider_requests=planned_requests,
            maximum_physical_provider_attempts=self._maximum_physical_provider_attempts,
            atomic_fact_write_count=atomic_fact_write_count,
            failure_reason=failure_reason,
            observed_provider_requests=observed_requests,
        )


def _accumulate_observed_provider_requests(
    previous: int | None,
    current: object,
) -> int | None:
    """Sum exact physical attempts, propagating unknown instead of estimating."""

    if previous is None or isinstance(current, bool) or not isinstance(current, int) or current < 0:
        return None
    return previous + current


def _valid_slice(item: FinancialAnnouncementSlice) -> bool:
    """Return whether a slice contains a canonical asset code and calendar date."""

    return (
        isinstance(item.asset_code, str)
        and len(item.asset_code) == 9
        and item.asset_code[:6].isdigit()
        and item.asset_code[6] == "."
        and item.asset_code[7:] in {"SH", "SZ", "BJ"}
        and item.asset_code == item.asset_code.strip()
        and not isinstance(item.announcement_date, datetime)
        and isinstance(item.announcement_date, date)
    )


__all__ = [
    "FinancialAnnouncementSlice",
    "FinancialSliceEvidenceVerifier",
    "FinancialSliceFetcherFactory",
    "FinancialSliceFetcherProtocol",
    "FinancialSliceSyncBudget",
    "FinancialSliceSyncRequest",
    "FinancialSliceSyncResult",
    "SyncAkshareFinancialSlicesUseCase",
]
