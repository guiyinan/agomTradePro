from datetime import date

from core.integration.alpha_cache import (
    collect_alpha_cache_codes,
    get_alpha_cache_earliest_trade_date,
    normalize_alpha_cached_code,
)


def test_normalize_alpha_cached_code_uses_query_service(monkeypatch):
    monkeypatch.setattr(
        "core.integration.alpha_cache._normalize_alpha_cached_code",
        lambda raw_code: raw_code.upper(),
    )

    assert normalize_alpha_cached_code("000001.sz") == "000001.SZ"


def test_collect_alpha_cache_codes_uses_query_service(monkeypatch):
    seen = {}

    def _collect(**kwargs):
        seen.update(kwargs)
        return ["000001.SZ", "000002.SZ", "600000.SH"]

    monkeypatch.setattr(
        "core.integration.alpha_cache._collect_alpha_cache_codes",
        _collect,
    )

    assert collect_alpha_cache_codes(
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 26),
        extra_codes=["600000.sh"],
    ) == ["000001.SZ", "000002.SZ", "600000.SH"]
    assert seen == {
        "start_date": date(2026, 4, 1),
        "end_date": date(2026, 4, 26),
        "extra_codes": ["600000.sh"],
    }


def test_get_alpha_cache_earliest_trade_date_uses_query_service(monkeypatch):
    monkeypatch.setattr(
        "core.integration.alpha_cache._get_alpha_cache_earliest_trade_date",
        lambda: date(2026, 4, 20),
    )

    assert get_alpha_cache_earliest_trade_date() == date(2026, 4, 20)
