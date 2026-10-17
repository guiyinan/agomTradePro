"""Continuation validation changes must invalidate cached published metadata."""

from pathlib import Path

import pytest

from apps.terminal.infrastructure.tui_metadata_repository import PublishedTuiMetadataRepository


def test_runtime_cache_token_tracks_continuation_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changing only the extracted validator invalidates the runtime cache key."""
    token = PublishedTuiMetadataRepository._runtime_contract_token
    original = Path.read_bytes
    token.cache_clear()
    try:
        before = token()

        def changed(path: Path) -> bytes:
            content = original(path)
            if path.name == "tui_metadata_continuation_validation.py":
                return content + b"\n# changed continuation contract\n"
            return content

        monkeypatch.setattr(Path, "read_bytes", changed)
        token.cache_clear()
        assert token() != before
    finally:
        token.cache_clear()
