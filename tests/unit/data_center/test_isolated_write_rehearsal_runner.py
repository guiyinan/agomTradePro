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
    ("vendor", "name", "in_atomic_block", "enabled"),
    [
        ("sqlite", "agom_release_rehearsal_test", False, True),
        ("postgresql", "agomtradepro", False, True),
        ("postgresql", "agom_release_rehearsal_test", True, True),
        ("postgresql", "agom_release_rehearsal_test", False, False),
    ],
)
def test_isolated_database_guard_rejects_unsafe_scope(
    monkeypatch: pytest.MonkeyPatch,
    vendor: str,
    name: str,
    in_atomic_block: bool,
    enabled: bool,
) -> None:
    monkeypatch.setattr(
        runner,
        "connection",
        SimpleNamespace(
            vendor=vendor,
            in_atomic_block=in_atomic_block,
            settings_dict={"NAME": name, "HOST": EXPECTED_HOST, "PORT": "5432"},
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
    assert exc_info.value.code == "REHEARSAL_WRITE_SCOPE_INVALID"


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
    ("actual_name", "actual_address", "actual_port"),
    [
        ("agom_release_rehearsal_other", "172.18.0.2", 5432),
        (EXPECTED_NAME, "10.0.0.5", 5432),
        (EXPECTED_NAME, "172.18.0.2", 6543),
    ],
)
def test_isolated_database_guard_rejects_connected_endpoint_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    actual_name: str,
    actual_address: str,
    actual_port: int,
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

    assert exc_info.value.code == "REHEARSAL_WRITE_SCOPE_INVALID"


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
        raise DataFetchError("unsafe", code="REHEARSAL_WRITE_SCOPE_INVALID")

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

    assert exc_info.value.code == "REHEARSAL_WRITE_SCOPE_INVALID"
    assert not (tmp_path / "output").exists()
