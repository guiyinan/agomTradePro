"""Security and finite-value checks for shared core runtime boundaries."""

from __future__ import annotations

import logging

import pytest
from django.http import HttpResponse
from django.test import RequestFactory

from core.log_buffer import append_record, get_entries
from core.management.commands.healthcheck import _public_checks
from core.middleware.logging import RequestLoggingMiddleware, TraceIDMiddleware
from core.templatetags.alert_tags import render_alerts
from core.templatetags.factor_tags import add, divide, subtract


def test_alert_renderer_escapes_content_and_rejects_active_urls() -> None:
    """Alert content must not cross the template boundary as executable HTML."""

    rendered = str(
        render_alerts(
            [
                {
                    "type": 'danger" onclick="alert(1)',
                    "title": "<script>alert(1)</script>",
                    "message": '<img src=x onerror="alert(2)">',
                    "action_url": "javascript:alert(3)",
                    "action_text": "Open",
                }
            ]
        )
    )

    assert "<script>" not in rendered
    assert "<img" not in rendered
    assert "javascript:" not in rendered
    assert "alert-info" in rendered


@pytest.mark.parametrize("operation", [add, subtract, divide])
def test_factor_numeric_filters_reject_non_finite_values(operation) -> None:
    """Template arithmetic must not emit NaN or infinity into HTML attributes."""

    result = operation("nan", "2")

    assert result != float("nan")
    assert str(result).lower() not in {"nan", "inf", "-inf"}


def test_log_buffer_redacts_credentials_before_retention() -> None:
    """The administrator log buffer must not persist credential-bearing text."""

    record = logging.LogRecord("core.test", logging.ERROR, __file__, 1, "failure", (), None)
    sequence = append_record(
        record,
        "postgresql://user:secret@internal/db token=raw-token",
    )

    entries, _ = get_entries(since_id=sequence - 1, limit=1)

    assert entries[-1]["message"] == ("postgresql://<redacted>@internal/db token=<redacted>")


def test_request_middleware_does_not_log_invalid_trace_or_exception_body(caplog) -> None:
    """Untrusted headers and exception messages must not be copied into request logs."""

    request = RequestFactory().get(
        "/api/example/",
        HTTP_X_TRACE_ID="postgresql://user:secret@internal/db",
    )
    trace_middleware = TraceIDMiddleware(lambda _: HttpResponse())

    with caplog.at_level(logging.WARNING, logger="core.middleware.logging"):
        trace_middleware(request)

    def fail(_: object) -> HttpResponse:
        raise RuntimeError("redis://user:secret@internal/0")

    with pytest.raises(RuntimeError):
        with caplog.at_level(logging.ERROR, logger="core.middleware.logging"):
            RequestLoggingMiddleware(fail)(request)

    assert "secret" not in caplog.text
    assert "RuntimeError" in caplog.text


def test_healthcheck_public_payload_drops_exception_details() -> None:
    """Health command output exposes status evidence but not backend error text."""

    public = _public_checks(
        {
            "database": {
                "status": "error",
                "error": "postgresql://user:secret@internal/db",
            }
        }
    )

    assert public == {"database": {"status": "error"}}
