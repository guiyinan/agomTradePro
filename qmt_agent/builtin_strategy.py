# ruff: noqa: UP006, UP035, UP045
"""QMT built-in Python 3.6 strategy using a private Windows named-pipe bridge."""

import json
import math
import queue
import threading
import time
from datetime import datetime, timedelta, timezone
from multiprocessing import connection as pipe_connection
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional

PipeClient = pipe_connection.__dict__["PipeClient"]
PipeListener = pipe_connection.__dict__["PipeListener"]
PIPE_ADDRESS = r"\\.\pipe\agom_qmt_builtin_bridge"
_SCHEMA = "agom-qmt-builtin-bridge.v1"
_STRATEGY_NAME = "AgomTradePro"
_MAX_REQUEST_BYTES = 65536
_MAX_RESPONSE_BYTES = 2_000_000
_runtime: Dict[str, Any] = {}
_requests: Any = queue.Queue()
_pending: Dict[str, Dict[str, Any]] = {}
_responses: Dict[str, Dict[str, Any]] = {}
_response_order: List[str] = []
_submission_markers: Dict[str, str] = {}
_listener: Any = None
_server_thread: Any = None
_stopping = threading.Event()

if TYPE_CHECKING:

    def get_trade_detail_data(account_id: str, account_type: str, data_type: str) -> Any:
        """Declare the native query function injected by QMT at strategy runtime."""

    def passorder(*args: Any) -> None:
        """Declare the native order function injected by QMT at strategy runtime."""

    def cancel(*args: Any) -> bool:
        """Declare the native cancel function injected by QMT at strategy runtime."""


def _parse_not_after(value: object) -> float:
    """Parse the Agent's aware ISO deadline under QMT's Python 3.6 runtime."""

    if isinstance(value, bool) or not isinstance(value, str):
        raise ValueError("REQUEST_DEADLINE_INVALID")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if len(text) < 25 or text[-6] not in ("+", "-") or text[-3] != ":":
        raise ValueError("REQUEST_DEADLINE_INVALID")
    offset_sign = 1 if text[-6] == "+" else -1
    offset = timedelta(hours=int(text[-5:-3]), minutes=int(text[-2:]))
    base = text[:-6]
    try:
        parsed = datetime.strptime(base, "%Y-%m-%dT%H:%M:%S.%f")
    except ValueError:
        parsed = datetime.strptime(base, "%Y-%m-%dT%H:%M:%S")
    aware = parsed.replace(tzinfo=timezone(offset_sign * offset))
    return aware.timestamp()


