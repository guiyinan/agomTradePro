"""Persistence contracts for realtime alerts and subscriptions."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from apps.realtime.domain.entities import AlertCondition, AlertStatus, PriceAlert
from apps.realtime.infrastructure.models import (
    PriceAlertModel,
    PriceSubscriptionModel,
)
from apps.realtime.infrastructure.repositories import (
    DjangoPriceAlertRepository,
    DjangoPriceSubscriptionRepository,
    RedisRealtimePriceRepository,
)


def test_cached_price_deserialization_preserves_decimal_zero_values() -> None:
    """Cached numeric strings and zero changes retain their domain semantics."""

    cached = {
        "asset_code": "510300.SH",
        "asset_type": "fund",
        "price": "3.500001",
        "change": 0,
        "change_pct": "0",
        "volume": 123,
        "timestamp": "2026-07-22T09:30:00+08:00",
        "source": "redis-test",
    }

    price = RedisRealtimePriceRepository()._dict_to_price(cached)

    assert price.price == Decimal("3.500001")
    assert isinstance(price.price, Decimal)
    assert price.change == Decimal("0")
    assert price.change_pct == Decimal("0")


@pytest.fixture
def owners(db):
    user_model = get_user_model()
    return (
        user_model.objects.create_user(username="realtime-owner-a"),
        user_model.objects.create_user(username="realtime-owner-b"),
    )


def _alert(owner_id: int, **overrides: object) -> PriceAlert:
    values: dict[str, object] = {
        "owner_id": owner_id,
        "asset_code": "510300.SH",
        "condition": AlertCondition.CROSS_UP,
        "threshold": Decimal("3.500001"),
        "message": "突破提醒",
    }
    values.update(overrides)
    return PriceAlert(**values)


@pytest.mark.django_db
def test_alert_repository_is_owner_scoped_for_every_mutation(owners) -> None:
    owner, other = owners
    repository = DjangoPriceAlertRepository()
    created = repository.create(_alert(owner.id))

    assert repository.list_for_owner(owner.id) == [created]
    assert repository.list_for_owner(other.id) == []
    assert repository.get_for_owner(other.id, created.id or 0) is None
    assert repository.delete(other.id, created.id or 0) is False
    assert repository.update(replace(created, owner_id=other.id, message="hijack")) is None
    assert repository.get_for_owner(owner.id, created.id or 0) == created


@pytest.mark.django_db
def test_alert_repository_updates_and_deletes_owner_record(owners) -> None:
    owner, _ = owners
    repository = DjangoPriceAlertRepository()
    created = repository.create(_alert(owner.id))

    updated = repository.update(
        replace(
            created,
            condition=AlertCondition.BELOW,
            threshold=Decimal("3.1"),
            status=AlertStatus.INACTIVE,
            message="跌破提醒",
        )
    )

    assert updated is not None
    assert updated.condition is AlertCondition.BELOW
    assert updated.threshold == Decimal("3.1")
    assert updated.status is AlertStatus.INACTIVE
    assert repository.delete(owner.id, created.id or 0) is True
    assert repository.get_for_owner(owner.id, created.id or 0) is None


@pytest.mark.django_db
def test_subscription_constraint_and_reactivation(owners) -> None:
    owner, _ = owners
    repository = DjangoPriceSubscriptionRepository()

    first = repository.subscribe(owner.id, " 510300.sh ")
    duplicate = repository.subscribe(owner.id, "510300.SH")
    assert duplicate.id == first.id
    assert repository.count_active(owner.id) == 1

    with transaction.atomic(), pytest.raises(IntegrityError):
        PriceSubscriptionModel.objects.create(
            owner=owner,
            asset_code="510300.SH",
            is_active=True,
        )

    assert repository.unsubscribe(owner.id, "510300.sh") is True
    assert repository.unsubscribe(owner.id, "510300.sh") is False
    reactivated = repository.subscribe(owner.id, "510300.sh")
    assert reactivated.id == first.id
    assert reactivated.is_active is True


@pytest.mark.django_db
def test_subscription_repository_is_owner_scoped_and_lists_distinct_assets(owners) -> None:
    owner, other = owners
    repository = DjangoPriceSubscriptionRepository()
    repository.subscribe(owner.id, "510300.sh")
    repository.subscribe(other.id, "510300.sh")
    repository.subscribe(other.id, "000001.sz")

    assert [item.asset_code for item in repository.list_for_owner(owner.id)] == ["510300.SH"]
    assert repository.unsubscribe(owner.id, "000001.SZ") is False
    assert repository.list_active_asset_codes() == ["000001.SZ", "510300.SH"]


@pytest.mark.django_db
def test_claim_trigger_transitions_an_active_alert_exactly_once(owners) -> None:
    owner, _ = owners
    repository = DjangoPriceAlertRepository()
    created = repository.create(_alert(owner.id))
    now = datetime.now(UTC)

    claimed = repository.claim_trigger(created.id or 0, Decimal("3.6"), now)
    repeated = repository.claim_trigger(created.id or 0, Decimal("3.7"), now)

    assert claimed is not None
    assert claimed.status is AlertStatus.TRIGGERED
    assert claimed.triggered_price == Decimal("3.6")
    assert claimed.triggered_at == now
    assert repeated is None
    assert (
        PriceAlertModel.objects.filter(
            id=created.id,
            status=AlertStatus.TRIGGERED.value,
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_claim_trigger_ignores_inactive_alerts(owners) -> None:
    owner, _ = owners
    repository = DjangoPriceAlertRepository()
    inactive = repository.create(_alert(owner.id, status=AlertStatus.INACTIVE))

    assert (
        repository.claim_trigger(
            inactive.id or 0,
            Decimal("3.6"),
            datetime.now(UTC),
        )
        is None
    )
