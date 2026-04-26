from datetime import date
from types import SimpleNamespace

from core.integration.alpha_cache import (
    collect_alpha_cache_codes,
    get_alpha_cache_earliest_trade_date,
    normalize_alpha_cached_code,
)


def test_normalize_alpha_cached_code_uses_alpha_parser(monkeypatch):
    monkeypatch.setattr(
        "apps.alpha.infrastructure.cache_code_parser.normalize_cached_stock_code",
        lambda raw_code: raw_code.upper(),
    )

    assert normalize_alpha_cached_code("000001.sz") == "000001.SZ"


def test_collect_alpha_cache_codes_uses_alpha_models_and_parser(monkeypatch):
    class _FakeQueryset(list):
        def order_by(self, *args):
            return self

        def filter(self, **kwargs):
            return self

    fake_queryset = _FakeQueryset(
        [
            SimpleNamespace(scores=[{"stock_code": "000001.sz"}]),
            SimpleNamespace(scores=[{"stock_code": "000002.sz"}]),
        ]
    )

    monkeypatch.setattr(
        "apps.alpha.infrastructure.models.AlphaScoreCacheModel.objects",
        fake_queryset,
    )
    monkeypatch.setattr(
        "apps.alpha.infrastructure.cache_code_parser.collect_cached_score_codes",
        lambda scores: [item["stock_code"].upper() for item in scores],
    )
    monkeypatch.setattr(
        "apps.alpha.infrastructure.cache_code_parser.normalize_cached_stock_code",
        lambda raw_code: raw_code.upper(),
    )

    assert collect_alpha_cache_codes(
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 26),
        extra_codes=["600000.sh"],
    ) == ["000001.SZ", "000002.SZ", "600000.SH"]


def test_get_alpha_cache_earliest_trade_date_uses_alpha_model(monkeypatch):
    class _FakeManager:
        def order_by(self, *args):
            return self

        def values_list(self, *args, **kwargs):
            return self

        def first(self):
            return date(2026, 4, 20)

    monkeypatch.setattr(
        "apps.alpha.infrastructure.models.AlphaScoreCacheModel.objects",
        _FakeManager(),
    )

    assert get_alpha_cache_earliest_trade_date() == date(2026, 4, 20)
