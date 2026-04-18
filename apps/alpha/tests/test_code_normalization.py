from datetime import date

from apps.alpha.domain.entities import normalize_stock_code
from apps.alpha.infrastructure.adapters.cache_adapter import CacheAlphaProvider


def test_normalize_stock_code_handles_tuple_serialized_prefix_symbol():
    raw_code = "(Timestamp('2026-04-14 00:00:00'), 'SZ002493')"

    assert normalize_stock_code(raw_code) == "002493.SZ"


def test_cache_provider_parse_scores_normalizes_legacy_codes_and_dates():
    provider = CacheAlphaProvider()

    scores = provider._parse_scores(
        [
            {
                "code": "(Timestamp('2026-04-14 00:00:00'), 'SH600522')",
                "score": 0.9,
                "rank": 1,
                "factors": {},
                "source": "qlib",
                "confidence": 0.8,
            }
        ],
        top_n=1,
        default_asof_date=date(2026, 4, 14),
        default_intended_trade_date=date(2026, 4, 16),
    )

    assert len(scores) == 1
    assert scores[0].code == "600522.SH"
    assert scores[0].asof_date == date(2026, 4, 14)
    assert scores[0].intended_trade_date == date(2026, 4, 16)
