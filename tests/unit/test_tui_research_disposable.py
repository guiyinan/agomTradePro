from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.support.tui_research import disposable

_ALLOWED_TEST_IDS = (
    "tests/api/test_equity_published_valuation_member_read.py::"
    "test_published_valuation_api_reads_exact_current_members_and_source_clocks",
    "tests/api/test_equity_published_valuation_member_read.py::"
    "test_published_valuation_api_blocks_when_current_member_is_missing",
)


def _postgres_connection(database_name: str) -> SimpleNamespace:
    """Build the connection surface consumed by the admission router."""

    return SimpleNamespace(
        vendor="postgresql",
        alias="default",
        settings_dict={"NAME": database_name, "TEST": {"NAME": database_name}},
    )


def test_native_postgres_fixture_admission_is_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep native PostgreSQL admission disabled unless explicitly requested."""

    monkeypatch.setattr(disposable, "connection", _postgres_connection("test_critical"))
    monkeypatch.setenv("PYTEST_CURRENT_TEST", f"{_ALLOWED_TEST_IDS[0]} (call)")

    with pytest.raises(AssertionError, match="disposable SQLite"):
        disposable.require_test_database()


def test_native_postgres_fixture_admission_rejects_unlisted_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject an unregistered node before consulting the native database guard."""

    monkeypatch.setattr(disposable, "connection", _postgres_connection("test_critical"))
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/api/test_other.py::test_write (call)")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "core.settings.critical_postgres_test")
    monkeypatch.setenv("AGOM_CRITICAL_TEST_DB_NAME", "test_critical")
    called: list[bool] = []

    def unexpected_guard_call() -> str:
        called.append(True)
        return "test_critical"

    monkeypatch.setattr(
        disposable,
        "assert_native_postgres_test_database",
        unexpected_guard_call,
    )
    with pytest.raises(AssertionError, match="disposable SQLite"):
        disposable.require_test_database(allow_native_postgres_test=True)
    assert called == []


@pytest.mark.parametrize("node_id", _ALLOWED_TEST_IDS)
def test_native_postgres_fixture_admission_uses_exact_test_identity(
    monkeypatch: pytest.MonkeyPatch,
    node_id: str,
) -> None:
    """Use the existing database identity checker for both exact API contracts."""

    database_name = "test_agomtradepro_critical"
    monkeypatch.setattr(disposable, "connection", _postgres_connection(database_name))
    monkeypatch.setenv("PYTEST_CURRENT_TEST", f"{node_id} (call)")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "core.settings.critical_postgres_test")
    monkeypatch.setenv("AGOM_CRITICAL_TEST_DB_NAME", database_name)
    calls: list[bool] = []

    def verify_native_database() -> str:
        calls.append(True)
        return database_name

    monkeypatch.setattr(
        disposable,
        "assert_native_postgres_test_database",
        verify_native_database,
    )
    assert disposable.require_test_database(allow_native_postgres_test=True) is None
    assert calls == [True]


@pytest.mark.parametrize(
    ("settings_module", "configured_name", "native_name", "guard_called"),
    (
        (
            "core.settings.playwright",
            "test_agomtradepro_critical",
            "test_agomtradepro_critical",
            False,
        ),
        (
            "core.settings.critical_postgres_test",
            "test_other_database",
            "test_agomtradepro_critical",
            True,
        ),
    ),
)
def test_native_postgres_fixture_admission_rejects_wrong_ci_identity(
    monkeypatch: pytest.MonkeyPatch,
    settings_module: str,
    configured_name: str,
    native_name: str,
    guard_called: bool,
) -> None:
    """Require both the dedicated settings module and its exact DB environment."""

    monkeypatch.setattr(disposable, "connection", _postgres_connection(native_name))
    monkeypatch.setenv("PYTEST_CURRENT_TEST", f"{_ALLOWED_TEST_IDS[0]} (call)")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", settings_module)
    monkeypatch.setenv("AGOM_CRITICAL_TEST_DB_NAME", configured_name)
    calls: list[bool] = []

    def verify_native_database() -> str:
        calls.append(True)
        return native_name

    monkeypatch.setattr(
        disposable,
        "assert_native_postgres_test_database",
        verify_native_database,
    )
    with pytest.raises(AssertionError):
        disposable.require_test_database(allow_native_postgres_test=True)
    assert bool(calls) is guard_called


def test_native_postgres_fixture_admission_rejects_non_test_database_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject the opt-in when the active test database lacks its test_ name."""

    monkeypatch.setattr(disposable, "connection", _postgres_connection("agomtradepro"))
    node_id = _ALLOWED_TEST_IDS[0]
    monkeypatch.setenv("PYTEST_CURRENT_TEST", f"{node_id} (call)")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "core.settings.critical_postgres_test")
    monkeypatch.setenv("AGOM_CRITICAL_TEST_DB_NAME", "agomtradepro")
    monkeypatch.setattr(
        disposable,
        "assert_native_postgres_test_database",
        lambda: "agomtradepro",
    )

    with pytest.raises(AssertionError, match="exact test_ database"):
        disposable.require_test_database(allow_native_postgres_test=True)
