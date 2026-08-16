"""Application orchestration for resumable A-share core-data backfills."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Protocol

from shared.domain.task_outcomes import TaskBusinessOutcome

from .current_valuation_sync import SyncCurrentValuationBatchUseCase
from .dtos import SyncFinancialRequest, SyncPriceRequest, SyncQuoteRequest, SyncResult
from .sync_use_cases import SyncFinancialUseCase, SyncPriceUseCase, SyncQuoteUseCase


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
    published_count_from_result: Callable[[object], int]
    persist_control_plane: PersistBackfillControlPlane


def run_active_a_share_core_data_backfill_batch(
    *,
    validated_offset: int,
    validated_batch_size: int,
    normalized_source: str,
    validated_history_days: int,
    validated_periods: int,
    idempotency_key: str,
    started_at: datetime,
    services: CoreDataBackfillServices,
) -> dict[str, Any]:
    """Run one validated, resumable active-A-share core-data batch."""

    asset_codes = services.list_active_stock_codes()
    total_assets = len(asset_codes)
    batch_codes = asset_codes[validated_offset : validated_offset + validated_batch_size]
    next_offset = validated_offset + len(batch_codes)
    checkpoint = {
        "offset": validated_offset,
        "next_offset": next_offset,
        "total_assets": total_assets,
        "complete": next_offset >= total_assets,
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

    domain_counts: dict[str, dict[str, int]] = {
        name: {
            "requested": len(batch_codes),
            "succeeded": 0,
            "failed": 0,
            "stored": 0,
        }
        for name in ("quote", "price", "valuation", "financial")
    }
    published_total = 0
    errors: list[dict[str, str]] = []
    failed_asset_codes: set[str] = set()
    try:
        quote_result = quote_use_case.execute(
            SyncQuoteRequest(provider_id=provider_id, asset_codes=batch_codes)
        )
        published_total += services.published_count_from_result(quote_result)
        quote_stored = int(quote_result.stored_count)
        domain_counts["quote"]["stored"] = quote_stored
        domain_counts["quote"]["succeeded"] = min(quote_stored, len(batch_codes))
        domain_counts["quote"]["failed"] = max(len(batch_codes) - quote_stored, 0)
    except Exception:
        domain_counts["quote"]["failed"] = len(batch_codes)
        errors.append({"domain": "quote", "asset_code": "batch", "error": "sync_failed"})

    try:
        valuation_result = valuation_batch_use_case.execute(
            provider_id=provider_id,
            asset_codes=batch_codes,
            as_of_date=end_date,
        )
        published_total += services.published_count_from_result(valuation_result)
        valuation_succeeded = set(valuation_result.succeeded_asset_codes)
        valuation_missing = set(batch_codes) - valuation_succeeded
        domain_counts["valuation"]["stored"] = int(valuation_result.stored_count)
        domain_counts["valuation"]["succeeded"] = len(valuation_succeeded)
        domain_counts["valuation"]["failed"] = len(valuation_missing)
        failed_asset_codes.update(valuation_missing)
        for asset_code in sorted(valuation_missing)[:20]:
            errors.append({"domain": "valuation", "asset_code": asset_code, "error": "zero_output"})
    except Exception:
        domain_counts["valuation"]["failed"] = len(batch_codes)
        failed_asset_codes.update(batch_codes)
        errors.append({"domain": "valuation", "asset_code": "batch", "error": "sync_failed"})

    for asset_code in batch_codes:
        domain_names = ("price", "financial")
        for domain_name in domain_names:
            try:
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
                    result = financial_use_case.execute(
                        SyncFinancialRequest(
                            provider_id=provider_id,
                            asset_code=asset_code,
                            periods=validated_periods,
                        )
                    )
                published_total += services.published_count_from_result(result)
                stored_count = int(result.stored_count)
                domain_counts[domain_name]["stored"] += stored_count
                if stored_count > 0:
                    domain_counts[domain_name]["succeeded"] += 1
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
            else ("partial_failure" if outcome is TaskBusinessOutcome.PARTIAL else "")
        ),
        error_message=(errors[0]["error"] if errors else ""),
    )
    return {
        "success": outcome not in {TaskBusinessOutcome.FAILED, TaskBusinessOutcome.BLOCKED},
        "outcome": outcome.value,
        "stage": "batch",
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
