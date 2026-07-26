"""Transaction-safety tests for Dashboard Alpha history persistence."""

from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError

from apps.dashboard.infrastructure.models import (
    AlphaRecommendationRunModel,
    AlphaRecommendationSnapshotModel,
)
from apps.dashboard.infrastructure.repositories import (
    AlphaRecommendationHistoryRepository,
)


@pytest.mark.django_db
def test_snapshot_replace_failure_preserves_rows_and_outer_transaction() -> None:
    """A rejected bulk insert rolls back locally without poisoning later queries."""

    user = get_user_model().objects.create_user(
        username="dashboard_history_atomic",
        password="testpass123",
    )
    run = AlphaRecommendationRunModel.objects.create(
        user=user,
        trade_date=date(2026, 7, 26),
        scope_hash="atomic-scope",
        source="cache",
    )
    AlphaRecommendationSnapshotModel.objects.create(
        run=run,
        stock_code="000001.SZ",
        stage="top_ranked",
        gate_status="allowed",
        alpha_score=0.8,
    )

    repository = AlphaRecommendationHistoryRepository()
    with pytest.raises(IntegrityError):
        repository.replace_snapshots(
            run=run,
            snapshots=[
                {
                    "stock_code": "600000.SH",
                    "stage": "top_ranked",
                    "gate_status": "allowed",
                    "alpha_score": None,
                }
            ],
        )

    assert list(
        AlphaRecommendationSnapshotModel.objects.filter(run=run).values_list(
            "stock_code", flat=True
        )
    ) == ["000001.SZ"]
    assert AlphaRecommendationRunModel.objects.filter(id=run.id).exists()
