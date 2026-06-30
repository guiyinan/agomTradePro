from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

from apps.decision_rhythm.application.advisor_services import (
    AdvisorAccountSnapshot,
    AdvisorHoldingSnapshot,
    GenerateAdvisorDecisionSheetUseCase,
)

EXPECTED_ORDER_INTENT_FIELDS = {
    "order_intent_id",
    "account_id",
    "asset_code",
    "asset_name",
    "side",
    "current_quantity",
    "target_quantity",
    "delta_quantity",
    "estimated_price",
    "estimated_amount",
    "current_weight",
    "target_weight",
    "priority",
    "price_band",
    "reason",
    "risk_notes",
    "invalidation_rule",
    "execution_hint",
    "source_recommendation_id",
    "blocking_status",
    "source_recommendation_ids",
    "conflict_resolution",
    "risk_gate_status",
    "risk_gate",
    "data_asof",
    "tracking",
    "confirmation",
    "decision_card",
}


class FakeHoldingProvider:
    def __init__(self, snapshot: AdvisorAccountSnapshot):
        self.snapshot = snapshot

    def get_snapshot(self, *, account_id: str, user):
        return self.snapshot


class FakeRecommendationProvider:
    def __init__(self, recommendations):
        self.recommendations = recommendations

    def list_recommendations(self, *, account_id: str):
        return self.recommendations


class FakeRiskGateProvider:
    def __init__(self, *, blocked_codes=None, review_codes=None, unavailable=False, parameters=None):
        self.blocked_codes = set(blocked_codes or [])
        self.review_codes = set(review_codes or [])
        self.unavailable = unavailable
        self.parameters = parameters or {"max_single_position_pct": 0.25, "min_cash_pct": 0.1}

    def get_policy_context(self, *, account_id: str):
        return {
            "version": "riskcfg_test",
            "account_id": account_id,
            "risk_profile": "moderate",
            "template_key": "test",
            "parameters": self.parameters,
            "sources": {"template": "test"},
            "floor_applied": [],
            "exceptions_applied": [],
            "warnings": [],
            "unavailable": self.unavailable,
        }

    def evaluate_order(self, *, account, intent, holdings, policy_context):
        if self.unavailable and intent.side in {"BUY", "ADD"}:
            return {
                "status": "BLOCKED",
                "code": "risk_policy_unavailable",
                "messages": ["个人风险配置不可用，新增买入默认阻断。"],
                "policy_version": "riskcfg_test",
                "metrics": {},
            }
        if intent.asset_code in self.blocked_codes:
            return {
                "status": "BLOCKED",
                "code": "risk_gate_failed",
                "messages": ["max_single_position_pct exceeded"],
                "policy_version": "riskcfg_test",
                "metrics": {"projected_single_position_pct": 0.31},
            }
        if intent.asset_code in self.review_codes:
            return {
                "status": "REVIEW",
                "code": "risk_gate_review",
                "messages": ["manual confirmation required"],
                "policy_version": "riskcfg_test",
                "metrics": {"projected_single_position_pct": 0.22},
            }
        return {
            "status": "OK" if intent.blocking_status == "OK" else "SKIPPED",
            "code": "risk_gate_passed",
            "messages": [],
            "policy_version": "riskcfg_test",
            "metrics": {},
        }


class FakeDataHealthProvider:
    def __init__(self, *, blocked=False):
        self.blocked = blocked

    def get_health(self, *, asset_codes):
        quotes = {
            code: {
                "status": "blocked" if self.blocked else "ok",
                "asset_code": code,
                "snapshot_at": "2026-06-25T09:30:00+08:00",
                "freshness_status": "stale" if self.blocked else "fresh",
                "source": "test",
                "must_not_use_for_decision": self.blocked,
                "blocked_reason": "stale quote" if self.blocked else "",
            }
            for code in asset_codes
        }
        return {
            "status": "blocked" if self.blocked else "ok",
            "asset_codes": asset_codes,
            "quotes": quotes,
            "market_thermometer": {
                "status": "ok",
                "as_of_date": "2026-06-25",
                "must_not_use_for_decision": False,
            },
            "must_not_use_for_decision": self.blocked,
            "blocked_reasons": ["quotes stale"] if self.blocked else [],
        }


