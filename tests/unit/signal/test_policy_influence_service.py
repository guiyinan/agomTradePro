from apps.signal.application.services import PolicyInfluenceService
from apps.signal.domain.entities import InvestmentSignal


class _FakePolicyRepository:
    def list_blacklist_policies(self, asset_code: str):
        assert asset_code == "000001.SZ"
        return [
            {
                "id": 1,
                "title": "高风险政策",
                "level": "P2",
                "info_category": "macro",
                "structured_data": {},
            }
        ]

    def list_whitelist_policies(self, asset_code: str):
        return []

    def list_recent_sector_policies(self, cutoff_datetime):
        return [
            {
                "id": 2,
                "title": "行业利好",
                "level": "P1",
                "info_category": "sector",
                "structured_data": {
                    "affected_sectors": ["银行"],
                    "sentiment": "positive",
                },
            }
        ]

    def list_recent_sentiment_policies(self, *, asset_code: str, cutoff_datetime):
        return [
            {
                "id": 3,
                "title": "个股负面舆情",
                "level": "P1",
                "info_category": "individual",
                "structured_data": {
                    "sentiment": "negative",
                    "sentiment_score": -0.8,
                },
            }
        ]


class _FakeSectorRepository:
    def get_stock_sector_name_map(self):
        return {
            "000001.SZ": ["银行"],
        }


def test_policy_influence_service_uses_application_providers(monkeypatch):
    monkeypatch.setattr(
        "apps.signal.application.services.get_current_policy_repository",
        lambda: _FakePolicyRepository(),
    )
    monkeypatch.setattr(
        "apps.signal.application.services.get_sector_repository",
        lambda: _FakeSectorRepository(),
    )

    service = PolicyInfluenceService()
    signal = InvestmentSignal(
        id="sig-1",
        asset_code="000001.SZ",
        asset_class="a_share_finance",
        direction="LONG",
        logic_desc="test",
    )

    result = service.apply_policy_influences(signal)

    assert result["blacklisted"] is True
    assert result["whitelisted"] is False
    assert len(result["affected_by_policies"]) == 3
    assert result["risk_adjustments"] == [
        {
            "policy_id": 2,
            "adjustment": "favorable_sector",
            "reason": "利好政策: 行业利好",
        }
    ]
    assert any("负面舆情" in item for item in result["recommendations"])
