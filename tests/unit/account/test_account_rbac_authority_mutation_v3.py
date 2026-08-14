from __future__ import annotations

import ast
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Conflict,
    AccountActorAuthorityRawSourceV3Recorder,
)
from apps.account.application.account_rbac_authority_mutation_v3 import (
    AccountRbacAuthorityMutationIdentityV3,
    AccountRbacAuthorityMutationObservationV3,
    AccountRbacAuthorityProfileStateV3,
    SetAccountRbacAuthorityRoleV3,
    SetAccountRbacAuthorityRoleV3Command,
)
from apps.account.application.account_rbac_authority_source_v3 import (
    PersistedAccountRbacAuthoritySourceV3,
)
from tests.unit.account.test_account_rbac_authority_source_v3 import _source

NOW = datetime(2026, 8, 14, 10, tzinfo=UTC)


class _Uow:
    def __init__(self) -> None:
        self.profile = AccountRbacAuthorityProfileStateV3(41, "django-user:41", "owner")
        self.records: list[PersistedAccountRbacAuthoritySourceV3] = []
        self.profile_reads = 0
        self.times = [NOW, NOW + timedelta(seconds=2)]
        self.observed_at = NOW + timedelta(seconds=1)
        self.fail_append = False

    @contextmanager
    def atomic(self) -> Iterator[None]:
        old_profile, old_records = self.profile, list(self.records)
        try:
            yield
        except Exception:
            self.profile, self.records = old_profile, old_records
            raise

    def now(self) -> datetime:
        return self.times.pop(0) if self.times else NOW + timedelta(seconds=3)

    def resolve_source_identity(
        self, *, target_user_id: int, mutation_id: str
    ) -> AccountRbacAuthorityMutationIdentityV3:
        return AccountRbacAuthorityMutationIdentityV3(
            f"profile-rbac:{target_user_id}", f"mutation:{mutation_id}"
        )

    def get_winner(
        self, *, source_id: str, source_version: str, as_of: datetime
    ) -> PersistedAccountRbacAuthoritySourceV3 | None:
        return next(
            (
                item
                for item in self.records
                if (item.source.identity.source_id, item.source.identity.source_version)
                == (source_id, source_version)
            ),
            None,
        )

    def get_current_head(
        self, *, source_id: str, as_of: datetime
    ) -> PersistedAccountRbacAuthoritySourceV3 | None:
        matches = [item for item in self.records if item.source.identity.source_id == source_id]
        return matches[-1] if matches else None

    def lock_profile(self, *, user_id: int) -> AccountRbacAuthorityProfileStateV3 | None:
        self.profile_reads += 1
        return self.profile

    def compare_and_set_profile(
        self, *, expected: AccountRbacAuthorityProfileStateV3, new_rbac_role: str
    ) -> AccountRbacAuthorityMutationObservationV3:
        if expected != self.profile:
            raise AccountActorAuthorityRawSourceV3Conflict("CAS drift")
        self.profile = AccountRbacAuthorityProfileStateV3(
            expected.user_id, expected.actor_id, new_rbac_role
        )
        return AccountRbacAuthorityMutationObservationV3(self.profile, self.observed_at)

    def append(
        self,
        record: PersistedAccountRbacAuthoritySourceV3,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountRbacAuthoritySourceV3:
        if self.fail_append:
            raise AccountActorAuthorityRawSourceV3Conflict("append CAS")
        actual = self.records[-1].source.content_hash if self.records else None
        if actual != expected_predecessor_hash:
            raise AccountActorAuthorityRawSourceV3Conflict("append CAS")
        self.records.append(record)
        return record


def test_root_and_successor_are_atomic_server_issued_sources() -> None:
    uow = _Uow()
    writer = SetAccountRbacAuthorityRoleV3(uow)
    root = writer.execute(SetAccountRbacAuthorityRoleV3Command(41, "m1", "admin"))
    assert root.chain.root_claim_hash is not None
    assert root.clock.observed_at == NOW + timedelta(seconds=1)
    uow.times = [NOW + timedelta(minutes=1), NOW + timedelta(minutes=1, seconds=2)]
    uow.observed_at = NOW + timedelta(minutes=1, seconds=1)
    successor = writer.execute(SetAccountRbacAuthorityRoleV3Command(41, "m2", "risk"))
    assert successor.chain.supersedes_content_hash == root.content_hash
    assert successor.identity.source_version == "mutation:m2"


def test_winner_replay_has_zero_profile_reads() -> None:
    uow = _Uow()
    writer = SetAccountRbacAuthorityRoleV3(uow)
    command = SetAccountRbacAuthorityRoleV3Command(41, "m1", "admin")
    expected = writer.execute(command)
    uow.profile_reads = 0
    uow.times = [NOW + timedelta(minutes=1)]
    assert writer.execute(command) == expected
    assert uow.profile_reads == 0


def test_terminal_head_blocks_before_profile_mutation() -> None:
    uow = _Uow()
    terminal = _source(source_id="profile-rbac:41", authority_state="revoked", rbac_role="owner")
    uow.records = [
        PersistedAccountRbacAuthoritySourceV3(
            terminal,
            AccountActorAuthorityRawSourceV3Recorder("account-rbac-authority-mutation-v3"),
        )
    ]
    with pytest.raises(AccountActorAuthorityRawSourceV3Conflict):
        SetAccountRbacAuthorityRoleV3(uow).execute(
            SetAccountRbacAuthorityRoleV3Command(41, "m2", "admin")
        )
    assert uow.profile.rbac_role == "owner"


def test_expired_final_head_remains_the_only_valid_successor_predecessor() -> None:
    uow = _Uow()
    writer = SetAccountRbacAuthorityRoleV3(uow)
    root = writer.execute(SetAccountRbacAuthorityRoleV3Command(41, "m1", "admin"))
    uow.times = [NOW + timedelta(minutes=6), NOW + timedelta(minutes=6, seconds=2)]
    uow.observed_at = NOW + timedelta(minutes=6, seconds=1)

    successor = writer.execute(SetAccountRbacAuthorityRoleV3Command(41, "m2", "risk"))

    assert successor.chain.supersedes_content_hash == root.content_hash
    assert successor.rbac_role == "risk"


@pytest.mark.parametrize("failure", ["clock", "append"])
def test_clock_or_append_failure_rolls_back_profile(failure: str) -> None:
    uow = _Uow()
    if failure == "clock":
        uow.observed_at = NOW + timedelta(days=1)
    else:
        uow.fail_append = True
    with pytest.raises((AccountActorAuthorityRawSourceV3Conflict, ValueError)):
        SetAccountRbacAuthorityRoleV3(uow).execute(
            SetAccountRbacAuthorityRoleV3Command(41, "m1", "admin")
        )
    assert uow.profile.rbac_role == "owner"
    assert uow.records == []


@pytest.mark.parametrize("role", ["Admin", " admin", "admin ", "readonly", "", True])
def test_command_rejects_noncanonical_role(role: object) -> None:
    with pytest.raises(ValueError):
        SetAccountRbacAuthorityRoleV3Command(41, "m1", role)  # type: ignore[arg-type]


def test_dormant_application_contract_has_one_uow_and_no_orm_or_normalization() -> None:
    path = Path("apps/account/application/account_rbac_authority_mutation_v3.py")
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert all(not name.startswith(("django", "apps.account.infrastructure")) for name in imports)
    assert ".objects" not in source
    assert "normalize_role" not in source
    assert "ProfileMutationPort" not in source
