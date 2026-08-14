from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.account.domain.account_actor_authority_raw_source_primitives_v3 import (
    AccountAuthorityRawSourceChainV3,
)
from apps.account.domain.account_rbac_authority_mutation_binding_v3 import (
    AccountRbacAuthorityHumanOperatorRefV3,
    AccountRbacAuthorityMutationBindingV3,
    AccountRbacAuthorityMutationIssuerV3,
    AccountRbacAuthorityProfileStateRefV3,
    AccountRbacAuthoritySourceEpochV3,
    root_claim_hash_for_account_rbac_authority_mutation_binding_v3,
    select_exact_account_rbac_authority_mutation_binding_v3,
    validate_account_rbac_authority_mutation_binding_v3_successor,
    validate_account_rbac_authority_source_epoch_v3_successor,
)

NOW = datetime(2026, 8, 14, 10, tzinfo=UTC)


def _subject(role: str = "owner", version: str = "p1", minute: int = 1):
    return AccountRbacAuthorityProfileStateRefV3(
        "profile-41",
        version,
        f"{(minute % 9) + 1:x}" * 64,
        role,
        41,
        "django-user:41",
        NOW + timedelta(minutes=minute),
    )


def _operator(minute: int = 0, **changes: object):
    values: dict[str, object] = {
        "principal_id": "admin-principal-7",
        "user_id": 7,
        "actor_id": "django-user:7",
        "is_authenticated": True,
        "is_active": True,
        "is_staff": True,
        "is_superuser": False,
        "rbac_role": "admin",
        "authentication_source_id": "session-7",
        "authentication_source_version": "a1",
        "authentication_source_content_hash": "2" * 64,
        "user_source_id": "user-7",
        "user_source_version": "u1",
        "user_source_content_hash": "3" * 64,
        "rbac_source_id": "rbac-7",
        "rbac_source_version": "r1",
        "rbac_source_content_hash": "4" * 64,
        "observed_at": NOW + timedelta(minutes=minute),
        "valid_until": NOW + timedelta(hours=3),
    }
    values.update(changes)
    return AccountRbacAuthorityHumanOperatorRefV3(**values)  # type: ignore[arg-type]


def _epoch(
    sequence: int = 1,
    *,
    previous: AccountRbacAuthoritySourceEpochV3 | None = None,
    terminal_source_hash: str | None = None,
    terminal_binding_hash: str | None = None,
):
    return AccountRbacAuthoritySourceEpochV3(
        epoch_id=f"rbac-epoch-41-{sequence}",
        target_user_id=41,
        subject_actor_id="django-user:41",
        source_id=f"profile-rbac:41:epoch:{sequence}",
        epoch_sequence=sequence,
        opened_at=NOW + timedelta(minutes=10 * (sequence - 1)),
        previous_epoch_content_hash=previous.content_hash if previous else None,
        terminal_authority_source_content_hash=terminal_source_hash,
        terminal_mutation_binding_content_hash=terminal_binding_hash,
    )


