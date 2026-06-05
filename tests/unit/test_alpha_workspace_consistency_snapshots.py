"""Tests for ORM-backed Alpha/workspace consistency snapshots."""

from datetime import UTC, date, datetime

import pytest
from django.utils import timezone

from apps.alpha.infrastructure.models import AlphaScoreCacheModel
from apps.decision_rhythm.infrastructure.consistency_snapshots import (
    get_latest_alpha_ranking_snapshot,
    get_workspace_recommendation_snapshot,
    run_alpha_workspace_consistency_check,
)
from apps.decision_rhythm.infrastructure.models import UnifiedRecommendationModel

pytestmark = pytest.mark.django_db


def test_alpha_ranking_snapshot_reads_latest_cache() -> None:
    """Latest Alpha cache row becomes the ranking snapshot."""

    AlphaScoreCacheModel.objects.create(
        universe_id="csi300",
        intended_trade_date=date(2026, 6, 3),
        provider_source=AlphaScoreCacheModel.PROVIDER_QLIB,
        asof_date=date(2026, 6, 3),
        scores=[{"code": "000001.SZ", "score": 0.5}],
        status=AlphaScoreCacheModel.STATUS_AVAILABLE,
    )
    AlphaScoreCacheModel.objects.create(
        universe_id="csi300",
        intended_trade_date=date(2026, 6, 4),
        provider_source=AlphaScoreCacheModel.PROVIDER_QLIB,
        asof_date=date(2026, 6, 4),
        scores=[
            {"code": "002709.SZ", "score": 0.8},
            {"code": "300274.SZ", "score": 0.7},
        ],
        status=AlphaScoreCacheModel.STATUS_AVAILABLE,
    )

    snapshot = get_latest_alpha_ranking_snapshot(top_n=1)

    assert snapshot.latest_trade_date == date(2026, 6, 4)
    assert snapshot.top_codes == ("002709.SZ",)
    assert snapshot.provider_source == AlphaScoreCacheModel.PROVIDER_QLIB


def test_workspace_snapshot_reads_latest_recommendations() -> None:
    """Workspace snapshot includes latest recommendations and source candidate ids."""

    old = UnifiedRecommendationModel.objects.create(
        recommendation_id="urec_old",
        account_id="510",
        security_code="601169.SH",
        side="HOLD",
        source_candidate_ids=[],
    )
    new = UnifiedRecommendationModel.objects.create(
        recommendation_id="urec_new",
        account_id="510",
        security_code="002709.SZ",
        side="HOLD",
        source_candidate_ids=["alpha_rank:002709.SZ:2026-06-04"],
    )
    UnifiedRecommendationModel.objects.filter(pk=old.pk).update(
        updated_at=datetime(2026, 5, 20, 1, tzinfo=UTC)
    )
    UnifiedRecommendationModel.objects.filter(pk=new.pk).update(
        updated_at=timezone.make_aware(datetime(2026, 6, 5, 6))
    )

    snapshot = get_workspace_recommendation_snapshot(account_id="510")

    assert snapshot.account_id == "510"
    assert snapshot.total_count == 2
    assert snapshot.recommendation_codes[0] == "002709.SZ"
    assert snapshot.source_candidate_ids == ("alpha_rank:002709.SZ:2026-06-04",)


def test_persisted_consistency_check_flags_old_workspace_rows() -> None:
    """Persisted check catches the stale-workspace scenario from production."""

    AlphaScoreCacheModel.objects.create(
        universe_id="csi300",
        intended_trade_date=date(2026, 6, 4),
        provider_source=AlphaScoreCacheModel.PROVIDER_QLIB,
        asof_date=date(2026, 6, 4),
        scores=[{"code": "002709.SZ", "score": 0.8}],
        status=AlphaScoreCacheModel.STATUS_AVAILABLE,
    )
    stale = UnifiedRecommendationModel.objects.create(
        recommendation_id="urec_stale",
        account_id="510",
        security_code="601169.SH",
        side="HOLD",
        source_candidate_ids=[],
    )
    UnifiedRecommendationModel.objects.filter(pk=stale.pk).update(
        updated_at=datetime(2026, 5, 20, 1, tzinfo=UTC)
    )

    result = run_alpha_workspace_consistency_check(account_id="510")

    assert result.status == "warning"
    assert {issue.code for issue in result.issues} >= {
        "workspace_recommendations_stale",
        "workspace_missing_alpha_rank_origin",
    }
