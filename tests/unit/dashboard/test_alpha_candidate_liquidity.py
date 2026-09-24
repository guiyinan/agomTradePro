from datetime import date
from types import SimpleNamespace

import pytest

from apps.dashboard.application.alpha_homepage import AlphaHomepageQuery
from apps.dashboard.infrastructure.repositories import DashboardAlphaContextRepository
from apps.strategy.domain.services import DecisionPolicyEngine, PreTradeRiskGate, SizingEngine


def candidate(volume, *, score=0.8, **context):
    query = object.__new__(AlphaHomepageQuery)
    query.decision_engine = DecisionPolicyEngine()
    query.sizing_engine = SizingEngine()
    query.risk_gate = PreTradeRiskGate()
    return query._build_candidate_item(
        score=SimpleNamespace(
            code="300750.SZ",
            score=score,
            rank=1,
            confidence=0.8,
            factors={},
            asof_date=date(2026, 9, 18),
            source="qlib",
        ),
        stock_context={"close": 10.0, "volume": volume, **context},
        actionable_candidate=None,
        pending_request=None,
        sizing_context=SimpleNamespace(
            multiplier_result=SimpleNamespace(multiplier=0.5, market_temperature_factor=1.0),
            regime_name="Recovery",
            regime_confidence=0.8,
            pulse_composite=0.2,
            pulse_warning=False,
            market_temperature_score=50.0,
            market_temperature_band="warm",
            warnings=[],
        ),
        portfolio_snapshot=SimpleNamespace(total_value=100000),
        position_map={},
        policy_state={"gate_level": "L0"},
        meta={},
    )


@pytest.mark.parametrize("volume", [None, float("nan"), float("inf"), -1, "bad", True])
def test_unavailable_volume_blocks_alpha_instead_of_skipping_liquidity(volume):
    item = candidate(volume)
    assert item["recommendation_ready"] is False
    assert item["must_not_use_for_decision"] is True
    assert item["risk_snapshot"]["risk_checks"]["liquidity_check"]["status"] == "blocked"
    assert "流动性检查未通过" in item["no_buy_reason_summary"]
    assert item["no_buy_reason_summary"].count("流动性检查未通过") == 1
    assert "跳过" not in item["no_buy_reason_summary"]


def test_zero_volume_is_insufficient_liquidity_not_missing_data():
    item = candidate(0)
    assert item["recommendation_ready"] is False
    assert "流动性不足: 成交量 0" in item["no_buy_reason_summary"]
    assert item["risk_snapshot"]["risk_checks"]["liquidity_check"]["avg_volume"] == 0


def test_missing_price_blocks_recommendation_without_inventing_zero_market_data():
    item = candidate(1000000, close=None)

    assert item["recommendation_ready"] is False
    assert item["must_not_use_for_decision"] is True
    assert "当前价格缺失" in item["no_buy_reason_summary"]


def test_valid_volume_keeps_observation_and_can_pass():
    item = candidate(1000000, volume_source="published_daily", volume_observed_at="2026-09-18")
    assert item["recommendation_ready"] is True
    check = item["risk_snapshot"]["risk_checks"]["liquidity_check"]
    assert check["observed_at"] == "2026-09-18"
    assert check["source"] == "published_daily"


def test_publication_block_is_explained_and_kept_even_with_numeric_context():
    gates = {"price": {"blocked_reason": "publication_policy_changed"}}
    item = candidate(None, must_not_use_for_decision=True, publication_gates=gates)
    assert "行情发布规则已变更" in str(item["no_buy_reasons"])
    item = candidate(1000000, must_not_use_for_decision=True)
    assert item["recommendation_ready"] is False
    assert item["must_not_use_for_decision"] is True


@pytest.mark.parametrize(
    "code,message",
    [
        ("publication_policy_changed", "财报发布规则已变更"),
        ("publication_member_evidence_missing", "财报缺少来源时间或来源证据"),
        ("untrusted error with token", "财报未通过发布校验"),
    ],
)
def test_alpha_page_names_financial_block_even_when_volume_is_available(code, message):
    from django.template.loader import render_to_string

    item = candidate(
        1000000,
        must_not_use_for_decision=True,
        publication_gates={
            "financial": {"must_not_use_for_decision": True, "blocked_reason": code}
        },
    )
    assert not item["recommendation_ready"]
    html = render_to_string("dashboard/alpha_ranking.html", {"alpha_stocks": [item]})
    assert message in html
    assert "untrusted error with token" not in html


def test_weak_signal_explains_mapping_and_uses_the_actual_threshold():
    item = candidate(1000000, score=0.11408015747041618)
    assert item["recommendation_ready"] is False
    assert "0.1141" in item["no_buy_reason_summary"]
    assert "0.5570" in item["no_buy_reason_summary"]
    assert "0.6000" in item["no_buy_reason_summary"]
    assert item["extra_payload"]["signal_strength"] == pytest.approx(0.5570400787352081)
    assert "映射信号强度低于 0.6000" in item["invalidation_summary"]
    assert "0.55" not in item["invalidation_summary"]


@pytest.mark.parametrize(
    "quote_volume,daily_volume,expected", [(0, 1000, 0), (None, 1000, 1000), (None, None, None)]
)
def test_context_preserves_zero_missing_and_volume_provenance(quote_volume, daily_volume, expected):
    repo = DashboardAlphaContextRepository(
        SimpleNamespace(
            get_stock_context_map=lambda codes: {
                "300750.SZ": {"name": "N", "volume": daily_volume, "trade_date": date(2026, 9, 18)}
            }
        )
    )
    repo._load_data_center_asset_context = lambda *args: {}
    repo._load_legacy_holding_asset_context = lambda *args, **kwargs: {}
    repo._load_data_center_quote_context = lambda *args: {
        "300750.SZ": {
            "volume": quote_volume,
            "source": "published_quote",
            "snapshot_at": "2026-09-18T07:00:00Z",
        }
    }
    context = repo.load_stock_context(["300750.SZ"])["300750.SZ"]
    assert context["volume"] == expected
    if quote_volume is not None:
        assert context["volume_source"] == "published_quote"
        assert context["volume_observed_at"] == "2026-09-18T07:00:00Z"


def test_ranking_page_exposes_candidate_block_reason():
    from django.template.loader import render_to_string

    item = candidate(
        None,
        score=0.11408015747041618,
        must_not_use_for_decision=True,
        publication_gates={"price": {"blocked_reason": "publication_policy_changed"}},
    )
    html = render_to_string("dashboard/alpha_ranking.html", {"alpha_stocks": [item]})
    assert "信号强度不足" in html
    assert "0.5570" in html
    assert "行情发布规则已变更" in html
    assert "跳过流动性检查" not in html