def _binding(
    kind: str = "bootstrap",
    *,
    previous: AccountRbacAuthorityMutationBindingV3 | None = None,
    epoch: AccountRbacAuthoritySourceEpochV3 | None = None,
    new_role: str = "owner",
):
    chosen_epoch = epoch or (previous.epoch if previous else _epoch())
    minute = {"bootstrap": 2, "role_change": 6, "revoke": 10, "reactivate": 13}[kind]
    old_state = None if previous is None else previous.new_authority_state
    old_role = None if previous is None else previous.new_rbac_role
    new_state = "revoked" if kind == "revoke" else "current"
    return AccountRbacAuthorityMutationBindingV3(
        mutation_id=f"mutation-{minute}",
        mutation_kind=kind,
        epoch=chosen_epoch,
        old_subject=None if previous is None else previous.subject,
        subject=_subject(new_role, f"p{minute}", minute - 1),
        operator=_operator(minute - 2),
        issuer=AccountRbacAuthorityMutationIssuerV3("rbac-mutation-issuer-v3"),
        source_version=f"v{minute}",
        old_authority_state=old_state,
        new_authority_state=new_state,
        old_rbac_role=old_role,
        new_rbac_role=new_role,
        authority_source_identity_hash="a" * 64,
        authority_source_content_hash=chr(97 + minute % 5) * 64,
        authority_source_record_seal="f" * 64,
        observed_at=NOW + timedelta(minutes=minute),
        issued_at=NOW + timedelta(minutes=minute, seconds=1),
        recorded_at=NOW + timedelta(minutes=minute, seconds=2),
        valid_until=NOW + timedelta(minutes=minute + 20),
        binding_chain=AccountAuthorityRawSourceChainV3(
            root_claim_hash=(
                root_claim_hash_for_account_rbac_authority_mutation_binding_v3(41, "django-user:41")
                if previous is None
                else None
            ),
            supersedes_content_hash=previous.content_hash if previous else None,
        ),
        authority_source_chain=AccountAuthorityRawSourceChainV3(
            root_claim_hash=(
                chosen_epoch.root_claim_hash if kind in {"bootstrap", "reactivate"} else None
            ),
            supersedes_content_hash=(
                previous.authority_source_content_hash
                if previous is not None and kind != "reactivate"
                else None
            ),
        ),
    )


def test_subject_operator_and_service_issuer_are_distinct_frozen_evidence() -> None:
    subject, operator = _subject(), _operator()
    issuer = AccountRbacAuthorityMutationIssuerV3("rbac-mutation-issuer-v3")
    assert subject.user_id != operator.user_id
    assert subject.subject_actor_id != operator.actor_id
    assert operator.rbac_role == "admin" and operator.is_superuser is False
    assert issuer.kind == "service" and issuer.is_automated
    assert all(
        len(value) == 64
        for value in (subject.content_hash, operator.authority_hash, issuer.identity_hash)
    )
    with pytest.raises(FrozenInstanceError):
        subject.rbac_role = "risk"  # type: ignore[misc]


@pytest.mark.parametrize("field", ["is_authenticated", "is_active", "is_staff"])
def test_human_operator_requires_exact_active_staff_admin(field: str) -> None:
    with pytest.raises((TypeError, ValueError)):
        _operator(**{field: False})
    with pytest.raises(ValueError):
        _operator(rbac_role="owner")
    assert _operator(is_superuser=True).is_superuser is True


def test_bootstrap_has_nullable_old_state_and_separate_dual_roots() -> None:
    root = _binding()
    assert root.old_authority_state is None and root.old_rbac_role is None
    assert root.binding_chain.root_claim_hash != root.authority_source_chain.root_claim_hash
    assert root.authority_source_chain.root_claim_hash == root.epoch.root_claim_hash
    assert root.execution_allowed is False and root.must_not_execute is True
    assert len(root.to_payload()["operator"]["authentication_source_content_hash"]) == 64  # type: ignore[index]


def test_role_change_and_revoke_state_machine_and_source_continuity() -> None:
    root = _binding()
    changed = _binding("role_change", previous=root, new_role="admin")
    revoked = _binding("revoke", previous=changed, new_role="admin")
    validate_account_rbac_authority_mutation_binding_v3_successor(root, changed)
    validate_account_rbac_authority_mutation_binding_v3_successor(changed, revoked)
    assert changed.old_rbac_role != changed.new_rbac_role
    assert changed.old_subject == root.subject
    assert changed.old_subject.profile_content_hash != changed.subject.profile_content_hash
    assert revoked.old_rbac_role == revoked.new_rbac_role
    assert (
        changed.authority_source_chain.supersedes_content_hash == root.authority_source_content_hash
    )
    assert revoked.new_authority_state == "revoked"


def test_profile_aba_or_old_reference_substitution_fails_closed() -> None:
    root = _binding()
    changed = _binding("role_change", previous=root, new_role="admin")
    with pytest.raises(ValueError):
        replace(
            changed,
            old_subject=replace(changed.old_subject, profile_content_hash="9" * 64),
        )
    with pytest.raises(ValueError):
        validate_account_rbac_authority_mutation_binding_v3_successor(
            root,
            replace(changed, old_subject=None),
        )


