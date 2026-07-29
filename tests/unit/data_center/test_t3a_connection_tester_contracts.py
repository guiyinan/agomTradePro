"""T3A connectivity-probe success, degradation, and timeout contracts."""

from __future__ import annotations

import queue
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.infrastructure import connection_tester


def _config(
    source_type: str,
    *,
    api_key: str = "token",
    is_active: bool = True,
    extra_config: dict[str, object] | None = None,
) -> ProviderConfig:
    return ProviderConfig(
        id=1,
        name=f"{source_type}-fixture",
        source_type=source_type,
        is_active=is_active,
        priority=1,
        api_key=api_key,
        api_secret="",
        http_url="https://proxy.example.test",
        api_endpoint="",
        extra_config=extra_config or {},
        description="fixture",
    )


def test_tushare_probe_rejects_missing_token_and_fetches_shibor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = connection_tester._probe_tushare(_config("tushare", api_key=""), [])
    assert missing.status == "error"

    monkeypatch.setattr(
        connection_tester,
        "TushareAdapter",
        lambda **_kwargs: SimpleNamespace(fetch=lambda *_args: [1, 2]),
    )
    success = connection_tester._probe_tushare(_config("tushare"), [])
    assert success.success is True
    assert "2 rows" in success.summary


def test_akshare_probe_fetches_pmi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        connection_tester,
        "AKShareAdapter",
        lambda: SimpleNamespace(fetch=lambda *_args: [1]),
    )
    result = connection_tester._probe_akshare(_config("akshare"), [])
    assert result.success is True


def test_qmt_probe_passes_runtime_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded: list[tuple[str, dict[str, object]]] = []

    class _Gateway:
        def __init__(self, source_name: str, extra_config: dict[str, object]) -> None:
            loaded.append((source_name, extra_config))

        def _load_xtdata(self) -> object:
            return object()

    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.qmt_gateway.QMTGateway",
        _Gateway,
    )
    result = connection_tester._probe_qmt(
        _config(
            "qmt",
            extra_config={"client_path": "C:/qmt", "data_dir": "C:/qmt/data"},
        ),
        [],
    )
    assert result.success is True
    assert loaded[0][1]["data_dir"] == "C:/qmt/data"


def test_eastmoney_probe_distinguishes_empty_and_live_quote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Gateway:
        snapshots: list[object] = []

        def get_quote_snapshots(self, _codes: list[str]) -> list[object]:
            return self.snapshots

    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway."
        "AKShareEastMoneyGateway",
        _Gateway,
    )
    warning = connection_tester._probe_eastmoney(_config("eastmoney"), [])
    assert warning.status == "warning"

    _Gateway.snapshots = [SimpleNamespace(price=Decimal("10.5"))]
    success = connection_tester._probe_eastmoney(_config("eastmoney"), [])
    assert success.status == "success"
    assert "10.5" in success.summary


def test_credential_only_probe_requires_key() -> None:
    missing = connection_tester._probe_credential_only(_config("fred", api_key=""), [])
    present = connection_tester._probe_credential_only(_config("fred"), [])
    assert missing.status == "error"
    assert present.status == "warning"


def test_timeout_wrapper_returns_success_and_probe_error() -> None:
    config = _config("akshare")
    success = connection_tester._run_with_timeout(
        config,
        [],
        lambda _config, logs: connection_tester.ConnectionTestResult(
            success=True,
            status="success",
            summary="ok",
            logs=logs,
        ),
    )
    assert success.success is True

    failed = connection_tester._run_with_timeout(
        config,
        [],
        lambda _config, _logs: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    assert failed.status == "error"
    assert failed.summary == "Connection test failed (RuntimeError)"


def test_timeout_wrapper_handles_queue_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Queue:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def put(self, _value: object) -> None:
            pass

        def get(self, **_kwargs: object) -> object:
            raise queue.Empty

    monkeypatch.setattr(connection_tester.queue, "Queue", _Queue)
    result = connection_tester._run_with_timeout(
        _config("akshare"), [], lambda *_args: None, timeout=0
    )
    assert result.status == "error"
    assert "timed out" in result.summary


@pytest.mark.parametrize("source_type", ["tushare", "akshare", "qmt", "eastmoney"])
def test_public_dispatch_uses_timeout_wrapper(
    monkeypatch: pytest.MonkeyPatch,
    source_type: str,
) -> None:
    monkeypatch.setattr(
        connection_tester,
        "_run_with_timeout",
        lambda _config, logs, probe: connection_tester.ConnectionTestResult(
            success=True,
            status="success",
            summary=probe.__name__,
            logs=logs,
        ),
    )
    result = connection_tester.run_connection_test(_config(source_type, is_active=False))
    assert result.success is True
    assert result.summary.startswith("_probe_")


def test_public_dispatch_handles_credentials_unsupported_and_unexpected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert connection_tester.run_connection_test(_config("wind")).status == "warning"
    unsupported = connection_tester.run_connection_test(_config("unknown"))
    assert unsupported.status == "error"

    monkeypatch.setattr(
        connection_tester,
        "_probe_credential_only",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("broken probe")),
    )
    unexpected = connection_tester.run_connection_test(_config("fred"))
    assert unexpected.status == "error"
    assert unexpected.summary == "Connection test failed (RuntimeError)"
