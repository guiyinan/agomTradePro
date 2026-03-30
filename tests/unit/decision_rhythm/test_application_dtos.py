from apps.decision_rhythm.application.dtos import UnifiedRecommendationDTO


def test_unified_recommendation_dto_can_init_without_optional_security_name():
    dto = UnifiedRecommendationDTO(
        recommendation_id="rec_001",
        account_id="acct_001",
        security_code="000001.SH",
        side="BUY",
    )

    assert dto.security_name == ""
    assert dto.side == "BUY"


def test_unified_recommendation_dto_accepts_security_name_as_keyword_only():
    dto = UnifiedRecommendationDTO(
        recommendation_id="rec_002",
        account_id="acct_001",
        security_code="000001.SH",
        side="SELL",
        security_name="Ping An Bank",
    )

    assert dto.security_name == "Ping An Bank"
    assert dto.side == "SELL"