class FakeExecutionGuardProvider:
    def __init__(self, *, blocked_codes=None, invalidated_codes=None):
        self.blocked_codes = set(blocked_codes or [])
        self.invalidated_codes = set(invalidated_codes or [])

    def evaluate(self, *, recommendation, intent, resolution):
        if intent.asset_code in self.blocked_codes:
            return {
                "status": "BLOCKED",
                "code": "execution_guard_failed",
                "checks": {
                    "cooldown": {
                        "passed": False,
                        "hours_remaining": 12.0,
                        "reason": "冷却期内，剩余 12.0 小时",
                    }
                },
                "messages": ["冷却期内，剩余 12.0 小时"],
            }
        if intent.asset_code in self.invalidated_codes:
            return {
                "status": "BLOCKED",
                "code": "execution_guard_failed",
                "checks": {
                    "signal_invalidation": {
                        "passed": False,
                        "reason": "来源信号已被证伪: 100",
                        "invalidated": [{"signal_id": "100"}],
                    }
                },
                "messages": ["来源信号已被证伪: 100"],
            }
        return {
            "status": "OK" if intent.blocking_status == "OK" else "SKIPPED",
            "code": "execution_guard_passed",
            "checks": {"cooldown": {"passed": True, "reason": ""}},
            "messages": [],
        }


class FakeExposureProvider:
    def __init__(self, exposures=None):
        self.exposures = exposures or {}

    def get_asset_exposures(self, *, asset_codes):
        return {code: dict(self.exposures.get(code, {})) for code in asset_codes}


class FakeTrackingProvider:
    def __init__(self, links_by_recommendation=None):
        self.links_by_recommendation = links_by_recommendation or {}

    def get_execution_links(self, *, account_id, recommendation_ids, user):
        return {
            recommendation_id: list(self.links_by_recommendation.get(recommendation_id, []))
            for recommendation_id in recommendation_ids
        }


class FakePerformanceProvider:
    def __init__(self, series_by_asset=None):
        self.series_by_asset = series_by_asset or {}

    def get_close_price_series(self, *, asset_code, start_date, end_date):
        return list(self.series_by_asset.get(asset_code, []))


class FakeAttributionContextProvider:
    def __init__(self, contexts=None):
        self.contexts = contexts or {}

    def get_context(self, *, recommendation_date, outcome_date):
        key = (
            recommendation_date.isoformat() if recommendation_date else None,
            outcome_date.isoformat() if outcome_date else None,
        )
        return self.contexts.get(
            key,
            {
                "recommendation": {
                    "status": "OK",
                    "date": key[0],
                    "regime": "Recovery",
                    "regime_confidence": 0.8,
                    "policy_level": "neutral",
                    "errors": [],
                },
                "outcome": {
                    "status": "OK",
                    "date": key[1],
                    "regime": "Recovery",
                    "regime_confidence": 0.8,
                    "policy_level": "neutral",
                    "errors": [],
                },
            },
        )


def _snapshot(*, holdings, baseline="existing_positions", cash="20000", account_type="simulated"):
    return AdvisorAccountSnapshot(
        account_summary={
            "account_id": "1",
            "account_name": "Growth Account",
            "account_type": account_type,
            "account_type_label": "实盘账户" if account_type == "real" else "模拟盘账户",
            "account_status": "active",
            "total_asset": 100000.0,
            "cash": float(Decimal(cash)),
            "available_cash": float(Decimal(cash)),
            "market_value": 80000.0,
            "holding_count": len(holdings),
            "baseline": baseline,
        },
        holdings=holdings,
        baseline=baseline,
    )


def _holding(code, *, weight, quantity="100", price="10", pnl_pct="0"):
    return AdvisorHoldingSnapshot(
        asset_code=code,
        asset_name=code,
        asset_class="equity",
        quantity=Decimal(quantity),
        market_value=Decimal("100000") * Decimal(weight),
        current_weight=Decimal(weight),
        avg_cost=Decimal("8"),
        current_price=Decimal(price) if price is not None else None,
        unrealized_pnl=Decimal("0"),
        unrealized_pnl_pct=Decimal(pnl_pct),
        data_source="unified",
        price_time="2026-06-25T09:30:00+08:00",
    )


