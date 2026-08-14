from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import django
import pytest

os.environ["DJANGO_SETTINGS_MODULE"] = "tests.settings_account_actor_authority_source_v3"
django.setup()

from django.db import connection

from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Conflict,
    AccountActorAuthorityRawSourceV3Corruption,
    AccountActorAuthorityRawSourceV3Recorder,
)
from apps.account.application.account_rbac_authority_source_v3 import (
    PersistedAccountRbacAuthoritySourceV3,
)
from apps.account.domain.account_actor_authority_raw_source_primitives_v3 import (
    AccountAuthorityRawSourceChainV3,
    AccountAuthorityRawSourceClockV3,
    AccountAuthorityRawSourceIdentityV3,
)
from apps.account.domain.account_rbac_authority_source_v3 import (
    AccountRbacAuthoritySourceV3,
    root_claim_hash_for_account_rbac_authority_source_v3,
)
from apps.account.infrastructure.account_actor_authority_raw_source_models_v3 import (
    AccountRbacAuthoritySourceV3AnchorModel,
    AccountRbacAuthoritySourceV3Model,
)
from apps.account.infrastructure.account_rbac_authority_source_v3_repository import (
    DjangoAccountRbacAuthoritySourceV3Repository,
)

NOW = datetime(2026, 8, 14, 12, tzinfo=UTC)
RECORDER = AccountActorAuthorityRawSourceV3Recorder("account-rbac-recorder-v3")


class _Clock:
    def now(self) -> datetime:
        return NOW + timedelta(days=30)


def _source(
    *,
    source_id: str = "rbac-user-41",
    version: str = "v1",
    observed_at: datetime = NOW - timedelta(minutes=1),
    recorded_at: datetime = NOW,
    role: str = "owner",
    state: str = "current",
    predecessor: AccountRbacAuthoritySourceV3 | None = None,
) -> AccountRbacAuthoritySourceV3:
    chain = (
        AccountAuthorityRawSourceChainV3(
            root_claim_hash=root_claim_hash_for_account_rbac_authority_source_v3(
                source_id=source_id, user_id=41, actor_id="django-user:41"
            )
        )
        if predecessor is None
        else AccountAuthorityRawSourceChainV3(supersedes_content_hash=predecessor.content_hash)
    )
    return AccountRbacAuthoritySourceV3(
        identity=AccountAuthorityRawSourceIdentityV3(source_id, version),
        clock=AccountAuthorityRawSourceClockV3(
            observed_at, recorded_at, recorded_at + timedelta(hours=1)
        ),
        chain=chain,
        user_id=41,
        actor_id="django-user:41",
        rbac_role=role,
        authority_state=state,
    )


def _record(source: AccountRbacAuthoritySourceV3) -> PersistedAccountRbacAuthoritySourceV3:
    return PersistedAccountRbacAuthoritySourceV3(source, RECORDER)


@pytest.fixture(autouse=True)
def _schema() -> None:
    with connection.schema_editor() as editor:
        editor.create_model(AccountRbacAuthoritySourceV3AnchorModel)
        editor.create_model(AccountRbacAuthoritySourceV3Model)
    yield
    with connection.schema_editor() as editor:
        editor.delete_model(AccountRbacAuthoritySourceV3Model)
        editor.delete_model(AccountRbacAuthoritySourceV3AnchorModel)


def _repository() -> DjangoAccountRbacAuthoritySourceV3Repository:
    return DjangoAccountRbacAuthoritySourceV3Repository(clock=_Clock())


def test_root_append_exact_winner_and_permanent_pit_history() -> None:
    repository = _repository()
    source = _source()
    with repository.atomic():
        assert repository.append(
            _record(source), expected_predecessor_hash=None, recorded_at=source.clock.recorded_at
        ) == _record(source)

    before = source.clock.recorded_at - timedelta(microseconds=1)
    after_expiry = source.clock.valid_until + timedelta(days=1)
    assert (
        repository.get_winner(
            source_id=source.identity.source_id,
            source_version=source.identity.source_version,
            as_of=before,
        )
        is None
    )
    assert repository.get_exact_by_hash(
        source_id=source.identity.source_id,
        source_version=source.identity.source_version,
        expected_content_hash=source.content_hash,
        as_of=after_expiry,
    ) == _record(source)


