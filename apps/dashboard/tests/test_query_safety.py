"""Safety contracts for Dashboard shared query services."""

from apps.alpha.domain.entities import AlphaResult
from apps.dashboard.application.queries import (
    AlphaVisualizationQuery,
    DashboardDetailQuery,
    RegimeSummaryQuery,
)


def _alpha_result(
    *,
    success: bool,
    source: str,
    metadata: dict[str, object],
    error_message: str | None = None,
) -> AlphaResult:
    """Build a minimal Alpha result for metadata-boundary tests."""

    return AlphaResult(
        success=success,
        scores=[],
        source=source,
        timestamp="2026-07-28T00:00:00+00:00",
        error_message=error_message,
        metadata=metadata,
    )


def test_alpha_fallback_rejects_corrupt_notice_and_provider_error_text() -> None:
    """Malformed nested metadata and raw provider errors cannot reach UI hints."""

    qlib_result = _alpha_result(
        success=False,
        source="qlib",
        metadata={
            "async_task_triggered": True,
            "reliability_notice": "not-an-object",
        },
        error_message="token=secret-provider-detail",
    )
    cache_result = _alpha_result(
        success=True,
        source="cache",
        metadata={"cache_date": "2026-07-27"},
    )

    annotated = AlphaVisualizationQuery()._annotate_dashboard_alpha_result(
        cache_result,
        selected_provider="cache",
        attempts=[("qlib", qlib_result), ("cache", cache_result)],
    )

    assert annotated.metadata["fallback_reason"] == (
        "实时 Qlib 结果尚未就绪，系统已触发异步推理任务"
    )
    assert "secret-provider-detail" not in str(annotated.metadata)
    assert annotated.metadata["reliability_notice"]["code"] == "dashboard_cache_fallback"


def test_stock_score_meta_rejects_non_mapping_notice() -> None:
    """A corrupt reliability notice degrades to empty optional fields."""

    result = _alpha_result(
        success=True,
        source="cache",
        metadata={"reliability_notice": ["invalid"]},
    )

    meta = AlphaVisualizationQuery()._build_stock_scores_meta(result)

    assert meta["warning_message"] is None
    assert meta["warning_code"] is None


def test_position_detail_failure_is_sanitized(monkeypatch, caplog) -> None:
    """Repository exception details do not enter API payloads or logs."""

    class FailingRepository:
        def get_position_detail(self, *, user_id: int, asset_code: str) -> dict[str, object]:
            raise ValueError("database password=secret-value")

    monkeypatch.setattr(
        "apps.dashboard.application.queries.get_dashboard_query_repository",
        lambda: FailingRepository(),
    )

    payload = DashboardDetailQuery().get_position_detail(7, "000001.SZ")

    assert payload["error"] == "持仓详情暂不可用"
    assert "secret-value" not in str(payload)
    assert "secret-value" not in caplog.text
    assert "ValueError" in caplog.text


def test_regime_summary_failure_is_sanitized(monkeypatch, caplog) -> None:
    """Current resolver errors expose only a stable availability warning."""

    def fail_resolver() -> object:
        raise RuntimeError("dsn=secret-value")

    monkeypatch.setattr(
        "apps.dashboard.application.queries.resolve_current_regime",
        fail_resolver,
    )

    result = RegimeSummaryQuery().execute(user_id=7)

    assert result.regime_warnings == ["Regime data unavailable"]
    assert "secret-value" not in caplog.text
    assert "RuntimeError" in caplog.text
