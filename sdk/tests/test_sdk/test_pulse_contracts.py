from unittest.mock import patch

from agomtradepro import AgomTradeProClient


def test_pulse_action_recommendation_preserves_blocked_contract():
    client = AgomTradeProClient(base_url="http://test.com", api_token="test_token")
    blocked_payload = {
        "success": True,
        "data": {
            "asset_weights": {},
            "risk_budget_pct": 0.0,
            "position_limit_pct": 0.0,
            "recommended_sectors": [],
            "benefiting_styles": [],
            "hedge_recommendation": None,
            "reasoning": "Pulse 数据未通过 freshness/reliability 校验，联合行动建议已阻断。",
            "regime_contribution": "Recovery 导航仪仍可读取，但 Pulse 数据未达到决策级可靠性。",
            "pulse_contribution": "Pulse 数据不可靠，联合行动建议已阻断。",
            "generated_at": "2026-04-21",
            "confidence": 0.41,
            "must_not_use_for_decision": True,
            "blocked_reason": "Pulse 数据未通过 freshness/reliability 校验，联合行动建议已阻断。",
            "blocked_code": "pulse_unreliable",
            "pulse_observed_at": "2026-04-20",
            "pulse_is_reliable": False,
            "stale_indicator_codes": ["CN_PMI", "000300.SH"],
            "contract": {
                "must_not_use_for_decision": True,
                "blocked_reason": "Pulse 数据未通过 freshness/reliability 校验，联合行动建议已阻断。",
                "blocked_code": "pulse_unreliable",
                "pulse_observed_at": "2026-04-20",
                "pulse_is_reliable": False,
                "stale_indicator_codes": ["CN_PMI", "000300.SH"],
            },
        },
    }

    with patch.object(client, "get", return_value=blocked_payload):
        result = client.pulse.get_action_recommendation()

    assert result["data"]["contract"]["must_not_use_for_decision"] is True
    assert result["data"]["contract"]["pulse_is_reliable"] is False
    assert result["data"]["contract"]["stale_indicator_codes"] == ["CN_PMI", "000300.SH"]

