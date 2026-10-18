"""CSV/XLSX broker file boundary with a typed normalized-fact parser."""

from __future__ import annotations

import csv
import hashlib
import importlib
import io
import math
from collections.abc import Callable, Mapping
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Literal, Protocol, cast

from django.utils import timezone

from apps.account.application.broker_trade_reconciliation_contracts import (
    BrokerTradeParseIssue,
    BrokerTradeParseResult,
    JsonValue,
    NormalizedTradeRow,
)
from shared.numeric import safe_float

_REQUIRED_COLUMNS = frozenset({"traded_at", "action", "asset_code", "shares", "price"})
_MAX_BROKER_TRADE_IMPORT_ROWS = 5000


class _BrokerFrameProtocol(Protocol):
    """Narrow dataframe contract used at the optional pandas boundary."""

    def where(self, condition: object, other: object) -> _BrokerFrameProtocol:
        """Replace missing dataframe cells with the configured sentinel."""
        ...

    def to_dict(self, orient: str) -> list[dict[str, object]]:
        """Materialize dataframe rows at the third-party boundary."""
        ...


class _PandasProtocol(Protocol):
    """Optional pandas operations required for Excel imports."""

    def read_excel(self, source: io.BytesIO) -> _BrokerFrameProtocol:
        """Read an Excel byte stream."""
        ...

    def notnull(self, frame: _BrokerFrameProtocol) -> object:
        """Return pandas' cell-presence mask."""
        ...


class BrokerTradeFactParserProtocol(Protocol):
    """Typed parser boundary consumed by Application orchestration."""

    def parse_normalized_facts(
        self,
        *,
        content: bytes,
        filename: str,
        broker_name: str,
        portfolio_id: int,
    ) -> BrokerTradeParseResult:
        """Return only validated facts and JSON-safe source payloads."""
        ...


class BrokerTradeFileParser:
    """Parse CSV/XLSX rows and expose a validated facts-first parse operation."""

    def __init__(self, raw_parser: object | None = None) -> None:
        self._raw_parser = raw_parser

    def parse(self, *, content: bytes, filename: str) -> list[dict[str, Any]]:
        """Keep the historical raw-row API for other callers."""
        if self._raw_parser is not None:
            parse_method = getattr(self._raw_parser, "parse", None)
            if not callable(parse_method):
                raise TypeError("Injected broker parser must provide parse()")
            raw_result = cast("Callable[..., object]", parse_method)(
                content=content,
                filename=filename,
            )
            if not isinstance(raw_result, list) or not all(
                isinstance(row, dict) for row in raw_result
            ):
                raise TypeError("Injected broker parser returned an invalid row payload")
            return cast(list[dict[str, Any]], raw_result)
        suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else "csv"
        if suffix in {"xlsx", "xls"}:
            return self._parse_excel(content)
        return self._parse_csv(content)

    def parse_normalized_facts(
        self,
        *,
        content: bytes,
        filename: str,
        broker_name: str,
        portfolio_id: int,
    ) -> BrokerTradeParseResult:
        """Narrow external rows, validate persisted precision, and retain JSON-safe source."""
        raw_rows = self.parse(content=content, filename=filename)
        if len(raw_rows) > _MAX_BROKER_TRADE_IMPORT_ROWS:
            raise ValueError(
                f"Broker trade import cannot exceed {_MAX_BROKER_TRADE_IMPORT_ROWS} rows"
            )

        normalized_rows: list[NormalizedTradeRow] = []
        errors: list[BrokerTradeParseIssue] = []
        for row_number, raw_row in enumerate(raw_rows, start=2):
            try:
                lowered = _normalize_source_columns(raw_row)
                if lowered is None:
                    errors.append(
                        BrokerTradeParseIssue(
                            row_number=row_number,
                            error_code="broker_row_invalid",
                            message="Broker parser returned a row with a non-string column name",
                        )
                    )
                    continue
                missing = sorted(_REQUIRED_COLUMNS - set(lowered))
                if missing:
                    errors.append(
                        BrokerTradeParseIssue(
                            row_number=row_number,
                            error_code="broker_required_columns_missing",
                            message=f"Missing columns: {', '.join(missing)}",
                        )
                    )
                    continue
                normalized_rows.append(
                    _normalize_row(
                        lowered,
                        raw_row=raw_row,
                        row_number=row_number,
                        broker_name=broker_name,
                        portfolio_id=portfolio_id,
                    )
                )
            except ValueError as exc:
                errors.append(
                    BrokerTradeParseIssue(
                        row_number=row_number,
                        error_code="broker_row_invalid",
                        message=str(exc),
                    )
                )
        return BrokerTradeParseResult(rows=tuple(normalized_rows), errors=tuple(errors))

    def _parse_csv(self, content: bytes) -> list[dict[str, Any]]:
        """Parse CSV text while retaining the old raw dictionaries at this boundary."""
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("broker_trade_file_invalid_encoding") from exc
        reader = csv.DictReader(io.StringIO(text))
        return [dict(row) for row in reader]

    def _parse_excel(self, content: bytes) -> list[dict[str, Any]]:
        """Read Excel through pandas without leaking its types past this boundary."""
        pandas_module = cast(_PandasProtocol, importlib.import_module("pandas"))
        frame = pandas_module.read_excel(io.BytesIO(content))
        frame = frame.where(pandas_module.notnull(frame), "")
        return [dict(row) for row in frame.to_dict(orient="records")]