def test_reactivation_requires_new_exact_epoch_and_terminal_links() -> None:
    root = _binding()
    changed = _binding("role_change", previous=root, new_role="admin")
    revoked = _binding("revoke", previous=changed, new_role="admin")
    next_epoch = _epoch(
        2,
        previous=revoked.epoch,
        terminal_source_hash=revoked.authority_source_content_hash,
        terminal_binding_hash=revoked.content_hash,
    )
    validate_account_rbac_authority_source_epoch_v3_successor(
        revoked.epoch,
        next_epoch,
        terminal_authority_source_content_hash=revoked.authority_source_content_hash,
        terminal_mutation_binding_content_hash=revoked.content_hash,
    )
    reactivated = _binding("reactivate", previous=revoked, epoch=next_epoch, new_role="owner")
    validate_account_rbac_authority_mutation_binding_v3_successor(revoked, reactivated)
    assert reactivated.binding_chain.supersedes_content_hash == revoked.content_hash
    assert reactivated.authority_source_chain.root_claim_hash == next_epoch.root_claim_hash


def test_wrong_binding_or_source_predecessor_is_rejected() -> None:
    root = _binding()
    successor = _binding("role_change", previous=root, new_role="admin")
    object.__setattr__(successor.binding_chain, "supersedes_content_hash", "0" * 64)
    with pytest.raises(ValueError):
        validate_account_rbac_authority_mutation_binding_v3_successor(root, successor)


@pytest.mark.parametrize(
    ("kind", "old_state", "new_state", "old_role", "new_role"),
    [
        ("bootstrap", "current", "current", None, "owner"),
        ("role_change", "current", "current", "owner", "owner"),
        ("revoke", "revoked", "revoked", "owner", "owner"),
        ("reactivate", "current", "current", "owner", "admin"),
    ],
)
def test_invalid_state_machine_edges_fail_closed(
    kind: str,
    old_state: str,
    new_state: str,
    old_role: str | None,
    new_role: str,
) -> None:
    base = _binding()
    with pytest.raises(ValueError):
        replace(
            base,
            mutation_kind=kind,
            old_authority_state=old_state,
            new_authority_state=new_state,
            old_rbac_role=old_role,
            new_rbac_role=new_role,
        )


def test_full_clock_rejects_expired_operator_and_successor_discontinuity() -> None:
    root = _binding()
    successor = _binding("role_change", previous=root, new_role="admin")
    with pytest.raises(ValueError):
        replace(
            root,
            operator=_operator(valid_until=root.valid_until - timedelta(seconds=1)),
        )
    with pytest.raises(ValueError):
        validate_account_rbac_authority_mutation_binding_v3_successor(
            root,
            replace(successor, observed_at=root.recorded_at),
        )
    assert root.is_knowable_at(root.recorded_at)
    assert not root.is_knowable_at(root.recorded_at - timedelta(microseconds=1))


def test_exact_pit_selector_never_falls_back() -> None:
    root = _binding()
    changed = _binding("role_change", previous=root, new_role="admin")
    history = (root, changed)
    assert (
        select_exact_account_rbac_authority_mutation_binding_v3(
            history,
            mutation_id=root.mutation_id,
            source_version=root.source_version,
            expected_content_hash=root.content_hash,
            as_of=root.recorded_at,
        )
        == root
    )
    assert (
        select_exact_account_rbac_authority_mutation_binding_v3(
            history,
            mutation_id=root.mutation_id,
            source_version=root.source_version,
            expected_content_hash=changed.content_hash,
            as_of=changed.recorded_at,
        )
        is None
    )


def test_domain_module_has_no_external_runtime_dependency() -> None:
    path = Path("apps/account/domain/account_rbac_authority_mutation_binding_v3.py")
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert all(not name.startswith(("django", "pandas", "numpy", "requests")) for name in imports)
