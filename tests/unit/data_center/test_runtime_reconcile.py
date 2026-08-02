"""Tests for deterministic desired-state reconciliation."""

from apps.data_center.application.reconcile import (
    DesiredStateEntry,
    ReconcileRuntimeCatalogUseCase,
)


def test_reconcile_reports_missing_drift_and_extra_without_nondeterminism() -> None:
    desired = (
        DesiredStateEntry("b", "1", "owner", "hash-b"),
        DesiredStateEntry("a", "1", "owner", "hash-a"),
    )
    result = ReconcileRuntimeCatalogUseCase().execute(
        desired,
        {"a": "old-a", "c": "hash-c"},
    )
    assert result.missing == ("b",)
    assert result.drifted == ("a",)
    assert result.extra == ("c",)
    assert result.applied == ()
    assert not result.healthy
