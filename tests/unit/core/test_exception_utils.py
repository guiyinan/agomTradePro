"""Behavioral tests for the typed core exception utilities."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from core.exception_utils import (
    ExceptionRecorder,
    exception_context,
    handle_external_service_errors,
    handle_repository_errors,
    retry_on_exception,
    safe_execute,
    validate_and_execute,
)
from core.exceptions import DataFetchError, ExternalServiceError, InvalidInputError


def test_external_service_decorator_returns_configured_default() -> None:
    @handle_external_service_errors("quotes", default_value=[])
    def load_quotes() -> list[str]:
        raise OSError("offline")

    assert load_quotes() == []


def test_external_service_decorator_can_raise_normalized_error() -> None:
    @handle_external_service_errors("quotes", raise_on_error=True)
    def load_quotes() -> list[str]:
        raise OSError("offline")

    with pytest.raises(ExternalServiceError, match="quotes error"):
        load_quotes()


def test_repository_decorator_distinguishes_not_found_from_fetch_failure() -> None:
    @handle_repository_errors("positions", default_value=None)
    def missing_position() -> object | None:
        raise LookupError("not found")

    @handle_repository_errors("positions")
    def failed_position() -> object | None:
        raise RuntimeError("database offline")

    assert missing_position() is None
    with pytest.raises(DataFetchError, match="positions"):
        failed_position()


def test_exception_context_suppresses_or_normalizes_as_configured() -> None:
    with exception_context("optional", "tests"):
        raise ValueError("ignored")

    with pytest.raises(DataFetchError, match="broken"):
        with exception_context("required", "tests", reraise=DataFetchError):
            raise ValueError("broken")


def test_safe_execute_returns_default_for_selected_exception() -> None:
    assert safe_execute(lambda: 1 / 0, default_value=4, log_error=False) == 4


def test_validate_and_execute_preserves_signature_and_exception_type() -> None:
    @validate_and_execute(
        validator=lambda value: value > 0,
        error_message="positive value required",
        exception_type=InvalidInputError,
    )
    def double(value: int) -> int:
        return value * 2

    assert double(3) == 6
    with pytest.raises(InvalidInputError, match="positive value required"):
        double(0)


def test_exception_recorder_tracks_and_does_not_suppress() -> None:
    recorder = ExceptionRecorder("test", "tests")

    with pytest.raises(ValueError, match="boom"):
        with recorder:
            raise ValueError("boom")

    assert recorder.exception_occurred is True
    assert recorder.exception_type == "ValueError"


def test_retry_decorator_calls_callback_before_success() -> None:
    attempts = 0
    retries: list[tuple[int, str]] = []

    @retry_on_exception(
        max_retries=2,
        backoff_factor=0,
        exception_types=(ExternalServiceError,),
        on_retry=lambda attempt, exc: retries.append((attempt, str(exc))),
    )
    def eventually_succeeds() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise ExternalServiceError("temporary")
        return "ok"

    with patch("time.sleep"):
        assert eventually_succeeds() == "ok"

    assert retries == [(1, "temporary")]
