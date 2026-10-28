"""Capture one exact Tushare ``stk_limit`` response with its original bytes."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Protocol, cast

from apps.data_center.application.price_limit_response_capture import (
    _FIELDS,
    CapturedPriceLimitResponse,
    ExactPriceLimitRequestScope,
    extract_exact_tushare_price_limit_values,
    validate_exact_price_limit_capture,
)
from apps.data_center.application.price_response_capture import _safe_decimal
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

_REQUIRED_FIELDS = frozenset({"ts_code", "trade_date", "down_limit", "up_limit"})


class _LimitFrame(Protocol):
    """Minimal SDK frame surface required for a captured limit query."""

    empty: bool

    def to_dict(self, orient: str) -> list[dict[str, object]]:
        """Return the table rows in record orientation."""
        ...


class _ExactPriceLimitClient(Protocol):
    """Single Tushare method used for exact per-security daily limits."""

    def stk_limit(
        self,
        *,
        ts_code: str,
        trade_date: str,
        fields: str,
    ) -> _LimitFrame | None:
        """Fetch one security's price-limit row for one exact trading day."""
        ...


def _same_requested_identity(
    row: Mapping[str, object],
    *,
    scope: ExactPriceLimitRequestScope,
) -> bool:
    """Require exact, non-coerced code and date identities on a provider row."""

    return row.get("ts_code") == scope.asset_code and row.get(
        "trade_date"
    ) == scope.trade_date.strftime("%Y%m%d")


def _same_row_values(
    frame_row: Mapping[str, object],
    body_row: Mapping[str, object],
) -> bool:
    """Require SDK-decoded values to agree with the exact source-body values."""

    if frame_row.keys() != body_row.keys():
        return False
    for field_name, body_value in body_row.items():
        frame_value = frame_row[field_name]
        if isinstance(frame_value, bool) or isinstance(body_value, bool):
            if type(frame_value) is not type(body_value) or frame_value != body_value:
                return False
            continue
        frame_decimal = _safe_decimal(frame_value)
        body_decimal = _safe_decimal(body_value)
        if frame_decimal is not None or body_decimal is not None:
            if frame_decimal is None or body_decimal is None or frame_decimal != body_decimal:
                return False
            continue
        if type(frame_value) is not type(body_value) or frame_value != body_value:
            return False
    return True


def fetch_exact_tushare_price_limit(
    config: ProviderConfig,
    *,
    asset_code: str,
    target_trade_date: date,
    deployment_region: str,
    request_mode: str | None,
) -> CapturedPriceLimitResponse:
    """Fetch and validate one exact ``stk_limit`` row through the configured route.

    Normalized values come from the original strict JSON body, never from the
    SDK's dataframe. The SDK row is only an additional equality check. The
    capture completion time is local body-acquisition time, not a provider
    publication or market-effective timestamp.
    """

    if type(config.is_active) is not bool or config.is_active is not True:
        raise TushareError(
            "Exact Tushare price-limit provider is inactive",
            code="TUSHARE_EXACT_PRICE_LIMIT_PROVIDER_INACTIVE",
        )
    provider_id = config.id
    if type(provider_id) is not int or provider_id < 1:
        raise TushareError(
            "Exact Tushare price-limit capture requires configured provider identity",
            code="TUSHARE_EXACT_PRICE_LIMIT_REQUEST_INVALID",
        )
    canonical_code = normalize_asset_code(asset_code, "tushare")
    if canonical_code is None or canonical_code != asset_code:
        raise TushareError(
            "Exact Tushare price-limit request requires one canonical security code",
            code="TUSHARE_EXACT_PRICE_LIMIT_REQUEST_INVALID",
        )
    if config.source_type.strip().casefold() != "tushare":
        raise TushareError(
            "Exact price-limit capture requires a Tushare provider",
            code="TUSHARE_EXACT_PRICE_LIMIT_REQUEST_INVALID",
        )
    try:
        scope = ExactPriceLimitRequestScope(
            provider_id=provider_id,
            provider_name=config.name,
            dataset_key="equity.price.limit",
            api_name="stk_limit",
            asset_code=canonical_code,
            trade_date=target_trade_date,
        )
    except (TypeError, ValueError) as error:
        raise TushareError(
            "Exact Tushare price-limit request scope is invalid",
            code="TUSHARE_EXACT_PRICE_LIMIT_REQUEST_INVALID",
        ) from error

    client = cast(
        _ExactPriceLimitClient,
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
    frame = client.stk_limit(
        ts_code=scope.asset_code,
        trade_date=compact_date,
        fields=_FIELDS,
    )
    if frame is None or frame.empty:
        raise TushareError(
            "Exact Tushare price-limit response is empty",
            code="TUSHARE_EXACT_PRICE_LIMIT_RESPONSE_MISMATCH",
        )
    frame_rows = frame.to_dict("records")
    evidence = getattr(frame, "response_evidence", None)
    if not isinstance(evidence, TushareResponseEvidence):
        raise TushareError(
            "Exact Tushare price-limit response capture is unavailable",
            code="TUSHARE_PROVIDER_RESPONSE_CAPTURE_UNAVAILABLE",
        )
    capture = evidence.response_capture
    if not isinstance(capture, ProviderResponseCapture) or not capture.payload_matches_body():
        raise TushareError(
            "Exact Tushare price-limit bytes do not match the returned payload",
            code="TUSHARE_PROVIDER_RESPONSE_CAPTURE_INVALID",
        )
    payload = capture.payload_from_body()
    if not isinstance(payload, dict) or _validated_provider_code(payload) != 0:
        raise TushareError(
            "Exact Tushare price-limit provider envelope is invalid",
            code="TUSHARE_PROVIDER_REJECTED",
        )
    data = payload.get("data")
    if not isinstance(data, dict):
        raise TushareError(
            "Exact Tushare price-limit table is missing",
            code="TUSHARE_PROVIDER_RESPONSE_CAPTURE_INVALID",
        )
    columns, items = _validated_provider_table(
        data,
        api_name=scope.api_name,
        params={"ts_code": scope.asset_code, "trade_date": compact_date},
    )
    if set(columns) != _REQUIRED_FIELDS:
        raise TushareError(
            "Exact Tushare price-limit fields do not match the request",
            code="TUSHARE_EXACT_PRICE_LIMIT_RESPONSE_MISMATCH",
        )
    body_rows = [dict(zip(columns, cast(list[object], item), strict=True)) for item in items]
    if (
        len(frame_rows) != 1
        or len(body_rows) != 1
        or not _same_requested_identity(frame_rows[0], scope=scope)
        or not _same_requested_identity(body_rows[0], scope=scope)
        or not _same_row_values(frame_rows[0], body_rows[0])
    ):
        raise TushareError(
            "Tushare returned rows outside the exact price-limit request scope",
            code="TUSHARE_EXACT_PRICE_LIMIT_RESPONSE_MISMATCH",
        )

    values = extract_exact_tushare_price_limit_values(payload, scope=scope)
    captured = CapturedPriceLimitResponse(
        request_scope=scope,
        values=values,
        capture=capture,
        sensitive_values=evidence.sensitive_values,
    )
    return validate_exact_price_limit_capture(captured, scope=scope)


__all__ = ["fetch_exact_tushare_price_limit"]
