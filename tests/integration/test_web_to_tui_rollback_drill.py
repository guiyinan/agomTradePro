"""Integration coverage for the candidate-bound Web-to-TUI rollback drill."""

from __future__ import annotations

import json
import re

import pytest

from scripts.drill_web_to_tui_rollback import (
    CLASSIC_TEMPLATE_PATHS,
    GRAPH_PATH,
    MIGRATION_ANCHOR_PATH,
    RollbackDrillError,
    _candidate_binding,
    _derive_baseline_revision,
    _digest,
    _required_snapshot_bytes,
    _resolve_commit,
    _scope_snapshots,
    run_drill,
)

REGISTRY_KEY = "test-web-to-tui-rollback-drill"


def test_drill_rolls_back_and_restores_one_immutable_candidate() -> None:
    """The real patch round-trip is derived from one exact candidate commit."""

    candidate_commit = _resolve_commit("HEAD")
    candidate_version = f"test-{candidate_commit[:12]}"

    evidence = run_drill(
        candidate_version=candidate_version,
        candidate_revision=candidate_commit,
    )

    binding = evidence["candidate_binding"]
    assert evidence["ok"] is True
    assert evidence["version"] == "web-to-tui-rollback-drill.v2"
    assert binding["candidate_version"] == candidate_version
    assert binding["candidate_commit"] == candidate_commit
    assert evidence["candidate_graph_hash"] == _digest(
        _required_snapshot_bytes(candidate_commit, GRAPH_PATH)
    )

    baseline_commit, migration_commit = _derive_baseline_revision(candidate_commit)
    assert evidence["baseline_commit"] == baseline_commit
    assert evidence["migration_commit"] == migration_commit
    assert _required_snapshot_bytes(candidate_commit, MIGRATION_ANCHOR_PATH)

    manifest = {row["path"]: row for row in evidence["artifact_manifest"]}
    assert manifest[MIGRATION_ANCHOR_PATH]["transition"] == "added"
    assert manifest[MIGRATION_ANCHOR_PATH]["baseline_sha256"] is None
    for template_path in CLASSIC_TEMPLATE_PATHS:
        assert manifest[template_path]["transition"] == "modified"
        assert evidence["matrix_rollback_commits"][template_path]

    assert evidence["transition_counts"]["added"] >= 1
    assert evidence["transition_counts"]["modified"] >= 1
    assert evidence["baseline_contract"]["actions"] > 0
    assert evidence["candidate_contract"]["actions"] > 0
    assert evidence["baseline_runtime"]["verified_files"] > 0
    assert evidence["candidate_runtime"]["verified_files"] > 0
    assert re.fullmatch(r"[0-9a-f]{64}", evidence["patch_sha256"])
    assert evidence["working_tree_read_as_candidate"] is False
    assert evidence["working_tree_unchanged"] is True


def test_candidate_binding_rejects_an_invalid_release_version() -> None:
    """An unparseable release identity cannot be written into drill evidence."""

    with pytest.raises(RollbackDrillError, match="invalid candidate version"):
        _candidate_binding(
            candidate_version="not a version with spaces",
            candidate_commit=_resolve_commit("HEAD"),
        )


def test_scope_fails_closed_when_baseline_equals_candidate() -> None:
    """A drifted baseline cannot silently produce a vacuous successful drill."""

    candidate_commit = _resolve_commit("HEAD")
    with pytest.raises(RollbackDrillError, match="core paths are unchanged"):
        _scope_snapshots(
            baseline_commit=candidate_commit,
            candidate_commit=candidate_commit,
            runtime_paths=(),
        )


@pytest.mark.django_db  # type: ignore[misc]
def test_registry_can_publish_rollback_and_restore_bound_graphs() -> None:
    """Preserve the registry round-trip check using the derived snapshots."""

    pytest.importorskip("django")
    from apps.terminal.infrastructure.tui_metadata_repository import (
        PublishedTuiMetadataRepository,
    )

    candidate_commit = _resolve_commit("HEAD")
    baseline_commit, _migration_commit = _derive_baseline_revision(candidate_commit)
    candidate_payload = json.loads(_required_snapshot_bytes(candidate_commit, GRAPH_PATH))
    baseline_payload = json.loads(_required_snapshot_bytes(baseline_commit, GRAPH_PATH))
    repository = PublishedTuiMetadataRepository()

    candidate = repository.publish_payload(
        payload=candidate_payload,
        registry_key=REGISTRY_KEY,
        review_note="Publish bound candidate for isolated rollback drill",
        backend_version="m5-rollback-drill-candidate",
    )
    rollback = repository.publish_payload(
        payload=baseline_payload,
        registry_key=REGISTRY_KEY,
        review_note="Republish derived pre-migration baseline",
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
    assert rollback.rollback_of_id == candidate.pk
    assert rollback_matches is True
    assert active_rollback == rollback

    restored = repository.publish_payload(
        payload=candidate_payload,
        registry_key=REGISTRY_KEY,
        review_note="Restore bound candidate after isolated rollback drill",
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
