"""Database-registry drill for the Web-to-TUI release rollback path."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from apps.terminal.infrastructure.tui_metadata_repository import (
    PublishedTuiMetadataRepository,
)
from scripts.drill_web_to_tui_rollback import BASELINE_REVISION, GRAPH_PATH

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_KEY = "test-web-to-tui-rollback-drill"


def _load_payload_from_git(revision: str, relative_path: str) -> dict[str, Any]:
    """Load one historical JSON payload without changing the working tree."""

    content = subprocess.check_output(
        ["git", "show", f"{revision}:{relative_path}"],
        cwd=ROOT,
    )
    payload = json.loads(content)
    assert isinstance(payload, dict)
    return payload


@pytest.mark.django_db
def test_registry_can_publish_rollback_and_restore_reviewed_graph() -> None:
    """A compatible baseline graph can replace and then restore the candidate."""

    repository = PublishedTuiMetadataRepository()
    candidate_payload = json.loads((ROOT / GRAPH_PATH).read_text(encoding="utf-8"))
    baseline_payload = _load_payload_from_git(BASELINE_REVISION, GRAPH_PATH)

    candidate = repository.publish_payload(
        payload=candidate_payload,
        registry_key=REGISTRY_KEY,
        review_note="Publish candidate for isolated rollback drill",
        backend_version="m5-rollback-drill-candidate",
    )
    rollback = repository.publish_payload(
        payload=baseline_payload,
        registry_key=REGISTRY_KEY,
        review_note="Republish compatible pre-migration baseline",
        backend_version="m5-rollback-drill-baseline",
        rollback_of=candidate,
    )

    candidate.refresh_from_db()
    rollback_matches, active_rollback, baseline_hash = repository.verify_active_payload(
        payload=baseline_payload,
        registry_key=REGISTRY_KEY,
    )
    assert candidate.status == "archived"
    assert candidate.source_hash != baseline_hash
    assert candidate.source_hash != rollback.source_hash
    assert rollback.rollback_of_id == candidate.pk
    assert candidate.source_hash == repository.payload_hash(dict(candidate.payload))
    assert rollback_matches is True
    assert active_rollback == rollback

    restored = repository.publish_payload(
        payload=candidate_payload,
        registry_key=REGISTRY_KEY,
        review_note="Restore candidate after isolated rollback drill",
        backend_version="m5-rollback-drill-restored",
        rollback_of=rollback,
    )

    rollback.refresh_from_db()
    restore_matches, active_restore, candidate_hash = repository.verify_active_payload(
        payload=candidate_payload,
        registry_key=REGISTRY_KEY,
    )
    assert rollback.status == "archived"
    assert restored.rollback_of_id == rollback.pk
    assert restored.source_hash == candidate_hash
    assert restore_matches is True
    assert active_restore == restored
