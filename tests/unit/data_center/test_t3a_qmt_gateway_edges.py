"""T3A QMT conversion, lazy-loading, and degradation contracts."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from apps.data_center.infrastructure.gateways import qmt_gateway


def test_qmt_scalar_helpers_and_code_normalization() -> None:
    assert qmt_gateway._safe_decimal(None) is None
    assert qmt_gateway._safe_decimal("bad") is None
    assert qmt_gateway._safe_decimal(float("nan")) is None
    assert qmt_gateway._safe_int("") is None
    assert qmt_gateway._safe_int("bad") is None
    assert qmt_gateway._pick_value({"a": "", "b": 2}, "a", "b") == 2
    assert qmt_gateway._pick_value({}, "a") is None
    assert qmt_gateway._normalize_provider_name(None) == "qmt"
    assert qmt_gateway._normalize_provider_name("  ") == "qmt"
    assert qmt_gateway._normalize_provider_name("local") == "qmt:local"
    assert qmt_gateway.QMTGateway._to_qmt_code("") == ""
    assert qmt_gateway.QMTGateway._to_qmt_code("600000") == "600000.SH"
    assert qmt_gateway.QMTGateway._to_qmt_code("000001") == "000001.SZ"
    assert qmt_gateway.QMTGateway._to_qmt_code("830001") == "830001.BJ"
    assert qmt_gateway.QMTGateway._to_qmt_code("MARKET") == "MARKET"


def test_quote_path_skips_invalid_rows_computes_changes_and_isolates_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = qmt_gateway.QMTGateway()
    xtdata = SimpleNamespace(
        get_full_tick=lambda _codes: {
            "000001.SZ": "invalid",
            "600000.SH": {"lastPrice": 0},
            "300001.SZ": {"lastPrice": 12, "lastClose": 10},
        }
    )
    monkeypatch.setattr(gateway, "_load_xtdata", lambda: xtdata)

    result = gateway.get_quote_snapshots(["000001", "600000", "300001"])

    assert len(result) == 1
    assert result[0].change == Decimal("2")
    assert result[0].change_pct == 20

    monkeypatch.setattr(
        gateway,
        "_load_xtdata",
        lambda: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    assert gateway.get_quote_snapshots(["000001"]) == []
    assert gateway.get_technical_snapshot("000001") is None


def test_history_path_handles_shape_variants_and_invalid_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = qmt_gateway.QMTGateway(extra_config={"dividend_type": "front"})
    xtdata = SimpleNamespace(
        get_market_data_ex=lambda **_kwargs: {
            "000001.SZ": pd.DataFrame(
                [
                    {
                        "time": "20240102",
                        "open": 1,
                        "high": 2,
                        "low": 0.5,
                        "close": 1.5,
                        "volume": 100,
                        "amount": 200,
                    },
                    {
                        "time": "bad",
                        "open": "bad",
                        "high": 2,
                        "low": 0.5,
                        "close": 1.5,
                    },
                ]
            )
        }
    )
    monkeypatch.setattr(gateway, "_load_xtdata", lambda: xtdata)
    result = gateway.get_historical_prices("000001.SZ", "20240101", "20240131")
    assert len(result) == 1

    xtdata.get_market_data_ex = lambda **_kwargs: pd.DataFrame({"open": [1]})
    assert gateway.get_historical_prices("000001.SZ", "20240101", "20240131") == []
    monkeypatch.setattr(
        gateway,
        "_load_xtdata",
        lambda: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    assert gateway.get_historical_prices("000001.SZ", "20240101", "20240131") == []


def test_lazy_loader_configures_data_dir_and_connect_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []

    def connect(*args: object) -> None:
        calls.append(("connect", args))
        if args:
            raise TypeError("legacy signature")

    module = SimpleNamespace(
        set_data_dir=lambda value: calls.append(("data_dir", value)),
        connect=connect,
    )
    monkeypatch.setattr(qmt_gateway.importlib, "import_module", lambda _name: module)
    loaded = qmt_gateway.QMTGateway(
        extra_config={"data_dir": "D:/qmt/data", "client_path": "D:/qmt"}
    )._load_xtdata()
    assert loaded is module
    assert ("data_dir", "D:/qmt/data") in calls
    assert ("connect", ()) in calls

    monkeypatch.setattr(
        qmt_gateway.importlib,
        "import_module",
        lambda _name: (_ for _ in ()).throw(ImportError("missing")),
    )
    with pytest.raises(RuntimeError, match="xtquant"):
        qmt_gateway.QMTGateway()._load_xtdata()


def test_history_frame_and_trade_date_parsers_cover_supported_shapes() -> None:
    frame = pd.DataFrame({"open": [1], "high": [2], "low": [0], "close": [1]})
    assert qmt_gateway.QMTGateway._extract_history_frame(None, "code") is None
    assert qmt_gateway.QMTGateway._extract_history_frame(frame, "code") is not frame
    assert qmt_gateway.QMTGateway._extract_history_frame({"code": frame}, "code") is not None
    assert (
        qmt_gateway.QMTGateway._extract_history_frame(
            {"open": [1], "high": [2], "low": [0], "close": [1]}, "code"
        )
        is not None
    )
    assert qmt_gateway.QMTGateway._extract_history_frame({"other": frame}, "code") is not None
    assert qmt_gateway.QMTGateway._extract_history_frame([{"open": 1}], "code") is not None
    assert qmt_gateway.QMTGateway._extract_history_frame("invalid", "code") is None

    assert qmt_gateway.QMTGateway._parse_trade_date(None) is None
    assert qmt_gateway.QMTGateway._parse_trade_date(" ") is None
    assert qmt_gateway.QMTGateway._parse_trade_date(date(2024, 1, 2)) == date(2024, 1, 2)
    assert qmt_gateway.QMTGateway._parse_trade_date(datetime(2024, 1, 2, tzinfo=UTC)) == date(
        2024, 1, 2
    )
    assert qmt_gateway.QMTGateway._parse_trade_date("20240102") == date(2024, 1, 2)
    assert qmt_gateway.QMTGateway._parse_trade_date("1704153600") == date(2024, 1, 2)
    assert qmt_gateway.QMTGateway._parse_trade_date("1704153600000") == date(2024, 1, 2)
    assert qmt_gateway.QMTGateway._parse_trade_date("2024/01/02") == date(2024, 1, 2)
    assert qmt_gateway.QMTGateway._parse_trade_date("bad") is None


def test_technical_invalid_history_row_empty_frame_and_default_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = qmt_gateway.QMTGateway()
    monkeypatch.setattr(
        gateway,
        "get_quote_snapshots",
        lambda _codes: [
            SimpleNamespace(
                price=Decimal("10"),
                turnover_rate=2.0,
                volume_ratio=1.1,
            )
        ],
    )
    assert gateway.get_technical_snapshot("000001.SZ") is not None

    xtdata = SimpleNamespace(
        get_market_data_ex=lambda **_kwargs: pd.DataFrame(
            [
                {
                    "trade_date": date(2024, 1, 2),
                    "open": "bad",
                    "high": 2,
                    "low": 0,
                    "close": 1,
                }
            ]
        )
    )
    monkeypatch.setattr(gateway, "_load_xtdata", lambda: xtdata)
    assert gateway.get_historical_prices("000001.SZ", "20240101", "20240131") == []
    xtdata.get_market_data_ex = lambda **_kwargs: pd.DataFrame()
    assert gateway.get_historical_prices("000001.SZ", "20240101", "20240131") == []

    calls: list[tuple[object, ...]] = []
    module = SimpleNamespace(connect=lambda *args: calls.append(args))
    monkeypatch.setattr(qmt_gateway.importlib, "import_module", lambda _name: module)
    qmt_gateway.QMTGateway()._load_xtdata()
    assert calls == [()]
