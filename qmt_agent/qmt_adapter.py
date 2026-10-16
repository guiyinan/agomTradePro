"""QMT adapter; this is the only Agent file allowed to import ``xtquant``."""

from __future__ import annotations

import base64
import hashlib
import math
import operator
import random
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol, SupportsIndex, cast

_ORDER_REMARK_PREFIX = "A"


def encode_order_remark(client_order_id: str) -> str:
    """Encode a UUID into a reversible QMT remark under its 24-byte limit."""

    raw = uuid.UUID(str(client_order_id)).bytes
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"{_ORDER_REMARK_PREFIX}{encoded}"


def decode_order_remark(order_remark: str) -> str | None:
    """Decode an Agom compact remark, while accepting legacy full UUID remarks."""

    value = str(order_remark or "").strip()
    try:
        if value.startswith(_ORDER_REMARK_PREFIX) and len(value) == 23:
            raw = base64.urlsafe_b64decode(value[1:] + "==")
            return str(uuid.UUID(bytes=raw))
        return str(uuid.UUID(value))
    except (ValueError, TypeError):
        return None


def _qmt_order_status_map(xtconstant: Any) -> dict[Any, str]:
    """Map all documented stock-order states to the server lifecycle."""

    return {
        getattr(xtconstant, "ORDER_UNREPORTED", object()): "SUBMITTED",
        getattr(xtconstant, "ORDER_WAIT_REPORTING", object()): "SUBMITTED",
        getattr(xtconstant, "ORDER_REPORTED", object()): "SUBMITTED",
        getattr(xtconstant, "ORDER_REPORTED_CANCEL", object()): "CANCEL_PENDING",
        getattr(xtconstant, "ORDER_PARTSUCC_CANCEL", object()): "CANCEL_PENDING",
        getattr(xtconstant, "ORDER_PART_CANCEL", object()): "CANCELED",
        getattr(xtconstant, "ORDER_CANCELED", object()): "CANCELED",
        getattr(xtconstant, "ORDER_PART_SUCC", object()): "PARTIALLY_FILLED",
        getattr(xtconstant, "ORDER_SUCCEEDED", object()): "FILLED",
        getattr(xtconstant, "ORDER_JUNK", object()): "BROKER_REJECTED",
        getattr(xtconstant, "ORDER_UNKNOWN", object()): "RECONCILIATION_REQUIRED",
    }


def _qmt_event_time(raw: Any, fallback: str) -> str:
    """Return an aware ISO timestamp from QMT epoch seconds when available."""

    try:
        value = int(raw)
        if value > 0:
            return datetime.fromtimestamp(value, UTC).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        pass
    return fallback


@dataclass(frozen=True)
class BrokerSubmitResult:
    """Normalized result returned immediately by QMT order submission."""

    accepted: bool
    broker_order_id: str
    message: str = ""


class QmtMarketFieldState(StrEnum):
    """State of one value projected from the local QMT vendor response."""

    PRESENT = "PRESENT"
    UNKNOWN = "UNKNOWN"
    INVALID = "INVALID"


class QmtSecurityState(StrEnum):
    """Security tradability state supported by this local snapshot slice."""

    UNKNOWN = "UNKNOWN"


class QmtBoundaryMode(StrEnum):
    """Whether QMT supplied a complete, internally ordered limit pair."""

    UNKNOWN = "UNKNOWN"
    REPORTED_LIMITS = "REPORTED_LIMITS"


@dataclass(frozen=True)
class QmtMarketFieldEvidence:
    """Typed value plus its vendor API and field provenance."""

    state: QmtMarketFieldState
    value: str | int | bool | None
    source_api: str
    source_field: str
    reason_code: str | None = None

    def __post_init__(self) -> None:
        """Keep evidence state and value shape consistent."""

        if not self.source_api or not self.source_field:
            raise ValueError("QMT market evidence must identify its source field")
        if self.state is QmtMarketFieldState.PRESENT and self.value is None:
            raise ValueError("present QMT market evidence requires a value")
        if self.state is not QmtMarketFieldState.PRESENT and self.value is not None:
            raise ValueError("unknown or invalid QMT market evidence cannot carry a value")

    def to_payload(self) -> dict[str, object]:
        """Serialize one field as an auditable, JSON-safe payload."""

        return {
            "state": self.state.value,
            "value": self.value,
            "source_api": self.source_api,
            "source_field": self.source_field,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True)
