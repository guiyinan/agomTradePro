"""The native runtime role refuses unapproved targets before changing any ACL."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.support import ash07_native_runtime_role as roles


@pytest.mark.parametrize(
    "profile,port,expected",
    [
        ("ash07_local", 59513, "test_ash03_close_20261102"),
        ("ash05_local", 56405, "ash05_tax_payment_basis_qa"),
        ("ash05_ci", 5432, "ash05_owner_goldens_test_ci"),
        ("ash05_nightly", 5432, "test_agomtradepro_critical_aud05"),
    ],
)
def test_explicit_profile_requires_original_test_database_guard_before_sql(
    monkeypatch, tmp_path: Path, profile, port, expected
) -> None:
    database = SimpleNamespace(settings_dict={"PORT": str(port)}, cursor=Mock())
    guard = Mock(side_effect=RuntimeError("synthetic test database mismatch"))
    monkeypatch.setattr(roles, "connections", {"default": database})
    monkeypatch.setattr(roles, "assert_native_postgres_test_database", guard)
    with pytest.raises(RuntimeError, match="synthetic test database mismatch"):
        with roles.isolated_ash07_runtime_role(tmp_path, target_profile=profile):
            raise AssertionError("unapproved role was entered")
    guard.assert_called_once_with(expected_name=expected)
    database.cursor.assert_not_called()
    assert not tuple(tmp_path.iterdir())


@pytest.mark.parametrize(
    "profile,port",
    [
        ("unknown", 5432),
        ("ash05_ci", 56405),
        ("ash05_local", 5432),
        ("ash07_local", 5432),
        ("ash05_nightly", 56405),
    ],
)
def test_wrong_runtime_profile_or_port_never_opens_a_database_cursor(
    monkeypatch, tmp_path: Path, profile, port
) -> None:
    database = SimpleNamespace(settings_dict={"PORT": str(port)}, cursor=Mock())
    guard = Mock()
    monkeypatch.setattr(roles, "connections", {"default": database})
    monkeypatch.setattr(roles, "assert_native_postgres_test_database", guard)
    with pytest.raises(RuntimeError, match="unapproved|unknown"):
        with roles.isolated_ash07_runtime_role(tmp_path, target_profile=profile):
            raise AssertionError("unapproved role was entered")
    guard.assert_not_called()
    database.cursor.assert_not_called()
    assert not tuple(tmp_path.iterdir())


@pytest.mark.parametrize(
    "name",
    [
        "agomtradepro_critical",
        "test_agomtradepro_critical_aud05_flush",
        "test_ash03_close_20261102",
    ],
)
def test_ash05_role_refuses_unassigned_database_names(name: str) -> None:
    with pytest.raises(RuntimeError, match="unassigned"):
        roles._ash05_runtime_profile(name)
