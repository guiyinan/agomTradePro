"""Regression tests for Alpha ORM model invariants."""

from datetime import date

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.alpha.infrastructure.models import (
    AlphaScoreCacheModel,
    QlibModelRegistryModel,
)


def _registry_model(artifact_hash: str, *, is_active: bool = False) -> QlibModelRegistryModel:
    return QlibModelRegistryModel._default_manager.create(
        model_name=f"model-{artifact_hash}",
        artifact_hash=artifact_hash,
        model_type=QlibModelRegistryModel.MODEL_LGB,
        universe="csi300",
        train_config={},
        feature_set_id="features-v1",
        label_id="label-v1",
        data_version="data-v1",
        model_path=f"/models/{artifact_hash}.pkl",
        is_active=is_active,
    )


def test_cache_staleness_uses_django_local_date(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "apps.alpha.infrastructure.models.timezone.localdate",
        lambda: date(2026, 7, 26),
    )
    cache = AlphaScoreCacheModel(
        universe_id="csi300",
        intended_trade_date=date(2026, 7, 28),
        provider_source=AlphaScoreCacheModel.PROVIDER_QLIB,
        asof_date=date(2026, 7, 25),
        scores=[],
    )

    assert cache.get_staleness_days() == 1
    assert cache.is_stale(max_days=1) is False
    with pytest.raises(ValueError, match="non-negative"):
        cache.is_stale(max_days=-1)


def test_cache_clean_rejects_non_list_even_when_empty() -> None:
    cache = AlphaScoreCacheModel(
        universe_id="csi300",
        intended_trade_date=date(2026, 7, 26),
        provider_source=AlphaScoreCacheModel.PROVIDER_QLIB,
        asof_date=date(2026, 7, 26),
        scores={},
    )

    with pytest.raises(ValidationError, match="scores 必须是列表"):
        cache.clean()


@pytest.mark.django_db
def test_activate_keeps_exactly_one_model_active() -> None:
    first = _registry_model("a" * 64)
    second = _registry_model("b" * 64)

    first.activate("first-user")
    second.activate("second-user")

    first.refresh_from_db()
    second.refresh_from_db()
    assert first.is_active is False
    assert second.is_active is True
    assert second.activated_by == "second-user"


@pytest.mark.django_db
def test_database_rejects_two_directly_active_models() -> None:
    _registry_model("c" * 64, is_active=True)

    with pytest.raises(IntegrityError), transaction.atomic():
        _registry_model("d" * 64, is_active=True)


@pytest.mark.django_db
def test_latest_registered_does_not_override_django_latest_contract() -> None:
    assert QlibModelRegistryModel.objects.latest_registered() is None
    first = _registry_model("e" * 64)
    second = _registry_model("f" * 64)

    assert QlibModelRegistryModel.objects.latest_registered() == second
    assert QlibModelRegistryModel.objects.latest("created_at") in {first, second}