def _rec(
    code,
    side="BUY",
    *,
    price="10",
    quantity=0,
    rationale="candidate",
    confidence=0.8,
    composite_score=0.8,
    source_signal_ids=None,
    source_candidate_ids=None,
    recommendation_id=None,
    strategy_bucket="alpha",
    user_action="PENDING",
    created_at=None,
    regime="Recovery",
    regime_confidence=0.8,
    policy_level="neutral",
):
    return SimpleNamespace(
        recommendation_id=recommendation_id or f"rec_{code}_{side}",
        security_code=code,
        side=side,
        human_rationale=rationale,
        fair_value=Decimal(price or "0"),
        entry_price_low=Decimal(price or "0"),
        entry_price_high=Decimal(price or "0"),
        stop_loss_price=Decimal("0"),
        position_pct=5.0,
        suggested_quantity=quantity,
        confidence=confidence,
        composite_score=composite_score,
        regime=regime,
        regime_confidence=regime_confidence,
        policy_level=policy_level,
        source_signal_ids=source_signal_ids or [],
        source_candidate_ids=source_candidate_ids or [],
        strategy_bucket=strategy_bucket,
        user_action=user_action,
        user_action_note="",
        user_action_at=None,
        created_at=created_at,
    )


def _execute(
    snapshot,
    recommendations,
    *,
    risk_gate_provider=None,
    data_health_provider=None,
    execution_guard_provider=None,
    exposure_provider=None,
    tracking_provider=None,
    performance_provider=None,
    attribution_context_provider=None,
):
    use_case = GenerateAdvisorDecisionSheetUseCase(
        holding_provider=FakeHoldingProvider(snapshot),
        recommendation_provider=FakeRecommendationProvider(recommendations),
        risk_gate_provider=risk_gate_provider or FakeRiskGateProvider(),
        data_health_provider=data_health_provider or FakeDataHealthProvider(),
        execution_guard_provider=execution_guard_provider or FakeExecutionGuardProvider(),
        exposure_provider=exposure_provider or FakeExposureProvider(),
        tracking_provider=tracking_provider or FakeTrackingProvider(),
        performance_provider=performance_provider or FakePerformanceProvider(),
        attribution_context_provider=(
            attribution_context_provider or FakeAttributionContextProvider()
        ),
    )
    return use_case.execute(account_id="1", user=object())


def test_existing_positions_prioritize_exit_and_reduce_before_new_buy():
    sheet = _execute(
        _snapshot(
            holdings=[
                _holding("AAA", weight="0.30", quantity="300", price="100"),
                _holding("BBB", weight="0.08", quantity="200", price="40", pnl_pct="-12"),
            ]
        ),
        [_rec("CCC", "BUY", price="20")],
    )

    assert sheet["today_conclusion"] == "ACT"
    sides = [item["side"] for item in sheet["order_intents"][:3]]
    assert sides == ["EXIT", "REDUCE", "BUY"]
    assert sheet["order_intents"][0]["asset_code"] == "BBB"
    assert sheet["order_intents"][1]["asset_code"] == "AAA"
    assert sheet["order_summary"]["buy"] == 1
    assert sheet["order_summary"]["reduce"] == 1
    assert sheet["order_summary"]["exit"] == 1


def test_empty_account_builds_starter_buy_from_cash_and_target_weight():
    sheet = _execute(
        _snapshot(holdings=[], baseline="empty_positions", cash="50000"),
        [_rec("CCC", "BUY", price="25", quantity=0)],
    )

    assert sheet["baseline"] == "empty_positions"
    assert sheet["today_conclusion"] == "ACT"
    order = sheet["order_intents"][0]
    assert order["side"] == "BUY"
    assert order["risk_gate_status"] == "OK"
    assert order["risk_gate"]["risk_center"]["policy_version"] == "riskcfg_test"
    assert order["risk_gate"]["execution_guard"]["status"] == "OK"
    assert order["data_asof"]["quote_freshness_status"] == "fresh"
    assert order["decision_card"]["action"] == "BUY"
    assert order["decision_card"]["expected_loss_if_wrong"] == 250.0
    assert order["tracking"]["review_status"] == "PENDING_REVIEW"
    assert order["decision_card"]["tracking"]["review_status"] == "PENDING_REVIEW"
    assert order["confirmation"]["required"] is False
    assert sheet["execution_plan"]["broker_execution_enabled"] is False
    assert order["delta_quantity"] == 200.0
    assert order["estimated_amount"] == 5000.0
    assert sheet["risk_policy"]["version"] == "riskcfg_test"
    assert sheet["data_health"]["status"] == "ok"
    assert sheet["decision_cards"][0]["order_intent_id"] == order["order_intent_id"]
    assert "recommendation_quantity_zero_recomputed" in ";".join(sheet["warnings"])


