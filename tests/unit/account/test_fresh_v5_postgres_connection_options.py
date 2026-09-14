"""Offline contract checks for the disposable V5 PostgreSQL alias settings."""

from __future__ import annotations

import pytest

from tests.component.account.test_owner_tenant_authority_v3_fresh_v5_parents_postgres import (
    _FIXED_POSTGRES_OPTIONS,
    PG_ALIAS,
    _build_postgres_alias_settings,
)

_BASE_URL = f"postgresql://reader:private-password@127.0.0.1:55439/{PG_ALIAS}"
_CANONICAL_QUERY = "connect_timeout=30&gssencmode=disable&sslmode=disable"


def test_fixed_transport_options_are_added_without_url_query() -> None:
    """A query-free private URL still gets the fixed local transport map."""

    settings = _build_postgres_alias_settings(_BASE_URL)

    assert settings["ENGINE"] == "django.db.backends.postgresql"
    assert settings["NAME"] == PG_ALIAS
    assert settings["HOST"] == "127.0.0.1"
    assert settings["PORT"] == "55439"
    assert settings["USER"] == "reader"
    assert settings["PASSWORD"] == "private-password"
    assert settings["OPTIONS"] == _FIXED_POSTGRES_OPTIONS


def test_exact_transport_query_is_validated_but_never_passed_through() -> None:
    """The compatibility query is allowlisted while the returned map stays fixed."""

    settings = _build_postgres_alias_settings(_BASE_URL + "?" + _CANONICAL_QUERY)

    assert settings["OPTIONS"] == {
        "connect_timeout": 30,
        "sslmode": "disable",
        "gssencmode": "disable",
    }
    assert set(settings["OPTIONS"]) == {
        "connect_timeout",
        "sslmode",
        "gssencmode",
    }


@pytest.mark.parametrize(
    ("suffix", "message"),
    (
        ("?sslmode=disable&sslmode=disable", "repeats"),
        ("?service=untrusted", "unsupported"),
        ("?options=sslmode%3Drequire", "unsupported"),
        ("?sslmode=require", "non-fixed"),
        ("?connect_timeout=60", "non-fixed"),
    ),
)
def test_rejects_duplicate_unknown_or_non_fixed_query_values(suffix: str, message: str) -> None:
    """URL query input cannot alter the fixed alias transport contract."""

    with pytest.raises(RuntimeError, match=message) as error:
        _build_postgres_alias_settings(_BASE_URL + suffix)

    assert "private-password" not in str(error.value)
    assert _BASE_URL not in str(error.value)


@pytest.mark.parametrize(
    "url",
    (
        "postgresql://reader:private-password@example.test:55439/" + PG_ALIAS,
        "postgresql://reader:private-password@127.0.0.1:55439/other_database",
        "postgresql://reader:private-password@127.0.0.1:not-a-port/" + PG_ALIAS,
    ),
)
def test_rejects_non_loopback_non_dedicated_or_malformed_urls(url: str) -> None:
    """The fixture cannot be redirected outside its dedicated loopback database."""

    with pytest.raises(RuntimeError):
        _build_postgres_alias_settings(url)
