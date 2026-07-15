"""Unit contracts for realtime WebSocket authentication."""

from apps.realtime.interface.websocket_auth import extract_formal_token


def test_extract_formal_token_accepts_only_authorization_header() -> None:
    assert extract_formal_token(
        [(b"authorization", b"Token secret-key")],
        b"",
    ) == ("secret-key", False)
    assert extract_formal_token(
        [(b"authorization", b"Bearer secret-key")],
        b"",
    ) == (None, False)


def test_extract_formal_token_rejects_query_string_credentials() -> None:
    assert extract_formal_token([], b"token=secret-key") == (None, True)
    assert extract_formal_token(
        [(b"authorization", b"Token header-key")],
        b"access_token=query-key",
    ) == (None, True)


def test_extract_formal_token_ignores_unrelated_query_parameters() -> None:
    assert extract_formal_token([], b"view=compact") == (None, False)
