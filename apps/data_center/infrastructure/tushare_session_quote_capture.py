"""Infrastructure composition for one captured full-market Tushare quote session."""

from __future__ import annotations

from datetime import date

from apps.data_center.application.quote_session_capture import (
    CapturedQuoteSessionResponse,
    QuoteSessionRequestScope,
)
from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.domain.entities import QuoteSnapshot as DomainQuoteSnapshot
from apps.data_center.domain.market_time import cn_market_session_close_utc
from apps.data_center.infrastructure.gateways.tushare_gateway import TushareGateway
from apps.data_center.infrastructure.market_gateway_entities import QuoteSnapshot
from apps.data_center.infrastructure.tushare_exact_quote_capture import (
    domain_quote_from_tushare_gateway,
)
from apps.data_center.infrastructure.tushare_response_capture_support import (
    TushareResponseEvidence,
)
from core.exceptions import TushareError


def fetch_tushare_quote_session_with_capture(
    config: ProviderConfig,
    *,
    asset_codes: list[str],
    target_trade_date: date,
    deployment_region: str,
    request_mode: str | None,
) -> CapturedQuoteSessionResponse:
    """Fetch one full-market daily table and map quotes from its exact body bytes."""

    provider_id = config.id
    if isinstance(provider_id, bool) or not isinstance(provider_id, int) or provider_id <= 0:
        raise TushareError(
            "Configured Tushare provider identity is missing",
            code="TUSHARE_SESSION_QUOTE_REQUEST_INVALID",
        )
    provider_name = config.name
    provider_source = str(config.source_type or "").strip() or provider_name
    try:
        scope = QuoteSessionRequestScope(
            provider_id=provider_id,
            provider_name=provider_name,
            dataset_key="equity.quote.snapshot",
            api_name="daily",
            asset_codes=tuple(asset_codes),
            target_trade_date=target_trade_date,
        )
    except (TypeError, ValueError) as error:
        raise TushareError(
            "Tushare session quote request scope is invalid",
            code="TUSHARE_SESSION_QUOTE_REQUEST_INVALID",
        ) from error
    gateway = TushareGateway(
        token=config.api_key,
        http_url=config.http_url,
        request_mode=request_mode,
        source_name=provider_name,
        provider_id=provider_id,
        deployment_region=deployment_region,
        dataset_key=scope.dataset_key,
    )
    gateway_quotes, evidence = gateway.get_quote_snapshots_for_session_with_capture(
        list(scope.asset_codes),
        scope.target_trade_date,
    )
    if not isinstance(evidence, TushareResponseEvidence) or evidence.response_capture is None:
        raise TushareError(
            "Tushare full-session response capture is unavailable",
            code="TUSHARE_PROVIDER_RESPONSE_CAPTURE_UNAVAILABLE",
        )
    capture = evidence.response_capture
    mapped_quotes: list[DomainQuoteSnapshot] = []
    requested_codes = set(scope.asset_codes)
    for quote in gateway_quotes:
        if not isinstance(quote, QuoteSnapshot):
            raise TushareError(
                "Tushare full-session returned an invalid quote type",
                code="TUSHARE_SESSION_QUOTE_RESPONSE_MISMATCH",
            )
        if (
            quote.stock_code not in requested_codes
            or quote.fetched_at != capture.response_completed_at
            or quote.observed_at != cn_market_session_close_utc(scope.target_trade_date)
            or quote.extra.get("raw_payload_hash") != capture.body_sha256
            or quote.extra.get("raw_payload_scope") != "batch_response_body"
        ):
            raise TushareError(
                "Tushare full-session quote is detached from its response bytes",
                code="TUSHARE_SESSION_QUOTE_RESPONSE_MISMATCH",
            )
        domain_quote = domain_quote_from_tushare_gateway(
            quote,
            provider_name=provider_name,
            provider_source=provider_source,
        )
        if domain_quote is None or domain_quote.asset_code not in requested_codes:
            raise TushareError(
                "Tushare full-session quote could not be normalized",
                code="TUSHARE_SESSION_QUOTE_RESPONSE_MISMATCH",
            )
        mapped_quotes.append(domain_quote)
    return CapturedQuoteSessionResponse(
        request_scope=scope,
        quotes=tuple(mapped_quotes),
        capture=capture,
        sensitive_values=evidence.sensitive_values,
    )


__all__ = ["fetch_tushare_quote_session_with_capture"]
