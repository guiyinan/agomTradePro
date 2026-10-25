"""Pure unit checks for the native Daphne transport compatibility candidate."""

from __future__ import annotations

import io
import logging
import ssl
import sys
from pathlib import Path
from types import ModuleType

import pytest

from scripts.check_daphne_transport_compatibility import (
    MAX_EXCEPTION_CAUSES,
    MAX_EXCEPTION_MESSAGE_CHARS,
    MAX_WSS_LOG_BYTES,
    PROTOCOLS,
    CompatibilityError,
    _assert_echo,
    _bounded_logs,
    _exception_chain,
    _is_inside_prefix,
    _parse_expected_lock,
    _safe_exception_message,
    _save_wss_log,
    _success_eligible,
    _validate_locked_versions,
    _websocket_probe,
)


def _lock_text() -> str:
    """Build a minimal exact-pin lock fixture for the required distributions."""
    return "\n".join(
        (
            "Twisted==26.10.0rc1 ",
            "djangorestframework==3.18.3 ",
            "Daphne==4.2.2 ",
            "channels==4.3.2 ",
            "zope-interface==8.7 ",
            "pyOpenSSL==26.2.0 ",
            "cryptography==46.0.7 ",
            "websockets==16.0",
        )
    )


def test_duplicate_exact_pin_is_rejected() -> None:
    """Reject duplicate normalized requirements even when their versions match."""
    text = _lock_text() + "\ntwisted==26.10.0rc1"
    with pytest.raises(CompatibilityError, match="LOCK_DUPLICATE_PIN"):
        _parse_expected_lock(text)


@pytest.mark.parametrize("name", ("twisted", "djangorestframework"))
def test_target_installed_version_must_match_lock(name: str) -> None:
    """Reject installed Twisted or DRF metadata that differs from its lock pin."""
    pins = _parse_expected_lock(_lock_text())
    actual = dict(pins)
    actual[name] = "0.0.0"
    with pytest.raises(CompatibilityError, match="INSTALLED_VERSION_DIFFERS_FROM_LOCK"):
        _validate_locked_versions(pins, actual)


def test_non_exact_target_pin_is_rejected() -> None:
    """Reject a range instead of an exact Twisted target pin."""
    text = _lock_text().replace("Twisted==26.10.0rc1", "Twisted>=26.10.0rc1")
    with pytest.raises(CompatibilityError, match="LOCK_LINE_INVALID"):
        _parse_expected_lock(text)


@pytest.mark.parametrize(
    "old_pin",
    ("Twisted==26.9.0", "djangorestframework==3.16.1"),
)
def test_stale_target_lock_version_is_rejected(old_pin: str) -> None:
    """Require the exact reviewed Twisted and DRF targets in the lock."""
    text = _lock_text().replace(
        "Twisted==26.10.0rc1" if old_pin.startswith("Twisted") else "djangorestframework==3.18.3",
        old_pin,
    )
    with pytest.raises(CompatibilityError, match="LOCK_TARGET_VERSION_MISMATCH"):
        _parse_expected_lock(text)


def test_missing_required_pin_is_rejected() -> None:
    """Reject a lock that does not pin each required transport distribution."""
    text = "\n".join(
        line for line in _lock_text().splitlines() if not line.lower().startswith("websockets==")
    )
    with pytest.raises(CompatibilityError, match="LOCK_REQUIRED_PIN_MISSING"):
        _parse_expected_lock(text)


def test_module_path_outside_venv_is_rejected(tmp_path: Path) -> None:
    """Reject module files resolved from an overlay outside sys.prefix."""
    prefix = tmp_path / "venv"
    outside = tmp_path / "overlay" / "twisted" / "__init__.py"
    prefix.mkdir()
    outside.parent.mkdir(parents=True)
    outside.write_text("", encoding="utf-8")
    assert not _is_inside_prefix(outside, prefix)


@pytest.mark.parametrize("actual", (b"wrong", "wrong"))
def test_protocol_response_mismatch_is_rejected(actual: bytes | str) -> None:
    """Reject a protocol response that does not exactly echo its challenge."""
    with pytest.raises(CompatibilityError, match="HTTP_ECHO_MISMATCH"):
        _assert_echo(actual, b"expected", "http")


def test_cleanup_failure_cannot_produce_success() -> None:
    """Require successful process cleanup in addition to all four transports."""
    checks = dict.fromkeys(PROTOCOLS, True)
    assert not _success_eligible(checks, cleanup_ok=False, cancelled=False)


def test_wss_timeout_cannot_produce_success() -> None:
    """Keep a WSS timeout failed when the other three transports pass."""
    checks = {"http": True, "https": True, "ws": True, "wss": False}
    assert not _success_eligible(checks, cleanup_ok=True, cancelled=False)


def test_missing_protocol_cannot_produce_success() -> None:
    """Require every HTTP, HTTPS, WS, and WSS probe key to be present."""
    checks = {name: True for name in PROTOCOLS if name != "wss"}
    assert not _success_eligible(checks, cleanup_ok=True, cancelled=False)