def test_zero_quantity_recommendation_is_recomputed_not_shown_as_zero_order():
    sheet = _execute(
        _snapshot(holdings=[], baseline="empty_positions", cash="10000"),
        [_rec("DDD", "BUY", price="10", quantity=0)],
    )

    assert set(sheet["order_intents"][0]) == EXPECTED_ORDER_INTENT_FIELDS
    assert sheet["order_intents"][0]["delta_quantity"] > 0
    assert sheet["order_intents"][0]["blocking_status"] == "OK"


def test_missing_price_blocks_order_without_fake_quantity():
    sheet = _execute(
        _snapshot(holdings=[], baseline="empty_positions", cash="10000"),
        [_rec("EEE", "BUY", price="0", quantity=0)],
    )

    assert sheet["today_conclusion"] == "BLOCKED"
    order = sheet["order_intents"][0]
    assert order["blocking_status"] == "BLOCKED_PRICE_MISSING"
    assert order["delta_quantity"] == 0.0
    assert sheet["order_summary"]["blocked"] == 1


def test_existing_holding_missing_price_blocks_without_fake_sell_quantity():
    sheet = _execute(
        _snapshot(
            holdings=[
                _holding("FFF", weight="0.30", quantity="300", price=None),
            ]
        ),
        [],
    )

    assert sheet["today_conclusion"] == "BLOCKED"
    order = sheet["order_intents"][0]
    assert order["side"] == "REDUCE"
    assert order["blocking_status"] == "BLOCKED_PRICE_MISSING"
    assert order["target_quantity"] == order["current_quantity"]
    assert order["delta_quantity"] == 0.0
    assert order["estimated_amount"] == 0.0


def test_risk_gate_blocks_actionable_order_and_preserves_policy_version():
    sheet = _execute(
        _snapshot(holdings=[], baseline="empty_positions", cash="10000"),
        [_rec("GGG", "BUY", price="10", quantity=0)],
        risk_gate_provider=FakeRiskGateProvider(blocked_codes={"GGG"}),
    )

    assert sheet["today_conclusion"] == "BLOCKED"
    order = sheet["order_intents"][0]
    assert order["blocking_status"] == "BLOCKED_RISK_GATE"
    assert order["risk_gate_status"] == "BLOCKED"
    assert order["risk_gate"]["risk_center"]["policy_version"] == "riskcfg_test"
    assert "max_single_position_pct exceeded" in order["risk_notes"]


def test_missing_risk_policy_blocks_new_buy_conservatively():
    sheet = _execute(
        _snapshot(holdings=[], baseline="empty_positions", cash="10000"),
        [_rec("HHH", "BUY", price="10", quantity=0)],
        risk_gate_provider=FakeRiskGateProvider(unavailable=True),
    )

    order = sheet["order_intents"][0]
    assert sheet["today_conclusion"] == "BLOCKED"
    assert order["blocking_status"] == "BLOCKED_RISK_POLICY_UNAVAILABLE"
    assert order["risk_gate"]["risk_center"]["code"] == "risk_policy_unavailable"


def test_risk_gate_review_downgrades_sheet_without_blocking_order():
    sheet = _execute(
        _snapshot(holdings=[], baseline="empty_positions", cash="10000"),
        [_rec("JJJ", "BUY", price="10", quantity=0)],
        risk_gate_provider=FakeRiskGateProvider(review_codes={"JJJ"}),
    )

    order = sheet["order_intents"][0]
    assert sheet["today_conclusion"] == "REVIEW"
    assert order["blocking_status"] == "OK"
    assert order["risk_gate_status"] == "REVIEW"
    assert "manual confirmation required" in order["risk_notes"]


