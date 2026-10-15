"""Secret-input and owner authentication contracts for the S6 authorization command."""

import io
from datetime import date
from types import SimpleNamespace

import pytest

from apps.data_center.management.commands import authorize_s6_financial_scope_discovery as command


def _stdin(raw: bytes) -> io.TextIOWrapper:
    return io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8")


def test_password_reader_accepts_one_bounded_line_without_echo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(command.sys, "stdin", _stdin(b"owner-password\n"))

    assert command._read_password_from_stdin() == "owner-password"


@pytest.mark.parametrize(
    "raw",
    [b"", b"owner-password", b"owner-password\r\n", b"one\ntwo\n", b"bad\x00value\n"],
)
def test_password_reader_rejects_ambiguous_or_multi_line_input(
    monkeypatch: pytest.MonkeyPatch,
    raw: bytes,
) -> None:
    monkeypatch.setattr(command.sys, "stdin", _stdin(raw))

    with pytest.raises(
        command._AuthorizationFailure,
        match="REHEARSAL_FINANCIAL_SCOPE_AUTHORIZATION_INPUT_INVALID",
    ):
        command._read_password_from_stdin()


def test_owner_authentication_requires_exact_active_superuser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        command,
        "get_user_model",
        lambda: SimpleNamespace(USERNAME_FIELD="username"),
    )
    monkeypatch.setattr(
        command,
        "authenticate",
        lambda **kwargs: SimpleNamespace(
            is_active=True,
            is_superuser=True,
            get_username=lambda: "admin",
        ),
    )

    owner = command._authenticate_owner(owner="admin", password="owner-password")

    assert owner.get_username() == "admin"


def test_owner_authentication_fails_closed_for_non_superuser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        command,
        "get_user_model",
        lambda: SimpleNamespace(USERNAME_FIELD="username"),
    )
    monkeypatch.setattr(
        command,
        "authenticate",
        lambda **kwargs: SimpleNamespace(
            is_active=True,
            is_superuser=False,
            get_username=lambda: "admin",
        ),
    )

    with pytest.raises(
        command._AuthorizationFailure,
        match="REHEARSAL_FINANCIAL_SCOPE_AUTHORIZATION_AUTHENTICATION_FAILED",
    ):
        command._authenticate_owner(owner="admin", password="owner-password")


def test_target_trade_date_parser_requires_canonical_iso_date() -> None:
    """Reject ambiguous target dates before any owner credential is read."""

    assert command._parse_target_trade_date("2026-10-14") == date(2026, 10, 14)

    for value in ("2026-10-14T00:00:00", "2026/10/14", ""):
        with pytest.raises(
            command._AuthorizationFailure,
            match="REHEARSAL_FINANCIAL_SCOPE_AUTHORIZATION_INPUT_INVALID",
        ):
            command._parse_target_trade_date(value)
