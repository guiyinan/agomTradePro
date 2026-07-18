"""Unit coverage for the in-process Django SDK transport."""

from unittest.mock import Mock, patch

import pytest
from django.http import JsonResponse
from django.test import override_settings

from shared.infrastructure.django_sdk_transport import DjangoSdkTransport


def test_transport_encodes_multipart_files_and_form_fields():
    """Requests-style file tuples must become a bounded Django multipart body."""

    transport = DjangoSdkTransport()
    client = Mock()
    client.generic.return_value = JsonResponse({"ok": True})

    with patch.object(transport, "_build_client", return_value=client):
        response = transport.request(
            method="POST",
            url="http://testserver/api/account/broker-trades/preview/",
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            params=None,
            data={"portfolio_id": 7, "broker_name": "demo"},
            json=None,
            files={
                "file": (
                    "../broker_trades.csv",
                    b"traded_at,action,asset_code,shares,price\n",
                    "text/csv",
                )
            },
            timeout=30,
        )

    assert response.json() == {"ok": True}
    request = client.generic.call_args
    body = request.kwargs["data"]
    assert request.kwargs["content_type"].startswith("multipart/form-data; boundary=")
    assert b'name="portfolio_id"' in body
    assert b"7" in body
    assert b'name="broker_name"' in body
    assert b"demo" in body
    assert b'filename="broker_trades.csv"' in body
    assert b"../broker_trades.csv" not in body
    assert b"Content-Type: text/csv" in body
    assert b"traded_at,action,asset_code,shares,price" in body
    assert "Content-Type" not in request.kwargs["headers"]


@override_settings(FILE_UPLOAD_MAX_MEMORY_SIZE=4)
def test_transport_rejects_oversized_embedded_file():
    """The local transport must enforce Django's configured in-memory file bound."""

    with pytest.raises(ValueError, match="exceeds local multipart limit"):
        DjangoSdkTransport().request(
            method="POST",
            url="http://testserver/upload/",
            headers={},
            params=None,
            data=None,
            json=None,
            files={"file": ("large.csv", b"12345")},
            timeout=30,
        )


@override_settings(DATA_UPLOAD_MAX_NUMBER_FILES=1)
def test_transport_rejects_too_many_embedded_files():
    """The local path must enforce Django's configured upload file count."""

    with pytest.raises(ValueError, match="file count exceeds local limit"):
        DjangoSdkTransport().request(
            method="POST",
            url="http://testserver/upload/",
            headers={},
            params=None,
            data=None,
            json=None,
            files={
                "first": ("first.csv", b"a", "text/csv"),
                "second": ("second.csv", b"b", "text/csv"),
            },
            timeout=30,
        )