def test_real_account_order_requires_manual_confirmation_and_never_auto_broker_execution():
    sheet = _execute(
        _snapshot(holdings=[], baseline="empty_positions", cash="10000", account_type="real"),
        [_rec("RRR", "BUY", price="10", quantity=0)],
    )

    order = sheet["order_intents"][0]
    assert order["blocking_status"] == "OK"
    assert order["confirmation"]["required"] is True
    assert order["confirmation"]["status"] == "PENDING"
    assert order["confirmation"]["reasons"][0]["code"] == "real_account_manual_confirm"
    assert order["decision_card"]["confirmation"]["required"] is True
    assert sheet["execution_plan"]["execution_mode"] == "real_confirm_only"
    assert sheet["execution_plan"]["broker_execution_enabled"] is False
    assert sheet["execution_plan"]["requires_human_confirmation"] is True
    assert sheet["execution_plan"]["orders"][0]["confirmation"]["required"] is True


def test_large_order_amount_requires_confirmation_by_policy_threshold():
    sheet = _execute(
        _snapshot(holdings=[], baseline="empty_positions", cash="50000"),
        [_rec("SSS", "BUY", price="25", quantity=0)],
        risk_gate_provider=FakeRiskGateProvider(
            parameters={
                "max_single_position_pct": 0.25,
                "min_cash_pct": 0.1,
                "advisor_confirmation_amount_threshold": 1000,
            }
        ),
    )

    order = sheet["order_intents"][0]
    assert order["estimated_amount"] == 5000.0
    assert order["confirmation"]["required"] is True
    assert order["confirmation"]["reasons"][0]["code"] == "large_order_amount"
    assert sheet["execution_plan"]["confirmation_status"] == "PENDING"


def test_execution_guard_cooldown_blocks_actionable_order():
    sheet = _execute(
        _snapshot(holdings=[], baseline="empty_positions", cash="10000"),
        [_rec("NNN", "BUY", price="10", quantity=0)],
        execution_guard_provider=FakeExecutionGuardProvider(blocked_codes={"NNN"}),
    )

    order = sheet["order_intents"][0]
    assert sheet["today_conclusion"] == "BLOCKED"
    assert order["blocking_status"] == "BLOCKED_EXECUTION_GUARD"
    assert order["risk_gate_status"] == "BLOCKED"
    assert order["risk_gate"]["execution_guard"]["checks"]["cooldown"]["passed"] is False
    assert "冷却期内" in order["risk_notes"][0]


def test_execution_guard_invalidated_signal_blocks_actionable_order():
    sheet = _execute(
        _snapshot(holdings=[], baseline="empty_positions", cash="10000"),
        [_rec("OOO", "BUY", price="10", quantity=0, source_signal_ids=["100"])],
        execution_guard_provider=FakeExecutionGuardProvider(invalidated_codes={"OOO"}),
    )

    order = sheet["order_intents"][0]
    assert sheet["today_conclusion"] == "BLOCKED"
    assert order["blocking_status"] == "BLOCKED_EXECUTION_GUARD"
    assert order["risk_gate"]["execution_guard"]["checks"]["signal_invalidation"]["passed"] is False
    assert "来源信号已被证伪" in order["risk_notes"][0]


def test_recommendation_tracking_marks_executed_source_links():
    recommendation_id = "rec_PPP_BUY_alpha"
    sheet = _execute(
        _snapshot(holdings=[], baseline="empty_positions", cash="10000"),
        [
            _rec(
                "PPP",
                "BUY",
                price="10",
                quantity=0,
                recommendation_id=recommendation_id,
                user_action="ADOPTED",
            )
        ],
        tracking_provider=FakeTrackingProvider(
            {
                recommendation_id: [
                    {
                        "id": 7,
                        "recommendation_id": recommendation_id,
                        "transaction_id": 99,
                        "transaction_source": "manual_trade",
                        "actual_action": "buy",
                        "match_method": "auto",
                        "match_confidence": 0.85,
                        "created_at": "2026-06-26T10:00:00+08:00",
                    }
                ]
            }
        ),
    )

    order = sheet["order_intents"][0]
    assert order["tracking"]["review_status"] == "EXECUTED"
    assert order["tracking"]["execution_count"] == 1
    assert order["tracking"]["recommendations"][0]["user_action"] == "ADOPTED"
    assert order["tracking"]["execution_links"][0]["transaction_id"] == 99
    assert order["decision_card"]["tracking"]["is_executed"] is True


