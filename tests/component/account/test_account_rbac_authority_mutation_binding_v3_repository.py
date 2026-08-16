from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings_account_actor_authority_source_v3")
django.setup()

from django.core.exceptions import ValidationError

from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Conflict,
    AccountActorAuthorityRawSourceV3Corruption,
    AccountActorAuthorityRawSourceV3Unavailable,
)
from apps.account.infrastructure.account_actor_authority_raw_source_models_v3 import (
    AccountRbacAuthoritySourceV3AnchorModel,
    AccountRbacAuthoritySourceV3Model,
)
from apps.account.infrastructure.account_rbac_authority_mutation_binding_v3_models import (
    AccountRbacAuthorityMutationBindingV3Model,
    AccountRbacAuthorityMutationEpochV3AnchorModel,
    AccountRbacAuthorityProfileV3AnchorModel,
    AccountRbacAuthorityProfileV3VersionModel,
)
from apps.account.infrastructure.account_rbac_authority_mutation_binding_v3_repository import (
    DjangoAccountRbacAuthorityMutationBindingV3Repository,
)
from tests.support.isolated_schema import isolated_schema

SCHEMA_MODELS = (
    AccountRbacAuthoritySourceV3AnchorModel,
    AccountRbacAuthoritySourceV3Model,
    AccountRbacAuthorityMutationEpochV3AnchorModel,
    AccountRbacAuthorityProfileV3AnchorModel,
    AccountRbacAuthorityProfileV3VersionModel,
    AccountRbacAuthorityMutationBindingV3Model,
)


@pytest.fixture(autouse=True)
def _schema(django_db_blocker: object) -> Iterator[None]:
    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        with isolated_schema(SCHEMA_MODELS):
            yield


def test_empty_world_readers_are_stable_and_do_not_seed() -> None:
    as_of = datetime(2026, 8, 14, tzinfo=UTC)
    repository = DjangoAccountRbacAuthorityMutationBindingV3Repository(clock=_FixedClock(as_of))

    assert (
        repository.get_winner(
            mutation_id="mutation-1", source_id="epoch-1", source_version="v1", as_of=as_of
        )
        is None
    )
    assert repository.get_current_head(source_id="epoch-1", as_of=as_of) is None
    assert (
        repository.get_exact_by_hash(
            mutation_id="mutation-1",
            source_id="epoch-1",
            source_version="v1",
            expected_content_hash="a" * 64,
            as_of=as_of,
        )
        is None
    )
    assert AccountRbacAuthorityMutationEpochV3AnchorModel.objects.count() == 0
    assert AccountRbacAuthorityMutationBindingV3Model.objects.count() == 0


def test_future_cutoff_and_naive_clock_fail_closed() -> None:
    now = datetime(2026, 8, 14, tzinfo=UTC)
    repository = DjangoAccountRbacAuthorityMutationBindingV3Repository(clock=_FixedClock(now))
    with pytest.raises(AccountActorAuthorityRawSourceV3Unavailable):
        repository.get_current_head(source_id="epoch-1", as_of=now.replace(year=2027))
    with pytest.raises(AccountActorAuthorityRawSourceV3Unavailable):
        repository.get_current_head(source_id="epoch-1", as_of=datetime(2026, 8, 14))
    with pytest.raises(AccountActorAuthorityRawSourceV3Corruption):
        DjangoAccountRbacAuthorityMutationBindingV3Repository(
            clock=_FixedClock(datetime(2026, 8, 14))
        ).now()


def test_atomic_is_non_nested_and_append_requires_the_private_uow() -> None:
    now = datetime(2026, 8, 14, tzinfo=UTC)
    repository = DjangoAccountRbacAuthorityMutationBindingV3Repository(clock=_FixedClock(now))
    with pytest.raises(AccountActorAuthorityRawSourceV3Corruption):
        repository.append(object(), expected_predecessor_hash=None, recorded_at=now)  # type: ignore[arg-type]
    with repository.atomic():
        with pytest.raises(AccountActorAuthorityRawSourceV3Conflict, match="nested"):
            with repository.atomic():
                pass


def test_direct_model_mutations_remain_blocked_even_with_repository_present() -> None:
    row = AccountRbacAuthorityMutationEpochV3AnchorModel()
    with pytest.raises(ValidationError):
        row.save()
    with pytest.raises(ValidationError):
        AccountRbacAuthorityMutationEpochV3AnchorModel.objects.all().update()
    with pytest.raises(ValidationError):
        AccountRbacAuthorityMutationEpochV3AnchorModel.objects.all().delete()


class _FixedClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value
