"""Bounded public Sina quote transport that preserves response-body bytes."""

from __future__ import annotations

import re
from datetime import UTC, datetime

import requests

from apps.data_center.domain.sina_quote_capture import (
    MAX_SINA_QUOTE_RESPONSE_BYTES,
    SinaQuoteCapture,
    build_sina_quote_request_url,
    parse_sina_quote_capture,
)
from core.exceptions import DataFetchError

_HTTP_TIMEOUT_SECONDS = 5.0
_READ_CHUNK_BYTES = 8192
_CHARSET_RE = re.compile(
    r"(?:^|;)\s*charset\s*=\s*(?:\"([^\"]+)\"|'([^']+)'|([^;\s]+))", re.IGNORECASE
)


class SinaQuoteHTTPGateway:
    """Read a single unauthenticated Sina response without retry or fallback."""

    def fetch_quote_capture(self, asset_code: str) -> SinaQuoteCapture:
        """Return exact source bytes, source quote, and independent receipt clocks."""

        requested_url = build_sina_quote_request_url(asset_code)
        request_started_at = datetime.now(UTC)
        try:
            response = requests.get(
                requested_url,
                headers={
                    "Accept": "application/javascript,text/javascript,*/*;q=0.1",
                    "Accept-Encoding": "identity",
                    "User-Agent": "AgomTradePro public quote reader",
                    "Referer": (
                        "https://finance.sina.com.cn/realstock/company/"
                        + requested_url.rsplit("=", 1)[1]
                        + "/nc.shtml"
                    ),
                },
                timeout=_HTTP_TIMEOUT_SECONDS,
                stream=True,
            )
        except requests.RequestException as error:
            raise DataFetchError(
                "Sina quote request failed", code="SINA_QUOTE_FETCH_FAILED"
            ) from error

        try:
            body = _read_bounded_body(response)
            response_completed_at = datetime.now(UTC)
            content_type = response.headers.get("Content-Type")
            return parse_sina_quote_capture(
                asset_code=asset_code,
                requested_url=requested_url,
                final_url=response.url,
                request_started_at=request_started_at,
                response_completed_at=response_completed_at,
                http_status=response.status_code,
                http_date=response.headers.get("Date"),
                content_type=content_type,
                charset=_charset_from_content_type(content_type),
                content_encoding=response.headers.get("Content-Encoding"),
                body=body,
            )
        except requests.RequestException as error:
            raise DataFetchError(
                "Sina quote response could not be read", code="SINA_QUOTE_READ_FAILED"
            ) from error
        finally:
            response.close()


def _read_bounded_body(response: requests.Response) -> bytes:
    """Read the HTTP entity body while preserving content-encoded bytes."""

    response.raw.decode_content = False
    body = bytearray()
    try:
        for chunk in response.raw.stream(_READ_CHUNK_BYTES, decode_content=False):
            if not chunk:
                continue
            if len(body) + len(chunk) > MAX_SINA_QUOTE_RESPONSE_BYTES:
                raise DataFetchError(
                    "Sina quote response exceeds its byte bound",
                    code="SINA_QUOTE_RESPONSE_TOO_LARGE",
                )
            body.extend(chunk)
    except DataFetchError:
        raise
    except requests.RequestException:
        raise
    return bytes(body)


def _charset_from_content_type(content_type: str | None) -> str | None:
    """Extract the declared charset without applying a default encoding."""

    if content_type is None:
        return None
    matched = _CHARSET_RE.search(content_type)
    if matched is None:
        return None
    return next((value.strip() for value in matched.groups() if value is not None), None)


__all__ = ("SinaQuoteHTTPGateway",)