def test_recommendation_tracking_includes_7_20_60_day_performance():
    created_at = datetime(2026, 4, 1, 9, 30, tzinfo=UTC)
    sheet = _execute(
        _snapshot(holdings=[], baseline="empty_positions", cash="10000"),
        [
            _rec(
                "QQQ",
                "BUY",
                price="10",
                quantity=0,
                recommendation_id="rec_QQQ_BUY_alpha",
                created_at=created_at,
            )
        ],
        performance_provider=FakePerformanceProvider(
            {
                "QQQ": [
                    (date(2026, 4, 1), 10.0),
                    (date(2026, 4, 8), 11.0),
                    (date(2026, 4, 21), 12.0),
                    (date(2026, 5, 31), 9.0),
                ]
            }
        ),
    )

    performance = sheet["order_intents"][0]["tracking"]["recommendations"][0]["performance"]
    assert performance["status"] == "AVAILABLE"
    assert performance["anchor_date"] == "2026-04-01"
    assert performance["windows"]["7d"]["raw_return"] == 0.1
    assert performance["windows"]["20d"]["directional_return"] == 0.2
    assert performance["windows"]["60d"]["directional_return"] == -0.1
    assert performance["error_attribution"]["status"] == "ATTRIBUTED"
    assert performance["error_attribution"]["primary_category"] == "MODEL_MISJUDGMENT"
    aggregate = sheet["order_intents"][0]["tracking"]["performance"]["windows"]
    assert aggregate["7d"]["directional_return_avg"] == 0.1
    assert sheet["order_intents"][0]["decision_card"]["tracking"]["performance"][
        "windows"
    ]["60d"]["directional_return_avg"] == -0.1
    assert sheet["order_intents"][0]["tracking"]["performance"]["error_attribution"][
        "primary_categories"
    ] == ["MODEL_MISJUDGMENT"]


def test_recommendation_tracking_adds_deep_regime_policy_and_override_attribution():
    created_at = datetime(2026, 4, 1, 9, 30, tzinfo=UTC)
    sheet = _execute(
        _snapshot(holdings=[], baseline="empty_positions", cash="10000"),
        [
            _rec(
                "QQQ",
                "BUY",
                price="10",
                quantity=0,
                recommendation_id="rec_QQQ_BUY_alpha",
                created_at=created_at,
                regime="UNKNOWN",
                regime_confidence=0.2,
                policy_level="UNKNOWN",
                user_action="IGNORED",
            )
        ],
        performance_provider=FakePerformanceProvider(
            {
                "QQQ": [
                    (date(2026, 4, 1), 10.0),
                    (date(2026, 4, 21), 12.0),
                ]
            }
        ),
    )

    attribution = sheet["order_intents"][0]["tracking"]["recommendations"][0][
        "performance"
    ]["error_attribution"]
    deep = attribution["deep_attribution"]
    assert deep["regime"]["category"] == "REGIME_CONTEXT_MISSING"
    assert deep["policy"]["category"] == "POLICY_CONTEXT_MISSING"
    assert deep["manual_override"]["category"] == "MANUAL_OVERRIDE_ERROR"
    assert "MANUAL_OVERRIDE_ERROR" in deep["secondary_categories"]