class QmtMarketSnapshot:
    """Typed local evidence from QMT metadata and its latest full-tick response.

    Capture time records when this process assembled the object. Instrument
    metadata has no observation timestamp in the consumed QMT API, so it is
    always left unknown and this snapshot never proves order usability.
    """

    asset_code: str
    captured_at_utc: datetime
    metadata_observed_at: datetime | None
    last_price: QmtMarketFieldEvidence
    upper_limit: QmtMarketFieldEvidence
    lower_limit: QmtMarketFieldEvidence
    price_tick: QmtMarketFieldEvidence
    ask_price: QmtMarketFieldEvidence
    bid_price: QmtMarketFieldEvidence
    open_int: QmtMarketFieldEvidence
    tick_time_ms: QmtMarketFieldEvidence
    instrument_status: QmtMarketFieldEvidence
    is_trading: QmtMarketFieldEvidence
    stock_status: QmtMarketFieldEvidence
    security_state: QmtSecurityState
    boundary_mode: QmtBoundaryMode

    def __post_init__(self) -> None:
        """Reject timestamps that could be mistaken for naive source times."""

        utc_offset = self.captured_at_utc.utcoffset()
        if utc_offset is None:
            raise ValueError("QMT snapshot capture time must be timezone-aware")
        if utc_offset.total_seconds() != 0:
            raise ValueError("QMT snapshot capture time must be UTC")
        if self.metadata_observed_at is not None:
            raise ValueError("QMT instrument metadata has no source observation time")
        if self.security_state is not QmtSecurityState.UNKNOWN:
            raise ValueError("this QMT snapshot slice cannot prove security tradability")

    @property
    def boundary_usable_for_submission(self) -> bool:
        """Return false because local metadata has no verified source timestamp."""

        return False

    @property
    def market_evidence_usable_for_submission(self) -> bool:
        """Return false because this local snapshot is not a server authorization."""

        return False

    def to_payload(self) -> dict[str, object]:
        """Serialize typed evidence and preserve legacy executor keys."""

        fields: dict[str, QmtMarketFieldEvidence] = {
            "last_price": self.last_price,
            "upper_limit": self.upper_limit,
            "lower_limit": self.lower_limit,
            "price_tick": self.price_tick,
            "ask_price": self.ask_price,
            "bid_price": self.bid_price,
            "open_int": self.open_int,
            "tick_time_ms": self.tick_time_ms,
            "instrument_status": self.instrument_status,
            "is_trading": self.is_trading,
            "stock_status": self.stock_status,
        }
        boundary_is_reported = self.boundary_mode is QmtBoundaryMode.REPORTED_LIMITS

        def present_value(evidence: QmtMarketFieldEvidence) -> str | int | bool | None:
            """Project only explicitly present local field values."""

            if evidence.state is QmtMarketFieldState.PRESENT:
                return evidence.value
            return None

        return {
            "asset_code": self.asset_code,
            "captured_at_utc": self.captured_at_utc.isoformat(),
            "metadata_observed_at": None,
            "metadata_freshness": QmtMarketFieldState.UNKNOWN.value,
            "last_price": present_value(self.last_price),
            "upper_limit": present_value(self.upper_limit) if boundary_is_reported else None,
            "lower_limit": present_value(self.lower_limit) if boundary_is_reported else None,
            "price_tick": present_value(self.price_tick),
            "ask_price": present_value(self.ask_price),
            "bid_price": present_value(self.bid_price),
            "open_int": present_value(self.open_int),
            "tick_time_ms": present_value(self.tick_time_ms),
            "instrument_status": present_value(self.instrument_status),
            "is_trading": present_value(self.is_trading),
            "stock_status": present_value(self.stock_status),
            "security_state": self.security_state.value,
            "boundary_mode": self.boundary_mode.value,
            "boundary_usable_for_submission": self.boundary_usable_for_submission,
            "market_evidence_usable_for_submission": (self.market_evidence_usable_for_submission),
            "field_evidence": {name: evidence.to_payload() for name, evidence in fields.items()},
            "field_sources": {
                name: f"{evidence.source_api}.{evidence.source_field}"
                for name, evidence in fields.items()
            },
        }


class BrokerAdapter(Protocol):
    """Minimal broker boundary used by the executor."""

    def connect(self) -> None: ...
    def health(self) -> dict[str, Any]: ...
    def account_snapshot(self) -> dict[str, Any]: ...
    def market_snapshot(self, asset_code: str) -> dict[str, Any]: ...
    def submit_order(self, order: dict[str, Any]) -> BrokerSubmitResult: ...
    def cancel_order(self, broker_order_id: str) -> bool: ...
    def query_order(self, client_order_id: str, broker_order_id: str = "") -> dict[str, Any] | None:
        """Look up one order by its client identity and optional broker identity."""
        ...

    def find_order_candidates(self, order: dict[str, Any]) -> list[dict[str, Any]]: ...
    def poll_events(self) -> list[dict[str, Any]]: ...


