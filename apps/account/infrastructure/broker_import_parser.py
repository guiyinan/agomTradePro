"""Broker trade file parser implementations."""

from __future__ import annotations

import csv
import importlib
import io
from typing import Any, Protocol, cast


class _BrokerFrameProtocol(Protocol):
    """Narrow dataframe contract used at the optional pandas boundary."""

    def where(self, condition: object, other: object) -> _BrokerFrameProtocol: ...

    def to_dict(self, orient: str) -> list[dict[str, object]]: ...


class _PandasProtocol(Protocol):
    """Optional pandas operations required for Excel imports."""

    def read_excel(self, source: io.BytesIO) -> _BrokerFrameProtocol: ...

    def notnull(self, frame: _BrokerFrameProtocol) -> object: ...


class BrokerTradeFileParser:
    """Parse CSV/XLSX broker trade files into row dictionaries."""

    def parse(self, *, content: bytes, filename: str) -> list[dict[str, Any]]:
        suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else "csv"
        if suffix in {"xlsx", "xls"}:
            return self._parse_excel(content)
        return self._parse_csv(content)

    def _parse_csv(self, content: bytes) -> list[dict[str, Any]]:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("broker_trade_file_invalid_encoding") from exc
        reader = csv.DictReader(io.StringIO(text))
        return [dict(row) for row in reader]

    def _parse_excel(self, content: bytes) -> list[dict[str, Any]]:
        pandas_module = cast(_PandasProtocol, importlib.import_module("pandas"))
        frame = pandas_module.read_excel(io.BytesIO(content))
        frame = frame.where(pandas_module.notnull(frame), "")
        return [dict(row) for row in frame.to_dict(orient="records")]
