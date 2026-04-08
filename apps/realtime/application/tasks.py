"""Celery tasks for realtime price polling."""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="apps.realtime.application.tasks.poll_realtime_prices_task",
    time_limit=600,
    soft_time_limit=570,
)
def poll_realtime_prices_task(asset_codes: list[str] | None = None) -> dict:
    """
    Poll realtime prices for monitored assets or fetch the latest snapshot for a subset.

    Args:
        asset_codes: Optional asset codes. When omitted or empty, poll the full
            watchlist and update cached/position prices.

    Returns:
        dict: Polling snapshot or fetched price payload.
    """
    from apps.realtime.application.price_polling_service import PricePollingUseCase

    use_case = PricePollingUseCase()
    requested_codes = [code for code in (asset_codes or []) if code]

    if requested_codes:
        logger.info("Polling realtime prices for %s requested assets", len(requested_codes))
        return {
            "success": True,
            "asset_codes": requested_codes,
            "prices": use_case.get_latest_prices(requested_codes),
        }

    logger.info("Polling realtime prices for the monitored watchlist")
    return use_case.execute_price_polling()
