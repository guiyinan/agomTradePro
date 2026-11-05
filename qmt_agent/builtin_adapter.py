"""External Agent adapter for QMT built-in Python over a Windows named pipe."""

from __future__ import annotations

import importlib
import json
import os
import re
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from multiprocessing import connection as pipe_connection
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast

from .qmt_adapter import BrokerSubmitResult, XtQuantAdapter, _XtTraderProtocol

_winapi: ModuleType | None
try:
    _winapi = importlib.import_module("_winapi")
except ImportError:
    _winapi = None

PipeClient = pipe_connection.Client
_SCHEMA = "agom-qmt-builtin-bridge.v1"
_MAX_RESPONSE_BYTES = 2_000_000
_PIPE_NAME_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,80}")


class _BuiltinPipeTrader:
    """Synchronous named-pipe transport consumed through the existing trader shape."""

    def __init__(self, pipe_name: str, timeout_seconds: float) -> None:
        if _PIPE_NAME_PATTERN.fullmatch(pipe_name) is None:
            raise ValueError("QMT built-in pipe name contains unsupported characters")
        self.address = rf"\\.\pipe\{pipe_name}"
        self.timeout_seconds = timeout_seconds

    def request(self, operation: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Send one expiring request and wait for its exact native pipe response."""

        if os.name != "nt" or _winapi is None:
            raise RuntimeError("QMT built-in named-pipe bridge is only supported on Windows")
        request_id = str(uuid.uuid4())
        request = {
            "schema": _SCHEMA,
            "request_id": request_id,
            "operation": operation,
            "not_after": (datetime.now(UTC) + timedelta(seconds=self.timeout_seconds)).isoformat(),
            "payload": dict(payload),
        }
        encoded = json.dumps(
            request, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
        try:
            _winapi.WaitNamedPipe(self.address, int(self.timeout_seconds * 1000))
        except OSError as exc:
            raise RuntimeError("QMT built-in pipe is unavailable") from exc
        connection = PipeClient(self.address)
        try:
            connection.send_bytes(encoded)
            if not connection.poll(self.timeout_seconds):
                raise RuntimeError("QMT built-in bridge outcome unknown")
            response_bytes = connection.recv_bytes()
        finally:
            connection.close()
        return self._read_response(response_bytes, request_id)

    def _read_response(self, data: bytes, request_id: str) -> dict[str, Any]:
        """Validate a bounded response envelope and return its untyped native result."""

        if len(data) > _MAX_RESPONSE_BYTES:
            raise RuntimeError("QMT built-in bridge response is invalid")
        try:
            response = json.loads(data.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("QMT built-in bridge response is invalid") from exc
        if (
            not isinstance(response, dict)
            or response.get("schema") != _SCHEMA
            or response.get("request_id") != request_id
        ):
            raise RuntimeError("QMT built-in bridge response identity mismatch")
        if response.get("ok") is not True:
            code = str(response.get("error_code") or "NATIVE_OPERATION_FAILED")
            raise RuntimeError(f"QMT built-in bridge failed: {code[:64]}")
        result = response.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("QMT built-in bridge result is invalid")
        return cast(dict[str, Any], result)

    def _rows(self, account: object, data_type: str) -> list[SimpleNamespace]:
        """Convert native JSON rows to attribute objects used by the common normalizer."""

        result = self.request("query", {"account_id": str(account), "data_type": data_type})
        rows = result.get("rows")
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise RuntimeError("QMT built-in query rows are invalid")
        return [SimpleNamespace(**cast(dict[str, Any], row)) for row in rows]

    def query_stock_asset(self, account: object) -> object:
        """Return exactly one native account asset row."""

        rows = self._rows(account, "ACCOUNT")
        if len(rows) != 1:
            raise RuntimeError("QMT built-in account query did not return one asset")
        return rows[0]

    def query_stock_positions(self, account: object) -> list[SimpleNamespace]:
        """Return native positions in the common adapter shape."""

        return self._rows(account, "POSITION")

    def query_stock_orders(self, account: object) -> list[SimpleNamespace]:
        """Return native current-day orders in the common adapter shape."""

        return self._rows(account, "ORDER")

    def query_stock_trades(self, account: object) -> list[SimpleNamespace]:
        """Return native current-day deals in the common adapter shape."""

        return self._rows(account, "DEAL")

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
        """Submit through native passorder; an empty ID means later query reconciliation."""

        if price_type != 11:
            raise ValueError("QMT built-in bridge supports fixed-price stock orders only")
        result = self.request(
            "submit",
            {
                "account_id": str(account),
                "asset_code": stock_code,
                "side": order_type,
                "quantity": order_volume,
                "price_type": price_type,
                "price": price,
                "strategy_name": strategy_name,
                "order_remark": order_remark,
            },
        )
        if result.get("accepted") is not True:
            return -1
        return str(result.get("broker_order_id") or "") or None

    def cancel_order_stock(self, account: object, order_id: int | str) -> int:
        """Send native cancel and map its boolean signal to the common status code."""

        result = self.request(
            "cancel",
            {"account_id": str(account), "broker_order_id": str(order_id)},
        )
        return 0 if result.get("accepted") is True else -1


class BuiltinPythonAdapter(XtQuantAdapter):
    """Reuse Agent normalization while routing trading through QMT built-in Python."""

    def __init__(
        self,
        *,
        userdata_path: Path,
        broker_account_id: str,
        account_type: str = "STOCK",
        qmt_client_version: str = "",
        xtquant_version: str = "",
        pipe_name: str = "agom_qmt_builtin_bridge",
        bridge_timeout_seconds: float = 10,
    ) -> None:
        """Configure the local native pipe without starting an external trader."""

        super().__init__(
            userdata_path=userdata_path,
            broker_account_id=broker_account_id,
            account_type=account_type,
            qmt_client_version=qmt_client_version,
            xtquant_version=xtquant_version,
        )
        if not 1 <= bridge_timeout_seconds <= 30:
            raise ValueError("QMT built-in bridge timeout must be between 1 and 30 seconds")
        self.pipe_name = pipe_name
        self.bridge_timeout_seconds = bridge_timeout_seconds

    def connect(self) -> None:
        """Verify the native strategy and exact account binding without XtQuantTrader."""

        client = _BuiltinPipeTrader(self.pipe_name, self.bridge_timeout_seconds)
        result = client.request("ping", {})
        if result.get("ready") is not True or result.get("api") != "builtin_python":
            raise RuntimeError("QMT built-in bridge is not ready")
        if result.get("account_id") != self.broker_account_id:
            raise RuntimeError("QMT built-in bridge account mismatch")
        self.trader = cast(_XtTraderProtocol, client)
        self.account = self.broker_account_id
        self.callback = None
        self._callback_disconnected = False
        self._callback_dirty.set()

    def _missing_order_id_result(self) -> BrokerSubmitResult:
        """Accept native passorder completion while its broker ID awaits an order query."""

        return BrokerSubmitResult(
            True,
            "",
            "QMT built-in order sent; broker order ID pending query",
        )

    def _text_order_id_result(self, broker_order_id: str) -> BrokerSubmitResult:
        """Preserve the documented native string order ID without numeric coercion."""

        normalized = broker_order_id.strip()
        if not normalized or len(normalized) > 128:
            raise RuntimeError("QMT returned an invalid order identifier")
        return BrokerSubmitResult(True, normalized)

    def _vendor_cancel_order_id(self, broker_order_id: str) -> int | str:
        """Pass the exact native string order ID to cancel without losing its identity."""

        normalized = broker_order_id.strip()
        if not normalized or len(normalized) > 128:
            raise ValueError("broker_order_id must be a non-empty native order identifier")
        return normalized
