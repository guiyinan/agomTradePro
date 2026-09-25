"""Isolated publication rehearsals fail closed before any production write."""

from types import SimpleNamespace

import pytest

from apps.data_center.infrastructure import isolated_write_rehearsal_runner as runner
from core.exceptions import DataFetchError


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
            settings_dict={"NAME": name},
        ),
    )
    if enabled:
        monkeypatch.setenv("AGOM_RELEASE_REHEARSAL_DATABASE", "1")
    else:
        monkeypatch.delenv("AGOM_RELEASE_REHEARSAL_DATABASE", raising=False)

    with pytest.raises(DataFetchError) as exc_info:
        runner._assert_isolated_database()
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
            settings_dict={"NAME": "agom_release_rehearsal_test"},
        ),
    )
    monkeypatch.setenv("AGOM_RELEASE_REHEARSAL_DATABASE", "1")

    runner._assert_isolated_database()


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
