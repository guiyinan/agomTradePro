"""Isolated publication rehearsals fail closed before any production write."""

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.data_center.infrastructure import isolated_write_rehearsal_runner as runner
from core.exceptions import DataFetchError

EXPECTED_NAME = "agom_release_rehearsal_test"
EXPECTED_HOST = "agom-s6-postgres-test"


@pytest.mark.parametrize(
    ("vendor", "name", "host", "in_atomic_block", "enabled", "expected_code"),
    [
        (
            "sqlite",
            EXPECTED_NAME,
            EXPECTED_HOST,
            False,
            True,
            "REHEARSAL_WRITE_SCOPE_VENDOR_INVALID",
        ),
        (
            "postgresql",
            EXPECTED_NAME,
            EXPECTED_HOST,
            True,
            True,
            "REHEARSAL_WRITE_SCOPE_TRANSACTION_ACTIVE",
        ),
        (
            "postgresql",
            EXPECTED_NAME,
            EXPECTED_HOST,
            False,
            False,
            "REHEARSAL_WRITE_SCOPE_OPT_IN_MISSING",
        ),
        (
            "postgresql",
            "agomtradepro",
            EXPECTED_HOST,
            False,
            True,
            "REHEARSAL_WRITE_SCOPE_DATABASE_NAME_INVALID",
        ),
        (
            "postgresql",
            "agom_release_rehearsal_other",
            EXPECTED_HOST,
            False,
            True,
            "REHEARSAL_WRITE_SCOPE_DATABASE_NAME_MISMATCH",
        ),
        (
            "postgresql",
            EXPECTED_NAME,
            "postgres",
            False,
            True,
            "REHEARSAL_WRITE_SCOPE_HOST_CONFIG_MISMATCH",
        ),
    ],
)
def test_isolated_database_guard_rejects_unsafe_scope(
    monkeypatch: pytest.MonkeyPatch,
    vendor: str,
    name: str,
    host: str,
    in_atomic_block: bool,
    enabled: bool,
    expected_code: str,
) -> None:
    monkeypatch.setattr(
        runner,
        "connection",
        SimpleNamespace(
            vendor=vendor,
            in_atomic_block=in_atomic_block,
            settings_dict={"NAME": name, "HOST": host, "PORT": "5432"},
        ),
    )
    if enabled:
        monkeypatch.setenv("AGOM_RELEASE_REHEARSAL_DATABASE", "1")
    else:
        monkeypatch.delenv("AGOM_RELEASE_REHEARSAL_DATABASE", raising=False)

    with pytest.raises(DataFetchError) as exc_info:
        runner._assert_isolated_database(
            expected_database_name=EXPECTED_NAME,
            expected_database_host=EXPECTED_HOST,
            require_ephemeral_host=True,
        )
    assert exc_info.value.code == expected_code


def test_isolated_database_guard_rejects_non_ephemeral_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner,
        "connection",
        SimpleNamespace(
            vendor="postgresql",
            in_atomic_block=False,
            settings_dict={"NAME": EXPECTED_NAME, "HOST": "localhost", "PORT": "5432"},
        ),
    )
    monkeypatch.setenv("AGOM_RELEASE_REHEARSAL_DATABASE", "1")

    with pytest.raises(DataFetchError) as exc_info:
        runner._assert_isolated_database(
            expected_database_name=EXPECTED_NAME,
            expected_database_host="localhost",
            require_ephemeral_host=True,
        )

    assert exc_info.value.code == "REHEARSAL_WRITE_SCOPE_HOST_NOT_EPHEMERAL"