class _XtTraderProtocol(Protocol):
    """Local shape of the QMT trader methods used by this adapter."""

    def register_callback(self, callback: object) -> None:
        """Register the adapter callback with the vendor trader."""
        ...

    def start(self) -> None:
        """Start the vendor trader runtime."""
        ...

    def connect(self) -> int:
        """Return the vendor connection status code."""
        ...

    def subscribe(self, account: object) -> int:
        """Subscribe the exact vendor account and return its status code."""
        ...

    def query_stock_asset(self, account: object) -> Any:
        """Read the untyped vendor asset response for this account."""
        ...

    def query_stock_positions(self, account: object) -> Any:
        """Read untyped vendor positions for this account."""
        ...

    def query_stock_orders(self, account: object) -> Any:
        """Read untyped vendor orders for this account."""
        ...

    def query_stock_trades(self, account: object) -> Any:
        """Read untyped vendor fills for this account."""
        ...

    def order_stock(
        self,
        account: object,
        stock_code: str,
        order_type: int,
        order_volume: int,
        price_type: int,
        price: float,
        strategy_name: str,
        order_remark: str,
    ) -> object:
        """Submit validated volume and price through the vendor stock-order API."""
        ...

    def cancel_order_stock(self, account: object, order_id: int) -> int:
        """Cancel the exact vendor account order and return its status code."""
        ...


class _XtTraderFactory(Protocol):
    """Constructor shape exported by ``xtquant.xttrader``."""

    def __call__(self, userdata_path: str, session_id: int) -> _XtTraderProtocol: ...


class _XtStockAccountFactory(Protocol):
    """Constructor shape exported by ``xtquant.xttype``."""

    def __call__(self, account_id: str, account_type: str) -> object: ...


class _XtConstantsProtocol(Protocol):
    """Constants consumed directly by the stock-order boundary."""

    STOCK_BUY: int
    STOCK_SELL: int
    FIX_PRICE: int


class _XtConstantsModuleProtocol(Protocol):
    """Module shape containing the optional QMT constants object."""

    xtconstant: _XtConstantsProtocol


class _XtDataProtocol(Protocol):
    """Quote function consumed from the optional QMT data module."""

    def get_full_tick(self, asset_codes: list[str]) -> Any:
        """Read untyped vendor ticks for the requested securities."""
        ...

    def get_instrument_detail(self, asset_code: str) -> Any:
        """Read untyped vendor instrument metadata for one security."""
        ...


class _XtDataModuleProtocol(Protocol):
    """Module shape containing the optional QMT data API."""

    xtdata: _XtDataProtocol


class _XtTraderModuleProtocol(Protocol):
    """Module shape containing QMT trader constructors and callback base."""

    XtQuantTrader: _XtTraderFactory
    XtQuantTraderCallback: type[object]


class _XtTypeModuleProtocol(Protocol):
    """Module shape containing the QMT stock-account constructor."""

    StockAccount: _XtStockAccountFactory


class _XtCallbackOwnerProtocol(Protocol):
    """Adapter state touched by dynamically constructed QMT callbacks."""

    _callback_dirty: threading.Event
    _callback_disconnected: bool


def _as_mapping(value: object) -> Mapping[object, object] | None:
    """Narrow an external QMT result to a mapping when its shape is valid."""

    if isinstance(value, Mapping):
        return value
    return None


def _unknown_market_field(
    source_api: str,
    source_field: str,
    reason_code: str,
) -> QmtMarketFieldEvidence:
    """Build a missing or unsupported QMT value without inventing a default."""

    return QmtMarketFieldEvidence(
        QmtMarketFieldState.UNKNOWN,
        None,
        source_api,
        source_field,
        reason_code,
    )


def _invalid_market_field(
    source_api: str,
    source_field: str,
    reason_code: str,
) -> QmtMarketFieldEvidence:
    """Build an invalid QMT value without carrying untrusted numeric content."""

    return QmtMarketFieldEvidence(
        QmtMarketFieldState.INVALID,
        None,
        source_api,
        source_field,
        reason_code,
    )


