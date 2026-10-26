"""Infrastructure helpers for one exact Tushare quote and its raw response."""

from __future__ import annotations

from datetime import date, datetime

from apps.data_center.application.quote_response_capture import (
    CapturedQuoteSnapshotResponse,
    ExactQuoteRequestScope,
)
from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.domain.entities import QuoteSnapshot as DomainQuoteSnapshot
from apps.data_center.domain.rules import normalize_asset_code
from apps.data_center.infrastructure._provider_adapter_base import _ensure_aware
from apps.data_center.infrastructure.gateways.tushare_gateway import TushareGateway
from apps.data_center.infrastructure.market_gateway_entities import QuoteSnapshot
from apps.data_center.infrastructure.provider_quote_snapshot_mapping import (
    optional_quote_change_pct_candidate,
    optional_quote_source_extra,
    quote_source,
)
from apps.data_center.infrastructure.tushare_quote_transport import (
    _optional_quote_transport_extra,
)
from apps.data_center.infrastructure.tushare_replay_parser import (
    _optional_nonnegative_float,
)
from shared.numeric import safe_float


def domain_quote_from_tushare_gateway(
    quote: QuoteSnapshot,
    *,
    provider_name: str,
    provider_source: str,
) -> DomainQuoteSnapshot | None:
    """Map a validated gateway quote to the canonical Data Center fact."""

    current_price = safe_float(quote.price)
    observed_at = getattr(quote, "observed_at", None)
    fetched_at = getattr(quote, "fetched_at", None)
    if (
        current_price is None
        or current_price <= 0
        or not isinstance(observed_at, datetime)
        or not isinstance(fetched_at, datetime)
    ):
        return None
    extra = {
        **_optional_quote_transport_extra(quote),
        **optional_quote_source_extra(quote),
    }
    extra.setdefault("provider_name", provider_name)
    extra["source_type"] = provider_source
    return DomainQuoteSnapshot(
        asset_code=normalize_asset_code(quote.stock_code, "tushare"),
        snapshot_at=_ensure_aware(observed_at),
        fetched_at=_ensure_aware(fetched_at),
        current_price=current_price,
        source=provider_source,
        open=safe_float(quote.open),
        high=safe_float(quote.high),
        low=safe_float(quote.low),
        prev_close=safe_float(quote.pre_close),
        volume=_optional_nonnegative_float(quote.volume),
        amount=_optional_nonnegative_float(quote.amount),
        change_pct_candidate=optional_quote_change_pct_candidate(
            quote, provider_source=quote_source(quote, provider_source)
        ),
        extra=extra,
    )


def fetch_exact_tushare_quote_snapshot(
    config: ProviderConfig,
    *,
    asset_code: str,
    target_trade_date: date,
    deployment_region: str,
    request_mode: str | None,
) -> CapturedQuoteSnapshotResponse:
    """Fetch one scoped daily quote before any identity transaction is opened."""

    provider_id = config.id
    if provider_id is None:
        raise ValueError("Configured Tushare provider identity is missing")
    provider_name = config.name
    provider_source = str(config.source_type or "").strip() or provider_name
    scope = ExactQuoteRequestScope(
        provider_id=provider_id,
        provider_name=provider_name,
        dataset_key="equity.quote.snapshot",
        api_name="daily",
        asset_code=asset_code,
        trade_date=target_trade_date,
    )
    gateway = TushareGateway(
        token=config.api_key,
        http_url=config.http_url,
        request_mode=request_mode,
        source_name=provider_name,
        provider_id=provider_id,
        deployment_region=deployment_region,
        dataset_key=scope.dataset_key,
        capture_provider_responses=True,
    )
    gateway_quote, evidence = gateway.get_quote_snapshot_with_capture(
        scope.asset_code,
        scope.trade_date,
    )
    capture = evidence.response_capture
    if capture is None:
        raise ValueError("Exact Tushare quote response capture is missing")
    domain_quote = domain_quote_from_tushare_gateway(
        gateway_quote,
        provider_name=provider_name,
        provider_source=provider_source,
    )
    if domain_quote is None or domain_quote.asset_code != scope.asset_code:
        raise ValueError("Exact Tushare quote did not match its requested asset")
    return CapturedQuoteSnapshotResponse(
        request_scope=scope,
        quote=domain_quote,
        capture=capture,
        sensitive_values=evidence.sensitive_values,
    )


__all__ = [
    "domain_quote_from_tushare_gateway",
    "fetch_exact_tushare_quote_snapshot",
]
