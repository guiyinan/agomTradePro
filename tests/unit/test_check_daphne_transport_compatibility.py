"""Pure unit checks for the native Daphne transport compatibility candidate."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_daphne_transport_compatibility import (
    PROTOCOLS,
    CompatibilityError,
    _assert_echo,
    _is_inside_prefix,
    _parse_expected_lock,
    _success_eligible,
    _validate_locked_versions,
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


def test_missing_protocol_cannot_produce_success() -> None:
    """Require every HTTP, HTTPS, WS, and WSS probe to be present."""
    checks = {name: True for name in PROTOCOLS if name != "wss"}
    assert not _success_eligible(checks, cleanup_ok=True, cancelled=False)


def test_cancellation_cannot_produce_success() -> None:
    """A recorded CI cancellation remains a failed result after cleanup."""
    checks = dict.fromkeys(PROTOCOLS, True)
    assert not _success_eligible(checks, cleanup_ok=True, cancelled=True)


def test_unknown_lock_line_is_rejected() -> None:
    """Reject unrecognized non-comment lock lines instead of silently skipping them."""
    with pytest.raises(CompatibilityError, match="LOCK_LINE_INVALID"):
        _parse_expected_lock(_lock_text() + "\nnot-a-valid-lock-entry")
