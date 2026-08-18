from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from apps.data_center.application.public import (
    get_latest_quote_payloads,
    get_macro_fact_series,
    get_price_bar_series,
)
from apps.data_center.infrastructure.models import (
    MacroFactModel,
    PriceBarModel,
    QuoteSnapshotModel,
)
from apps.pulse.infrastructure.data_provider import (
    DEFAULT_PULSE_INDICATORS,
    DjangoPulseDataProvider,
    PulseIndicatorDef,
)
from apps.pulse.infrastructure.models import PulseIndicatorConfigModel
from apps.sentiment.application.pulse_facade import (
    SentimentPulsePoint,
    SentimentPulseSeriesResult,
)


def _approved_historical_payload(
    rows: list[dict[str, object]],
) -> dict[str, object]:
    """Wrap canonical historical rows as an explicitly approved test read."""

    return {
        "rows": rows,
        "freshness_status": "historical_test_approved",
        "must_not_use_for_decision": not rows,
        "blocked_reason": "" if rows else "canonical_historical_rows_missing",
    }


@pytest.fixture(autouse=True)
def _use_approved_canonical_historical_ports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep component fixtures canonical without weakening production gates."""

    def read_macro(
        indicator_code: str,
        *,
        start: date | None = None,
        end: date | None = None,
        limit: int = 500,
        **_kwargs: object,
    ) -> dict[str, object]:
        return _approved_historical_payload(
            get_macro_fact_series(
                indicator_code,
                start=start,
                end=end,
                limit=limit,
            )
        )

    def read_prices(
        asset_code: str,
        *,
        start: date | None = None,
        end: date | None = None,
        limit: int = 500,
        **_kwargs: object,
    ) -> dict[str, object]:
        return _approved_historical_payload(
            get_price_bar_series(
                asset_code,
                start=start,
                end=end,
                limit=limit,
            )
        )

    def read_quotes(
        asset_codes: list[str],
        **_kwargs: object,
    ) -> dict[str, object]:
        return _approved_historical_payload(get_latest_quote_payloads(asset_codes))

    monkeypatch.setattr(
        "apps.pulse.infrastructure.data_provider.get_published_macro_fact_series",
        read_macro,
    )
    monkeypatch.setattr(
        "apps.pulse.infrastructure.data_provider.get_published_price_bar_series",
        read_prices,
    )
    monkeypatch.setattr(
        "apps.pulse.infrastructure.data_provider.get_published_quote_payloads",
        read_quotes,
    )


@pytest.fixture(autouse=True)
def _clear_seeded_pulse_indicator_configs(db) -> None:
    """Keep provider tests isolated from data migrations that seed runtime configs."""

    PulseIndicatorConfigModel.objects.all().delete()


@pytest.mark.django_db
def test_pulse_data_provider_reads_data_center_macro_facts():
    PulseIndicatorConfigModel.objects.create(
        indicator_code="CN_TERM_SPREAD_10Y2Y",
        indicator_name="国债利差(10Y-2Y)",
        dimension="growth",
        frequency="daily",
        weight=1.0,
        signal_type="level",
        bullish_threshold=100.0,
        bearish_threshold=0.0,
        neutral_band=0.5,
        signal_multiplier=0.4,
        is_active=True,
    )

    for idx, value in enumerate([60.0, 80.0, 110.0], start=1):
        MacroFactModel.objects.create(
            indicator_code="CN_TERM_SPREAD_10Y2Y",
            value=value,
            unit="bp",
            reporting_period=date(2026, 3, idx),
            source="akshare",
            published_at=date(2026, 3, idx),
            extra={
                "original_unit": "bp",
                "period_type": "D",
                "source_type": "akshare",
                "provider_name": "AKShare Public",
            },
        )

    readings = DjangoPulseDataProvider().get_all_readings(date(2026, 3, 3))

    assert len(readings) == 1
    assert readings[0].code == "CN_TERM_SPREAD_10Y2Y"
    assert readings[0].value == 110.0


@pytest.mark.django_db
def test_pulse_data_provider_reads_latest_data_center_macro_fact():
    PulseIndicatorConfigModel.objects.create(
        indicator_code="CN_PMI",
        indicator_name="制造业PMI",
        dimension="growth",
        frequency="monthly",
        weight=1.0,
        signal_type="level",
        bullish_threshold=52.0,
        bearish_threshold=48.0,
        neutral_band=0.5,
        signal_multiplier=0.4,
        is_active=True,
    )
    for day, value in [(19, 49.0), (20, 50.0), (21, 51.2)]:
        MacroFactModel.objects.create(
            indicator_code="CN_PMI",
            reporting_period=date(2026, 4, day),
            value=value,
            unit="指数",
            source="akshare",
            published_at=date(2026, 4, day),
            quality="valid",
            extra={
                "original_unit": "指数",
                "period_type": "M",
                "source_type": "akshare",
                "provider_name": "AKShare Public",
            },
        )

    readings = DjangoPulseDataProvider().get_all_readings(date(2026, 4, 21))

    assert len(readings) == 1
    assert readings[0].code == "CN_PMI"
    assert readings[0].value == 51.2


@pytest.mark.django_db
def test_pulse_data_provider_reads_asset_code_from_data_center_price_bars():
    PulseIndicatorConfigModel.objects.create(
        indicator_code="000300.SH",
        indicator_name="沪深300",
        dimension="sentiment",
        frequency="daily",
        weight=1.0,
        signal_type="level",
        bullish_threshold=4100.0,
        bearish_threshold=3500.0,
        neutral_band=0.5,
        signal_multiplier=0.4,
        is_active=True,
    )
    for day, close in [(19, 3840.0), (20, 3880.0), (21, 3925.5)]:
        PriceBarModel.objects.create(
            asset_code="000300.SH",
            bar_date=date(2026, 4, day),
            open=3800.0,
            high=3950.0,
            low=3790.0,
            close=close,
            source="AKShare Public",
        )

    readings = DjangoPulseDataProvider().get_all_readings(date(2026, 4, 21))

    assert len(readings) == 1
    assert readings[0].code == "000300.SH"
    assert readings[0].value == 3925.5
    assert readings[0].observed_at == date(2026, 4, 21)
    assert readings[0].source_kind == "price_bar_close"


@pytest.mark.django_db
def test_pulse_market_indicator_prefers_same_day_current_quote_over_previous_close():
    PulseIndicatorConfigModel.objects.create(
        indicator_code="000300.SH",
        indicator_name="沪深300",
        dimension="sentiment",
        frequency="daily",
        weight=1.0,
        signal_type="level",
        bullish_threshold=4700.0,
        bearish_threshold=4600.0,
        neutral_band=0.5,
        signal_multiplier=0.4,
        is_active=True,
    )
    for day, close in [(17, 4550.0), (18, 4575.0), (20, 4598.32)]:
        PriceBarModel.objects.create(
            asset_code="000300.SH",
            bar_date=date(2026, 7, day),
            open=close,
            high=close,
            low=close,
            close=close,
            source="AKShare Public",
        )
    QuoteSnapshotModel.objects.create(
        asset_code="000300.SH",
        snapshot_at=datetime(
            2026,
            7,
            21,
            15,
            5,
            tzinfo=ZoneInfo("Asia/Shanghai"),
        ),
        current_price=4739.23,
        prev_close=4598.32,
        source="AKShare Public",
    )

    readings = DjangoPulseDataProvider().get_all_readings(date(2026, 7, 21))

    assert len(readings) == 1
    assert readings[0].value == pytest.approx(4739.23)
    assert readings[0].observed_at == date(2026, 7, 21)
    assert readings[0].source_kind == "quote_current_price"
    assert readings[0].signal == "bullish"
    assert readings[0].is_stale is False


@pytest.mark.django_db
def test_pulse_market_indicator_marks_previous_session_close_stale_on_weekday():
    PulseIndicatorConfigModel.objects.create(
        indicator_code="000300.SH",
        indicator_name="沪深300",
        dimension="sentiment",
        frequency="daily",
        weight=1.0,
        signal_type="level",
        bullish_threshold=4700.0,
        bearish_threshold=4600.0,
        neutral_band=0.5,
        signal_multiplier=0.4,
        is_active=True,
    )
    PriceBarModel.objects.create(
        asset_code="000300.SH",
        bar_date=date(2026, 7, 20),
        open=4598.32,
        high=4598.32,
        low=4598.32,
        close=4598.32,
        source="AKShare Public",
    )

    readings = DjangoPulseDataProvider().get_all_readings(date(2026, 7, 21))

    assert len(readings) == 1
    assert readings[0].value == pytest.approx(4598.32)
    assert readings[0].observed_at == date(2026, 7, 20)
    assert readings[0].source_kind == "price_bar_close"
    assert readings[0].is_stale is True


@pytest.mark.django_db
def test_pulse_daily_freshness_tracks_business_day_age_but_blocks_old_market_session():
    PulseIndicatorConfigModel.objects.create(
        indicator_code="000300.SH",
        indicator_name="沪深300",
        dimension="sentiment",
        frequency="daily",
        weight=1.0,
        signal_type="level",
        bullish_threshold=4100.0,
        bearish_threshold=3500.0,
        neutral_band=0.5,
        signal_multiplier=0.4,
        is_active=True,
    )
    PriceBarModel.objects.create(
        asset_code="000300.SH",
        bar_date=date(2026, 7, 15),
        open=3800.0,
        high=3950.0,
        low=3790.0,
        close=3925.5,
        source="Tushare Pro",
    )

    readings = DjangoPulseDataProvider().get_all_readings(date(2026, 7, 20))

    assert len(readings) == 1
    assert readings[0].data_age_days == 3
    assert readings[0].is_stale is True


@pytest.mark.django_db
def test_pulse_data_provider_reads_fresh_module_sentiment_series(monkeypatch):
    PulseIndicatorConfigModel.objects.create(
        indicator_code="SENTIMENT_DAILY_INDEX",
        indicator_name="文本情绪指数",
        dimension="sentiment",
        frequency="daily",
        weight=1.0,
        signal_type="level",
        bullish_threshold=0.3,
        bearish_threshold=-0.3,
        neutral_band=0.1,
        signal_multiplier=0.4,
        is_active=True,
    )
    result = SentimentPulseSeriesResult(
        points=(
            SentimentPulsePoint(date(2026, 7, 29), -0.2),
            SentimentPulsePoint(date(2026, 7, 30), 0.5),
        ),
        observed_at=date(2026, 7, 30),
        must_not_use_for_decision=False,
        blocked_reason="",
    )
    monkeypatch.setattr(
        "apps.sentiment.application.pulse_facade.get_sentiment_pulse_series",
        lambda **kwargs: result,
    )

    readings = DjangoPulseDataProvider().get_all_readings(date(2026, 7, 30))

    assert len(readings) == 1
    assert readings[0].code == "SENTIMENT_DAILY_INDEX"
    assert readings[0].value == pytest.approx(0.5)
    assert readings[0].observed_at == date(2026, 7, 30)
    assert readings[0].source_kind == "sentiment_index"
    assert readings[0].is_stale is False


@pytest.mark.django_db
def test_pulse_data_provider_excludes_blocked_module_sentiment(monkeypatch):
    PulseIndicatorConfigModel.objects.create(
        indicator_code="SENTIMENT_DAILY_INDEX",
        indicator_name="文本情绪指数",
        dimension="sentiment",
        frequency="daily",
        weight=1.0,
        signal_type="level",
        bullish_threshold=0.3,
        bearish_threshold=-0.3,
        neutral_band=0.1,
        signal_multiplier=0.4,
        is_active=True,
    )
    result = SentimentPulseSeriesResult(
        points=(),
        observed_at=date(2026, 7, 24),
        must_not_use_for_decision=True,
        blocked_reason="sentiment_index_stale",
    )
    monkeypatch.setattr(
        "apps.sentiment.application.pulse_facade.get_sentiment_pulse_series",
        lambda **kwargs: result,
    )

    readings = DjangoPulseDataProvider().get_all_readings(date(2026, 7, 30))

    assert readings == []


def test_default_pulse_indicators_use_m2_yoy_not_balance_level():
    codes = {indicator.code for indicator in DEFAULT_PULSE_INDICATORS}

    assert "CN_M2_YOY" in codes
    assert "CN_M2" not in codes

    m2_yoy = next(
        indicator for indicator in DEFAULT_PULSE_INDICATORS if indicator.code == "CN_M2_YOY"
    )
    assert m2_yoy.signal_type == "level"
    assert m2_yoy.bullish_threshold == 8.0
    assert m2_yoy.bearish_threshold == 6.0

    new_credit = next(
        indicator for indicator in DEFAULT_PULSE_INDICATORS if indicator.code == "CN_NEW_CREDIT"
    )
    assert new_credit.bullish_threshold == 3.0e12
    assert new_credit.bearish_threshold == 1.0e12


def test_default_pulse_sentiment_portfolio_has_governed_signal_config():
    sentiment_defs = {
        indicator.code: indicator
        for indicator in DEFAULT_PULSE_INDICATORS
        if indicator.dimension == "sentiment"
    }

    assert set(sentiment_defs) == {
        "000300.SH",
        "CN_A_TOTAL_TURNOVER",
        "CN_A_MARGIN_BALANCE",
        "CN_A_MARKET_NEWS_SENTIMENT",
        "CN_A_ETF_NET_FLOW",
        "SENTIMENT_DAILY_INDEX",
        "CN_A_ADVANCE_COUNT",
        "CN_A_DECLINE_COUNT",
        "CN_A_LIMIT_UP_COUNT",
        "CN_A_LIMIT_DOWN_COUNT",
    }
    assert all(indicator.weight == 1.0 for indicator in sentiment_defs.values())
    assert sentiment_defs["000300.SH"].signal_type == "pct_change"
    assert sentiment_defs["CN_A_TOTAL_TURNOVER"].signal_type == "pct_change"
    assert sentiment_defs["CN_A_MARGIN_BALANCE"].signal_type == "pct_change"
    assert sentiment_defs["CN_A_MARKET_NEWS_SENTIMENT"].signal_type == "level"
    assert sentiment_defs["CN_A_ETF_NET_FLOW"].signal_type == "zscore"
    assert sentiment_defs["SENTIMENT_DAILY_INDEX"].signal_type == "level"
    assert sentiment_defs["CN_A_ADVANCE_COUNT"].signal_type == "zscore"
    assert sentiment_defs["CN_A_DECLINE_COUNT"].signal_multiplier < 0
    assert sentiment_defs["CN_A_LIMIT_UP_COUNT"].signal_multiplier > 0
    assert sentiment_defs["CN_A_LIMIT_DOWN_COUNT"].signal_multiplier < 0
    assert sentiment_defs["CN_A_LIMIT_UP_COUNT"].name == "A股涨停家数（不含 ST）"
    assert sentiment_defs["CN_A_LIMIT_DOWN_COUNT"].name == "A股跌停家数（不含 ST）"
    assert sentiment_defs["CN_A_MARKET_NEWS_SENTIMENT"].bullish_threshold == 0.2
    assert sentiment_defs["CN_A_MARKET_NEWS_SENTIMENT"].bearish_threshold == -0.2


def test_level_signal_is_consistent_at_bullish_boundary():
    provider = DjangoPulseDataProvider()
    indicator = PulseIndicatorDef(
        code="CN_PMI",
        name="制造业PMI",
        dimension="growth",
        frequency="monthly",
        signal_type="level",
        bullish_threshold=50.0,
        bearish_threshold=49.0,
    )

    signal, score = provider._signal_by_level(indicator, 50.0)

    assert signal == "bullish"
    assert score == 1.0