def test_recommendation_tracking_compares_actual_regime_and_policy_context():
    created_at = datetime(2026, 4, 1, 9, 30, tzinfo=UTC)
    sheet = _execute(
        _snapshot(holdings=[], baseline="empty_positions", cash="10000"),
        [
            _rec(
                "QQQ",
                "BUY",
                price="10",
                quantity=0,
                recommendation_id="rec_QQQ_BUY_alpha",
                created_at=created_at,
                regime="Recovery",
                regime_confidence=0.8,
                policy_level="neutral",
                user_action="ADOPTED",
            )
        ],
        performance_provider=FakePerformanceProvider(
            {
                "QQQ": [
                    (date(2026, 4, 1), 10.0),
                    (date(2026, 4, 21), 8.0),
                ]
            }
        ),
        attribution_context_provider=FakeAttributionContextProvider(
            {
                ("2026-04-01", "2026-04-21"): {
                    "recommendation": {
                        "status": "OK",
                        "date": "2026-04-01",
                        "regime": "Recovery",
                        "regime_confidence": 0.8,
                        "policy_level": "neutral",
                        "errors": [],
                    },
                    "outcome": {
                        "status": "OK",
                        "date": "2026-04-21",
                        "regime": "Deflation",
                        "regime_confidence": 0.7,
                        "policy_level": "tight",
                        "errors": [],
                    },
                }
            }
        ),
    )

    deep = sheet["order_intents"][0]["tracking"]["recommendations"][0][
        "performance"
    ]["error_attribution"]["deep_attribution"]
    assert deep["regime"]["category"] == "REGIME_JUDGMENT_ERROR"
    assert deep["policy"]["category"] == "POLICY_MISJUDGMENT"
    assert "REGIME_JUDGMENT_ERROR" in deep["secondary_categories"]
    assert "POLICY_MISJUDGMENT" in deep["secondary_categories"]
    assert sheet["order_intents"][0]["tracking"]["performance"]["error_attribution"][
        "deep_categories"
    ] == ["REGIME_JUDGMENT_ERROR", "POLICY_MISJUDGMENT"]


def test_sector_exposure_limit_blocks_new_buy_and_reports_summary():
    sheet = _execute(
        _snapshot(
            holdings=[
                _holding("AAA", weight="0.24", quantity="240", price="100"),
            ],
            cash="76000",
        ),
        [_rec("BBB", "BUY", price="10", quantity=0)],
        risk_gate_provider=FakeRiskGateProvider(
            parameters={
                "max_single_position_pct": 0.25,
                "min_cash_pct": 0.1,
                "max_sector_position_pct": 0.25,
                "max_strategy_position_pct": 0.30,
            }
        ),
        exposure_provider=FakeExposureProvider(
            {
                "AAA": {"sector": "Technology", "industry": "Software", "strategy": "alpha"},
                "BBB": {"sector": "Technology", "industry": "Hardware", "strategy": "alpha"},
            }
        ),
    )

    order = [item for item in sheet["order_intents"] if item["asset_code"] == "BBB"][0]
    assert sheet["today_conclusion"] == "BLOCKED"
    assert order["blocking_status"] == "BLOCKED_EXPOSURE_LIMIT"
    assert order["risk_gate_status"] == "BLOCKED"
    assert order["risk_gate"]["exposure_guard"]["code"] == "exposure_limit_exceeded"
    assert "Technology" in order["risk_notes"][0]
    technology = [
        item for item in sheet["exposure_summary"]["by_sector"] if item["name"] == "Technology"
    ][0]
    assert technology["status"] == "BREACH"
    assert technology["projected_weight"] == 0.29
    assert sheet["risk_summary"]["exposure_alerts"][0]["asset_code"] == "BBB"


def test_exposure_guard_does_not_block_reduce_orders_in_overexposed_group():
    sheet = _execute(
        _snapshot(
            holdings=[
                _holding("AAA", weight="0.30", quantity="300", price="100"),
            ],
            cash="70000",
        ),
        [],
        risk_gate_provider=FakeRiskGateProvider(
            parameters={
                "max_single_position_pct": 0.25,
                "min_cash_pct": 0.1,
                "max_sector_position_pct": 0.25,
            }
        ),
        exposure_provider=FakeExposureProvider(
            {"AAA": {"sector": "Technology", "industry": "Software", "strategy": "alpha"}}
        ),
    )

    order = sheet["order_intents"][0]
    assert order["side"] == "REDUCE"
    assert order["blocking_status"] == "OK"
    assert order["risk_gate"]["exposure_guard"]["status"] == "SKIPPED"
    technology = [
        item for item in sheet["exposure_summary"]["by_sector"] if item["name"] == "Technology"
    ][0]
    assert technology["projected_weight"] == 0.2


