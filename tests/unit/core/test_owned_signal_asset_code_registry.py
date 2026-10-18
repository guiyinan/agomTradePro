"""Contracts for the app-neutral owner-scoped Signal lookup registry."""

from __future__ import annotations

import pytest

from core.integration import owned_signal_asset_code


class _RecordingLookup:
    """Capture calls made through the registry without importing an App."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    def __call__(self, *, signal_id: int, user_id: int) -> str | None:
        """Record a valid lookup invocation and return a sentinel asset code."""

        self.calls.append((signal_id, user_id))
        return "600000.SH"


def test_unregistered_lookup_fails_closed_for_valid_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    """The neutral registry returns no asset code when no App registered a provider."""

    monkeypatch.setattr(owned_signal_asset_code, "_owned_signal_asset_code_lookup", None)

    assert owned_signal_asset_code.get_owned_signal_asset_code(signal_id=7, user_id=11) is None


def test_invalid_ids_do_not_call_registered_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-positive identifiers are rejected before the registered lookup is called."""

    lookup = _RecordingLookup()
    monkeypatch.setattr(owned_signal_asset_code, "_owned_signal_asset_code_lookup", lookup)

    for signal_id, user_id in ((0, 11), (-1, 11), (7, 0), (7, -1)):
        assert (
            owned_signal_asset_code.get_owned_signal_asset_code(
                signal_id=signal_id,
                user_id=user_id,
            )
            is None
        )

    assert lookup.calls == []
