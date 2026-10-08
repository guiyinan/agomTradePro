from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from apps.data_center.infrastructure import isolated_write_rehearsal_runner
from scripts import manage_vps_migrations as migrations


def _set_s6_environment(monkeypatch: pytest.MonkeyPatch, result_path: Path) -> None:
    values = {
        "AGOM_S6_ISOLATED_DATABASE_MIGRATION": "1",
        "AGOM_RELEASE_REHEARSAL_DATABASE": "1",
        "AGOM_S6_EXPECTED_DATABASE_NAME": "agom_release_rehearsal_attempt_1234",
        "AGOM_S6_EXPECTED_DATABASE_HOST": "agom-s6-postgres-attempt-1234",
        "AGOM_S6_EXPECTED_DATABASE_CONTAINER_ID": "a" * 64,
        "AGOM_S6_EXPECTED_DATABASE_ADDRESS": "172.30.0.2",
        "AGOM_S6_MIGRATION_RESULT_PATH": str(result_path),
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(migrations, "_S6_MIGRATION_RESULT_PATH", str(result_path))


def _run_s6_migration_main(
    monkeypatch: pytest.MonkeyPatch,
    result_path: Path,
    states: list[tuple[list[str], list[str]]],
) -> int:
    _set_s6_environment(monkeypatch, result_path)
    monkeypatch.setattr(migrations.connection_created, "connect", lambda *args, **kwargs: None)
    monkeypatch.setattr(migrations.connections["default"], "ensure_connection", lambda: None)
    monkeypatch.setattr(migrations, "_assert_s6_rehearsal_scope", lambda: (5432, "172.30.0.2"))
    remaining = iter(states)
    monkeypatch.setattr(migrations, "_migration_state", lambda: next(remaining))
    monkeypatch.setattr(migrations, "execute_from_command_line", lambda argv: None)
    return migrations.main(["migrate", "--noinput"])


def test_migration_scope_checks_exact_database_host_and_live_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[dict[str, object]] = []

    class Cursor:
        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, query: str) -> None:
            assert query == "SELECT host(inet_server_addr()), inet_server_port()"

        def fetchone(self) -> tuple[str, int]:
            return "172.30.0.2", 5432

    fake_connection = SimpleNamespace(
        settings_dict={"PORT": "5432"},
        cursor=lambda: Cursor(),
    )
    monkeypatch.setattr(migrations, "connection", fake_connection)
    monkeypatch.setattr(
        isolated_write_rehearsal_runner,
        "assert_isolated_rehearsal_database",
        lambda **kwargs: observed.append(kwargs),
    )
    _set_s6_environment(monkeypatch, Path("/run/agom/stage/migration-command-result.json"))

    assert migrations._assert_s6_rehearsal_scope() == (5432, "172.30.0.2")
    assert observed == [
        {
            "expected_database_name": "agom_release_rehearsal_attempt_1234",
            "expected_database_host": "agom-s6-postgres-attempt-1234",
            "require_ephemeral_host": True,
        }
    ]


def test_migration_scope_rejects_cidr_bearing_live_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Cursor:
        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, query: str) -> None:
            assert query == "SELECT host(inet_server_addr()), inet_server_port()"

        def fetchone(self) -> tuple[str, int]:
            return "172.30.0.2/32", 5432

    monkeypatch.setattr(
        migrations,
        "connection",
        SimpleNamespace(settings_dict={"PORT": "5432"}, cursor=lambda: Cursor()),
    )
    monkeypatch.setattr(
        isolated_write_rehearsal_runner,
        "assert_isolated_rehearsal_database",
        lambda **kwargs: None,
    )
    _set_s6_environment(monkeypatch, Path("/run/agom/stage/migration-command-result.json"))

    with pytest.raises(RuntimeError, match="database address is invalid"):
        migrations._assert_s6_rehearsal_scope()


@pytest.mark.parametrize(
    ("server_address", "server_port"),
    [("172.30.0.3", 5432), ("172.30.0.2", 5433)],
)
def test_migration_scope_rejects_connected_endpoint_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    server_address: str,
    server_port: int,
) -> None:
    class Cursor:
        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, query: str) -> None:
            return None

        def fetchone(self) -> tuple[str, int]:
            return server_address, server_port

    monkeypatch.setattr(
        migrations,
        "connection",
        SimpleNamespace(settings_dict={"PORT": "5432"}, cursor=lambda: Cursor()),
    )
    monkeypatch.setattr(
        isolated_write_rehearsal_runner,
        "assert_isolated_rehearsal_database",
        lambda **kwargs: None,
    )
    _set_s6_environment(monkeypatch, Path("/run/agom/stage/migration-command-result.json"))

    with pytest.raises(RuntimeError, match="endpoint did not match Docker identity"):
        migrations._assert_s6_rehearsal_scope()


