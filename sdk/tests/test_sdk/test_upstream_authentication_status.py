"""Preserve actual HTTP status while retaining SDK exception compatibility."""

from typing import Any

import pytest

from agomtradepro.exceptions import (
    AgomTradeProAPIError,
    AuthenticationError,
    raise_for_status,
)


def test_authentication_error_default_status_remains_401() -> None:
    """Direct construction retains its historical default."""
    assert AuthenticationError().status_code == 401


def test_authentication_error_legacy_positional_response_stays_supported() -> None:
    """The two existing positional constructor arguments keep their meanings."""
    response: dict[str, Any] = {"detail": "Not authorized"}
    error = AuthenticationError("Legacy message", response)
    assert error.status_code == 401
    assert error.message == "Legacy message"
    assert error.response is response


@pytest.mark.parametrize("status", [401, 403])
def test_http_authentication_error_keeps_exact_upstream_status(status: int) -> None:
    """Shared authentication subclasses must retain the actual HTTP status."""
    response: dict[str, Any] = {"error": "MCP access disabled"}
    with pytest.raises(AuthenticationError) as caught:
        raise_for_status(status, response)
    assert caught.value.status_code == status
    assert caught.value.code == f"http_{status}"
    assert caught.value.message == response["error"]
    assert caught.value.response is response


@pytest.mark.parametrize("status", [400, 404, 409, 418, 429, 500, 503])
def test_other_http_errors_keep_status_code_and_response(status: int) -> None:
    """Preserving shared-class status does not alter other HTTP error receipts."""
    response: dict[str, Any] = {"code": "PUBLIC_DENIAL", "message": "Request rejected"}
    with pytest.raises(AgomTradeProAPIError) as caught:
        raise_for_status(status, response)
    assert caught.value.status_code == status
    assert caught.value.code == "public_denial"
    assert caught.value.response is response