def _response(request_id: str, result: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Build a successful response envelope."""

    return {
        "schema": _SCHEMA,
        "request_id": request_id,
        "ok": True,
        "result": dict(result or {}),
    }


def _error(request_id: str, code: str) -> Dict[str, Any]:
    """Build a stable error envelope without returning account or broker details."""

    return {
        "schema": _SCHEMA,
        "request_id": request_id,
        "ok": False,
        "error_code": code,
    }


def _asset_code(item: object) -> str:
    """Join the native instrument and exchange fields without changing their identity."""

    instrument = str(getattr(item, "m_strInstrumentID", "") or "").strip().upper()
    exchange = str(getattr(item, "m_strExchangeID", "") or "").strip().upper()
    if not instrument:
        return ""
    return instrument if "." in instrument or not exchange else instrument + "." + exchange


def _source_timestamp(item: object, date_field: str, time_field: str) -> int:
    """Convert native China-local date/time fields to epoch seconds, or zero if absent."""

    day = str(getattr(item, date_field, "") or "").strip()
    clock = str(getattr(item, time_field, "") or "").strip()
    if not day or not clock:
        return 0
    try:
        parsed = datetime.strptime(day + " " + clock, "%Y%m%d %H:%M:%S")
    except ValueError:
        return 0
    return int(parsed.replace(tzinfo=timezone(timedelta(hours=8))).timestamp())


def _normalize_asset(item: object) -> Dict[str, Any]:
    """Project the native account object to the existing Agent asset shape."""

    return {
        "cash": getattr(item, "m_dAvailable", 0),
        "total_asset": getattr(item, "m_dBalance", 0),
    }


def _normalize_position(item: object) -> Dict[str, Any]:
    """Project the native position object to the existing Agent position shape."""

    return {
        "stock_code": _asset_code(item),
        "volume": getattr(item, "m_nVolume", 0),
        "can_use_volume": getattr(item, "m_nCanUseVolume", 0),
    }


def _normalize_order(item: object) -> Dict[str, Any]:
    """Project documented native order fields to the existing xtquant-like shape."""

    offset_flag = getattr(item, "m_nOffsetFlag", None)
    return {
        "order_id": str(getattr(item, "m_strOrderSysID", "") or ""),
        "order_remark": str(getattr(item, "m_strRemark", "") or ""),
        "stock_code": _asset_code(item),
        "order_type": 23 if offset_flag == 48 else 24 if offset_flag == 49 else -1,
        "order_volume": getattr(item, "m_nVolumeTotalOriginal", 0),
        "traded_volume": getattr(item, "m_nVolumeTraded", 0),
        "price": getattr(item, "m_dLimitPrice", 0),
        "traded_price": getattr(item, "m_dTradedPrice", 0),
        "order_status": getattr(item, "m_nOrderStatus", 255),
        "status_msg": str(
            getattr(item, "m_strErrorMsg", "") or getattr(item, "m_strCancelInfo", "") or ""
        ),
        "order_time": _source_timestamp(item, "m_strInsertDate", "m_strInsertTime"),
    }


def _normalize_trade(item: object) -> Dict[str, Any]:
    """Project documented native deal fields to the existing xtquant-like shape."""

    return {
        "traded_id": str(getattr(item, "m_strTradeID", "") or ""),
        "order_id": str(getattr(item, "m_strOrderSysID", "") or ""),
        "order_remark": str(getattr(item, "m_strRemark", "") or ""),
        "stock_code": _asset_code(item),
        "traded_volume": getattr(item, "m_nVolume", 0),
        "traded_price": getattr(item, "m_dPrice", 0),
        "traded_time": _source_timestamp(item, "m_strTradeDate", "m_strTradeTime"),
    }


def _query(data_type: str) -> List[Dict[str, Any]]:
    """Run one native query for the account bound by the QMT model-trading entry."""

    rows = get_trade_detail_data(_runtime["account_id"], _runtime["account_type"], data_type)
    if rows is None:
        raise RuntimeError("NATIVE_QUERY_UNAVAILABLE")
    normalizers = {
        "ACCOUNT": _normalize_asset,
        "POSITION": _normalize_position,
        "ORDER": _normalize_order,
        "DEAL": _normalize_trade,
    }
    normalizer = normalizers.get(data_type)
    if normalizer is None:
        raise ValueError("QUERY_TYPE_UNSUPPORTED")
    return [normalizer(item) for item in rows]


def _order_id_for_remark(order_remark: str) -> str:
    """Resolve an exact unique native remark; never guess when identities are ambiguous."""

    matches = [
        item for item in _query("ORDER") if str(item.get("order_remark") or "") == order_remark
    ]
    if len(matches) > 1:
        raise RuntimeError("NATIVE_ORDER_IDENTITY_AMBIGUOUS")
    return str(matches[0].get("order_id") or "") if matches else ""


def _submit(request_id: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Submit once through passorder and recover by remark instead of blindly retrying."""

    order_remark = str(payload.get("order_remark") or "")
    if request_id in _submission_markers:
        order_id = _order_id_for_remark(order_remark)
        if order_id:
            return {"accepted": True, "broker_order_id": order_id}
        raise RuntimeError("SUBMIT_OUTCOME_UNKNOWN")

    side = payload.get("side")
    quantity = payload.get("quantity")
    price = payload.get("price")
    asset_code = payload.get("asset_code")
    if side not in (23, 24) or isinstance(side, bool):
        raise ValueError("NATIVE_SIDE_INVALID")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise ValueError("NATIVE_QUANTITY_INVALID")
    if (
        isinstance(price, bool)
        or not isinstance(price, (int, float))
        or not math.isfinite(float(price))
        or float(price) <= 0
    ):
        raise ValueError("NATIVE_PRICE_INVALID")
    if not isinstance(asset_code, str) or not asset_code or not order_remark:
        raise ValueError("NATIVE_ORDER_IDENTITY_INVALID")
    if payload.get("strategy_name") != _STRATEGY_NAME:
        raise ValueError("NATIVE_STRATEGY_INVALID")

    _submission_markers[request_id] = order_remark
    passorder(
        side,
        1101,
        _runtime["account_id"],
        asset_code,
        11,
        float(price),
        quantity,
        _STRATEGY_NAME,
        2,
        order_remark,
        _runtime["context"],
    )
    return {"accepted": True, "broker_order_id": _order_id_for_remark(order_remark)}


def _cancel(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Send one native cancel signal for the exact configured account and order ID."""

    order_id = str(payload.get("broker_order_id") or "").strip()
    if not order_id:
        raise ValueError("NATIVE_CANCEL_ID_INVALID")
    accepted = cancel(
        order_id,
        _runtime["account_id"],
        _runtime["account_type"],
        _runtime["context"],
    )
    return {"accepted": accepted is True}


def _execute(request: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate and dispatch one bounded request against the bound native account."""

    operation = request.get("operation")
    payload = request.get("payload")
    request_id = str(request.get("request_id") or "")
    if not request_id or not isinstance(payload, dict):
        raise ValueError("REQUEST_PAYLOAD_INVALID")
    recovering_submission = operation == "submit" and request_id in _submission_markers
    if not recovering_submission and _parse_not_after(request.get("not_after")) < time.time():
        raise ValueError("REQUEST_EXPIRED")
    if operation != "ping" and payload.get("account_id") != _runtime["account_id"]:
        raise ValueError("REQUEST_ACCOUNT_MISMATCH")
    if operation == "ping":
        return {
            "ready": True,
            "api": "builtin_python",
            "account_id": _runtime["account_id"],
        }
    if operation == "query":
        data_type = payload.get("data_type")
        if not isinstance(data_type, str):
            raise ValueError("QUERY_TYPE_INVALID")
        return {"rows": _query(data_type.upper())}
    if operation == "submit":
        return _submit(request_id, payload)
    if operation == "cancel":
        return _cancel(payload)
    raise ValueError("REQUEST_OPERATION_UNSUPPORTED")


def _cache_response(request_id: str, response: Dict[str, Any]) -> None:
    """Keep a bounded in-process response cache for exact request-ID retries."""

    if request_id not in _responses:
        _response_order.append(request_id)
    _responses[request_id] = response
    while len(_response_order) > 1000:
        oldest = _response_order.pop(0)
        _responses.pop(oldest, None)


def _send(connection: Any, response: Mapping[str, Any]) -> None:
    """Send one bounded JSON response and close the pipe connection."""

    try:
        encoded = json.dumps(
            response, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
        if len(encoded) > _MAX_RESPONSE_BYTES:
            raise ValueError("RESPONSE_TOO_LARGE")
        connection.send_bytes(encoded)
    finally:
        connection.close()


def _serve() -> None:
    """Accept local named-pipe requests without calling QMT APIs on the server thread."""

    global _listener
    while not _stopping.is_set():
        try:
            connection = _listener.accept()
            data = connection.recv_bytes()
            if len(data) > _MAX_REQUEST_BYTES:
                _send(connection, _error("", "BRIDGE_MESSAGE_TOO_LARGE"))
                continue
            request = json.loads(data.decode("utf-8"))
            if not isinstance(request, dict):
                _send(connection, _error("", "REQUEST_INVALID"))
                continue
            request_id = str(request.get("request_id") or "")
            if not request_id:
                _send(connection, _error("", "REQUEST_IDENTITY_INVALID"))
                continue
            cached = _responses.get(request_id)
            if cached is not None:
                _send(connection, cached)
                continue
            if request_id in _pending:
                _send(connection, _error(request_id, "REQUEST_IN_PROGRESS"))
                continue
            _pending[request_id] = {"connection": connection}
            _requests.put(request)
        except (EOFError, OSError):
            if _stopping.is_set():
                return
        except Exception:
            if _stopping.is_set():
                return


def _process_requests(context: object) -> None:
    """Execute pending native calls serially on a QMT strategy callback thread."""

    del context
    if not _runtime:
        return
    while True:
        try:
            request = _requests.get_nowait()
        except queue.Empty:
            return
        request_id = str(request.get("request_id") or "")
        pending = _pending.get(request_id)
        if pending is None:
            continue
        try:
            if request.get("schema") != _SCHEMA or request.get("request_id") != request_id:
                raise ValueError("REQUEST_IDENTITY_INVALID")
            result = _execute(request)
            response = _response(request_id, result)
        except ValueError as exc:
            code = str(exc)
            if not code or not code.replace("_", "").isalnum() or not code.isupper():
                code = "REQUEST_INVALID"
            response = _error(request_id, code)
        except Exception as exc:
            code = str(exc)
            if code not in {
                "NATIVE_QUERY_UNAVAILABLE",
                "NATIVE_ORDER_IDENTITY_AMBIGUOUS",
                "SUBMIT_OUTCOME_UNKNOWN",
            }:
                code = "NATIVE_OPERATION_FAILED"
            response = _error(request_id, code)
        _cache_response(request_id, response)
        _pending.pop(request_id, None)
        try:
            _send(pending["connection"], response)
        except (EOFError, OSError):
            pass


def init(context: object) -> None:
    """Bind QMT's selected stock account and start the local named-pipe server."""

    global _runtime, _listener, _server_thread
    if _server_thread is not None and _server_thread.is_alive():
        raise RuntimeError("QMT built-in bridge is already running")
    account_id = str(
        globals().get("account", "")
        or getattr(context, "accountid", "")
        or getattr(context, "account_id", "")
        or ""
    ).strip()
    if not account_id:
        raise ValueError("Select the stock account in QMT model trading before starting")
    context.set_account(account_id)  # type: ignore[attr-defined]
    _runtime = {"account_id": account_id, "account_type": "STOCK", "context": context}
    _stopping.clear()
    _listener = PipeListener(PIPE_ADDRESS)
    _server_thread = threading.Thread(target=_serve, name="AgomQmtBuiltinBridge")
    _server_thread.daemon = True
    _server_thread.start()
    context.run_time("agom_poll", "1nSecond", "1970-01-01 00:00:00")  # type: ignore[attr-defined]


def after_init(context: object) -> None:
    """Process pending requests once after native strategy initialization."""

    _process_requests(context)


def agom_poll(context: object) -> None:
    """Process local Agent requests from the QMT native timer."""

    _process_requests(context)


def handlebar(context: object) -> None:
    """Also poll from handlebar so no trading request depends on a timer alone."""

    _process_requests(context)


def stop(context: object) -> None:
    """Stop only the local IPC transport; never submit or cancel during shutdown."""

    global _listener, _runtime
    del context
    _stopping.set()
    if _listener is not None:
        try:
            PipeClient(PIPE_ADDRESS).close()
        except OSError:
            pass
        try:
            _listener.close()
        except OSError:
            pass
    _listener = None
    _runtime = {}
