from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest

from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Conflict,
    AccountActorAuthorityRawSourceV3Corruption,
)
from apps.account.application.account_rbac_authority_mutation_binding_v3 import (
    AccountRbacAuthorityMutationBindingV3Command,
    AccountRbacAuthorityMutationBindingV3Identity,
    AccountRbacAuthorityMutationBindingV3Selector,
    GetCurrentAccountRbacAuthorityMutationBindingV3,
    GetExactAccountRbacAuthorityMutationBindingV3,
    PersistedAccountRbacAuthorityMutationBindingV3,
    RecordAccountRbacAuthorityMutationBindingV3,
)
from apps.account.domain.account_actor_authority_raw_source_primitives_v3 import (
    AccountAuthorityRawSourceChainV3,
    AccountAuthorityRawSourceClockV3,
)
from apps.account.domain.account_rbac_authority_mutation_binding_v3 import (
    AccountRbacAuthorityHumanOperatorRefV3,
    AccountRbacAuthorityProfileStateRefV3,
    AccountRbacAuthoritySourceEpochV3,
)
from apps.account.domain.account_rbac_authority_source_v3 import (
    AccountRbacAuthoritySourceV3,
    root_claim_hash_for_account_rbac_authority_source_v3,
)
from tests.unit.account.test_account_rbac_authority_mutation_binding_v3 import _binding
from tests.unit.account.test_account_rbac_authority_source_v3 import _source

NOW = datetime(2026, 8, 14, 10, tzinfo=UTC)


def _writer_profile(version: str, content_hash: str, role: str = "owner"):
    return AccountRbacAuthorityProfileStateRefV3(
        "profile-41",
        version,
        content_hash,
        role,
        41,
        "django-user:41",
        NOW - timedelta(minutes=2),
    )


def _writer_operator() -> AccountRbacAuthorityHumanOperatorRefV3:
    return AccountRbacAuthorityHumanOperatorRefV3(
        principal_id="admin-principal-7",
        user_id=7,
        actor_id="django-user:7",
        is_authenticated=True,
        is_active=True,
        is_staff=True,
        is_superuser=False,
        rbac_role="admin",
        authentication_source_id="session-7",
        authentication_source_version="a1",
        authentication_source_content_hash="2" * 64,
        user_source_id="user-7",
        user_source_version="u1",
        user_source_content_hash="3" * 64,
        rbac_source_id="rbac-7",
        rbac_source_version="r1",
        rbac_source_content_hash="4" * 64,
        observed_at=NOW - timedelta(minutes=3),
        valid_until=NOW + timedelta(hours=2),
    )


def _writer_source() -> AccountRbacAuthoritySourceV3:
    return _source(
        source_id="epoch-source-1",
        source_version="raw-1",
        user_id=41,
        actor_id="django-user:41",
        rbac_role="owner",
        clock=AccountAuthorityRawSourceClockV3(
            NOW - timedelta(minutes=1), NOW, NOW + timedelta(hours=1)
        ),
        chain=AccountAuthorityRawSourceChainV3(
            root_claim_hash=root_claim_hash_for_account_rbac_authority_source_v3(
                source_id="epoch-source-1", user_id=41, actor_id="django-user:41"
            )
        ),
    )