def _plain_decimal_text(value: Decimal) -> str | None:
    """Return bounded, exact plain decimal text or None when it is too long."""

    if value.is_zero():
        return "0"
    sign, digits, exponent = value.as_tuple()
    if not isinstance(exponent, int):
        return None
    digit_count = len(digits)
    sign_count = 1 if sign else 0
    if exponent >= 0:
        expanded_length = sign_count + digit_count + exponent
    elif digit_count + exponent > 0:
        expanded_length = sign_count + digit_count + 1
    else:
        expanded_length = sign_count + 2 - digit_count - exponent + digit_count
    if expanded_length > 257:
        return None
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _numeric_market_field(
    raw: object,
    *,
    source_api: str,
    source_field: str,
    allow_zero: bool = False,
) -> QmtMarketFieldEvidence:
    """Parse one exact vendor numeric value to a bounded decimal string."""

    if raw is None:
        return _unknown_market_field(source_api, source_field, "SOURCE_FIELD_MISSING")
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float, Decimal)):
        return _invalid_market_field(source_api, source_field, "UNSUPPORTED_NUMERIC_TYPE")
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return _invalid_market_field(source_api, source_field, "INVALID_NUMERIC_TEXT")
    if not value.is_finite():
        return _invalid_market_field(source_api, source_field, "NON_FINITE_NUMERIC")
    if value < 0:
        return _invalid_market_field(source_api, source_field, "NEGATIVE_NUMERIC")
    if value == 0 and not allow_zero:
        return _unknown_market_field(source_api, source_field, "NON_POSITIVE_PRICE")
    text = _plain_decimal_text(value)
    if text is None:
        return _invalid_market_field(source_api, source_field, "NUMERIC_TEXT_TOO_LONG")
    return QmtMarketFieldEvidence(
        QmtMarketFieldState.PRESENT,
        text,
        source_api,
        source_field,
    )


def _integer_market_field(
    raw: object,
    *,
    source_api: str,
    source_field: str,
    positive_only: bool = False,
) -> QmtMarketFieldEvidence:
    """Parse exact integer-like QMT codes and timestamps."""

    if raw is None:
        return _unknown_market_field(source_api, source_field, "SOURCE_FIELD_MISSING")
    if isinstance(raw, bool):
        return _invalid_market_field(source_api, source_field, "BOOLEAN_IS_NOT_INTEGER")
    if isinstance(raw, str):
        stripped = raw.strip()
        digits = stripped[1:] if stripped[:1] in {"+", "-"} else stripped
        if not digits or not digits.isascii() or not digits.isdigit():
            return _invalid_market_field(source_api, source_field, "INVALID_INTEGER_TEXT")
        value = int(stripped)
    else:
        try:
            value = operator.index(cast(SupportsIndex, raw))
        except (TypeError, ValueError, OverflowError):
            return _invalid_market_field(source_api, source_field, "INVALID_INTEGER_TYPE")
    if positive_only and value <= 0:
        return _unknown_market_field(source_api, source_field, "NON_POSITIVE_TIMESTAMP")
    return QmtMarketFieldEvidence(
        QmtMarketFieldState.PRESENT,
        value,
        source_api,
        source_field,
    )


def _boolean_market_field(
    raw: object,
    *,
    source_api: str,
    source_field: str,
) -> QmtMarketFieldEvidence:
    """Preserve a documented vendor boolean only when the runtime type matches."""

    if raw is None:
        return _unknown_market_field(source_api, source_field, "SOURCE_FIELD_MISSING")
    if type(raw) is not bool:
        return _invalid_market_field(source_api, source_field, "INVALID_BOOLEAN_TYPE")
    return QmtMarketFieldEvidence(
        QmtMarketFieldState.PRESENT,
        raw,
        source_api,
        source_field,
    )


def _first_price_level(raw: object, source_field: str) -> tuple[object, str, str | None]:
    """Select level zero from a documented quote array without importing NumPy."""

    if isinstance(raw, (list, tuple)):
        if not raw:
            return None, f"{source_field}[0]", "EMPTY_QUOTE_LEVELS"
        return raw[0], f"{source_field}[0]", None
    tolist_value: object = getattr(raw, "tolist", None)
    if callable(tolist_value):
        try:
            converted: object = cast(Callable[[], object], tolist_value)()
        except (TypeError, ValueError):
            return None, f"{source_field}[0]", "INVALID_QUOTE_LEVELS"
        if isinstance(converted, (list, tuple)):
            if not converted:
                return None, f"{source_field}[0]", "EMPTY_QUOTE_LEVELS"
            return converted[0], f"{source_field}[0]", None
        return converted, source_field, None
    return raw, source_field, None


class _XtQuantCallbackHandlerMixin:
    """Typed handlers mixed into the vendor callback base at runtime."""

    adapter: _XtCallbackOwnerProtocol

    def on_disconnected(self) -> None:
        """Record a disconnect and wake the polling loop."""

        self.adapter._callback_disconnected = True
        self.adapter._callback_dirty.set()

    def on_stock_order(self, _order: object) -> None:
        """Wake the polling loop after a QMT order callback."""

        self.adapter._callback_dirty.set()

    def on_stock_trade(self, _trade: object) -> None:
        """Wake the polling loop after a QMT trade callback."""

        self.adapter._callback_dirty.set()

    def on_order_error(self, _order_error: object) -> None:
        """Wake the polling loop after a QMT order-error callback."""

        self.adapter._callback_dirty.set()

    def on_cancel_error(self, _cancel_error: object) -> None:
        """Wake the polling loop after a QMT cancel-error callback."""

        self.adapter._callback_dirty.set()


