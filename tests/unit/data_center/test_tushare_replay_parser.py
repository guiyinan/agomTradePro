"""Offline tests exercise the Tushare production row mapping seams."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.infrastructure._provider_adapter_tushare import TushareUnifiedProviderAdapter
from apps.data_center.infrastructure.gateways.tushare_gateway import TushareGateway
from apps.data_center.infrastructure.tushare_client import (
    TushareResponseEvidence,
    _provider_frame,
)
from apps.data_center.infrastructure.tushare_replay_parser import (
    map_tushare_daily_basic_row,
    matches_tushare_market_cap_unit,
    parse_tushare_daily_quote_rows,
)


def _config() -> ProviderConfig:
    return ProviderConfig(
        id=1,
        name="tushare-fixture",
        source_type="tushare",
        is_active=True,
        priority=1,
        api_key="fixture-only",
        api_secret="",
        http_url="",
        api_endpoint="",
        extra_config={},
        description="",
    )


def test_production_quote_path_accepts_witnessed_frame_and_replay_target(monkeypatch) -> None:
    completed_at = datetime(2026, 9, 23, 8, 5, tzinfo=UTC)
    frame = _provider_frame(
        [
            ["20260922", 12.0, 11.9, 100, 1_000],
            ["20260923", 12.5, 12.0, 200, 2_500],
        ],
        ["trade_date", "close", "pre_close", "vol", "amount"],
        None,
        TushareResponseEvidence("a" * 64, completed_at),
    )
    gateway = TushareGateway()
    monkeypatch.setattr(
        gateway,
        "_create_client",
        lambda: SimpleNamespace(daily=lambda **_kwargs: frame),
    )

    quotes = gateway.get_quote_snapshots(["000001.SZ"])
    replayed = parse_tushare_daily_quote_rows(
        frame.to_dict("records"),
        requested_asset_code="000001.SZ",
        source="tushare",
        fetched_at=completed_at,
        target_date=date(2026, 9, 23),
    )

    assert len(quotes) == 1
    assert replayed is not None
    assert quotes[0].price == replayed.price == 12.5
    assert quotes[0].observed_at == datetime(2026, 9, 23, 7, tzinfo=UTC)
    assert quotes[0].fetched_at == completed_at
    assert quotes[0].volume == 200


def test_witnessed_frame_preserves_dataframe_operations_for_all_consumers() -> None:
    completed_at = datetime(2026, 9, 23, 8, 5, tzinfo=UTC)
    frame = _provider_frame(
        [
            ["000001.SZ", "20260923", 12.5],
            ["000001.SZ", "20260922", 12.0],
        ],
        ["ts_code", "trade_date", "close"],
        None,
        TushareResponseEvidence("e" * 64, completed_at),
    )

    assert len(frame) == 2
    assert set(frame.columns) == {"ts_code", "trade_date", "close"}
    assert frame["trade_date"].tolist() == ["20260923", "20260922"]
    assert frame.sort_values("trade_date").to_dict("records")[0]["close"] == 12.0
    assert frame.copy().loc[frame["close"] > 12.0].to_dict("records") == [
        {"ts_code": "000001.SZ", "trade_date": "20260923", "close": 12.5}
    ]


def test_production_daily_basic_path_uses_the_same_row_mapper(monkeypatch) -> None:
    completed_at = datetime(2026, 9, 23, 8, 5, tzinfo=UTC)
    evidence = TushareResponseEvidence("b" * 64, completed_at)
    frame = _provider_frame(
        [["000001.SZ", "20260923", 5.2, 0.5, 2256.91, 2256.87, 1.4]],
        ["ts_code", "trade_date", "pe_ttm", "pb", "total_mv", "circ_mv", "dv_ttm"],
        None,
        evidence,
    )

    class _Pro:
        def daily_basic(self, **_kwargs: object) -> object:
            return frame

    adapter = TushareUnifiedProviderAdapter(_config())
    monkeypatch.setattr(adapter, "_create_pro_client", lambda: _Pro())

    facts = adapter.fetch_current_valuations(["000001.SZ"], date(2026, 9, 23))

    assert len(facts) == 1
    fact = facts[0]
    assert fact.market_cap == 22_569_100.0
    assert fact.float_market_cap == 22_568_700.0
    assert fact.observed_at == datetime(2026, 9, 23, 7, tzinfo=UTC)
    assert fact.available_at == fact.fetched_at == completed_at
    assert fact.raw_payload_hash == "b" * 64
    assert matches_tushare_market_cap_unit(2256.91, fact.market_cap)
    assert not matches_tushare_market_cap_unit(2256.91, 2256.91)


def test_replay_target_missing_source_date_and_followup_body_are_distinguishable() -> None:
    old_row = {"trade_date": "20260922", "close": "12.0"}
    assert (
        parse_tushare_daily_quote_rows(
            [old_row],
            requested_asset_code="000001.SZ",
            source="tushare",
            fetched_at=datetime(2026, 9, 23, 8, 5, tzinfo=UTC),
            target_date=date(2026, 9, 23),
        )
        is None
    )
    assert (
        map_tushare_daily_basic_row(
            {"pb": 0.5},
            asset_code="000001.SZ",
            source="tushare",
            provider_extra={"source_type": "tushare"},
            response_completed_at=datetime(2026, 9, 23, 8, 5, tzinfo=UTC),
        )
        is None
    )
    first = map_tushare_daily_basic_row(
        {"trade_date": "20260923", "pb": 0.5, "total_mv": 2256.91},
        asset_code="000001.SZ",
        source="tushare",
        provider_extra={"source_type": "tushare"},
        response_completed_at=datetime(2026, 9, 23, 8, 5, tzinfo=UTC),
        response_evidence=TushareResponseEvidence(
            "c" * 64, datetime(2026, 9, 23, 8, 5, tzinfo=UTC)
        ),
    )
    later = map_tushare_daily_basic_row(
        {"trade_date": "20260923", "pb": 0.6, "total_mv": 2300.0},
        asset_code="000001.SZ",
        source="tushare",
        provider_extra={"source_type": "tushare"},
        response_completed_at=datetime(2026, 9, 23, 9, 0, tzinfo=UTC),
        response_evidence=TushareResponseEvidence(
            "d" * 64, datetime(2026, 9, 23, 9, 0, tzinfo=UTC)
        ),
    )
    assert first is not None and later is not None
    assert first.pb == 0.5 and later.pb == 0.6
    assert first.market_cap == 22_569_100.0 and later.market_cap == 23_000_000.0
    assert first.source_record_id != later.source_record_id