class _WriterUow:
    def __init__(self) -> None:
        self.source = _writer_source()
        self.subject = _writer_profile("p1", "1" * 64)
        self.operator = _writer_operator()
        self.epoch = AccountRbacAuthoritySourceEpochV3(
            epoch_id="epoch-41-1",
            target_user_id=41,
            subject_actor_id="django-user:41",
            source_id=self.source.identity.source_id,
            epoch_sequence=1,
            opened_at=NOW - timedelta(minutes=3),
        )
        self.identity = AccountRbacAuthorityMutationBindingV3Identity(
            "mutation-1", self.source.identity.source_version, self.epoch
        )
        self.records: list[PersistedAccountRbacAuthorityMutationBindingV3] = []
        self.calls: list[str] = []
        self.times = [NOW + timedelta(minutes=2), NOW + timedelta(minutes=2, seconds=1)]

    @contextmanager
    def atomic(self) -> Iterator[None]:
        self.calls.append("atomic")
        yield

    def now(self) -> datetime:
        self.calls.append("now")
        return self.times.pop(0) if self.times else NOW + timedelta(minutes=2, seconds=1)

    def resolve_identity(self, *, mutation_id: str, target_user_id: int):
        self.calls.append("identity")
        assert (mutation_id, target_user_id) == (self.identity.mutation_id, 41)
        return self.identity

    def get_winner(self, *, mutation_id: str, source_id: str, source_version: str, as_of: datetime):
        self.calls.append("winner")
        return next(
            (
                item
                for item in self.records
                if (
                    item.binding.mutation_id,
                    item.binding.epoch.source_id,
                    item.binding.source_version,
                )
                == (mutation_id, source_id, source_version)
                and item.binding.recorded_at <= as_of
            ),
            None,
        )

    def get_current_head(self, *, source_id: str, as_of: datetime):
        self.calls.append("head")
        values = [
            item
            for item in self.records
            if item.binding.epoch.source_id == source_id and item.binding.recorded_at <= as_of
        ]
        return values[-1] if values else None

    def get_terminal_head(self, *, target_user_id: int, as_of: datetime):
        self.calls.append("terminal")
        values = [
            item
            for item in self.records
            if item.binding.epoch.target_user_id == target_user_id
            and item.binding.recorded_at <= as_of
        ]
        return values[-1] if values else None

    def get_exact_profile(
        self,
        *,
        profile_id: str,
        profile_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ):
        self.calls.append("profile")
        value = self.subject
        if (
            value.profile_id,
            value.profile_version,
            value.profile_content_hash,
        ) == (profile_id, profile_version, expected_content_hash):
            return value
        return None

    def get_human_operator(
        self, *, principal_id: str, expected_authority_hash: str, as_of: datetime
    ):
        self.calls.append("operator")
        return self.operator

    def get_exact_raw_source(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ):
        self.calls.append("raw_exact")
        return self.source

    def get_current_raw_source(
        self, *, source_id: str, expected_content_hash: str, as_of: datetime
    ):
        self.calls.append("raw_current")
        return self.source

    def append(
        self,
        record: PersistedAccountRbacAuthorityMutationBindingV3,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountRbacAuthorityMutationBindingV3:
        self.calls.append("append")
        assert expected_predecessor_hash is None
        assert recorded_at == record.binding.recorded_at
        self.records.append(record)
        return record


def _writer_command() -> AccountRbacAuthorityMutationBindingV3Command:
    return AccountRbacAuthorityMutationBindingV3Command(
        mutation_id="mutation-1",
        mutation_kind="bootstrap",
        target_user_id=41,
        new_profile_id="profile-41",
        new_profile_version="p1",
        expected_new_profile_content_hash="1" * 64,
        operator_principal_id="admin-principal-7",
        expected_operator_authority_hash=_writer_operator().authority_hash,
        expected_authority_source_content_hash=_writer_source().content_hash,
    )


class _Repository:
    def __init__(self) -> None:
        root = _binding()
        changed = _binding("role_change", previous=root, new_role="admin")
        self.records = [
            PersistedAccountRbacAuthorityMutationBindingV3(root),
            PersistedAccountRbacAuthorityMutationBindingV3(changed),
        ]
        self.return_future = False
        self.return_substitution = False

    @contextmanager
    def atomic(self) -> Iterator[None]:
        yield

    def now(self) -> datetime:
        return NOW

    def get_winner(self, **kwargs: object):
        return self.get_exact_by_hash(
            **kwargs, expected_content_hash=kwargs["expected_content_hash"]
        )

    def get_current_head(self, *, source_id: str, as_of: datetime):
        records = [
            record
            for record in self.records
            if record.binding.epoch.source_id == source_id
            and (self.return_future or record.binding.recorded_at <= as_of)
        ]
        return records[-1] if records else None

    def get_exact_by_hash(
        self,
        *,
        mutation_id: str,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ):
        if self.return_substitution:
            return self.records[0]
        for record in self.records:
            binding = record.binding
            if (
                binding.mutation_id,
                binding.epoch.source_id,
                binding.source_version,
                binding.content_hash,
            ) == (mutation_id, source_id, source_version, expected_content_hash):
                if self.return_future or binding.recorded_at <= as_of:
                    return record
        return None

    def append(self, record, *, expected_predecessor_hash: str | None, recorded_at: datetime):
        self.records.append(record)
        return record


def _selector(binding, as_of: datetime) -> AccountRbacAuthorityMutationBindingV3Selector:
    return AccountRbacAuthorityMutationBindingV3Selector(
        mutation_id=binding.mutation_id,
        source_id=binding.epoch.source_id,
        source_version=binding.source_version,
        expected_content_hash=binding.content_hash,
        as_of=as_of,
    )


def test_exact_is_permanent_recorded_knowledge_and_current_is_final_head_only() -> None:
    repository = _Repository()
    root = repository.records[0].binding
    changed = repository.records[1].binding
    exact = GetExactAccountRbacAuthorityMutationBindingV3(repository)
    current = GetCurrentAccountRbacAuthorityMutationBindingV3(repository)

    assert exact.execute(_selector(root, NOW + timedelta(days=1))) == root
    assert current.execute(_selector(root, root.recorded_at)) == root
    assert current.execute(_selector(root, changed.recorded_at)) is None
    assert current.execute(_selector(changed, changed.recorded_at)) == changed


def test_terminal_final_head_is_exactly_readable_but_never_current() -> None:
    repository = _Repository()
    changed = repository.records[1].binding
    revoked = _binding("revoke", previous=changed, new_role="admin")
    repository.records.append(PersistedAccountRbacAuthorityMutationBindingV3(revoked))
    selector = _selector(revoked, revoked.recorded_at)

    assert GetExactAccountRbacAuthorityMutationBindingV3(repository).execute(selector) == revoked
    assert GetCurrentAccountRbacAuthorityMutationBindingV3(repository).execute(selector) is None


def test_writer_returns_complete_persisted_binding_and_replay_has_no_live_reads() -> None:
    uow = _WriterUow()
    writer = RecordAccountRbacAuthorityMutationBindingV3(uow)
    command = _writer_command()

    first = writer.execute(command)
    assert type(first) is PersistedAccountRbacAuthorityMutationBindingV3
    assert first.binding.old_subject is None
    assert first.binding.authority_source_content_hash == uow.source.content_hash
    assert first.binding.subject == uow.subject
    assert first.binding.operator == uow.operator

    uow.calls.clear()
    replay = writer.execute(command)

    assert replay == first
    assert uow.calls == ["atomic", "now", "identity", "winner"]


def test_writer_command_is_id_hash_only_and_application_has_no_infrastructure_or_orm() -> None:
    command = _writer_command()
    assert command.mutation_kind == "bootstrap"
    source = open(
        "apps/account/application/account_rbac_authority_mutation_binding_v3.py",
        encoding="utf-8",
    ).read()
    assert "normalize_role" not in source
    assert ".objects" not in source
    assert "apps.account.infrastructure" not in source


def test_writer_rejects_raw_role_substitution_against_exact_profile() -> None:
    uow = _WriterUow()
    uow.source = _source(
        source_id="epoch-source-1",
        source_version="raw-1",
        user_id=41,
        actor_id="django-user:41",
        rbac_role="admin",
        clock=AccountAuthorityRawSourceClockV3(
            NOW - timedelta(minutes=1), NOW, NOW + timedelta(hours=1)
        ),
        chain=AccountAuthorityRawSourceChainV3(
            root_claim_hash=root_claim_hash_for_account_rbac_authority_source_v3(
                source_id="epoch-source-1", user_id=41, actor_id="django-user:41"
            )
        ),
    )
    command = _writer_command()
    command = AccountRbacAuthorityMutationBindingV3Command(
        mutation_id=command.mutation_id,
        mutation_kind=command.mutation_kind,
        target_user_id=command.target_user_id,
        new_profile_id=command.new_profile_id,
        new_profile_version=command.new_profile_version,
        expected_new_profile_content_hash=command.expected_new_profile_content_hash,
        operator_principal_id=command.operator_principal_id,
        expected_operator_authority_hash=command.expected_operator_authority_hash,
        expected_authority_source_content_hash=uow.source.content_hash,
    )
    with pytest.raises(AccountActorAuthorityRawSourceV3Conflict):
        RecordAccountRbacAuthorityMutationBindingV3(uow).execute(command)
    assert uow.records == []


def test_future_repository_row_is_corruption_not_unavailable() -> None:
    repository = _Repository()
    repository.return_future = True
    root = repository.records[0].binding
    selector = _selector(root, root.recorded_at - timedelta(days=1))

    with pytest.raises(AccountActorAuthorityRawSourceV3Corruption):
        GetExactAccountRbacAuthorityMutationBindingV3(repository).execute(selector)


def test_selector_type_and_hash_substitution_fail_closed() -> None:
    repository = _Repository()
    root = repository.records[0].binding
    reader = GetExactAccountRbacAuthorityMutationBindingV3(repository)
    with pytest.raises(AccountActorAuthorityRawSourceV3Corruption):
        reader.execute(object())  # type: ignore[arg-type]
    repository.return_substitution = True
    with pytest.raises(AccountActorAuthorityRawSourceV3Corruption):
        reader.execute(
            AccountRbacAuthorityMutationBindingV3Selector(
                mutation_id=root.mutation_id,
                source_id=root.epoch.source_id,
                source_version=root.source_version,
                expected_content_hash="0" * 64,
                as_of=root.recorded_at,
            )
        )
