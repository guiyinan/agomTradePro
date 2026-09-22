"""Application orchestration for resumable A-share core-data backfills."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Protocol

from apps.data_center.domain.control_plane import (
    SyncItemAttempt,
    SyncItemAttemptPhase,
    SyncItemAttemptState,
)
from core.exceptions import InvalidInputError
from shared.domain.task_outcomes import TaskBusinessOutcome

from .backfill_control_plane import backfill_control_plane_ids, backfill_execution_token
from .batch_identity import ProviderAssetIdentityError
from .current_valuation_sync import SyncCurrentValuationBatchUseCase
from .dtos import SyncFinancialRequest, SyncPriceRequest, SyncQuoteRequest, SyncResult
from .sync_use_cases import (
    PreparedFinancialSync,
    SyncFinancialUseCase,
    SyncPriceUseCase,
    SyncQuoteUseCase,
)


class PersistBackfillControlPlane(Protocol):
    """Port for persisting one durable backfill lifecycle record."""

    def __call__(
        self,
        *,
        idempotency_key: str,
        provider_name: str,
        outcome: TaskBusinessOutcome,
        requested: int,
        succeeded: int,
        failed: int,
        stored: int,
        published: int,
        checkpoint: Mapping[str, object],
        window_start: date | None,
        window_end: date | None,
        started_at: datetime,
        error_code: str = "",
        error_message: str = "",
    ) -> None:
        """Persist a normalized run, batch, and checkpoint."""


class RebuildCurrentPublications(Protocol):
    """Port for atomically publishing the complete core asset universe."""

    def __call__(
        self,
        *,
        asset_codes: list[str],
        published_at: datetime,
    ) -> object:
        """Publish complete current snapshots or raise without partial commit."""


class BackfillItemAttemptStore(Protocol):
    """Port for durable per-asset DATA-02 execution evidence."""

    def begin(
        self,
        *,
        idempotency_key: str,
        provider_name: str,
        asset_code: str,
        phase: SyncItemAttemptPhase,
        execution_token: str,
        started_at: datetime,
        universe_hash: str,
        authority_content_hash: str,
        requested: int,
    ) -> SyncItemAttempt:
        """Persist one RUNNING item attempt before its external write."""

    def finish(
        self,
        attempt: SyncItemAttempt,
        *,
        state: SyncItemAttemptState,
        finished_at: datetime,
        stored_count: int = 0,
        error_code: str = "",
        error_message: str = "",
        evidence_hash: str = "",
    ) -> SyncItemAttempt:
        """Persist the single terminal transition for one item attempt."""

    def begin_many(
        self,
        *,
        idempotency_key: str,
        provider_name: str,
        asset_codes: Sequence[str],
        phase: SyncItemAttemptPhase,
        execution_token: str,
        started_at: datetime,
        universe_hash: str,
        authority_content_hash: str,
        requested: int,
    ) -> list[SyncItemAttempt]:
        """Persist one bounded phase batch of RUNNING item attempts atomically."""

    def finish_many(
        self,
        attempts: Sequence[SyncItemAttempt],
    ) -> list[SyncItemAttempt]:
        """Persist prepared terminal transitions for one phase batch atomically."""


class PublicationEvidenceHash(Protocol):
    """Port for binding a rebuild result to immutable Publication identities."""

    def __call__(self, result: object, expected_asset_count: int) -> str:
        """Return a canonical SHA-256 for committed Publication evidence."""


@dataclass(frozen=True, slots=True)
class BackfillAuthorityBinding:
    """Server-issued authority identity persisted with every batch checkpoint."""

    actor_id: str
    tenant_id: str
    owner_id: str
    content_hash: str
    valid_until: datetime

    def to_checkpoint(self) -> dict[str, str]:
        """Return the immutable, non-secret authority checkpoint projection."""

        return {
            "actor_id": self.actor_id,
            "tenant_id": self.tenant_id,
            "owner_id": self.owner_id,
            "content_hash": self.content_hash,
            "valid_until": self.valid_until.isoformat(),
        }


@dataclass(frozen=True)
class CoreDataBackfillServices:
    """Injected ports and use-case factories for one backfill batch."""

    list_active_stock_codes: Callable[[], list[str]]
    get_active_provider_id: Callable[[str], int | None]
    latest_completed_market_session: Callable[[datetime], date | None]
    current_time: Callable[[], datetime]
    make_sync_quote_use_case: Callable[[], SyncQuoteUseCase]
    make_sync_price_use_case: Callable[[], SyncPriceUseCase]
    make_sync_valuation_batch_use_case: Callable[[], SyncCurrentValuationBatchUseCase]
    make_sync_financial_use_case: Callable[[], SyncFinancialUseCase]
    rebuild_current_publications: RebuildCurrentPublications
    published_count_from_result: Callable[[object], int]
    publication_evidence_hash: PublicationEvidenceHash
    persist_control_plane: PersistBackfillControlPlane
    item_attempt_store: BackfillItemAttemptStore
    authority_binding: BackfillAuthorityBinding
    revalidate_authority: Callable[[datetime], bool]


def run_active_a_share_core_data_backfill_batch(
    *,
    validated_offset: int,
    validated_batch_size: int,
    normalized_source: str,
    validated_history_days: int,
    validated_periods: int,
    idempotency_key: str,
    expected_universe_hash: str,
    started_at: datetime,
    services: CoreDataBackfillServices,
) -> dict[str, Any]:
    """Run one validated, resumable active-A-share core-data batch."""

    if expected_universe_hash and (
        len(expected_universe_hash) != 64
        or any(character not in "0123456789abcdef" for character in expected_universe_hash)
    ):
        return {
            "success": False,
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "stage": "universe",
            "blocked_reason": "invalid_expected_universe_hash",
            "requested": 0,
            "succeeded": 0,
            "failed": 0,
            "stored": 0,
            "checkpoint": {
                "offset": validated_offset,
                "next_offset": validated_offset,
                "total_assets": 0,
                "complete": False,
                "universe_hash": expected_universe_hash,
                "authority": services.authority_binding.to_checkpoint(),
            },
        }
    raw_asset_codes = services.list_active_stock_codes()
    invalid_asset_code_type = any(not isinstance(asset_code, str) for asset_code in raw_asset_codes)
    if invalid_asset_code_type:
        normalized_asset_codes: tuple[str, ...] = ()
    else:
        normalized_asset_codes = tuple(asset_code.strip().upper() for asset_code in raw_asset_codes)
    if (
        invalid_asset_code_type
        or any(not asset_code for asset_code in normalized_asset_codes)
        or len(set(normalized_asset_codes)) != len(normalized_asset_codes)
    ):
        return {
            "success": False,
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "stage": "universe",
            "blocked_reason": "invalid_active_universe",
            "requested": 0,
            "succeeded": 0,
            "failed": 0,
            "stored": 0,
            "checkpoint": {
                "offset": validated_offset,
                "next_offset": validated_offset,
                "total_assets": 0,
                "complete": False,
                "authority": services.authority_binding.to_checkpoint(),
            },
        }
    asset_codes = sorted(normalized_asset_codes)
    universe_payload = json.dumps(
        {
            "schema": "active-a-share-universe.v1",
            "asset_codes": asset_codes,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    observed_universe_hash = hashlib.sha256(universe_payload.encode("utf-8")).hexdigest()
    bound_universe_hash = expected_universe_hash or observed_universe_hash
    idempotency_prefix = idempotency_key.rsplit(":", 1)[0]
    bound_digest = hashlib.sha256(
        f"{idempotency_key}|universe_hash={bound_universe_hash}".encode()
    ).hexdigest()[:16]
    idempotency_key = f"{idempotency_prefix}:{bound_digest}"
    total_assets = len(asset_codes)
    batch_codes = asset_codes[validated_offset : validated_offset + validated_batch_size]
    next_offset = validated_offset + len(batch_codes)
    checkpoint = {
        "offset": validated_offset,
        "next_offset": next_offset,
        "total_assets": total_assets,
        "complete": next_offset >= total_assets,
        "universe_hash": bound_universe_hash,
        "authority": services.authority_binding.to_checkpoint(),
    }
    if expected_universe_hash and expected_universe_hash != observed_universe_hash:
        failed_count = len(batch_codes)
        blocked_checkpoint = {
            **checkpoint,
            "next_offset": validated_offset,
            "complete": False,
            "observed_universe_hash": observed_universe_hash,
        }
        services.persist_control_plane(
            idempotency_key=idempotency_key,
            provider_name=normalized_source,
            outcome=TaskBusinessOutcome.BLOCKED,
            requested=failed_count,
            succeeded=0,
            failed=failed_count,
            stored=0,
            published=0,
            checkpoint=blocked_checkpoint,
            window_start=None,
            window_end=None,
            started_at=started_at,
            error_code="universe_hash_mismatch",
            error_message="active universe differs from the frozen resume binding",
        )
        return {
            "success": False,
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "stage": "universe",
            "blocked_reason": "universe_hash_mismatch",
            "requested": failed_count,
            "succeeded": 0,
            "failed": failed_count,
            "stored": 0,
            "checkpoint": blocked_checkpoint,
        }
    if not batch_codes:
        services.persist_control_plane(
            idempotency_key=idempotency_key,
            provider_name=normalized_source,
            outcome=TaskBusinessOutcome.NOOP,
            requested=0,
            succeeded=0,
            failed=0,
            stored=0,
            published=0,
            checkpoint=checkpoint,
            window_start=None,
            window_end=None,
            started_at=started_at,
        )
        return {
            "success": True,
            "outcome": TaskBusinessOutcome.NOOP.value,
            "stage": "complete",
            "requested": 0,
            "succeeded": 0,
            "failed": 0,
            "stored": 0,
            "noop_reason": "no remaining active A-share assets",
            "checkpoint": checkpoint,
        }

    provider_id = services.get_active_provider_id(normalized_source)
    if provider_id is None:
        failed_count = len(batch_codes)
        blocked_checkpoint = {**checkpoint, "complete": False}
        services.persist_control_plane(
            idempotency_key=idempotency_key,
            provider_name=normalized_source,
            outcome=TaskBusinessOutcome.FAILED,
            requested=failed_count,
            succeeded=0,
            failed=failed_count,
            stored=0,
            published=0,
            checkpoint=blocked_checkpoint,
            window_start=None,
            window_end=None,
            started_at=started_at,
            error_code="provider_unavailable",
            error_message=f"no active provider for source: {normalized_source}",
        )
        return {
            "success": False,
            "outcome": TaskBusinessOutcome.FAILED.value,
            "stage": "provider",
            "error": f"no active provider for source: {normalized_source}",
            "requested": failed_count,
            "succeeded": 0,
            "failed": failed_count,
            "stored": 0,
            "checkpoint": blocked_checkpoint,
        }

    end_date = services.latest_completed_market_session(services.current_time())
    if end_date is None:
        failed_count = len(batch_codes)
        blocked_checkpoint = {**checkpoint, "complete": False}
        services.persist_control_plane(
            idempotency_key=idempotency_key,
            provider_name=normalized_source,
            outcome=TaskBusinessOutcome.BLOCKED,
            requested=failed_count,
            succeeded=0,
            failed=failed_count,
            stored=0,
            published=0,
            checkpoint=blocked_checkpoint,
            window_start=None,
            window_end=None,
            started_at=started_at,
            error_code="market_calendar_unavailable",
            error_message="latest completed China market session is unavailable",
        )
        return {
            "success": False,
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "stage": "market_calendar",
            "error": "latest completed China market session is unavailable",
            "requested": failed_count,
            "succeeded": 0,
            "failed": failed_count,
            "stored": 0,
            "checkpoint": blocked_checkpoint,
        }
    start_date = end_date - timedelta(days=validated_history_days)
    quote_use_case = services.make_sync_quote_use_case()
    price_use_case = services.make_sync_price_use_case()
    valuation_batch_use_case = services.make_sync_valuation_batch_use_case()
    financial_use_case = services.make_sync_financial_use_case()
    authority_current = True

    def authority_allows_next_write() -> bool:
        """Revalidate once at every write boundary and stay closed after drift."""

        nonlocal authority_current
        if authority_current:
            authority_current = services.revalidate_authority(services.current_time())
        return authority_current

    domain_counts: dict[str, dict[str, int]] = {
        name: {
            "requested": len(batch_codes),
            "succeeded": 0,
            "failed": 0,
            "blocked": 0,
            "stored": 0,
        }
        for name in ("quote", "price", "valuation", "financial")
    }
    published_total = 0
    errors: list[dict[str, str]] = []
    failed_asset_codes: set[str] = set()
    execution_token = backfill_execution_token(idempotency_key)
    financial_attempts: list[SyncItemAttempt] = []
    terminal_attempt_ids: set[str] = set()

    def begin_attempts(
        phase: SyncItemAttemptPhase,
        phase_asset_codes: list[str],
    ) -> tuple[list[SyncItemAttempt], bool]:
        """Start complete item evidence before a phase can perform writes."""

        try:
            expected_run_id, expected_batch_id = backfill_control_plane_ids(idempotency_key)
            attempts = services.item_attempt_store.begin_many(
                idempotency_key=idempotency_key,
                provider_name=normalized_source,
                asset_codes=phase_asset_codes,
                phase=phase,
                execution_token=execution_token,
                started_at=started_at,
                universe_hash=bound_universe_hash,
                authority_content_hash=services.authority_binding.content_hash,
                requested=len(batch_codes),
            )
            if (
                len(attempts) != len(phase_asset_codes)
                or {attempt.asset_code for attempt in attempts} != set(phase_asset_codes)
                or len({attempt.attempt_id for attempt in attempts}) != len(attempts)
                or any(
                    attempt.run_id != expected_run_id
                    or attempt.batch_id != expected_batch_id
                    or attempt.phase is not phase
                    or attempt.state is not SyncItemAttemptState.RUNNING
                    or attempt.dataset_key != "equity.core.backfill"
                    or attempt.execution_token != execution_token
                    or attempt.started_at != started_at
                    or attempt.universe_hash != bound_universe_hash
                    or attempt.authority_content_hash != services.authority_binding.content_hash
                    for attempt in attempts
                )
            ):
                raise ValueError("item-attempt store returned incomplete RUNNING evidence")
        except Exception:
            return [], False
        return attempts, True

    def persist_finished_attempts(attempts: list[SyncItemAttempt]) -> bool:
        """Persist exact prepared terminal attempts and verify returned evidence."""

        try:
            finished = services.item_attempt_store.finish_many(attempts)
        except Exception:
            return False
        if finished != attempts:
            return False
        terminal_attempt_ids.update(attempt.attempt_id for attempt in attempts)
        return True

    def finish_attempts(
        attempts: list[SyncItemAttempt],
        *,
        state: SyncItemAttemptState,
        stored_count: int = 0,
        error_code: str = "",
        error_message: str = "",
        evidence_hash: str = "",
    ) -> bool:
        """Finish every started item attempt and report complete persistence."""

        try:
            finished_at = services.current_time()
            terminal_attempts = [
                attempt.finish(
                    state=state,
                    finished_at=finished_at,
                    stored_count=stored_count,
                    error_code=error_code,
                    error_message=error_message,
                    evidence_hash=evidence_hash,
                )
                for attempt in attempts
            ]
        except Exception:
            return False
        return persist_finished_attempts(terminal_attempts)

    def item_evidence_blocked_response() -> dict[str, Any]:
        """Fail closed without advancing when item evidence is incomplete."""

        pending_financial_attempts = [
            attempt
            for attempt in financial_attempts
            if attempt.attempt_id not in terminal_attempt_ids
        ]
        if pending_financial_attempts:
            finish_attempts(
                pending_financial_attempts,
                state=SyncItemAttemptState.BLOCKED,
                error_code="item_attempt_evidence_failed",
            )
        blocked_checkpoint = {
            **checkpoint,
            "next_offset": validated_offset,
            "complete": False,
        }
        stored_total = sum(item["stored"] for item in domain_counts.values())
        services.persist_control_plane(
            idempotency_key=idempotency_key,
            provider_name=normalized_source,
            outcome=TaskBusinessOutcome.BLOCKED,
            requested=len(batch_codes),
            succeeded=0,
            failed=len(batch_codes),
            stored=stored_total,
            published=published_total,
            checkpoint=blocked_checkpoint,
            window_start=start_date,
            window_end=end_date,
            started_at=started_at,
            error_code="item_attempt_evidence_failed",
            error_message="durable item-attempt evidence is incomplete",
        )
        return {
            "success": False,
            "outcome": TaskBusinessOutcome.BLOCKED.value,
            "stage": "item_evidence",
            "blocked_reason": "item_attempt_evidence_failed",
            "source": normalized_source,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "asset_codes": batch_codes,
            "requested": len(batch_codes),
            "succeeded": 0,
            "failed": len(batch_codes),
            "stored": stored_total,
            "published": published_total,
            "domain_counts": domain_counts,
            "errors": errors[:20],
            "checkpoint": blocked_checkpoint,
        }

    def financial_prepare_terminal_response(
        *,
        outcome: TaskBusinessOutcome,
        reason: str,
    ) -> dict[str, Any]:
        """Return a zero-write terminal result for the batch financial preflight."""

        blocked = outcome is TaskBusinessOutcome.BLOCKED
        domain_counts["financial"]["blocked"] = len(batch_codes) if blocked else 0
        domain_counts["financial"]["failed"] = 0 if blocked else len(batch_codes)
        failed = 0 if blocked else len(batch_codes)
        terminal_checkpoint = {
            **checkpoint,
            "next_offset": validated_offset,
            "complete": False,
        }
        services.persist_control_plane(
            idempotency_key=idempotency_key,
            provider_name=normalized_source,
            outcome=outcome,
            requested=len(batch_codes),
            succeeded=0,
            failed=failed,
            stored=0,
            published=0,
            checkpoint=terminal_checkpoint,
            window_start=start_date,
            window_end=end_date,
            started_at=started_at,
            error_code=reason,
            error_message="financial source evidence preflight did not permit writes",
        )
        response: dict[str, Any] = {
            "success": False,
            "outcome": outcome.value,
            "stage": (
                "authority"
                if reason == "authority_changed_or_expired"
                else ("financial_evidence" if blocked else "financial_prepare")
            ),
            "source": normalized_source,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "asset_codes": batch_codes,
            "requested": len(batch_codes),
            "succeeded": 0,
            "failed": failed,
            "stored": 0,
            "published": 0,
            "domains": domain_counts,
            "errors": [
                {
                    "domain": "financial",
                    "asset_code": "batch",
                    "error": reason,
                }
            ],
            "checkpoint": terminal_checkpoint,
        }
        if blocked:
            response["blocked_reason"] = reason
        else:
            response["error"] = reason
        return response

    financial_attempts, financial_evidence_ready = begin_attempts(
        SyncItemAttemptPhase.FINANCIAL,
        batch_codes,
    )
    if not financial_evidence_ready:
        return item_evidence_blocked_response()
    prepared_financial: dict[str, PreparedFinancialSync] = {}
    for asset_code in batch_codes:
        if not authority_allows_next_write():
            if not finish_attempts(
                financial_attempts,
                state=SyncItemAttemptState.BLOCKED,
                error_code="authority_changed_or_expired",
            ):
                return item_evidence_blocked_response()
            return financial_prepare_terminal_response(
                outcome=TaskBusinessOutcome.BLOCKED,
                reason="authority_changed_or_expired",
            )
        try:
            prepared_financial[asset_code] = financial_use_case.prepare_for_write(
                SyncFinancialRequest(
                    provider_id=provider_id,
                    asset_code=asset_code,
                    periods=validated_periods,
                )
            )
        except InvalidInputError as exc:
            if exc.code != "FINANCIAL_SOURCE_EVIDENCE_REQUIRED":
                if not finish_attempts(
                    financial_attempts,
                    state=SyncItemAttemptState.FAILED,
                    error_code="financial_prepare_failed",
                ):
                    return item_evidence_blocked_response()
                return financial_prepare_terminal_response(
                    outcome=TaskBusinessOutcome.FAILED,
                    reason="financial_prepare_failed",
                )
            if not finish_attempts(
                financial_attempts,
                state=SyncItemAttemptState.BLOCKED,
                error_code="financial_source_evidence_required",
            ):
                return item_evidence_blocked_response()
            return financial_prepare_terminal_response(
                outcome=TaskBusinessOutcome.BLOCKED,
                reason="financial_source_evidence_required",
            )
        except Exception:
            if not finish_attempts(
                financial_attempts,
                state=SyncItemAttemptState.FAILED,
                error_code="financial_prepare_failed",
            ):
                return item_evidence_blocked_response()
            return financial_prepare_terminal_response(
                outcome=TaskBusinessOutcome.FAILED,
                reason="financial_prepare_failed",
            )

    quote_attempts, quote_evidence_ready = begin_attempts(
        SyncItemAttemptPhase.QUOTE,
        batch_codes,
    )
    if not quote_evidence_ready:
        return item_evidence_blocked_response()
    try:
        if not authority_allows_next_write():
            domain_counts["quote"]["failed"] = len(batch_codes)
            errors.append({"domain": "quote", "asset_code": "batch", "error": "authority_changed"})
            if not finish_attempts(
                quote_attempts,
                state=SyncItemAttemptState.BLOCKED,
                error_code="authority_changed_or_expired",
            ):
                return item_evidence_blocked_response()
        else:
            quote_result = quote_use_case.execute(
                SyncQuoteRequest(
                    provider_id=provider_id,
                    asset_codes=batch_codes,
                    require_exact_asset_codes=True,
                )
            )
            published_total += services.published_count_from_result(quote_result)
            quote_stored = int(quote_result.stored_count)
            quote_asset_codes = tuple(
                str(asset_code or "").strip().upper()
                for asset_code in quote_result.stored_asset_codes
            )
            if (
                any(not asset_code for asset_code in quote_asset_codes)
                or quote_stored != len(batch_codes)
                or len(set(quote_asset_codes)) != len(quote_asset_codes)
                or len(quote_asset_codes) != len(batch_codes)
                or set(quote_asset_codes) != set(batch_codes)
            ):
                raise ValueError("quote batch asset identities are incomplete")
            domain_counts["quote"]["stored"] = quote_stored
            domain_counts["quote"]["succeeded"] = min(quote_stored, len(batch_codes))
            domain_counts["quote"]["failed"] = max(len(batch_codes) - quote_stored, 0)
            if not finish_attempts(
                quote_attempts,
                state=SyncItemAttemptState.SUCCEEDED,
                stored_count=1,
            ):
                return item_evidence_blocked_response()
    except Exception as error:
        error_code = (
            "provider_asset_identity_mismatch"
            if isinstance(error, ProviderAssetIdentityError)
            else "sync_failed"
        )
        domain_counts["quote"]["failed"] = len(batch_codes)
        errors.append({"domain": "quote", "asset_code": "batch", "error": error_code})
        if not finish_attempts(
            quote_attempts,
            state=SyncItemAttemptState.FAILED,
            error_code=error_code,
        ):
            return item_evidence_blocked_response()

    valuation_attempts, valuation_evidence_ready = begin_attempts(
        SyncItemAttemptPhase.VALUATION,
        batch_codes,
    )
    if not valuation_evidence_ready:
        return item_evidence_blocked_response()
    try:
        if not authority_allows_next_write():
            domain_counts["valuation"]["failed"] = len(batch_codes)
            failed_asset_codes.update(batch_codes)
            errors.append(
                {"domain": "valuation", "asset_code": "batch", "error": "authority_changed"}
            )
            if not finish_attempts(
                valuation_attempts,
                state=SyncItemAttemptState.BLOCKED,
                error_code="authority_changed_or_expired",
            ):
                return item_evidence_blocked_response()
        else:
            valuation_result = valuation_batch_use_case.execute(
                provider_id=provider_id,
                asset_codes=batch_codes,
                as_of_date=end_date,
                require_exact_asset_codes=True,
            )
            published_total += services.published_count_from_result(valuation_result)
            valuation_succeeded_codes = tuple(
                str(asset_code or "").strip().upper()
                for asset_code in valuation_result.succeeded_asset_codes
            )
            valuation_returned = tuple(
                str(asset_code or "").strip().upper()
                for asset_code in valuation_result.returned_asset_codes
            )
            if (
                any(
                    not asset_code
                    for asset_code in (*valuation_succeeded_codes, *valuation_returned)
                )
                or int(valuation_result.stored_count) != len(batch_codes)
                or len(set(valuation_succeeded_codes)) != len(valuation_succeeded_codes)
                or len(valuation_succeeded_codes) != len(batch_codes)
                or set(valuation_succeeded_codes) != set(batch_codes)
                or len(set(valuation_returned)) != len(valuation_returned)
                or len(valuation_returned) != len(batch_codes)
                or set(valuation_returned) != set(batch_codes)
            ):
                raise ValueError("valuation batch asset identities are incomplete")
            valuation_succeeded = set(valuation_succeeded_codes)
            valuation_missing = set(batch_codes) - valuation_succeeded
            domain_counts["valuation"]["stored"] = int(valuation_result.stored_count)
            domain_counts["valuation"]["succeeded"] = len(valuation_succeeded)
            domain_counts["valuation"]["failed"] = len(valuation_missing)
            failed_asset_codes.update(valuation_missing)
            for asset_code in sorted(valuation_missing)[:20]:
                errors.append(
                    {"domain": "valuation", "asset_code": asset_code, "error": "zero_output"}
                )
            if not finish_attempts(
                valuation_attempts,
                state=SyncItemAttemptState.SUCCEEDED,
                stored_count=1,
            ):
                return item_evidence_blocked_response()
    except Exception as error:
        error_code = (
            "provider_asset_identity_mismatch"
            if isinstance(error, ProviderAssetIdentityError)
            else "sync_failed"
        )
        domain_counts["valuation"]["failed"] = len(batch_codes)
        failed_asset_codes.update(batch_codes)
        errors.append({"domain": "valuation", "asset_code": "batch", "error": error_code})
        if not finish_attempts(
            valuation_attempts,
            state=SyncItemAttemptState.FAILED,
            error_code=error_code,
        ):
            return item_evidence_blocked_response()

    for domain_name, phase in (
        ("price", SyncItemAttemptPhase.PRICE),
        ("financial", SyncItemAttemptPhase.FINANCIAL),
    ):
        if domain_name == "financial":
            phase_attempts = financial_attempts
        else:
            phase_attempts, item_evidence_ready = begin_attempts(phase, batch_codes)
            if not item_evidence_ready:
                return item_evidence_blocked_response()
        attempts_by_asset = {attempt.asset_code: attempt for attempt in phase_attempts}
        completion_specs: list[tuple[SyncItemAttempt, SyncItemAttemptState, int, str]] = []
        for asset_code in batch_codes:
            completion_key: tuple[SyncItemAttemptState, int, str]
            try:
                if not authority_allows_next_write():
                    domain_counts[domain_name]["failed"] += 1
                    failed_asset_codes.add(asset_code)
                    if len(errors) < 20:
                        errors.append(
                            {
                                "domain": domain_name,
                                "asset_code": asset_code,
                                "error": "authority_changed",
                            }
                        )
                    completion_key = (
                        SyncItemAttemptState.BLOCKED,
                        0,
                        "authority_changed_or_expired",
                    )
                else:
                    result: SyncResult
                    if domain_name == "price":
                        result = price_use_case.execute(
                            SyncPriceRequest(
                                provider_id=provider_id,
                                asset_code=asset_code,
                                start=start_date,
                                end=end_date,
                            )
                        )
                    else:
                        result = financial_use_case.execute_prepared(prepared_financial[asset_code])
                    published_total += services.published_count_from_result(result)
                    stored_count = int(result.stored_count)
                    domain_counts[domain_name]["stored"] += stored_count
                    if stored_count > 0:
                        domain_counts[domain_name]["succeeded"] += 1
                        completion_key = (
                            SyncItemAttemptState.SUCCEEDED,
                            stored_count,
                            "",
                        )
                    else:
                        domain_counts[domain_name]["failed"] += 1
                        failed_asset_codes.add(asset_code)
                        if len(errors) < 20:
                            errors.append(
                                {
                                    "domain": domain_name,
                                    "asset_code": asset_code,
                                    "error": "zero_output",
                                }
                            )
                        completion_key = (
                            SyncItemAttemptState.FAILED,
                            0,
                            "zero_output",
                        )
            except Exception:
                domain_counts[domain_name]["failed"] += 1
                failed_asset_codes.add(asset_code)
                if len(errors) < 20:
                    errors.append(
                        {
                            "domain": domain_name,
                            "asset_code": asset_code,
                            "error": "sync_failed",
                        }
                    )
                completion_key = (SyncItemAttemptState.FAILED, 0, "sync_failed")
            completion_specs.append(
                (
                    attempts_by_asset[asset_code],
                    completion_key[0],
                    completion_key[1],
                    completion_key[2],
                )
            )
        phase_finished_at = services.current_time()
        completed_attempts = [
            attempt.finish(
                state=state,
                finished_at=phase_finished_at,
                stored_count=stored_count,
                error_code=error_code,
            )
            for attempt, state, stored_count, error_code in completion_specs
        ]
        if not persist_finished_attempts(completed_attempts):
            return item_evidence_blocked_response()
    quote_missing = domain_counts["quote"]["failed"]
    failed_total = max(len(failed_asset_codes), quote_missing)
    succeeded_total = max(len(batch_codes) - failed_total, 0)
    stored_total = sum(item["stored"] for item in domain_counts.values())
    # ``failed_total`` is an asset-level count: an asset is included when any
    # one of its domain writes fails.  A one-asset batch can therefore have
    # both a failure and successful writes (for example, price failed while
    # valuation/financial stored rows).  Treating ``failed_total ==
    # len(batch_codes)`` as an all-batch failure would incorrectly report that
    # partial provider failure as ``failed``.  Quote is a batch-level metadata
    # feed, so use the asset-specific domains to distinguish a genuine
    # zero-output failure from a partial batch; a quote-only write is not a
    # completed core-data asset.
    asset_domain_stored_total = sum(
        domain_counts[name]["stored"] for name in ("price", "valuation", "financial")
    )
    if asset_domain_stored_total == 0 and failed_total > 0:
        outcome = TaskBusinessOutcome.FAILED
    elif failed_total > 0:
        outcome = TaskBusinessOutcome.PARTIAL
    elif stored_total == 0:
        outcome = TaskBusinessOutcome.NOOP
    else:
        outcome = TaskBusinessOutcome.SUCCESS

    if outcome is not TaskBusinessOutcome.SUCCESS:
        checkpoint = {
            **checkpoint,
            "next_offset": validated_offset,
            "complete": False,
        }

    result_stage = "batch"
    if not authority_current or not services.revalidate_authority(services.current_time()):
        outcome = TaskBusinessOutcome.BLOCKED
        result_stage = "authority"
        checkpoint = {
            **checkpoint,
            "next_offset": validated_offset,
            "complete": False,
        }
        succeeded_total = 0
        failed_total = len(batch_codes)
        errors.append(
            {
                "domain": "authority",
                "asset_code": "batch",
                "error": "authority_changed_or_expired",
            }
        )
    if outcome is TaskBusinessOutcome.SUCCESS and checkpoint["complete"] is True:
        publication_attempts, publication_evidence_ready = begin_attempts(
            SyncItemAttemptPhase.PUBLICATION,
            asset_codes,
        )
        if not publication_evidence_ready:
            return item_evidence_blocked_response()
        if not services.revalidate_authority(services.current_time()):
            outcome = TaskBusinessOutcome.BLOCKED
            result_stage = "authority"
            checkpoint = {
                **checkpoint,
                "next_offset": validated_offset,
                "complete": False,
            }
            succeeded_total = 0
            failed_total = len(batch_codes)
            errors.append(
                {
                    "domain": "authority",
                    "asset_code": "publication",
                    "error": "authority_changed_or_expired",
                }
            )
            if not finish_attempts(
                publication_attempts,
                state=SyncItemAttemptState.BLOCKED,
                error_code="authority_changed_or_expired",
            ):
                return item_evidence_blocked_response()
        else:
            try:
                rebuild_result = services.rebuild_current_publications(
                    asset_codes=asset_codes,
                    published_at=services.current_time(),
                )
                rebuild_published_count = services.published_count_from_result(rebuild_result)
                publication_evidence_hash = services.publication_evidence_hash(
                    rebuild_result,
                    len(asset_codes),
                )
                published_total += rebuild_published_count
                if not finish_attempts(
                    publication_attempts,
                    state=SyncItemAttemptState.SUCCEEDED,
                    stored_count=1,
                    evidence_hash=publication_evidence_hash,
                ):
                    return item_evidence_blocked_response()
            except Exception:
                outcome = TaskBusinessOutcome.BLOCKED
                result_stage = "publication"
                checkpoint = {
                    **checkpoint,
                    "next_offset": validated_offset,
                    "complete": False,
                }
                succeeded_total = 0
                failed_total = len(batch_codes)
                errors.append(
                    {
                        "domain": "publication",
                        "asset_code": "universe",
                        "error": "rebuild_failed",
                    }
                )
                if not finish_attempts(
                    publication_attempts,
                    state=SyncItemAttemptState.FAILED,
                    error_code="rebuild_failed",
                ):
                    return item_evidence_blocked_response()

    services.persist_control_plane(
        idempotency_key=idempotency_key,
        provider_name=normalized_source,
        outcome=outcome,
        requested=len(batch_codes),
        succeeded=succeeded_total,
        failed=failed_total,
        stored=stored_total,
        published=published_total,
        checkpoint=checkpoint,
        window_start=start_date,
        window_end=end_date,
        started_at=started_at,
        error_code=(
            "zero_output"
            if outcome is TaskBusinessOutcome.FAILED and stored_total == 0
            else (
                "partial_failure"
                if outcome is TaskBusinessOutcome.PARTIAL
                else (
                    "authority_changed_or_expired"
                    if outcome is TaskBusinessOutcome.BLOCKED and result_stage == "authority"
                    else (
                        "current_publication_rebuild_failed"
                        if outcome is TaskBusinessOutcome.BLOCKED
                        else ""
                    )
                )
            )
        ),
        error_message=(errors[0]["error"] if errors else ""),
    )
    return {
        "success": outcome not in {TaskBusinessOutcome.FAILED, TaskBusinessOutcome.BLOCKED},
        "outcome": outcome.value,
        "stage": result_stage,
        "source": normalized_source,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "asset_codes": batch_codes,
        "requested": len(batch_codes),
        "succeeded": succeeded_total,
        "failed": failed_total,
        "stored": stored_total,
        "published": published_total,
        "domains": domain_counts,
        "errors": errors,
        "checkpoint": checkpoint,
    }
