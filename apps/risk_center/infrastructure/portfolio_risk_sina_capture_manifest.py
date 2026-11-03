"""Rebuild exact Sina transport captures from immutable Risk manifests."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime

from apps.data_center.domain.sina_quote_capture import (
    SINA_QUOTE_SOURCE_ID,
    SinaQuoteCapture,
    parse_sina_quote_capture,
)
from apps.risk_center.domain.portfolio_risk_clock_evidence import PortfolioRiskCaptureReceipt

_SINA_CAPTURE_METADATA_KEYS: frozenset[str] = frozenset(
    {
        "asset_code",
        "requested_url",
        "final_url",
        "request_started_at",
        "response_completed_at",
        "http_status",
        "http_date",
        "content_type",
        "charset",
        "content_encoding",
    }
)


def rebuild_sina_quote_capture_from_manifest(
    value: object,
    *,
    asset_code: str,
    original_url: str | None,
    original_body: bytes,
    receipt: PortfolioRiskCaptureReceipt | None,
) -> SinaQuoteCapture:
    """Reparse pinned response bytes using only retained original transport metadata."""

    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise TypeError("sina_capture_metadata must be a string-keyed mapping")
    if set(value) != _SINA_CAPTURE_METADATA_KEYS:
        raise ValueError("sina_capture_metadata fields do not match the exact schema")
    if type(receipt) is not PortfolioRiskCaptureReceipt:
        raise ValueError("Sina capture metadata requires its verified transport receipt")
    if type(original_body) is not bytes or not original_body:
        raise TypeError("Sina capture requires exact nonempty original body bytes")
    metadata_asset = _required_token(value["asset_code"], "asset_code")
    requested_url = _required_string(value["requested_url"], "requested_url")
    final_url = _required_string(value["final_url"], "final_url")
    request_started_at = _aware_datetime(value["request_started_at"], "request_started_at")
    response_completed_at = _aware_datetime(value["response_completed_at"], "response_completed_at")
    http_status = value["http_status"]
    if type(http_status) is not int:
        raise TypeError("http_status must be an exact integer")
    if (
        metadata_asset != asset_code
        or original_url != requested_url
        or receipt.source_id != SINA_QUOTE_SOURCE_ID
        or receipt.response_completed_at != response_completed_at
        or receipt.http_status != http_status
        or receipt.body_size_bytes != len(original_body)
        or receipt.original_body_sha256 != _sha256(original_body)
    ):
        raise ValueError("Sina transport metadata differs from its pinned source receipt")
    capture = parse_sina_quote_capture(
        asset_code=metadata_asset,
        requested_url=requested_url,
        final_url=final_url,
        request_started_at=request_started_at,
        response_completed_at=response_completed_at,
        http_status=http_status,
        http_date=_optional_string(value["http_date"], "http_date"),
        content_type=_optional_string(value["content_type"], "content_type"),
        charset=_optional_string(value["charset"], "charset"),
        content_encoding=_optional_string(value["content_encoding"], "content_encoding"),
        body=original_body,
    )
    if (
        capture.body != original_body
        or capture.body_sha256 != receipt.original_body_sha256
        or capture.body_size_bytes != receipt.body_size_bytes
        or capture.http_status != receipt.http_status
        or capture.response_completed_at != receipt.response_completed_at
    ):
        raise ValueError("rebuilt Sina capture differs from its exact receipt")
    return capture


def _required_string(value: object, field_name: str) -> str:
    if type(value) is not str or not value:
        raise ValueError(f"{field_name} must be nonempty text")
    return value


def _required_token(value: object, field_name: str) -> str:
    text = _required_string(value, field_name)
    if text.strip() != text or any(character.isspace() for character in text):
        raise ValueError(f"{field_name} must be a canonical token")
    return text


def _optional_string(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        raise TypeError(f"{field_name} must be text or None")
    return value


def _aware_datetime(value: object, field_name: str) -> datetime:
    text = _required_string(value, field_name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must retain its timezone")
    return parsed


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


__all__ = ("rebuild_sina_quote_capture_from_manifest",)
