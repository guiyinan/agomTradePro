"""Protect sealed fee versions from stale model instances held by listeners."""

from collections.abc import Iterator

import pytest
from django.core.exceptions import ValidationError
from django.db.models.signals import post_delete, post_save

from apps.simulated_trading.infrastructure.fee_policy_v2_repository import (
    DjangoFeePolicyV2Repository,
)
from apps.simulated_trading.infrastructure.models import FeeConfigModel, FeeConfigQuerySet
from tests.component.simulated_trading.test_fee_policy_v2_repository import _command
from tests.support.isolated_schema import isolated_schema

pytestmark = pytest.mark.django_db(transaction=True, available_apps=["apps.simulated_trading"])


@pytest.fixture(autouse=True)
def _schema() -> Iterator[None]:
    with isolated_schema((FeeConfigModel,)):
        yield


def test_post_save_shell_instance_cannot_delete_a_subsequently_sealed_version() -> None:
    """An actual save listener must not retain a deletion bypass after finalization."""

    shells: list[FeeConfigModel] = []

    def remember_shell(instance: FeeConfigModel, **_kwargs: object) -> None:
        shells.append(instance)

    post_save.connect(remember_shell, sender=FeeConfigModel, weak=False)
    try:
        policy = DjangoFeePolicyV2Repository(using="default").create_fee_policy_version(_command())
    finally:
        post_save.disconnect(remember_shell, sender=FeeConfigModel)

    assert len(shells) == 1
    stale = shells[0]
    assert stale.pk == policy.fee_schedule_v1.config_id
    assert stale.fee_policy_id is None
    assert FeeConfigModel.objects.get(pk=stale.pk).fee_policy_id == policy.policy_id

    with pytest.raises(ValidationError):
        stale.delete()

    assert FeeConfigModel.objects.count() == 1
    assert FeeConfigModel.objects.get().fee_policy_content_hash == policy.content_hash


def test_legacy_bulk_update_cannot_capture_a_new_strict_row_after_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A strict insert between the check and SQL must remain outside a broad update."""

    legacy = FeeConfigModel.objects.create(
        config_name="fixture-mutable-legacy", asset_type="all", min_commission=5.0
    )
    original_exists = FeeConfigQuerySet.exists
    inserted_ids: list[int] = []
    insert_started = False

    def insert_after_absence(query: FeeConfigQuerySet) -> bool:
        nonlocal insert_started
        result = original_exists(query)
        if not result and not insert_started:
            insert_started = True
            policy = DjangoFeePolicyV2Repository(using="default").create_fee_policy_version(
                _command()
            )
            inserted_ids.append(policy.fee_schedule_v1.config_id)
        return result

    monkeypatch.setattr(FeeConfigQuerySet, "exists", insert_after_absence)
    changed = FeeConfigModel.objects.filter(asset_type="all").update(commission_rate_buy=0.07)

    assert len(inserted_ids) == 1
    assert changed == 1
    legacy.refresh_from_db()
    assert legacy.commission_rate_buy == 0.07
    strict = FeeConfigModel.objects.get(pk=inserted_ids[0])
    assert strict.commission_rate_buy == _command().commission_rate_buy
    assert strict.fee_policy_id is not None


def test_legacy_queryset_deletion_preserves_django_delete_signals() -> None:
    """Protecting strict versions must preserve the existing legacy deletion contract."""

    legacy = FeeConfigModel.objects.create(
        config_name="fixture-delete-legacy", asset_type="all", min_commission=5.0
    )
    deleted_ids: list[int] = []

    def remember_deletion(instance: FeeConfigModel, **_kwargs: object) -> None:
        assert isinstance(instance.pk, int)
        deleted_ids.append(instance.pk)

    post_delete.connect(remember_deletion, sender=FeeConfigModel, weak=False)
    try:
        deleted, details = FeeConfigModel.objects.filter(pk=legacy.pk).delete()
    finally:
        post_delete.disconnect(remember_deletion, sender=FeeConfigModel)

    assert deleted == 1
    assert details == {FeeConfigModel._meta.label: 1}
    assert deleted_ids == [legacy.pk]
    assert FeeConfigModel.objects.count() == 0
