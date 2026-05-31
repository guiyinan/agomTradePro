"""Broker trade file parser implementations."""

from __future__ import annotations

import csv
import io
from typing import Any


class BrokerTradeFileParser:
    """Parse CSV/XLSX broker trade files into row dictionaries."""

    def parse(self, *, content: bytes, filename: str) -> list[dict[str, Any]]:
        suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else "csv"
        if suffix in {"xlsx", "xls"}:
            return self._parse_excel(content)
        return self._parse_csv(content)

    def _parse_csv(self, content: bytes) -> list[dict[str, Any]]:
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        return [dict(row) for row in reader]

    def _parse_excel(self, content: bytes) -> list[dict[str, Any]]:
        import pandas as pd

        frame = pd.read_excel(io.BytesIO(content))
        frame = frame.where(pd.notnull(frame), "")
        return [dict(row) for row in frame.to_dict(orient="records")]
