"""Cross-module aggregation contracts for the unified Signal service."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from apps.alpha.domain.entities import AlphaResult, StockScore
from apps.signal.application.unified_service import UnifiedSignalService


class _Repo:
    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []

    def create_signal(self, **payload: object) -> dict[str, object]:
        self.created.append(payload)
        return payload

    def get_signals_by_date(self, **kwargs: object) -> list[dict[str, object]]:
        return [{"priority": 2}, {"priority": 7}]

    def get_signal_summary(self, start_date: date, end_date: date | None) -> dict[str, int]:
        return {"total": len(self.created)}


def _service() -> UnifiedSignalService:
    service = UnifiedSignalService.__new__(UnifiedSignalService)
    service.unified_repo = _Repo()
    service.rotation_signal_fetcher = None
    service.factor_service = None
    service.hedge_service = None
    service._alpha_service = None
    return service


def test_rotation_factor_hedge_and_alpha_collectors_validate_and_project() -> None:
    """Module collectors skip malformed input and persist valid normalized signals."""
    service = _service()
    calc_date = date(2026, 7, 24)

    assert service._collect_rotation_signals(calc_date) == []
    service.rotation_signal_fetcher = lambda day: {
        "signals": [
            "bad",
            {"config_name": "bad-allocation", "target_allocation": []},
            {
                "config_name": "rotation",
                "strategy_type": "regime",
                "target_allocation": {"510300": 0.4, "BAD": "x"},
            },
        ]
    }
    rotation = service._collect_rotation_signals(calc_date)
    assert len(rotation) == 1 and rotation[0]["asset_code"] == "510300"

    service.factor_service = SimpleNamespace(
        get_all_configs=lambda: [{"name": "value"}],
        create_factor_portfolio=lambda name, day: {
            "holdings": [
                {
                    "stock_code": "000001.SZ",
                    "stock_name": "平安银行",
                    "weight": 12.5,
                    "factor_score": 0.8,
                    "rank": 1,
                    "sector": "银行",
                }
            ]
        },
    )
    factor = service._collect_factor_signals(calc_date)
    assert factor[0]["target_weight"] == 0.125

    alert = SimpleNamespace(
        severity="critical",
        pair_name="CSI300-IF",
        message="basis widened",
        action_priority=9,
        action_required="review hedge",
        alert_type=SimpleNamespace(value="basis"),
        current_value=0.1,
        threshold_value=0.05,
    )
    effectiveness = SimpleNamespace(
        effectiveness=0.2,
        pair_name="CSI300-IF",
        recommendation="increase hedge",
        rating="poor",
        correlation=0.2,
    )
    service.hedge_service = SimpleNamespace(
        monitor_hedge_pairs=lambda day: [alert],
        get_all_effectiveness=lambda day: [effectiveness],
    )
    assert len(service._collect_hedge_signals(calc_date)) == 2

    scores = [
        StockScore(
            code="000001.SZ",
            score=0.8,
            rank=1,
            factors={"quality": 0.8},
            source="cache",
            confidence=0.9,
            asof_date=calc_date,
            universe_id="csi300",
        ),
        StockScore(
            code="000002.SZ",
            score=0.4,
            rank=2,
            factors={},
            source="cache",
            confidence=0.7,
        ),
    ]
    service._alpha_service = lambda **kwargs: AlphaResult(
        success=True,
        scores=scores,
        source="cache",
        timestamp=calc_date.isoformat(),
        status="degraded",
        staleness_days=2,
    )
    alpha = service._collect_alpha_signals(calc_date)
    assert len(alpha) == 2
    assert alpha[-1]["asset_code"] == "ALPHA_SYSTEM"
    service._alpha_service = lambda **kwargs: AlphaResult(
        success=False,
        scores=[],
        source="qlib",
        timestamp=calc_date.isoformat(),
        error_message="unavailable",
    )
    assert service._collect_alpha_signals(calc_date) == []


def test_collection_best_effort_filters_and_summary(monkeypatch) -> None:
    """Collection isolates recoverable module errors and reports aggregate counts."""
    service = _service()
    calc_date = date(2026, 7, 24)
    monkeypatch.setattr(service, "_collect_regime_signals", lambda day: [{"id": 1}])
    monkeypatch.setattr(service, "_collect_rotation_signals", lambda day: [])
    monkeypatch.setattr(
        service,
        "_collect_factor_signals",
        lambda day: (_ for _ in ()).throw(RuntimeError("factor offline")),
    )
    monkeypatch.setattr(service, "_collect_hedge_signals", lambda day: [{"id": 2}, {"id": 3}])
    monkeypatch.setattr(service, "_collect_alpha_signals", lambda day: [{"id": 4}])
    result = service.collect_all_signals(calc_date)
    assert result["total_signals"] == 4
    assert result["factor_signals"] == 0
    assert result["errors"] == ["Factor: factor offline"]

    assert service.get_unified_signals(calc_date, min_priority=5) == [{"priority": 7}]
    assert service.get_signal_summary(calc_date)["total"] == 0
    assert service._get_regime_allocation("Recovery")["510300"]["weight"] == 0.30
    assert service._get_regime_allocation("Unknown") == {}