def test_missing_diagnostic_log_cannot_produce_success() -> None:
    """Require the private WSS diagnostic trace to be saved for success."""
    checks = dict.fromkeys(PROTOCOLS, True)
    assert not _success_eligible(checks, cleanup_ok=True, cancelled=False, diagnostic_log_ok=False)


@pytest.mark.parametrize("payload", (b"", b" \n"))
def test_empty_diagnostic_trace_is_not_saved_successfully(tmp_path: Path, payload: bytes) -> None:
    """A silently empty logger cannot satisfy the required diagnostic record."""
    metadata = _save_wss_log(io.BytesIO(payload), tmp_path, ())
    assert metadata["saved"] is False


def test_cancellation_cannot_produce_success() -> None:
    """A recorded CI cancellation remains a failed result after cleanup."""
    checks = dict.fromkeys(PROTOCOLS, True)
    assert not _success_eligible(checks, cleanup_ok=True, cancelled=True)


def test_unknown_lock_line_is_rejected() -> None:
    """Reject unrecognized non-comment lock lines instead of silently skipping them."""
    with pytest.raises(CompatibilityError, match="LOCK_LINE_INVALID"):
        _parse_expected_lock(_lock_text() + "\nnot-a-valid-lock-entry")


def test_wss_trace_redacts_markers_and_never_reads_beyond_limit() -> None:
    """Bound trace reads and remove full or cutoff-crossing secret markers."""
    marker = b"SENSITIVE-TOKEN"
    payload = b"prefix-" + marker + b"-" + (b"x" * MAX_WSS_LOG_BYTES)
    data, truncated = _bounded_logs(io.BytesIO(payload), (marker,), MAX_WSS_LOG_BYTES)
    assert truncated
    assert len(data) <= MAX_WSS_LOG_BYTES
    assert marker not in data

    cutoff_data, cutoff = _bounded_logs(io.BytesIO(b"prefix-SECRET-tail"), (b"SECRET",), 9)
    assert cutoff
    assert len(cutoff_data) <= 9
    assert b"SECRET" not in cutoff_data
    assert b"SE" not in cutoff_data


def test_exception_chain_redacts_and_caps_messages_and_causes() -> None:
    """Bound exception details and redact challenge or key material markers."""
    marker = b"challenge-marker"
    error: BaseException = TimeoutError(f"handshake timed out: {marker.decode()}")
    current = error
    for index in range(MAX_EXCEPTION_CAUSES + 2):
        cause = RuntimeError(f"cause {index}: {marker.decode()}")
        current.__cause__ = cause
        current = cause

    summaries = _exception_chain(error, (marker,))
    assert len(summaries) == MAX_EXCEPTION_CAUSES + 1
    assert all(marker.decode() not in item["message"] for item in summaries)

    message = _safe_exception_message("m" * (MAX_EXCEPTION_MESSAGE_CHARS + 100), ())
    assert len(message) == MAX_EXCEPTION_MESSAGE_CHARS
    assert message.endswith("…")


class _FakeWebSocket:
    """Minimal context manager for checking client phase logging without I/O."""

    def __init__(self) -> None:
        self.message = ""

    def __enter__(self) -> _FakeWebSocket:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def send(self, message: str) -> None:
        self.message = message

    def recv(self, timeout: float | None = None) -> str:
        assert timeout == 2
        return self.message


def test_wss_logger_marks_handshake_send_receive_and_close(monkeypatch: pytest.MonkeyPatch) -> None:
    """Record client-library handshake and explicit WSS operation boundaries."""
    client_module = ModuleType("websockets.sync.client")
    sync_module = ModuleType("websockets.sync")
    websockets_module = ModuleType("websockets")
    websockets_module.__path__ = []
    sync_module.__path__ = []
    websockets_module.sync = sync_module
    sync_module.client = client_module
    websocket = _FakeWebSocket()

    def fake_connect(uri: str, **options: object) -> _FakeWebSocket:
        assert uri.startswith("wss://127.0.0.1:")
        logger = options["logger"]
        assert isinstance(logger, logging.Logger)
        logger.debug("library_open_handshake_observed")
        return websocket

    client_module.connect = fake_connect
    monkeypatch.setitem(sys.modules, "websockets", websockets_module)
    monkeypatch.setitem(sys.modules, "websockets.sync", sync_module)
    monkeypatch.setitem(sys.modules, "websockets.sync.client", client_module)

    stream = io.StringIO()
    logger = logging.Logger("test-wss", level=logging.DEBUG)
    logger.addHandler(logging.StreamHandler(stream))
    result = _websocket_probe(
        443,
        True,
        ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
        [],
        logger=logger,
    )

    events = stream.getvalue()
    ordered_events = (
        "phase=connect_start",
        "library_open_handshake_observed",
        "phase=connect_complete",
        "phase=send_start",
        "phase=send_complete",
        "phase=recv_start",
        "phase=recv_complete",
        "phase=close_start",
        "phase=close_complete",
    )
    event_positions = [events.index(event) for event in ordered_events]
    assert event_positions == sorted(event_positions)
    assert "echo_sha256" in result