@pytest.mark.parametrize(
    ("vendor", "session_user", "current_user", "accepted"),
    [
        ("postgresql", "agomtradepro_migrator", "agomtradepro_owner", True),
        ("postgresql", "agomtradepro_runtime", "agomtradepro_owner", False),
        ("postgresql", "agomtradepro_migrator", "agomtradepro_runtime", False),
        ("sqlite", "agomtradepro_migrator", "agomtradepro_owner", False),
    ],
)
def test_migration_role_contract_is_exact(
    monkeypatch: pytest.MonkeyPatch,
    vendor: str,
    session_user: str,
    current_user: str,
    accepted: bool,
) -> None:
    class Cursor:
        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, query: str) -> None:
            assert query in {"SET ROLE agomtradepro_owner", "SELECT session_user, current_user"}

        def fetchone(self) -> tuple[str, str]:
            return session_user, current_user

    fake_connection = SimpleNamespace(
        alias="default",
        vendor=vendor,
        cursor=lambda: Cursor(),
    )
    monkeypatch.setattr(migrations, "_assert_s6_rehearsal_scope", lambda: None)
    typed_connection = cast(migrations.BaseDatabaseWrapper, fake_connection)
    if accepted:
        migrations._set_owner_role(migrations.BaseDatabaseWrapper, typed_connection)
    else:
        with pytest.raises(RuntimeError):
            migrations._set_owner_role(migrations.BaseDatabaseWrapper, typed_connection)


def test_s6_scope_requires_disposable_database_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGOM_S6_ISOLATED_DATABASE_MIGRATION", "1")
    monkeypatch.setenv("AGOM_RELEASE_REHEARSAL_DATABASE", "0")
    monkeypatch.setenv("AGOM_S6_EXPECTED_DATABASE_NAME", "agom_release_rehearsal_attempt_1234")
    monkeypatch.setenv("AGOM_S6_EXPECTED_DATABASE_HOST", "agom-s6-postgres-attempt-1234")
    monkeypatch.setenv("AGOM_S6_EXPECTED_DATABASE_CONTAINER_ID", "a" * 64)
    monkeypatch.setenv("AGOM_S6_EXPECTED_DATABASE_ADDRESS", "172.30.0.2")
    monkeypatch.setenv(
        "AGOM_S6_MIGRATION_RESULT_PATH", "/run/agom/stage/migration-command-result.json"
    )
    monkeypatch.setattr(
        isolated_write_rehearsal_runner,
        "assert_isolated_rehearsal_database",
        lambda **kwargs: pytest.fail("database guard must not run without opt-in"),
    )

    with pytest.raises(RuntimeError, match="scope is incomplete"):
        migrations._assert_s6_rehearsal_scope()


def test_s6_migration_result_reports_exact_new_delta_and_allows_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    initial = ["accounts.0001_initial"]
    pending = [
        "data_center.0090_financial_publication_capacity_workflow",
        "data_center.0091_financial_capacity_governance_record",
    ]
    applied_after = sorted([*initial, *pending])
    path = tmp_path / "migration-result.json"

    assert (
        _run_s6_migration_main(
            monkeypatch,
            path,
            [(pending, initial), ([], applied_after)],
        )
        == 0
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["pending_before"] == pending
    assert payload["pending_after"] == []
    assert payload["applied_migrations"] == pending
    assert payload["database_port"] == 5432
    assert payload["database_address"] == "172.30.0.2"

    noop_path = tmp_path / "migration-noop-result.json"
    assert _run_s6_migration_main(monkeypatch, noop_path, [([], initial), ([], initial)]) == 0
    noop = json.loads(noop_path.read_text(encoding="utf-8"))
    assert noop["pending_before"] == []
    assert noop["pending_after"] == []
    assert noop["applied_migrations"] == []


def test_s6_migration_rejects_unexpected_applied_delta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "migration-result.json"
    with pytest.raises(SystemExit, match="candidate migrations remain pending"):
        _run_s6_migration_main(
            monkeypatch,
            path,
            [(["data_center.0090_initial"], []), ([], ["data_center.0090_initial", "other.0001"])],
        )
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    assert payload["applied_migrations"] == ["data_center.0090_initial", "other.0001"]


@pytest.mark.parametrize("arguments", [["migrate"], ["migrate", "--noinput", "--database=default"]])
def test_s6_migration_requires_exact_noninteractive_command_before_connection(
    monkeypatch: pytest.MonkeyPatch, arguments: list[str]
) -> None:
    monkeypatch.setenv("AGOM_S6_ISOLATED_DATABASE_MIGRATION", "1")
    calls: list[str] = []
    monkeypatch.setattr(
        migrations.connections["default"], "ensure_connection", lambda: calls.append("db")
    )

    with pytest.raises(SystemExit, match="migrate --noinput"):
        migrations.main(arguments)

    assert calls == []


def test_s6_migration_scope_failure_prevents_state_reads_and_migration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result_path = tmp_path / "migration-result.json"
    _set_s6_environment(monkeypatch, result_path)
    calls: list[str] = []
    monkeypatch.setattr(migrations.connection_created, "connect", lambda *args, **kwargs: None)
    monkeypatch.setattr(migrations.connections["default"], "ensure_connection", lambda: None)
    monkeypatch.setattr(
        migrations,
        "_assert_s6_rehearsal_scope",
        lambda: (_ for _ in ()).throw(RuntimeError("endpoint mismatch")),
    )
    monkeypatch.setattr(migrations, "_migration_state", lambda: calls.append("state"))
    monkeypatch.setattr(
        migrations,
        "execute_from_command_line",
        lambda argv: calls.append("migrate"),
    )

    with pytest.raises(RuntimeError, match="endpoint mismatch"):
        migrations.main(["migrate", "--noinput"])

    assert calls == []
    assert not result_path.exists()