def test_duplicate_buy_recommendations_merge_into_one_final_order_with_sources():
    sheet = _execute(
        _snapshot(holdings=[], baseline="empty_positions", cash="20000"),
        [
            _rec(
                "KKK",
                "BUY",
                price="10",
                confidence=0.9,
                source_signal_ids=["sig_1"],
                source_candidate_ids=["cand_1"],
                recommendation_id="rec_KKK_BUY_alpha",
            ),
            _rec(
                "KKK",
                "BUY",
                price="10",
                confidence=0.7,
                source_signal_ids=["sig_2"],
                source_candidate_ids=["cand_2"],
                recommendation_id="rec_KKK_BUY_rotation",
            ),
        ],
    )

    orders = [item for item in sheet["order_intents"] if item["asset_code"] == "KKK"]
    assert len(orders) == 1
    order = orders[0]
    assert order["side"] == "BUY"
    assert order["source_recommendation_ids"] == [
        "rec_KKK_BUY_alpha",
        "rec_KKK_BUY_rotation",
    ]
    assert order["conflict_resolution"]["status"] == "MERGED"
    assert order["conflict_resolution"]["source_signal_ids"] == ["sig_1", "sig_2"]
    assert order["conflict_resolution"]["source_candidate_ids"] == ["cand_1", "cand_2"]


def test_conflicting_buy_sell_recommendations_emit_review_and_conflict_reason():
    sheet = _execute(
        _snapshot(holdings=[], baseline="empty_positions", cash="20000"),
        [
            _rec("LLL", "BUY", price="10", confidence=0.9),
            _rec("LLL", "SELL", price="10", confidence=0.8),
        ],
    )

    assert sheet["today_conclusion"] == "REVIEW"
    assert len(sheet["recommendation_conflicts"]) == 1
    conflict = sheet["recommendation_conflicts"][0]
    assert conflict["asset_code"] == "LLL"
    assert conflict["accepted_side"] == "BUY"
    assert "方向冲突" in conflict["conflict_reason"]
    orders = [item for item in sheet["order_intents"] if item["asset_code"] == "LLL"]
    assert len(orders) == 1
    assert orders[0]["conflict_resolution"]["status"] == "CONFLICT"
    assert "方向冲突" in orders[0]["risk_notes"][0]


def test_existing_holding_conflict_prefers_exit_before_add():
    sheet = _execute(
        _snapshot(holdings=[_holding("MMM", weight="0.10", quantity="100", price="20")]),
        [
            _rec("MMM", "BUY", price="20", confidence=0.95),
            _rec("MMM", "SELL", price="20", confidence=0.50),
        ],
    )

    assert sheet["today_conclusion"] == "REVIEW"
    orders = [item for item in sheet["order_intents"] if item["asset_code"] == "MMM"]
    assert len(orders) == 1
    assert orders[0]["side"] == "EXIT"
    assert orders[0]["conflict_resolution"]["accepted_side"] == "EXIT"
    assert orders[0]["conflict_resolution"]["rejected_recommendations"][0]["side"] == "BUY"


def test_stale_data_downgrades_action_to_review_and_marks_card_asof():
    sheet = _execute(
        _snapshot(holdings=[], baseline="empty_positions", cash="10000"),
        [_rec("III", "BUY", price="10", quantity=0)],
        data_health_provider=FakeDataHealthProvider(blocked=True),
    )

    order = sheet["order_intents"][0]
    assert sheet["today_conclusion"] == "REVIEW"
    assert sheet["data_health"]["must_not_use_for_decision"] is True
    assert "data_health:quotes stale" in sheet["warnings"]
    assert order["blocking_status"] == "OK"
    assert order["data_asof"]["quote_freshness_status"] == "stale"
    assert order["decision_card"]["data_asof"]["quote_freshness_status"] == "stale"


def test_wait_when_no_holdings_and_no_recommendations():
    sheet = _execute(_snapshot(holdings=[], baseline="empty_positions"), [])

    assert sheet["today_conclusion"] == "WAIT"
    assert sheet["order_summary"]["total"] == 0
    assert sheet["holdings"] == []
