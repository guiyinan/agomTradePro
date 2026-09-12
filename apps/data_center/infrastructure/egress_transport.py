"""Bounded HTTP transport with Config Center egress and shared runtime guards."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Mapping
from datetime import date
from typing import Any, cast
from urllib.parse import quote
from uuid import UUID

import pandas as pd  # type: ignore[import-untyped]
import requests
from django.conf import settings
from django.core.cache import cache

from apps.data_center.application.egress_service import EgressTransportResult, preview_route
from apps.data_center.domain.egress_routing import (
    EgressRequestContext,
    EgressRoutingError,
    target_hostname,
)
from apps.data_center.infrastructure.egress_target import (
    PreparedPublicTarget,
    prepare_public_target,
)
from core.integration.config_center_egress import (
    EgressEndpoint,
    get_egress_endpoint,
)

logger = logging.getLogger(__name__)

_EASTMONEY_HISTORY_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
MODEL_MARKET_DATASET_KEY = "equity.price.bar"
_EASTMONEY_HEADERS = {
    "Accept": "application/json,text/plain,*/*",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 " "Chrome/125.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/",
}
_EASTMONEY_BASE_PARAMS = {
    "fields1": "f1,f2,f3,f4,f5,f6",
    "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116",
    "ut": "7eea3edcaed734bea9cbfc24409ed989",
}


class _RequestBackendState(threading.local):
    """Keep failure classifications local to the synchronous request thread."""

    def __init__(self) -> None:
        self.backend_unavailable = False
        self.cache_unavailable = False


class _SharedEgressState:
    """Use Redis atomics in production and a bounded local fallback in tests.

    Production workers must share the limiter state.  A local counter is only
    suitable for development and tests because each worker would otherwise
    get its own independent concurrency budget.
    """

    _acquire_script = """
    local current = tonumber(redis.call('GET', KEYS[1]) or '0')
    local limit = tonumber(ARGV[1])
    if current >= limit then return 0 end
    redis.call('INCR', KEYS[1])
    redis.call('EXPIRE', KEYS[1], ARGV[2])
    return 1
    """
    _release_script = """
    local current = tonumber(redis.call('GET', KEYS[1]) or '0')
    if current <= 1 then redis.call('DEL', KEYS[1]); return 0 end
    return redis.call('DECR', KEYS[1])
    """

    def __init__(self) -> None:
        self._redis: Any | None = None
        self._redis_checked = False
        self._local_counts: dict[str, int] = {}
        self._lock = threading.Lock()
        self._request_state = _RequestBackendState()

    def acquire(self, key: str, limit: int, *, ttl_seconds: int = 90) -> bool:
        """Acquire one shared endpoint slot."""

        self._request_state.backend_unavailable = False
        redis_client = self._redis_client()
        if redis_client is not None:
            try:
                return bool(redis_client.eval(self._acquire_script, 1, key, limit, ttl_seconds))
            except Exception as exc:
                logger.warning("egress Redis limiter unavailable: %s", type(exc).__name__)
                if self._requires_shared_state():
                    self._request_state.backend_unavailable = True
                    return False
        elif self._requires_shared_state():
            logger.error("egress Redis limiter is required but unavailable")
            self._request_state.backend_unavailable = True
            return False
        with self._lock:
            current = self._local_counts.get(key, 0)
            if current >= limit:
                return False
            self._local_counts[key] = current + 1
            return True

    def backend_unavailable(self) -> bool:
        """Return whether the latest acquire failed closed for missing Redis."""

        return self._request_state.backend_unavailable

    def release(self, key: str) -> None:
        """Release one shared endpoint slot."""

        redis_client = self._redis_client()
        if redis_client is not None:
            try:
                redis_client.eval(self._release_script, 1, key)
                return
            except Exception as exc:
                logger.warning("egress Redis limiter release unavailable: %s", type(exc).__name__)
                if self._requires_shared_state():
                    return
        elif self._requires_shared_state():
            return
        with self._lock:
            current = self._local_counts.get(key, 0)
            if current <= 1:
                self._local_counts.pop(key, None)
            else:
                self._local_counts[key] = current - 1

    def circuit_open(self, key: str) -> bool:
        """Return whether a shared circuit is currently open."""

        self._request_state.cache_unavailable = False
        self._request_state.backend_unavailable = False
        try:
            return bool(cache.get(f"{key}:open"))
        except Exception as exc:
            logger.warning("egress circuit read unavailable: %s", type(exc).__name__)
            if self._requires_shared_state():
                self._request_state.cache_unavailable = True
            return False

    def shared_state_unavailable(self) -> bool:
        """Return whether a production request must fail closed for shared state."""

        return self._requires_shared_state() and (
            self._request_state.backend_unavailable or self._request_state.cache_unavailable
        )

    def failure(self, key: str, *, threshold: int = 3, ttl_seconds: int = 300) -> None:
        """Record one failure and open the shared circuit at the threshold."""

        failure_key = f"{key}:failures"
        try:
            if not cache.add(failure_key, 1, timeout=ttl_seconds):
                cache.incr(failure_key)
            failures = int(cache.get(failure_key, 0) or 0)
            if failures >= threshold:
                cache.set(f"{key}:open", 1, timeout=ttl_seconds)
        except Exception as exc:
            logger.warning("egress circuit failure state unavailable: %s", type(exc).__name__)
            if self._requires_shared_state():
                self._request_state.cache_unavailable = True

    def success(self, key: str) -> None:
        """Clear shared failure state after a successful request."""

        try:
            cache.delete(f"{key}:failures")
            cache.delete(f"{key}:open")
        except Exception as exc:
            logger.warning("egress circuit success state unavailable: %s", type(exc).__name__)
            if self._requires_shared_state():
                self._request_state.cache_unavailable = True

    def _redis_client(self) -> Any | None:
        """Build one optional Redis client from the configured cache URL."""

        if self._redis_checked:
            return self._redis
        self._redis_checked = True
        redis_url = str(getattr(settings, "REDIS_URL", "") or "").strip()
        if not redis_url.startswith(("redis://", "rediss://")):
            return None
        try:
            import redis

            self._redis = redis.Redis.from_url(
                redis_url, socket_timeout=1, socket_connect_timeout=1
            )
        except (ImportError, TypeError, ValueError):
            self._redis = None
        return self._redis

    @staticmethod
    def _requires_shared_state() -> bool:
        """Require Redis in production while keeping local development usable."""

        return not bool(getattr(settings, "DEBUG", True))


_shared_state = _SharedEgressState()


class EgressHttpTransport:
    """Perform safe HTTP GETs through direct or configured endpoint routes."""

    def __init__(
        self,
        *,
        connect_timeout: float = 8.0,
        read_timeout: float = 20.0,
        max_attempts: int = 2,
        max_response_bytes: int = 4 * 1024 * 1024,
    ) -> None:
        if connect_timeout <= 0 or read_timeout <= 0:
            raise ValueError("egress timeouts must be positive")
        if isinstance(max_attempts, bool) or not 1 <= max_attempts <= 2:
            raise ValueError("egress max_attempts must be between 1 and 2")
        if (
            isinstance(max_response_bytes, bool)
            or not 1024 <= max_response_bytes <= 64 * 1024 * 1024
        ):
            raise ValueError("egress max_response_bytes is out of range")
        self._timeout = (connect_timeout, read_timeout)
        self._max_attempts = max_attempts
        self._max_response_bytes = max_response_bytes

    def request(
        self,
        context: EgressRequestContext,
        *,
        egress_id: int | None,
        request_id: UUID,
        attempt: int,
    ) -> EgressTransportResult:
        """Issue one safe diagnostic request without following redirects."""

        del request_id
        return self._request_once(
            context,
            egress_id=egress_id,
            attempt=attempt,
            expect_json=False,
            max_response_bytes=self._max_response_bytes,
        )[0]

    def probe_endpoint(
        self,
        context: EgressRequestContext,
        *,
        egress_id: int | None,
        request_id: UUID,
        attempt: int,
    ) -> EgressTransportResult:
        """Probe one configured endpoint even while its production switch is off."""

        del request_id
        return self._request_once(
            context,
            egress_id=egress_id,
            attempt=attempt,
            allow_disabled_endpoint=True,
            expect_json=False,
            max_response_bytes=self._max_response_bytes,
        )[0]

    def request_payload(
        self,
        context: EgressRequestContext,
        *,
        egress_id: int | None,
        request_id: UUID,
        attempt: int,
        method: str,
        params: Mapping[str, object] | None,
        json_body: Mapping[str, object] | None,
        headers: Mapping[str, str] | None,
        expect_json: bool,
    ) -> tuple[EgressTransportResult, object | None]:
        """Issue one provider request for the application retry budget."""

        del request_id
        return self._request_once(
            context,
            egress_id=egress_id,
            attempt=attempt,
            method=method,
            params=params,
            json_body=json_body,
            headers=headers,
            expect_json=expect_json,
            max_response_bytes=self._max_response_bytes,
        )

    def should_route_history(self, *, provider_id: int, deployment_region: str) -> bool:
        """Return whether an explicit rule owns EastMoney history transport."""

        context = EgressRequestContext(
            provider_id=provider_id,
            dataset_key=MODEL_MARKET_DATASET_KEY,
            target_url=_EASTMONEY_HISTORY_URL,
            deployment_region=deployment_region,
        )
        return preview_route(context).rule_id is not None

    def fetch_eastmoney_history(
        self,
        *,
        provider_id: int,
        deployment_region: str,
        symbol: str,
        start_date: date,
        end_date: date,
        adjust: str,
    ) -> pd.DataFrame:
        """Fetch and decode one EastMoney daily-history response through the route."""

        context = EgressRequestContext(
            provider_id=provider_id,
            dataset_key=MODEL_MARKET_DATASET_KEY,
            target_url=_EASTMONEY_HISTORY_URL,
            deployment_region=deployment_region,
        )
        market_code = 1 if symbol.startswith("6") else 0
        params = {
            **_EASTMONEY_BASE_PARAMS,
            "klt": "101",
            "fqt": {"": "0", "qfq": "1", "hfq": "2"}.get(adjust, "0"),
            "secid": f"{market_code}.{symbol}",
            "beg": start_date.strftime("%Y%m%d"),
            "end": end_date.strftime("%Y%m%d"),
        }
        from apps.data_center.application.egress_service import execute_provider_request

        payload = execute_provider_request(
            context,
            method="GET",
            params=params,
            headers=_EASTMONEY_HEADERS,
            max_attempts=self._max_attempts,
        )
        try:
            return _decode_eastmoney_payload(payload, symbol)
        except (KeyError, TypeError, ValueError) as exc:
            return _raise_transport_result(
                EgressTransportResult(
                    outcome="failed",
                    error_code="EGRESS_INVALID_PAYLOAD",
                    message="上游返回的数据格式无效。",
                    retryable=False,
                ),
                cause=exc,
            )

    def _request_once(
        self,
        context: EgressRequestContext,
        *,
        egress_id: int | None,
        attempt: int,
        method: str = "GET",
        params: Mapping[str, object] | None = None,
        json_body: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
        expect_json: bool = True,
        max_response_bytes: int = 4 * 1024 * 1024,
        allow_disabled_endpoint: bool = False,
    ) -> tuple[EgressTransportResult, object | None]:
        """Perform one request after target, circuit, and concurrency checks."""

        normalized_method = str(method or "").strip().upper()
        if normalized_method not in {"GET", "POST"}:
            return (
                EgressTransportResult(
                    outcome="blocked",
                    error_code="EGRESS_METHOD_NOT_ALLOWED",
                    message="出网请求方法未被允许。",
                    retryable=False,
                ),
                None,
            )
        try:
            target = _validate_public_target(context.target_url)
        except EgressRoutingError as exc:
            return (
                EgressTransportResult(
                    outcome="blocked",
                    error_code=exc.code,
                    message="目标地址未通过安全校验。",
                    retryable=False,
                ),
                None,
            )
        endpoint: EgressEndpoint | None = None
        if egress_id is not None:
            endpoint = get_egress_endpoint(egress_id)
            if endpoint is None or (not endpoint.enabled and not allow_disabled_endpoint):
                return (
                    EgressTransportResult(
                        outcome="blocked",
                        error_code="EGRESS_ENDPOINT_UNAVAILABLE",
                        message="出口不存在或已停用。",
                        retryable=False,
                    ),
                    None,
                )
        state_key = (
            "data_center:egress:circuit:"
            f"{egress_id or 0}:{context.provider_id}:{target_hostname(context.target_url)}"
        )
        if _shared_state.circuit_open(state_key):
            return (
                EgressTransportResult(
                    outcome="blocked",
                    error_code="EGRESS_CIRCUIT_OPEN",
                    message="出口暂时熔断，请稍后再试。",
                    retryable=True,
                ),
                None,
            )
        if _shared_state.shared_state_unavailable():
            return (
                EgressTransportResult(
                    outcome="blocked",
                    error_code="EGRESS_SHARED_STATE_UNAVAILABLE",
                    message="共享出网状态不可用，已阻止请求。",
                    retryable=True,
                ),
                None,
            )
        limit = endpoint.concurrency_limit if endpoint is not None else 8
        slot_key = f"data_center:egress:concurrency:{egress_id or 0}"
        if not _shared_state.acquire(slot_key, limit):
            error_code = (
                "EGRESS_SHARED_STATE_UNAVAILABLE"
                if _shared_state.backend_unavailable()
                else "EGRESS_CONCURRENCY_LIMIT"
            )
            message = (
                "共享出网限流状态不可用，已阻止请求。"
                if error_code == "EGRESS_SHARED_STATE_UNAVAILABLE"
                else "出口当前并发已达上限。"
            )
            return (
                EgressTransportResult(
                    outcome="blocked",
                    error_code=error_code,
                    message=message,
                    retryable=True,
                ),
                None,
            )
        started = time.monotonic()
        session = requests.Session()
        session.trust_env = False
        session.mount(f"{target.scheme}://", target.adapter)
        if endpoint is not None:
            proxy_url = _proxy_url(endpoint)
            session.proxies.update({"http": proxy_url, "https": proxy_url})
        response: requests.Response | None = None
        try:
            request_headers = dict(_EASTMONEY_HEADERS)
            request_headers.update(dict(headers or {}))
            request_headers["Host"] = target.host_header
            request_params = cast(Any, dict(params or {}))
            if normalized_method == "POST":
                response = session.post(
                    target.url,
                    params=request_params,
                    json=dict(json_body or {}),
                    headers=request_headers,
                    timeout=self._timeout,
                    allow_redirects=False,
                    stream=True,
                )
            else:
                response = session.get(
                    target.url,
                    params=request_params,
                    headers=request_headers,
                    timeout=self._timeout,
                    allow_redirects=False,
                    stream=True,
                )
            elapsed_ms = round((time.monotonic() - started) * 1000, 3)
            if bool(getattr(response, "is_redirect", False)) or bool(
                getattr(response, "is_permanent_redirect", False)
            ):
                return (
                    EgressTransportResult(
                        outcome="failed",
                        error_code="EGRESS_REDIRECT_BLOCKED",
                        message="目标重定向未被允许。",
                        status_code=response.status_code,
                        latency_ms=elapsed_ms,
                        retryable=False,
                    ),
                    None,
                )
            if response.status_code in {401, 403, 429}:
                return (
                    EgressTransportResult(
                        outcome="failed",
                        error_code=f"EGRESS_HTTP_{response.status_code}",
                        message="上游拒绝了请求。",
                        status_code=response.status_code,
                        latency_ms=elapsed_ms,
                        retryable=False,
                    ),
                    None,
                )
            if not 200 <= response.status_code < 300:
                return (
                    EgressTransportResult(
                        outcome="failed",
                        error_code=f"EGRESS_HTTP_{response.status_code}",
                        message="上游服务返回错误。",
                        status_code=response.status_code,
                        latency_ms=elapsed_ms,
                        retryable=False,
                    ),
                    None,
                )
            payload = (
                _read_bounded_json(response, max_bytes=max_response_bytes) if expect_json else None
            )
            _shared_state.success(state_key)
            return (
                EgressTransportResult(
                    outcome="success",
                    status_code=response.status_code,
                    latency_ms=elapsed_ms,
                    retryable=False,
                ),
                payload,
            )
        except requests.exceptions.SSLError as exc:
            return _request_error_result(
                "EGRESS_TLS_ERROR", "目标 TLS 校验失败。", started, retryable=False, cause=exc
            )
        except requests.exceptions.Timeout as exc:
            _shared_state.failure(state_key)
            return _request_error_result(
                "EGRESS_TIMEOUT", "出网请求超时。", started, retryable=True, cause=exc
            )
        except requests.exceptions.ConnectionError as exc:
            _shared_state.failure(state_key)
            return _request_error_result(
                "EGRESS_CONNECTION_ERROR", "出网连接失败。", started, retryable=True, cause=exc
            )
        except requests.exceptions.RequestException as exc:
            return _request_error_result(
                "EGRESS_REQUEST_ERROR", "出网请求失败。", started, retryable=False, cause=exc
            )
        except (ValueError, TypeError) as exc:
            return _request_error_result(
                "EGRESS_INVALID_PAYLOAD",
                "上游返回的数据格式无效。",
                started,
                retryable=False,
                cause=exc,
            )
        finally:
            if response is not None:
                response.close()
            session.close()
            _shared_state.release(slot_key)


def _read_bounded_json(response: requests.Response, *, max_bytes: int) -> object:
    """Decode a response body after enforcing a strict byte ceiling."""

    content_length = response.headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise ValueError("response_body_too_large")
        except ValueError as exc:
            if str(exc) == "response_body_too_large":
                raise
            # An invalid length header is not trusted; the streamed body is
            # still bounded below.

    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=16 * 1024):
        if not chunk:
            continue
        data = bytes(chunk)
        total += len(data)
        if total > max_bytes:
            raise ValueError("response_body_too_large")
        chunks.append(data)
    try:
        text = b"".join(chunks).decode(response.encoding or "utf-8")
        return json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("response_body_is_not_json") from exc


def _raise_transport_result(
    result: EgressTransportResult, *, cause: BaseException | None = None
) -> pd.DataFrame:
    """Raise a sanitized provider error for the model adapter."""

    from core.exceptions import DataFetchError

    error = DataFetchError(result.message, code=result.error_code)
    if cause is not None:
        raise error from cause
    raise error


def _request_error_result(
    error_code: str,
    message: str,
    started: float,
    *,
    retryable: bool,
    cause: BaseException,
) -> tuple[EgressTransportResult, object | None]:
    """Create a sanitized transport error without including URLs or credentials."""

    del cause
    return (
        EgressTransportResult(
            outcome="failed",
            error_code=error_code,
            message=message,
            latency_ms=round((time.monotonic() - started) * 1000, 3),
            retryable=retryable,
        ),
        None,
    )


def _decode_eastmoney_payload(payload: object | None, symbol: str) -> pd.DataFrame:
    """Decode only the documented kline fields into AKShare-compatible columns."""

    if not isinstance(payload, dict):
        raise ValueError("payload_not_object")
    data = payload.get("data")
    if data is None:
        return pd.DataFrame()
    if not isinstance(data, dict):
        raise TypeError("data_not_object")
    klines = data.get("klines")
    if not klines:
        return pd.DataFrame()
    if not isinstance(klines, list):
        raise TypeError("klines_not_list")
    rows: list[list[str]] = []
    for item in klines:
        if not isinstance(item, str) or not item:
            continue
        fields = item.split(",")
        # EastMoney may append an undocumented field when ``f116`` is
        # requested.  The AKShare-compatible schema consumes the stable first
        # eleven kline fields and deliberately ignores that optional suffix.
        if len(fields) < 11:
            raise ValueError("kline_row_has_too_few_fields")
        rows.append(fields[:11])
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["股票代码"] = symbol
    frame.columns = [
        "日期",
        "开盘",
        "收盘",
        "最高",
        "最低",
        "成交量",
        "成交额",
        "振幅",
        "涨跌幅",
        "涨跌额",
        "换手率",
        "股票代码",
    ]
    frame["日期"] = pd.to_datetime(frame["日期"], errors="coerce").dt.date
    for field in (
        "开盘",
        "收盘",
        "最高",
        "最低",
        "成交量",
        "成交额",
        "振幅",
        "涨跌幅",
        "涨跌额",
        "换手率",
    ):
        frame[field] = pd.to_numeric(frame[field], errors="coerce")
    return frame[
        [
            "日期",
            "股票代码",
            "开盘",
            "收盘",
            "最高",
            "最低",
            "成交量",
            "成交额",
            "振幅",
            "涨跌幅",
            "涨跌额",
            "换手率",
        ]
    ]


def _proxy_url(endpoint: EgressEndpoint) -> str:
    """Build a proxy URL while keeping credentials out of logs and responses."""

    host = endpoint.host
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    auth = ""
    if endpoint.username or endpoint.password:
        auth = f"{quote(endpoint.username, safe='')}:{quote(endpoint.password, safe='')}@"
    return f"{endpoint.protocol}://{auth}{host}:{endpoint.port}"


def _validate_public_target(url: str) -> PreparedPublicTarget:
    """Resolve and pin the public origin while preserving its HTTP/TLS identity."""
    return prepare_public_target(url)


__all__ = ["EgressHttpTransport", "MODEL_MARKET_DATASET_KEY"]