def _normalize_source_columns(raw_row: Mapping[str, object]) -> dict[str, object] | None:
    """Normalize external header names and reject ambiguous duplicate columns."""
    lowered: dict[str, object] = {}
    for key, value in raw_row.items():
        if not isinstance(key, str):
            return None
        normalized_key = key.strip().lower()
        if normalized_key in lowered:
            raise ValueError(f"Duplicate column after normalization: {normalized_key}")
        lowered[normalized_key] = value
    return lowered


def build_normalized_broker_trade_file_parser(
    raw_parser: object | None = None,
) -> BrokerTradeFactParserProtocol:
    """Wrap the legacy raw parser at Infrastructure and expose a typed parser."""
    if raw_parser is not None:
        normalized_parser = getattr(raw_parser, "parse_normalized_facts", None)
        if callable(normalized_parser):
            return cast(BrokerTradeFactParserProtocol, raw_parser)
    return BrokerTradeFileParser(raw_parser=raw_parser)


def _normalize_row(
    lowered: dict[str, object],
    *,
    raw_row: Mapping[str, object],
    row_number: int,
    broker_name: str,
    portfolio_id: int,
) -> NormalizedTradeRow:
    """Build one fact after exact type, numeric, and persisted-scale validation."""
    action_value = _source_text(lowered.get("action"), field_name="action").lower()
    if action_value not in {"buy", "sell"}:
        raise ValueError("action must be buy or sell")
    action = cast("Literal['buy', 'sell']", action_value)
    traded_at = _parse_traded_at(lowered["traded_at"])
    asset_code = _source_text(lowered.get("asset_code"), field_name="asset_code").upper()
    if not asset_code:
        raise ValueError("asset_code is required")

    shares_decimal = _parse_finite_decimal(lowered["shares"], field_name="shares")
    if shares_decimal <= 0:
        raise ValueError("shares must be positive")
    if not _fits_database_decimal(shares_decimal, max_digits=20, decimal_places=6):
        raise ValueError("shares exceed supported 20-digit, 6-decimal position precision")
    shares_value = safe_float(lowered["shares"], default=None)
    if shares_value is None or shares_value <= 0:
        raise ValueError("shares must be a positive finite number")
    if Decimal(str(shares_value)) != shares_decimal:
        raise ValueError("shares cannot be represented exactly by the persisted float field")

    price = _parse_finite_decimal(lowered["price"], field_name="price")
    if price <= 0:
        raise ValueError("price must be positive")
    if not _fits_database_decimal(price, max_digits=20, decimal_places=4):
        raise ValueError("price exceeds supported 20-digit, 4-decimal database precision")

    notional = shares_decimal * price
    if not _fits_database_decimal(notional, max_digits=20, decimal_places=2):
        raise ValueError("notional exceeds supported 20-digit, 2-decimal database precision")

    commission = _parse_optional_fee(lowered.get("commission"), field_name="commission")
    stamp_duty = _parse_optional_fee(lowered.get("stamp_duty"), field_name="stamp_duty")
    transfer_fee = _parse_optional_fee(lowered.get("transfer_fee"), field_name="transfer_fee")
    external_trade_id = _source_text(
        lowered.get("external_trade_id", ""), field_name="external_trade_id"
    )
    notes = _source_text(lowered.get("notes", ""), field_name="notes")
    broker_trade_key = _build_broker_trade_key(
        broker_name=broker_name,
        portfolio_id=portfolio_id,
        external_trade_id=external_trade_id,
        traded_at=traded_at,
        action=action,
        asset_code=asset_code,
        shares=shares_value,
        price=price,
    )
    canonical_payload = _canonical_json_object(raw_row)
    return NormalizedTradeRow(
        row_number=row_number,
        traded_at=traded_at,
        action=action,
        asset_code=asset_code,
        shares=shares_value,
        price=price,
        commission=commission,
        stamp_duty=stamp_duty,
        transfer_fee=transfer_fee,
        external_trade_id=external_trade_id,
        notes=notes,
        broker_trade_key=broker_trade_key,
        raw_payload=canonical_payload,
    )


