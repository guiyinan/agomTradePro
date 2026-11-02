"""Counterexamples for retained Sina response identity and parse integrity."""

from __future__ import annotations

import base64
from hashlib import sha256

import pytest

from apps.data_center.domain.sina_quote_capture import SinaQuoteCapture
from tests.unit.data_center.test_sina_quote_capture import _response, _sina_body


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    [
        ("asset_code", "000001.SZ"),
        ("requested_url", "https://hq.sinajs.cn/list=sz000001"),
        ("final_url", "https://example.invalid/quote"),
        ("content_type", "text/plain"),
        ("content_encoding", "gzip"),
    ],
)
def test_capture_rejects_envelope_references_that_no_longer_parse_the_retained_row(
    field_name: str,
    replacement: str,
) -> None:
    capture = _response()
    payload: dict[str, object] = dict(capture.to_payload())
    payload[field_name] = replacement

    with pytest.raises(ValueError):
        SinaQuoteCapture.from_payload(payload)


def test_capture_rejects_rehashed_body_that_belongs_to_another_security() -> None:
    capture = _response()
    payload = capture.to_payload()
    changed_body = _sina_body(symbol="sz000001")
    payload["body_base64"] = base64.b64encode(changed_body).decode("ascii")
    payload["body_size_bytes"] = len(changed_body)
    payload["body_sha256"] = sha256(changed_body).hexdigest()

    with pytest.raises(ValueError, match="parsed source body"):
        SinaQuoteCapture.from_payload(payload)