def test_successor_and_revoked_terminal_head_never_fall_back() -> None:
    repository = _repository()
    root = _source()
    successor = _source(
        version="v2",
        observed_at=NOW + timedelta(minutes=1),
        recorded_at=NOW + timedelta(minutes=1),
        role="admin",
        predecessor=root,
    )
    revoked = _source(
        version="v3",
        observed_at=NOW + timedelta(minutes=2),
        recorded_at=NOW + timedelta(minutes=2),
        role="read_only",
        state="revoked",
        predecessor=successor,
    )
    with repository.atomic():
        repository.append(_record(root), expected_predecessor_hash=None, recorded_at=NOW)
        repository.append(
            _record(successor),
            expected_predecessor_hash=root.content_hash,
            recorded_at=successor.clock.recorded_at,
        )
        repository.append(
            _record(revoked),
            expected_predecessor_hash=successor.content_hash,
            recorded_at=revoked.clock.recorded_at,
        )

    assert repository.get_current_head(
        source_id=root.identity.source_id, as_of=revoked.clock.recorded_at
    ) == _record(revoked)
    assert repository.get_exact_by_hash(
        source_id=root.identity.source_id,
        source_version=root.identity.source_version,
        expected_content_hash=root.content_hash,
        as_of=revoked.clock.recorded_at,
    ) == _record(root)
    illegal = _source(
        version="v4",
        observed_at=NOW + timedelta(minutes=3),
        recorded_at=NOW + timedelta(minutes=3),
        predecessor=revoked,
    )
    with repository.atomic(), pytest.raises(AccountActorAuthorityRawSourceV3Conflict):
        repository.append(
            _record(illegal),
            expected_predecessor_hash=revoked.content_hash,
            recorded_at=illegal.clock.recorded_at,
        )


def test_every_selector_restores_whole_table_and_detects_unrelated_tamper() -> None:
    repository = _repository()
    first = _source()
    other = _source(source_id="rbac-user-42")
    with repository.atomic():
        repository.append(_record(first), expected_predecessor_hash=None, recorded_at=NOW)
        repository.append(_record(other), expected_predecessor_hash=None, recorded_at=NOW)
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE account_rbac_authority_source_v3_ledger SET actor_id = %s WHERE source_id = %s",
            ["django-user:999", other.identity.source_id],
        )

    with pytest.raises(AccountActorAuthorityRawSourceV3Corruption, match="actor_id"):
        repository.get_exact_by_hash(
            source_id=first.identity.source_id,
            source_version=first.identity.source_version,
            expected_content_hash=first.content_hash,
            as_of=NOW,
        )


def test_append_requires_private_nonnested_uow_and_failure_rolls_back_anchor() -> None:
    repository = _repository()
    source = _source()
    with pytest.raises(AccountActorAuthorityRawSourceV3Conflict, match="private"):
        repository.append(_record(source), expected_predecessor_hash=None, recorded_at=NOW)
    with repository.atomic():
        with pytest.raises(AccountActorAuthorityRawSourceV3Conflict, match="nested"):
            with repository.atomic():
                pass
        with pytest.raises(AccountActorAuthorityRawSourceV3Conflict, match="CAS"):
            repository.append(_record(source), expected_predecessor_hash="f" * 64, recorded_at=NOW)
    assert AccountRbacAuthoritySourceV3AnchorModel.objects.count() == 0
    assert AccountRbacAuthoritySourceV3Model.objects.count() == 0


def test_exact_replay_is_idempotent_but_different_winner_conflicts() -> None:
    repository = _repository()
    source = _source()
    with repository.atomic():
        repository.append(_record(source), expected_predecessor_hash=None, recorded_at=NOW)
        assert repository.append(
            _record(source), expected_predecessor_hash=None, recorded_at=NOW
        ) == _record(source)
        replacement = _source(role="admin")
        with pytest.raises(AccountActorAuthorityRawSourceV3Conflict, match="winner"):
            repository.append(_record(replacement), expected_predecessor_hash=None, recorded_at=NOW)
