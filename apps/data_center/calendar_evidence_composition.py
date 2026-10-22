"""Read-only composition for source-bound exchange-calendar evidence."""

from __future__ import annotations

from apps.data_center.domain.model_market_data import TradingCalendarEvidencePort
from core.exceptions import DataFetchError


def build_calendar_evidence_port() -> TradingCalendarEvidencePort:
    """Compose configured calendar routes without building a price audit writer."""

    from apps.data_center.application.interface_services import load_provider_settings_payload
    from apps.data_center.composition import get_price_bar_repository, get_provider_registry
    from apps.data_center.infrastructure.model_market_wiring import build_model_market_service

    service = build_model_market_service(
        get_provider_registry(),
        get_price_bar_repository(),
        load_provider_settings_payload(),
        history_fetch_audit=None,
    )
    if not isinstance(service, TradingCalendarEvidencePort):
        raise DataFetchError(
            "Trading calendar evidence contract is unavailable",
            code="MODEL_MARKET_CALENDAR_EVIDENCE_UNAVAILABLE",
        )
    return service
