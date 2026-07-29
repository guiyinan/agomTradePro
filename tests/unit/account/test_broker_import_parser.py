"""Broker import parser boundary tests."""

import pytest

from apps.account.infrastructure.broker_import_parser import BrokerTradeFileParser


def test_csv_parser_rejects_invalid_encoding_with_stable_error() -> None:
    """Invalid uploads fail without reflecting undecodable source bytes."""

    with pytest.raises(ValueError, match="^broker_trade_file_invalid_encoding$"):
        BrokerTradeFileParser().parse(content=b"\xff\xfe\x00\x81", filename="trades.csv")


def test_csv_parser_preserves_named_columns() -> None:
    """CSV rows retain broker headers for the application normalizer."""

    rows = BrokerTradeFileParser().parse(
        content="成交日期,证券代码,成交数量\n2026-07-29,000001,100\n".encode(),
        filename="trades.csv",
    )

    assert rows == [{"成交日期": "2026-07-29", "证券代码": "000001", "成交数量": "100"}]