def _source_text(value: object, *, field_name: str) -> str:
    """Convert a validated source cell to text without treating None as a number."""
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _parse_traded_at(value: object) -> datetime:
    """Read a broker execution clock and retain its original aware offset."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.fromisoformat(value.isoformat())
    else:
        raw = _source_text(value, field_name="traded_at").replace("/", "-")
        if not raw:
            raise ValueError("traded_at is required")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise ValueError("traded_at must be ISO datetime or date") from exc
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _parse_finite_decimal(value: object, *, field_name: str) -> Decimal:
    """Parse a finite Decimal without applying implicit database rounding."""
    raw = _source_text(value, field_name=field_name)
    if not raw:
        raise ValueError(f"{field_name} is required")
    try:
        parsed = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"{field_name} must be numeric") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field_name} must be finite")
    if parsed < 0:
        raise ValueError(f"{field_name} must not be negative")
    return parsed


def _parse_optional_fee(value: object, *, field_name: str) -> Decimal | None:
    """Apply the existing half-up cents rule before checking stored fee precision."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    parsed = _parse_finite_decimal(value, field_name=field_name)
    try:
        normalized = parsed.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError(f"{field_name} exceeds supported fee precision") from exc
    if not _fits_database_decimal(normalized, max_digits=10, decimal_places=2):
        raise ValueError(f"{field_name} exceeds supported 10-digit, 2-decimal database precision")
    return parsed if parsed == normalized else normalized


def _fits_database_decimal(
    value: Decimal,
    *,
    max_digits: int,
    decimal_places: int,
) -> bool:
    """Return whether an exact finite Decimal fits the declared Django field scale."""
    if not value.is_finite():
        return False
    quantum = Decimal(1).scaleb(-decimal_places)
    try:
        scaled = value.quantize(quantum)
    except InvalidOperation:
        return False
    if scaled != value:
        return False
    max_integer_digits = max_digits - decimal_places
    return value == 0 or value.adjusted() + 1 <= max_integer_digits


def _build_broker_trade_key(
    *,
    broker_name: str,
    portfolio_id: int,
    external_trade_id: str,
    traded_at: datetime,
    action: str,
    asset_code: str,
    shares: float,
    price: Decimal,
) -> str:
    """Preserve the historical stable-key formula, including its original offset."""
    if external_trade_id:
        raw_key = f"{broker_name}|{portfolio_id}|{external_trade_id}"
    else:
        raw_key = (
            f"{broker_name}|{portfolio_id}|{traded_at.isoformat()}|"
            f"{action}|{asset_code}|{shares:.6f}|{price}"
        )
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _canonical_json_object(raw_row: Mapping[str, object]) -> dict[str, JsonValue]:
    """Convert source values into JSON primitives before persistence."""
    return {str(key): _canonical_json_value(value) for key, value in raw_row.items()}


def _canonical_json_value(value: object) -> JsonValue:
    """Canonicalize common CSV/Excel values; keep non-finite values as text evidence."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _canonical_json_value(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_json_value(child) for child in value]
    item_method = getattr(value, "item", None)
    if callable(item_method):
        try:
            scalar = cast("Callable[[], object]", item_method)()
        except (TypeError, ValueError, OverflowError):
            return str(value)
        if scalar is not value:
            return _canonical_json_value(scalar)
    return str(value)
