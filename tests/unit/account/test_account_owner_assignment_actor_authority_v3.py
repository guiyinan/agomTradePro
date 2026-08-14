from __future__ import annotations

import ast
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    AuthenticatedAccountPrincipalV3,
    CurrentAccountActorAuthorityV3,
    CurrentAccountOwnerAssignmentApproverProviderV3,
    CurrentAccountOwnerClaimantProviderV3,
)
from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentCorruption,
)


def _at(hour: int) -> datetime:
    return datetime(2026, 8, 14, hour, tzinfo=UTC)


def _principal() -> AuthenticatedAccountPrincipalV3:
    return AuthenticatedAccountPrincipalV3("session-41", 41, "a" * 64, _at(8), _at(18))


def _authority(**changes: object) -> CurrentAccountActorAuthorityV3:
    values: dict[str, object] = {
        "principal_id": "session-41",
        "user_id": 41,
        "authentication_context_hash": "a" * 64,
        "actor_id": "django-user:41",
        "is_authenticated": True,
        "is_active": True,
        "is_staff": False,
        "is_superuser": False,
        "rbac_role": "owner",
        "source_id": "account-user-41",
        "source_version": "v1",
        "source_content_hash": "b" * 64,
        "recorded_at": _at(8),
        "valid_until": _at(18),
    }
    values.update(changes)
    return CurrentAccountActorAuthorityV3(**values)  # type: ignore[arg-type]


class _Reader:
    def __init__(self, values: list[object]) -> None:
        self.values = values
        self.calls: list[dict[str, object]] = []

    def get_exact_current(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self.values.pop(0)


def test_claimant_revalidates_authority_on_every_read_and_detects_revocation() -> None:
    reader = _Reader([_authority(), None])
    provider = CurrentAccountOwnerClaimantProviderV3(_principal(), reader)

    actor = provider.get_current(as_of=_at(10))
    assert actor is not None
    assert actor.to_payload() == {
        "actor_id": "django-user:41",
        "user_id": 41,
        "role": "account_owner_claimant",
        "kind": "human",
        "is_staff": False,
    }
    assert provider.get_current(as_of=_at(10)) is None
    assert len(reader.calls) == 2


@pytest.mark.parametrize("changes", [{"is_staff": True}, {"is_superuser": True}])
def test_claimant_rejects_staff_or_superuser(changes: dict[str, object]) -> None:
    provider = CurrentAccountOwnerClaimantProviderV3(_principal(), _Reader([_authority(**changes)]))

    assert provider.get_current(as_of=_at(10)) is None


def test_approver_requires_current_active_staff_admin_and_revalidates_role() -> None:
    reader = _Reader(
        [
            _authority(is_staff=True, is_superuser=True, rbac_role="admin"),
            _authority(is_staff=True, is_superuser=True, rbac_role="read_only"),
        ]
    )
    provider = CurrentAccountOwnerAssignmentApproverProviderV3(_principal(), reader)

    actor = provider.get_current(as_of=_at(10))
    assert actor is not None
    assert actor.role == "account_owner_assignment_approver"
    assert actor.is_staff is True
    assert provider.get_current(as_of=_at(10)) is None


@pytest.mark.parametrize(
    "authority",
    [
        _authority(is_staff=False, rbac_role="admin"),
        _authority(is_staff=True, rbac_role="owner"),
        _authority(is_staff=True, rbac_role="investment_manager"),
        _authority(is_staff=True, rbac_role="管理员"),
        _authority(is_staff=True, rbac_role="ADMIN"),
    ],
)
def test_approver_rejects_nonstaff_or_nonadmin(authority: CurrentAccountActorAuthorityV3) -> None:
    provider = CurrentAccountOwnerAssignmentApproverProviderV3(_principal(), _Reader([authority]))

    assert provider.get_current(as_of=_at(10)) is None


def test_expired_principal_returns_none_without_authority_read() -> None:
    reader = _Reader([_authority()])
    provider = CurrentAccountOwnerClaimantProviderV3(_principal(), reader)

    assert provider.get_current(as_of=_at(18)) is None
    assert reader.calls == []


@pytest.mark.parametrize(
    "replacement",
    [
        {"principal_id": "other-session"},
        {"user_id": 42},
        {"authentication_context_hash": "c" * 64},
        {"recorded_at": _at(11)},
    ],
)
def test_authority_selector_or_clock_substitution_fails_closed(
    replacement: dict[str, object],
) -> None:
    authority = replace(_authority(), **replacement)
    provider = CurrentAccountOwnerClaimantProviderV3(_principal(), _Reader([authority]))

    with pytest.raises(AccountOwnerAssignmentCorruption):
        provider.get_current(as_of=_at(10))


@pytest.mark.parametrize(
    "replacement",
    [
        {"is_authenticated": False},
        {"is_active": False},
        {"valid_until": _at(10)},
    ],
)
def test_revoked_or_expired_authority_returns_none(
    replacement: dict[str, object],
) -> None:
    authority = replace(_authority(), **replacement)
    provider = CurrentAccountOwnerClaimantProviderV3(_principal(), _Reader([authority]))

    assert provider.get_current(as_of=_at(10)) is None


def test_boundary_has_no_orm_interface_or_infrastructure_dependency() -> None:
    source = (
        Path(__file__).parents[3]
        / "apps/account/application/account_owner_assignment_actor_authority_v3.py"
    ).read_text(encoding="utf-8")
    modules = {
        node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert ".objects" not in source
    assert not any("infrastructure" in module or "interface" in module for module in modules)
    assert not any(module.startswith("django") for module in modules)