def _import_xtquant_module(module_name: str) -> ModuleType:
    """Import an optional QMT module only when an adapter operation needs it."""

    return import_module(module_name)


def _load_xtquant_constants() -> _XtConstantsProtocol:
    """Load and narrow the QMT constants at their optional boundary."""

    xtquant_module = _import_xtquant_module("xtquant")
    typed_module = cast(_XtConstantsModuleProtocol, xtquant_module)
    return typed_module.xtconstant


class XtQuantAdapter:
    """Thin adapter over the broker-distributed xtquant package."""

    def __init__(
        self,
        *,
        userdata_path: Path,
        broker_account_id: str,
        account_type: str = "STOCK",
        qmt_client_version: str = "",
        xtquant_version: str = "",
    ) -> None:
        if str(account_type).upper() != "STOCK":
            raise ValueError("The first QMT Agent release supports STOCK accounts only")
        self.userdata_path = userdata_path
        self.broker_account_id = broker_account_id
        self.account_type = account_type
        self.qmt_client_version = str(qmt_client_version).strip()
        self.xtquant_version = str(xtquant_version).strip()
        self.trader: _XtTraderProtocol | None = None
        self.account: object | None = None
        self.callback: object | None = None
        self._callback_dirty = threading.Event()
        self._callback_disconnected = False

    def connect(self) -> None:
        """Connect to QMT, register its callback, and subscribe the STOCK account."""

        # Keep the optional vendor dependency isolated to this method/module.
        xttrader_module = cast(
            _XtTraderModuleProtocol,
            _import_xtquant_module("xtquant.xttrader"),
        )
        xttype_module = cast(
            _XtTypeModuleProtocol,
            _import_xtquant_module("xtquant.xttype"),
        )
        trader_factory = xttrader_module.XtQuantTrader
        callback_base = xttrader_module.XtQuantTraderCallback
        account_factory = xttype_module.StockAccount
        session_id = random.randint(100000, 999999999)
        self.trader = trader_factory(str(self.userdata_path), session_id)
        callback_type = type(
            "AgomXtQuantCallback",
            (_XtQuantCallbackHandlerMixin, callback_base),
            {"adapter": self},
        )
        self.callback = callback_type()
        self.trader.register_callback(self.callback)
        self.trader.start()
        if self.trader.connect() != 0:
            raise RuntimeError("QMT trader connection failed")
        self.account = account_factory(self.broker_account_id, "STOCK")
        if self.trader.subscribe(self.account) != 0:
            raise RuntimeError("QMT account subscription failed")
        self._callback_disconnected = False
        self._callback_dirty.set()

    def health(self) -> dict[str, Any]:
        """Probe broker connectivity and report the configured vendor versions."""

        connected = False
        if self.trader is not None and self.account is not None:
            try:
                connected = self.trader.query_stock_asset(self.account) is not None
            except Exception:
                connected = False
        if connected:
            self._callback_disconnected = False
        elif self._callback_disconnected:
            connected = False
        version = (
            f"QMT {self.qmt_client_version or 'unknown'}; "
            f"xtquant {self.xtquant_version or 'unknown'}"
        )
        return {"qmt_connected": connected, "qmt_version": version[:64]}

    def account_snapshot(self) -> dict[str, Any]:
        """Project broker assets, positions, orders and trades without changing facts."""

        if self.trader is None or self.account is None:
            raise RuntimeError("QMT is not connected")
        xtconstant = _load_xtquant_constants()

        asset = self.trader.query_stock_asset(self.account)
        positions = self.trader.query_stock_positions(self.account) or []
        orders = self.trader.query_stock_orders(self.account) or []
        trades = self.trader.query_stock_trades(self.account) or []
        by_order_id = {str(getattr(item, "order_id", "")): item for item in orders}
        status_map = _qmt_order_status_map(xtconstant)
        return {
            "cash_available": str(getattr(asset, "cash", 0)),
            "total_asset": str(getattr(asset, "total_asset", 0)),
            "positions": [
                {
                    "asset_code": item.stock_code,
                    "quantity": str(item.volume),
                    "available_quantity": str(item.can_use_volume),
                    "payload": {},
                }
                for item in positions
            ],
            "orders": [
                {
                    "broker_order_id": str(getattr(item, "order_id", "")),
                    "client_order_id": decode_order_remark(
                        str(getattr(item, "order_remark", "") or "")
                    )
                    or "",
                    "asset_code": str(getattr(item, "stock_code", "")),
                    "side": (
                        "BUY"
                        if getattr(item, "order_type", None)
                        == getattr(xtconstant, "STOCK_BUY", object())
                        else (
                            "SELL"
                            if getattr(item, "order_type", None)
                            == getattr(xtconstant, "STOCK_SELL", object())
                            else "UNKNOWN"
                        )
                    ),
                    "quantity": str(getattr(item, "order_volume", 0)),
                    "traded_quantity": str(getattr(item, "traded_volume", 0)),
                    "limit_price": str(getattr(item, "price", 0)),
                    "status": status_map.get(getattr(item, "order_status", None), "UNKNOWN"),
                }
                for item in orders
            ],
            "trades": [
                {
                    "broker_trade_id": str(getattr(item, "traded_id", "")),
                    "broker_order_id": str(getattr(item, "order_id", "")),
                    "client_order_id": decode_order_remark(
                        str(
                            getattr(
                                by_order_id.get(str(getattr(item, "order_id", ""))),
                                "order_remark",
                                "",
                            )
                            or ""
                        )
                    )
                    or "",
                    "asset_code": str(getattr(item, "stock_code", "")),
                    "quantity": str(getattr(item, "traded_volume", 0)),
                    "price": str(getattr(item, "traded_price", 0)),
                }
                for item in trades
            ],
        }

    def capture_market_snapshot(self, asset_code: str) -> QmtMarketSnapshot:
        """Capture typed local QMT quote and instrument-detail evidence."""

        if self.trader is None:
            raise RuntimeError("QMT is not connected")
        xtquant_module = cast(_XtDataModuleProtocol, _import_xtquant_module("xtquant"))
        xtdata = xtquant_module.xtdata

        raw_detail: object = xtdata.get_instrument_detail(asset_code)
        detail = _as_mapping(raw_detail)
        raw_ticks: object = xtdata.get_full_tick([asset_code])
        ticks = _as_mapping(raw_ticks)
        raw_tick: object = ticks.get(asset_code) if ticks is not None else None
        tick = _as_mapping(raw_tick)

        detail_api = "xtdata.get_instrument_detail"
        tick_api = "xtdata.get_full_tick"
        detail_value = detail if detail is not None else {}
        tick_value = tick if tick is not None else {}

        last_price = _numeric_market_field(
            tick_value.get("lastPrice"),
            source_api=tick_api,
            source_field="lastPrice",
        )
        ask_raw, ask_source_field, ask_reason = _first_price_level(
            tick_value.get("askPrice"), "askPrice"
        )
        ask_price = (
            _unknown_market_field(tick_api, ask_source_field, ask_reason)
            if ask_reason is not None
            else _numeric_market_field(
                ask_raw,
                source_api=tick_api,
                source_field=ask_source_field,
            )
        )
        bid_raw, bid_source_field, bid_reason = _first_price_level(
            tick_value.get("bidPrice"), "bidPrice"
        )
        bid_price = (
            _unknown_market_field(tick_api, bid_source_field, bid_reason)
            if bid_reason is not None
            else _numeric_market_field(
                bid_raw,
                source_api=tick_api,
                source_field=bid_source_field,
            )
        )
        upper_limit = _numeric_market_field(
            detail_value.get("UpStopPrice"),
            source_api=detail_api,
            source_field="UpStopPrice",
        )
        lower_limit = _numeric_market_field(
            detail_value.get("DownStopPrice"),
            source_api=detail_api,
            source_field="DownStopPrice",
        )
        price_tick = _numeric_market_field(
            detail_value.get("PriceTick"),
            source_api=detail_api,
            source_field="PriceTick",
        )
        open_int = _numeric_market_field(
            tick_value.get("openInt"),
            source_api=tick_api,
            source_field="openInt",
            allow_zero=True,
        )
        tick_time_ms = _integer_market_field(
            tick_value.get("time"),
            source_api=tick_api,
            source_field="time",
            positive_only=True,
        )
        instrument_status = _integer_market_field(
            detail_value.get("InstrumentStatus"),
            source_api=detail_api,
            source_field="InstrumentStatus",
        )
        is_trading = _boolean_market_field(
            detail_value.get("IsTrading"),
            source_api=detail_api,
            source_field="IsTrading",
        )
        stock_status = _integer_market_field(
            tick_value.get("stockStatus"),
            source_api=tick_api,
            source_field="stockStatus",
        )

        boundary_mode = QmtBoundaryMode.UNKNOWN
        if (
            upper_limit.state is QmtMarketFieldState.PRESENT
            and lower_limit.state is QmtMarketFieldState.PRESENT
            and isinstance(upper_limit.value, str)
            and isinstance(lower_limit.value, str)
            and Decimal(lower_limit.value) <= Decimal(upper_limit.value)
        ):
            boundary_mode = QmtBoundaryMode.REPORTED_LIMITS

        return QmtMarketSnapshot(
            asset_code=asset_code,
            captured_at_utc=datetime.now(UTC),
            metadata_observed_at=None,
            last_price=last_price,
            upper_limit=upper_limit,
            lower_limit=lower_limit,
            price_tick=price_tick,
            ask_price=ask_price,
            bid_price=bid_price,
            open_int=open_int,
            tick_time_ms=tick_time_ms,
            instrument_status=instrument_status,
            is_trading=is_trading,
            stock_status=stock_status,
            security_state=QmtSecurityState.UNKNOWN,
            boundary_mode=boundary_mode,
        )

    def market_snapshot(self, asset_code: str) -> dict[str, Any]:
        """Return a legacy-compatible local snapshot payload with explicit evidence."""

        return self.capture_market_snapshot(asset_code).to_payload()

    def submit_order(self, order: dict[str, Any]) -> BrokerSubmitResult:
        """Validate and submit one finite, positive integer-share limit order."""

        if self.trader is None or self.account is None:
            raise RuntimeError("QMT is not connected")

        raw_side: object = order.get("side")
        if not isinstance(raw_side, str) or raw_side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")

        raw_quantity: object = order.get("quantity")
        if type(raw_quantity) not in {str, int, Decimal}:
            raise ValueError("quantity must use exact decimal text or an integer")
        try:
            quantity = Decimal(cast(str | int | Decimal, raw_quantity))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("quantity must be a positive finite integer") from exc
        if not quantity.is_finite() or quantity <= 0 or quantity != quantity.to_integral_value():
            raise ValueError("quantity must be a positive finite integer")
        order_volume = int(quantity)

        raw_price: object = order.get("limit_price")
        if type(raw_price) not in {str, int, Decimal}:
            raise ValueError("limit_price must use exact decimal text or an integer")
        try:
            decimal_price = Decimal(cast(str | int | Decimal, raw_price))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("limit_price must be positive and finite") from exc
        if not decimal_price.is_finite() or decimal_price <= 0:
            raise ValueError("limit_price must be positive and finite")
        try:
            vendor_price = float(decimal_price)
        except (OverflowError, ValueError) as exc:
            raise ValueError(
                "limit_price must be representable as a positive finite vendor price"
            ) from exc
        if not math.isfinite(vendor_price) or vendor_price <= 0:
            raise ValueError("limit_price must be representable as a positive finite vendor price")
        if Decimal(str(vendor_price)) != decimal_price:
            raise ValueError("limit_price loses decimal precision at the vendor boundary")

        asset_code: object = order.get("asset_code")
        if not isinstance(asset_code, str) or not asset_code:
            raise ValueError("asset_code must be a non-empty string")
        client_order_id: object = order.get("client_order_id")
        if not isinstance(client_order_id, str) or not client_order_id:
            raise ValueError("client_order_id must be a valid UUID")
        try:
            order_remark = encode_order_remark(client_order_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("client_order_id must be a valid UUID") from exc

        xtconstant = _load_xtquant_constants()

        vendor_side = xtconstant.STOCK_BUY if raw_side == "BUY" else xtconstant.STOCK_SELL
        raw_broker_order_id = self.trader.order_stock(
            self.account,
            asset_code,
            vendor_side,
            order_volume,
            xtconstant.FIX_PRICE,
            vendor_price,
            "AgomTradePro",
            order_remark,
        )
        if isinstance(raw_broker_order_id, bool):
            raise RuntimeError("QMT returned an invalid order identifier")
        try:
            if isinstance(raw_broker_order_id, str):
                broker_order_id = int(raw_broker_order_id)
            else:
                broker_order_id = operator.index(cast(SupportsIndex, raw_broker_order_id))
        except (TypeError, ValueError, OverflowError) as exc:
            raise RuntimeError("QMT returned an invalid order identifier") from exc

        accepted = broker_order_id > 0
        return BrokerSubmitResult(
            accepted,
            str(broker_order_id),
            "" if accepted else "QMT rejected",
        )

    def cancel_order(self, broker_order_id: str) -> bool:
        """Request cancellation of a known broker order when connected."""

        if self.trader is None or self.account is None:
            return False
        return self.trader.cancel_order_stock(self.account, int(broker_order_id)) == 0

    def query_order(self, client_order_id: str, broker_order_id: str = "") -> dict[str, Any] | None:
        """Find one broker order by its exact identifier or encoded client remark."""

        if self.trader is None or self.account is None:
            return None
        xtconstant = _load_xtquant_constants()

        status_map = _qmt_order_status_map(xtconstant)
        orders = self.trader.query_stock_orders(self.account) or []
        for item in orders:
            if (
                str(getattr(item, "order_id", "")) == broker_order_id
                or decode_order_remark(str(getattr(item, "order_remark", ""))) == client_order_id
            ):
                return {
                    "broker_order_id": str(item.order_id),
                    "broker_status": str(item.order_status),
                    "broker_message": str(getattr(item, "status_msg", "") or ""),
                    "status": status_map.get(
                        getattr(item, "order_status", None),
                        "RECONCILIATION_REQUIRED",
                    ),
                    "traded_volume": str(item.traded_volume),
                    "traded_price": str(item.traded_price),
                }
        return None

    def find_order_candidates(self, order: dict[str, Any]) -> list[dict[str, Any]]:
        """Conservatively match fields when the QMT remark cannot be trusted."""

        if self.trader is None or self.account is None:
            return []
        quantity = Decimal(str(order.get("quantity") or "0"))
        price = Decimal(str(order.get("limit_price") or "0"))
        candidates = []
        for item in self.trader.query_stock_orders(self.account) or []:
            if (
                str(getattr(item, "stock_code", "")).upper()
                != str(order.get("asset_code") or "").upper()
            ):
                continue
            if Decimal(str(getattr(item, "order_volume", 0))) != quantity:
                continue
            if abs(Decimal(str(getattr(item, "price", 0))) - price) > Decimal("0.0001"):
                continue
            candidates.append(
                {
                    "broker_order_id": str(getattr(item, "order_id", "")),
                    "broker_status": str(getattr(item, "order_status", "")),
                    "match_mode": "conservative_fields",
                }
            )
        return candidates

    def poll_events(self) -> list[dict[str, Any]]:
        """Normalize current-day QMT orders/trades into idempotent server events."""

        if self.trader is None or self.account is None:
            return []
        self._callback_dirty.clear()
        xtconstant = _load_xtquant_constants()

        order_status_map = _qmt_order_status_map(xtconstant)
        now = datetime.now(UTC).isoformat()
        orders = self.trader.query_stock_orders(self.account) or []
        by_order_id = {str(item.order_id): item for item in orders}
        order_events: list[dict[str, Any]] = []
        for item in orders:
            client_order_id = (
                decode_order_remark(str(getattr(item, "order_remark", "") or "")) or ""
            )
            status = order_status_map.get(getattr(item, "order_status", None))
            if not client_order_id or not status:
                continue
            order_events.append(
                {
                    "event_id": (
                        f"qmt-order:{item.order_id}:{item.order_status}:"
                        f"{getattr(item, 'traded_volume', 0)}"
                    ),
                    "client_order_id": client_order_id,
                    "event_type": "QMT_ORDER_STATUS",
                    "status": status,
                    "occurred_at": _qmt_event_time(getattr(item, "order_time", None), now),
                    "broker_order_id": str(item.order_id),
                    "payload": {
                        "broker_status": str(item.order_status),
                        "status_msg": str(getattr(item, "status_msg", "") or ""),
                    },
                }
            )
        trade_events: list[dict[str, Any]] = []
        trades = self.trader.query_stock_trades(self.account) or []
        for trade in trades:
            order = by_order_id.get(str(getattr(trade, "order_id", "")))
            client_order_id = (
                decode_order_remark(str(getattr(order, "order_remark", "") or "")) or ""
            )
            trade_id = str(getattr(trade, "traded_id", "") or "")
            if not client_order_id or not trade_id:
                continue
            event_key = f"{self.broker_account_id}:{trade_id}"
            trade_events.append(
                {
                    "event_id": (
                        "qmt-trade:" + hashlib.sha256(event_key.encode("utf-8")).hexdigest()
                    ),
                    "client_order_id": client_order_id,
                    "event_type": "QMT_TRADE",
                    # A fill is an immutable fact, not authoritative order state.
                    # The QMT order query below supplies PARTIALLY_FILLED/FILLED.
                    "status": "",
                    "occurred_at": _qmt_event_time(getattr(trade, "traded_time", None), now),
                    "broker_order_id": str(getattr(trade, "order_id", "")),
                    "payload": {},
                    "fill": {
                        "broker_account_ref": self.broker_account_id,
                        "broker_trade_id": trade_id,
                        "quantity": str(getattr(trade, "traded_volume", 0)),
                        "price": str(getattr(trade, "traded_price", 0)),
                        "occurred_at": _qmt_event_time(getattr(trade, "traded_time", None), now),
                    },
                }
            )
        # Persist fills first, then apply QMT's authoritative aggregate order state.
        return [*trade_events, *order_events]
