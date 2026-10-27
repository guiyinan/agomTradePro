"""Capture one exact Tushare daily price bar with its original response bytes."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Protocol, cast

from apps.data_center.application.price_response_capture import (
    CapturedPriceBarResponse,
    ExactPriceBarRequestScope,
    _safe_decimal,
    normalize_exact_tushare_price_bar,
)
from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.domain.provider_response import ProviderResponseCapture
from apps.data_center.domain.rules import normalize_asset_code
from apps.data_center.infrastructure.tushare_client import (
    TushareResponseEvidence,
    _validated_provider_code,
    _validated_provider_table,
    create_tushare_pro_client,
)
from core.exceptions import TushareError

_REQUIRED_FIELDS = frozenset(
    {"ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"}
)


class _DailyFrame(Protocol):
    """Minimal Tushare dataframe surface consumed by this exact request."""

    empty: bool

    def to_dict(self, orient: str) -> list[dict[str, object]]:
        """Return records materialized from the captured provider response."""


class _ExactDailyClient(Protocol):
    """Single Tushare method needed for exact daily bar capture."""

    def daily(self, *, ts_code: str, trade_date: str) -> _DailyFrame | None:
        """Fetch one stock's daily bar for one exact trade date."""


def fetch_exact_tushare_price_bar(
    config: ProviderConfig,
    *,
    asset_code: str,
    target_trade_date: date,
    deployment_region: str,
    request_mode: str | None,
) -> CapturedPriceBarResponse:
    """Fetch and validate exactly one daily bar from the configured Tushare route.

    The raw response body is the source of parsed values. The returned
    ``fetched_at`` is only the local response completion time; the bar date
    remains the provider's historical trade date.
    """

    provider_id = config.id
    if isinstance(provider_id, bool) or not isinstance(provider_id, int) or provider_id < 1:
        raise TushareError(
            "Exact Tushare price capture requires configured provider identity",
            code="TUSHARE_EXACT_PRICE_REQUEST_INVALID",
        )
    canonical_code = normalize_asset_code(asset_code, "tushare")
    if canonical_code is None or canonical_code != asset_code:
        raise TushareError(
            "Exact Tushare price request requires one canonical asset code",
            code="TUSHARE_EXACT_PRICE_REQUEST_INVALID",
        )
    try:
        scope = ExactPriceBarRequestScope(
            provider_id=provider_id,
            provider_name=config.name,
            dataset_key="equity.price.bar",
            api_name="daily",
            asset_code=canonical_code,
            trade_date=target_trade_date,
        )
    except (TypeError, ValueError) as exc:
        raise TushareError(
            "Exact Tushare price request scope is invalid",
            code="TUSHARE_EXACT_PRICE_REQUEST_INVALID",
        ) from exc

    client = cast(
        _ExactDailyClient,
        create_tushare_pro_client(
            token=config.api_key,
            http_url=config.http_url,
            request_mode=request_mode,
            provider_id=provider_id,
            deployment_region=deployment_region,
            dataset_key=scope.dataset_key,
            capture_provider_responses=True,
        ),
    )
    compact_date = scope.trade_date.strftime("%Y%m%d")
    frame = client.daily(ts_code=scope.asset_code, trade_date=compact_date)
    if frame is None or frame.empty:
        raise TushareError(
            "Exact Tushare daily price response is empty",
            code="TUSHARE_EXACT_PRICE_RESPONSE_MISMATCH",
        )
    frame_rows = frame.to_dict("records")
    evidence = getattr(frame, "response_evidence", None)
    if not isinstance(evidence, TushareResponseEvidence):
        raise TushareError(
            "Exact Tushare daily price response capture is unavailable",
            code="TUSHARE_PROVIDER_RESPONSE_CAPTURE_UNAVAILABLE",
        )
    capture = evidence.response_capture
    if not isinstance(capture, ProviderResponseCapture) or not capture.payload_matches_body():
        raise TushareError(
            "Exact Tushare daily price bytes do not match the returned payload",
            code="TUSHARE_PROVIDER_RESPONSE_CAPTURE_INVALID",
        )
    payload = capture.payload_from_body()
    if not isinstance(payload, dict) or _validated_provider_code(payload) != 0:
        raise TushareError(
            "Exact Tushare daily price provider envelope is invalid",
            code="TUSHARE_PROVIDER_REJECTED",
        )
    data = payload.get("data")
    if not isinstance(data, dict):
        raise TushareError(
            "Exact Tushare daily price table is missing",
            code="TUSHARE_PROVIDER_RESPONSE_CAPTURE_INVALID",
        )
    columns, items = _validated_provider_table(
        data,
        api_name="daily",
        params={"ts_code": scope.asset_code, "trade_date": compact_date},
    )
    if not _REQUIRED_FIELDS.issubset(columns):
        raise TushareError(
            "Exact Tushare daily price fields are incomplete",
            code="TUSHARE_EXACT_PRICE_RESPONSE_MISMATCH",
        )
    body_rows = [dict(zip(columns, cast(list[object], item), strict=True)) for item in items]
    if (
        len(frame_rows) != 1
        or len(body_rows) != 1
        or not _same_requested_identity(frame_rows[0], scope)
        or not _same_requested_identity(body_rows[0], scope)
        or not _same_row_values(frame_rows[0], body_rows[0])
    ):
        raise TushareError(
            "Tushare returned rows outside the exact daily price request scope",
            code="TUSHARE_EXACT_PRICE_RESPONSE_MISMATCH",
        )

    bar = normalize_exact_tushare_price_bar(
        body_rows[0],
        scope=scope,
        source=(str(config.source_type or "").strip() or config.name),
        fetched_at=capture.response_completed_at,
    )
    return CapturedPriceBarResponse(
        request_scope=scope,
        bar=bar,
        capture=capture,
        sensitive_values=evidence.sensitive_values,
    )


def _same_requested_identity(row: Mapping[str, object], scope: ExactPriceBarRequestScope) -> bool:
    """Check exact provider identity without accepting date or code coercions."""

    return row.get("ts_code") == scope.asset_code and row.get(
        "trade_date"
    ) == scope.trade_date.strftime("%Y%m%d")


def _same_row_values(frame_row: Mapping[str, object], body_row: Mapping[str, object]) -> bool:
    """Require every SDK row value to agree with the captured raw response."""

    if frame_row.keys() != body_row.keys():
        return False
    for field, body_value in body_row.items():
        frame_value = frame_row[field]
        if isinstance(frame_value, bool) or isinstance(body_value, bool):
            if type(frame_value) is not type(body_value) or frame_value != body_value:
                return False
            continue
        frame_numeric = _safe_decimal(frame_value)
        body_numeric = _safe_decimal(body_value)
        if frame_numeric is not None or body_numeric is not None:
            if frame_numeric is None or body_numeric is None or frame_numeric != body_numeric:
                return False
            continue
        if type(frame_value) is not type(body_value) or frame_value != body_value:
            return False
    return True


__all__ = ["fetch_exact_tushare_price_bar"]