def test_connected_database_identity_strips_postgresql_inet_netmask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live endpoint identity must be comparable with DNS host addresses."""

    class Cursor:
        def __enter__(self) -> "Cursor":
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def execute(self, query: str) -> None:
            assert "host(inet_server_addr())" in query

        def fetchone(self) -> tuple[str, str, int]:
            return EXPECTED_NAME, "172.18.0.2", 5432

    monkeypatch.setattr(runner, "connection", SimpleNamespace(cursor=Cursor))

    assert runner._connected_database_identity() == (EXPECTED_NAME, "172.18.0.2", 5432)


def test_isolated_database_guard_accepts_explicit_disposable_postgresql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner,
        "connection",
        SimpleNamespace(
            vendor="postgresql",
            in_atomic_block=False,
            settings_dict={
                "NAME": EXPECTED_NAME,
                "HOST": EXPECTED_HOST,
                "PORT": "5432",
            },
        ),
    )
    monkeypatch.setenv("AGOM_RELEASE_REHEARSAL_DATABASE", "1")
    monkeypatch.setattr(
        runner,
        "_connected_database_identity",
        lambda: (EXPECTED_NAME, "172.18.0.2", 5432),
    )
    monkeypatch.setattr(
        runner,
        "_resolved_host_addresses",
        lambda _host, _port: {"172.18.0.2"},
    )

    runner._assert_isolated_database(
        expected_database_name=EXPECTED_NAME,
        expected_database_host=EXPECTED_HOST,
        require_ephemeral_host=True,
    )


@pytest.mark.parametrize(
    ("actual_name", "actual_address", "actual_port", "expected_code"),
    [
        (
            "agom_release_rehearsal_other",
            "172.18.0.2",
            5432,
            "REHEARSAL_WRITE_SCOPE_CONNECTED_DATABASE_MISMATCH",
        ),
        (
            EXPECTED_NAME,
            "10.0.0.5",
            5432,
            "REHEARSAL_WRITE_SCOPE_CONNECTED_ADDRESS_MISMATCH",
        ),
        (
            EXPECTED_NAME,
            "172.18.0.2",
            6543,
            "REHEARSAL_WRITE_SCOPE_CONNECTED_PORT_MISMATCH",
        ),
    ],
)
def test_isolated_database_guard_rejects_connected_endpoint_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    actual_name: str,
    actual_address: str,
    actual_port: int,
    expected_code: str,
) -> None:
    monkeypatch.setattr(
        runner,
        "connection",
        SimpleNamespace(
            vendor="postgresql",
            in_atomic_block=False,
            settings_dict={
                "NAME": EXPECTED_NAME,
                "HOST": EXPECTED_HOST,
                "PORT": "5432",
            },
        ),
    )
    monkeypatch.setenv("AGOM_RELEASE_REHEARSAL_DATABASE", "1")
    monkeypatch.setattr(
        runner,
        "_connected_database_identity",
        lambda: (actual_name, actual_address, actual_port),
    )
    monkeypatch.setattr(
        runner,
        "_resolved_host_addresses",
        lambda _host, _port: {"172.18.0.2"},
    )

    with pytest.raises(DataFetchError) as exc_info:
        runner._assert_isolated_database(
            expected_database_name=EXPECTED_NAME,
            expected_database_host=EXPECTED_HOST,
            require_ephemeral_host=True,
        )

    assert exc_info.value.code == expected_code


def test_isolated_database_guard_reports_unresolvable_expected_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner,
        "connection",
        SimpleNamespace(
            vendor="postgresql",
            in_atomic_block=False,
            settings_dict={"NAME": EXPECTED_NAME, "HOST": EXPECTED_HOST, "PORT": "5432"},
        ),
    )
    monkeypatch.setenv("AGOM_RELEASE_REHEARSAL_DATABASE", "1")
    monkeypatch.setattr(
        runner,
        "_connected_database_identity",
        lambda: (EXPECTED_NAME, "172.18.0.2", 5432),
    )

    def reject_resolution(_host: str, _port: int) -> set[str]:
        raise DataFetchError(
            "unresolvable",
            code="REHEARSAL_WRITE_SCOPE_HOST_UNRESOLVED",
        )

    monkeypatch.setattr(runner, "_resolved_host_addresses", reject_resolution)

    with pytest.raises(DataFetchError) as exc_info:
        runner._assert_isolated_database(
            expected_database_name=EXPECTED_NAME,
            expected_database_host=EXPECTED_HOST,
            require_ephemeral_host=True,
        )

    assert exc_info.value.code == "REHEARSAL_WRITE_SCOPE_HOST_UNRESOLVED"


def test_host_resolution_maps_socket_error_to_stable_scope_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_resolution(*args: object, **kwargs: object) -> list[object]:
        del args, kwargs
        raise runner.socket.gaierror("synthetic resolution failure")

    monkeypatch.setattr(runner.socket, "getaddrinfo", reject_resolution)

    with pytest.raises(DataFetchError) as exc_info:
        runner._resolved_host_addresses(EXPECTED_HOST, 5432)

    assert exc_info.value.code == "REHEARSAL_WRITE_SCOPE_HOST_UNRESOLVED"


def test_database_identity_rejects_pending_migrations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Executor:
        loader = SimpleNamespace(graph=SimpleNamespace(leaf_nodes=lambda: [("app", "latest")]))

        def __init__(self, _connection: object) -> None:
            pass

        def migration_plan(self, _leaves: object) -> list[tuple[str, bool]]:
            return [("pending", False)]

    monkeypatch.setattr(runner, "MigrationExecutor", Executor)

    with pytest.raises(DataFetchError) as exc_info:
        runner._database_identity()
    assert exc_info.value.code == "REHEARSAL_WRITE_MIGRATIONS_PENDING"


def test_preflight_verifies_scope_candidate_then_migrations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    monkeypatch.setattr(
        runner,
        "assert_isolated_rehearsal_database",
        lambda **kwargs: events.append("scope"),
    )
    monkeypatch.setattr(
        runner,
        "verify_candidate_release_image",
        lambda _root, _sha: events.append("candidate") or ("attestation", "sha256:" + "f" * 64),
    )
    monkeypatch.setattr(
        runner,
        "_database_identity",
        lambda: events.append("migrations") or "d" * 64,
    )

    result = runner.preflight_isolated_write_rehearsal(
        candidate_sha="a" * 40,
        source_root=tmp_path,
        expected_database_name=EXPECTED_NAME,
        expected_database_host=EXPECTED_HOST,
        require_ephemeral_host=True,
    )

    assert events == ["scope", "candidate", "migrations"]
    assert result == ("attestation", "sha256:" + "f" * 64, "d" * 64)


def test_collector_requires_ephemeral_host_in_second_preflight(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def reject_non_ephemeral(**kwargs: object) -> tuple[str, str, str]:
        assert kwargs["require_ephemeral_host"] is True
        raise DataFetchError("unsafe", code="REHEARSAL_WRITE_SCOPE_HOST_NOT_EPHEMERAL")

    monkeypatch.setattr(runner, "preflight_isolated_write_rehearsal", reject_non_ephemeral)

    with pytest.raises(DataFetchError) as exc_info:
        runner.collect_isolated_write_rehearsal(
            candidate_sha="a" * 40,
            target_trade_date=date.today(),
            universe_sha256="b" * 64,
            provider_identities_sha256="c" * 64,
            output_dir=tmp_path / "output",
            source_root=tmp_path,
            expected_database_name=EXPECTED_NAME,
            expected_database_host="localhost",
        )

    assert exc_info.value.code == "REHEARSAL_WRITE_SCOPE_HOST_NOT_EPHEMERAL"
    assert not (tmp_path / "output").exists()
