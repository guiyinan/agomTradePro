"""Integrity tests for Account classification and FX models."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.account.infrastructure.account_profile_repository import (
    AccountClassificationRepository,
)
from apps.account.infrastructure.classification_models import (
    AssetCategoryModel,
    CurrencyModel,
    ExchangeRateModel,
)


def _currency(*, code: str, is_base: bool = False, is_active: bool = True) -> CurrencyModel:
    return CurrencyModel._default_manager.create(
        code=code,
        name=code,
        symbol=code,
        is_base=is_base,
        is_active=is_active,
        precision=2,
    )


@pytest.mark.django_db
@pytest.mark.parametrize("precision", [-1, 9])
def test_currency_precision_database_constraint_rejects_invalid_values(precision: int) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        CurrencyModel._default_manager.create(
            code="USD",
            name="美元",
            symbol="$",
            precision=precision,
        )


@pytest.mark.django_db
def test_currency_database_constraints_require_one_active_base_at_most() -> None:
    _currency(code="CNY", is_base=True)

    with pytest.raises(IntegrityError), transaction.atomic():
        _currency(code="USD", is_base=True)

    inactive = _currency(code="ZZZ", is_base=False, is_active=False)
    with pytest.raises(IntegrityError), transaction.atomic():
        CurrencyModel._default_manager.filter(pk=inactive.pk).update(is_base=True)


@pytest.mark.django_db
def test_currency_clean_rejects_noncanonical_code() -> None:
    currency = CurrencyModel(
        code="usd",
        name="美元",
        symbol="$",
        precision=2,
    )

    with pytest.raises(ValidationError, match="大写 ASCII"):
        currency.full_clean()


@pytest.mark.django_db
@pytest.mark.parametrize("rate", [Decimal("0"), Decimal("-1")])
def test_exchange_rate_database_constraint_requires_positive_rate(rate: Decimal) -> None:
    usd = _currency(code="USD")
    cny = _currency(code="CNY", is_base=True)

    with pytest.raises(IntegrityError), transaction.atomic():
        ExchangeRateModel._default_manager.create(
            from_currency=usd,
            to_currency=cny,
            rate=rate,
            effective_date=date(2026, 7, 28),
        )


@pytest.mark.django_db
def test_exchange_rate_database_constraint_rejects_same_currency_pair() -> None:
    cny = _currency(code="CNY", is_base=True)

    with pytest.raises(IntegrityError), transaction.atomic():
        ExchangeRateModel._default_manager.create(
            from_currency=cny,
            to_currency=cny,
            rate=Decimal("1"),
            effective_date=date(2026, 7, 28),
        )


@pytest.mark.django_db
def test_exchange_rate_repository_rejects_inactive_currency() -> None:
    usd = _currency(code="USD", is_active=False)
    cny = _currency(code="CNY", is_base=True)

    with pytest.raises(ValidationError, match="启用状态"):
        AccountClassificationRepository().create_exchange_rate(
            from_currency=usd,
            to_currency=cny,
            rate=Decimal("7.1"),
            effective_date=date(2026, 7, 28),
        )

    assert not ExchangeRateModel._default_manager.exists()


@pytest.mark.django_db
def test_asset_category_constraints_and_ancestor_walk_fail_closed_on_cycles() -> None:
    root = AssetCategoryModel._default_manager.create(
        code="ROOT",
        name="根",
        level=1,
        path="根",
    )
    child = AssetCategoryModel._default_manager.create(
        code="CHILD",
        name="子",
        parent=root,
        level=2,
        path="根/子",
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        AssetCategoryModel._default_manager.filter(pk=root.pk).update(parent_id=root.pk)

    AssetCategoryModel._default_manager.filter(pk=root.pk).update(parent_id=child.pk)
    root.refresh_from_db()
    child.refresh_from_db()
    with pytest.raises(ValueError, match="循环引用"):
        child.get_ancestors()


def test_exchange_rate_convert_rejects_nonfinite_amount() -> None:
    rate = ExchangeRateModel(rate=Decimal("7.1"))

    with pytest.raises(ValueError, match="有限 Decimal"):
        rate.convert(Decimal("NaN"))
