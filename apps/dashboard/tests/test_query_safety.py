"""Safety contracts for Dashboard shared query services."""

from datetime import date

from apps.alpha.domain.entities import AlphaResult, StockScore
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
    assert "reliability_notice" not in meta


def test_stock_scores_payload_preserves_qualified_source_metadata(
    monkeypatch,
) -> None:
    """Public score metadata keeps decision gates and a safe reliability notice."""

    reliability_notice = {
        "level": "warning",
        "code": "alpha_etf_holdings_unqualified",
        "title": "ETF 成分股仅用于研究观察",
        "message": "来源时点未知，当前结果不得用于决策或执行。",
        "private_id": "notice-private-id",
        "session_cookie": "notice-private-cookie",
    }
    source_evidence_by_asset = {
        "600519.SH": {
            "decision_date": "2026-11-02",
            "knowledge_cutoff_basis": "china_market_day_start",
            "valuation": {
                "observed_at": None,
                "available_at": None,
                "fetched_at": None,
                "source_record_id": None,
                "raw_payload_hash": None,
            },
            "financial_facts": [
                {
                    "period_end": "2026-09-30",
                    "announced_at": None,
                    "available_at": None,
                    "fetched_at": None,
                    "source_record_id": None,
                    "raw_payload_hash": None,
                }
            ],
        }
    }
    decision_metadata: dict[str, object] = {
        "must_not_use_for_decision": True,
        "must_not_execute": True,
        "blocked_reason": "alpha_etf_holdings_unqualified",
        "freshness_status": "unknown",
        "source_observed_at": None,
        "source_available_at": None,
        "factor_basis": "etf_holdings_observation",
        "report_date": "2025Q4",
        "source_evidence_by_asset": source_evidence_by_asset,
        "reliability_notice": reliability_notice,
        "private_account_id": "account-private-id",
        "session_cookie": "private-cookie",
        "raw_metadata": {"private_id": "nested-private-id"},
    }
    etf_result = AlphaResult(
        success=True,
        scores=[
            StockScore(
                code="600519.SH",
                score=0.045,
                rank=1,
                factors={"holding_ratio_pct": 4.5},
                source="etf",
                confidence=0.4,
                asof_date=None,
                intended_trade_date=date(2026, 11, 2),
            )
        ],
        source="etf",
        timestamp="2026-11-02T00:00:00+00:00",
        status="degraded",
        metadata=decision_metadata,
    )

    class StubAlphaService:
        def get_stock_scores(
            self,
            *,
            universe_id: str,
            intended_trade_date: date,
            top_n: int,
            user: object | None,
            provider_filter: str,
        ) -> AlphaResult:
            if provider_filter == "etf":
                return etf_result
            return _alpha_result(
                success=False,
                source=provider_filter,
                metadata={},
                error_message="provider unavailable",
            )

    monkeypatch.setattr(
        "apps.alpha.application.services.AlphaService",
        StubAlphaService,
    )
    query = AlphaVisualizationQuery()
    monkeypatch.setattr(
        query,
        "_resolve_security_names",
        lambda _codes: {"600519.SH": "贵州茅台"},
    )

    payload = query._get_stock_scores_payload(10)

    assert payload["items"][0]["code"] == "600519.SH"
    meta = payload["meta"]
    assert meta["status"] == "degraded"
    assert meta["must_not_use_for_decision"] is True
    assert meta["must_not_execute"] is True
    assert meta["blocked_reason"] == "alpha_etf_holdings_unqualified"
    assert meta["freshness_status"] == "unknown"
    assert meta["source_observed_at"] is None
    assert meta["source_available_at"] is None
    assert meta["factor_basis"] == "etf_holdings_observation"
    assert meta["report_date"] == "2025Q4"
    assert meta["source_evidence_by_asset"] == source_evidence_by_asset
    assert meta["source_evidence_by_asset"]["600519.SH"]["valuation"]["observed_at"] is None
    assert meta["source_evidence_by_asset"]["600519.SH"]["valuation"]["available_at"] is None
    financial_fact = meta["source_evidence_by_asset"]["600519.SH"]["financial_facts"][0]
    assert financial_fact["announced_at"] is None
    assert financial_fact["available_at"] is None
    assert financial_fact["fetched_at"] is None
    assert meta["reliability_notice"] == {
        "level": "warning",
        "code": "alpha_etf_holdings_unqualified",
        "title": "ETF 成分股仅用于研究观察",
        "message": "来源时点未知，当前结果不得用于决策或执行。",
    }
    assert meta["warning_code"] == "alpha_etf_holdings_unqualified"
    assert "private_account_id" not in meta
    assert "session_cookie" not in meta
    assert "raw_metadata" not in meta
    assert "private_id" not in str(meta)
    assert "private-cookie" not in str(meta)


def test_stock_score_meta_does_not_invent_missing_decision_fields() -> None:
    """Missing source facts remain missing instead of becoming safe-looking defaults."""

    result = _alpha_result(success=True, source="qlib", metadata={})

    meta = AlphaVisualizationQuery()._build_stock_scores_meta(result)

    optional_fields = (
        "must_not_use_for_decision",
        "must_not_execute",
        "blocked_reason",
        "freshness_status",
        "source_observed_at",
        "source_available_at",
        "factor_basis",
        "report_date",
        "source_evidence_by_asset",
        "reliability_notice",
    )
    assert all(field not in meta for field in optional_fields)


def test_position_detail_failure_is_sanitized(monkeypatch, caplog) -> None:
    """Repository exception details do not enter API payloads or logs."""

    monkeypatch.setattr(
        "apps.dashboard.application.detail_queries.logger.handlers", [caplog.handler]
    )

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

    monkeypatch.setattr(
        "apps.dashboard.application.detail_queries.logger.handlers", [caplog.handler]
    )

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
