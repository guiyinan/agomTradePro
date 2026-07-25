"""Safety regressions for Regime persistence boundaries."""

from datetime import date

import pytest

from apps.regime.domain.entities import RegimeSnapshot
from apps.regime.infrastructure.models import RegimeLog
from apps.regime.infrastructure.repositories import (
    DjangoRegimeRepository,
    RegimeRepositoryError,
)


def _snapshot(observed_at: date, **overrides: object) -> RegimeSnapshot:
    values: dict[str, object] = {
        "growth_momentum_z": 0.2,
        "inflation_momentum_z": -0.1,
        "distribution": {"Recovery": 1.0},
        "dominant_regime": "Recovery",
        "confidence": 0.8,
        "observed_at": observed_at,
    }
    values.update(overrides)
    return RegimeSnapshot(**values)  # type: ignore[arg-type]


@pytest.mark.django_db
def test_replace_rejects_out_of_range_snapshot_before_delete() -> None:
    repository = DjangoRegimeRepository()
    existing = _snapshot(date(2024, 1, 2))
    repository.save_snapshot(existing)

    with pytest.raises(RegimeRepositoryError, match="outside"):
        repository.replace_snapshots_in_range(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            snapshots=[_snapshot(date(2024, 2, 1))],
        )

    assert repository.get_snapshot_by_date(existing.observed_at) == existing


@pytest.mark.django_db
def test_replace_rejects_duplicate_dates_before_delete() -> None:
    repository = DjangoRegimeRepository()
    existing = _snapshot(date(2024, 1, 2))
    repository.save_snapshot(existing)
    replacement_date = date(2024, 1, 3)

    with pytest.raises(RegimeRepositoryError, match="duplicate"):
        repository.replace_snapshots_in_range(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            snapshots=[
                _snapshot(replacement_date),
                _snapshot(replacement_date, confidence=0.7),
            ],
        )

    assert repository.get_snapshot_by_date(existing.observed_at) == existing


@pytest.mark.django_db
def test_save_rejects_non_finite_snapshot_without_mutation() -> None:
    repository = DjangoRegimeRepository()

    with pytest.raises(RegimeRepositoryError, match="non-finite"):
        repository.save_snapshot(_snapshot(date(2024, 1, 1), confidence=float("nan")))

    assert RegimeLog._default_manager.count() == 0


@pytest.mark.django_db
def test_history_rejects_invalid_pagination_without_query_error() -> None:
    repository = DjangoRegimeRepository()
    repository.save_snapshot(_snapshot(date(2024, 1, 1)))

    assert repository.list_history_payloads(limit=0) == []
    assert repository.list_history_payloads(offset=-1) == []
