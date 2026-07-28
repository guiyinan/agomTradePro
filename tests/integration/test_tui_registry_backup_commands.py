"""Integration coverage for verified TUI registry backup and restore."""

from __future__ import annotations

import json
import tempfile
from collections.abc import Generator
from copy import deepcopy
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.terminal.infrastructure.models import TuiMetadataRegistryORM
from apps.terminal.infrastructure.tui_metadata_repository import (
    PublishedTuiMetadataRepository,
)

ROOT = Path(__file__).resolve().parents[2]


def _metadata_payload() -> dict[str, object]:
    """Return the smallest valid published TUI graph for registry tests."""

    return {
        "version": "tui-workbench.v2",
        "registry_key": "default",
        "default_screen": "command-center.overview",
        "interaction_model": "published-metadata-to-pc-tools",
        "groups": [{"key": "workflow", "label": "Workflow"}],
        "modules": [
            {
                "key": "command-center",
                "label": "Command Center",
                "group": "workflow",
                "summary": "Command tools.",
                "status": "online",
            }
        ],
        "screens": [
            {
                "key": "command-center.overview",
                "label": "Command Overview",
                "module_key": "command-center",
                "group": "workflow",
                "summary": "Overview.",
                "view_type": "status",
                "status": "online",
                "default_action_key": "sample.list",
            }
        ],
        "actions": [
            {
                "key": "sample.list",
                "label": "Sample List",
                "method": "GET",
                "endpoint": "/api/sample/list/",
                "intent": "sample",
                "screen_key": "command-center.overview",
                "module_key": "command-center",
                "view_type": "datagrid",
                "risk": "read",
                "fields": [],
                "description": "Sample.",
                "source": "approved:test",
                "raw_debug": True,
            }
        ],
    }


@pytest.fixture
def published_registry(db: object) -> TuiMetadataRegistryORM:
    """Publish the reviewed graph into the isolated test registry."""

    return PublishedTuiMetadataRepository().publish_payload(
        payload=_metadata_payload(),
        registry_key="default",
        review_note="registry backup command test",
        backend_version="test-backend",
    )


@pytest.fixture
def external_backup_dir() -> Generator[Path, None, None]:
    """Provide an auto-cleaned backup directory outside the Git worktree."""

    with tempfile.TemporaryDirectory(prefix="agom-tui-registry-backup-") as value:
        yield Path(value)


def _backup(tmp_path: Path) -> tuple[Path, Path, str]:
    """Run the backup command and return its two external artifacts."""

    output_path = tmp_path / "tui-registry-backup.json"
    stdout = StringIO()
    call_command(
        "backup_tui_registry",
        output=str(output_path),
        stdout=stdout,
    )
    return (
        output_path,
        output_path.with_suffix(".json.sha256"),
        stdout.getvalue(),
    )


@pytest.mark.django_db
def test_backup_command_writes_verified_external_bundle(
    published_registry: TuiMetadataRegistryORM,
    external_backup_dir: Path,
) -> None:
    """Backup contains the required generation, hashes and runtime identity."""

    output_path, sidecar_path, output = _backup(external_backup_dir)
    bundle = json.loads(output_path.read_text(encoding="utf-8"))

    assert sidecar_path.exists()
    assert bundle["format"] == "tui-registry-backup.v1"
    assert bundle["registry"]["generation"] == published_registry.pk
    assert bundle["registry"]["source_hash"] == published_registry.source_hash
    assert bundle["registry"]["schema_version"] == published_registry.schema_version
    assert bundle["runtime"]["build_id"]
    assert bundle["integrity"]["payload_sha256"] == published_registry.source_hash
    assert "bundle_sha256=" in output


@pytest.mark.django_db
def test_restore_command_verifies_bundle_without_mutation_by_default(
    published_registry: TuiMetadataRegistryORM,
    external_backup_dir: Path,
) -> None:
    """The default restore mode proves recoverability without publishing."""

    output_path, _sidecar_path, _output = _backup(external_backup_dir)
    before_count = TuiMetadataRegistryORM._default_manager.count()
    stdout = StringIO()

    call_command(
        "restore_tui_registry_backup",
        input=str(output_path),
        stdout=stdout,
    )

    assert TuiMetadataRegistryORM._default_manager.count() == before_count
    assert "verified (dry-run)" in stdout.getvalue()
    assert published_registry.source_hash in stdout.getvalue()


@pytest.mark.django_db
def test_restore_command_rejects_tampered_bundle(
    published_registry: TuiMetadataRegistryORM,
    external_backup_dir: Path,
) -> None:
    """The sidecar prevents a modified payload from reaching validation."""

    output_path, _sidecar_path, _output = _backup(external_backup_dir)
    output_path.write_text(
        output_path.read_text(encoding="utf-8").replace(
            published_registry.source_hash,
            "0" * 64,
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(CommandError, match="bundle SHA-256 mismatch"):
        call_command("restore_tui_registry_backup", input=str(output_path))


@pytest.mark.django_db
def test_approved_restore_requires_expected_active_hash_and_publishes_rollback(
    published_registry: TuiMetadataRegistryORM,
    external_backup_dir: Path,
) -> None:
    """Approved restore is concurrency guarded and records rollback ancestry."""

    output_path, _sidecar_path, _output = _backup(external_backup_dir)
    changed_payload = deepcopy(published_registry.payload)
    changed_payload["modules"][0]["label"] = "Changed after backup"
    repository = PublishedTuiMetadataRepository()
    changed = repository.publish_payload(
        payload=changed_payload,
        registry_key="default",
        review_note="change after backup",
        backend_version="test-backend-2",
    )

    with pytest.raises(CommandError, match="Active registry changed"):
        call_command(
            "restore_tui_registry_backup",
            input=str(output_path),
            approve=True,
            expected_active_source_hash=published_registry.source_hash,
        )

    call_command(
        "restore_tui_registry_backup",
        input=str(output_path),
        approve=True,
        expected_active_source_hash=changed.source_hash,
    )

    restored = repository.get_active_registry("default")
    assert restored is not None
    assert restored.pk not in {published_registry.pk, changed.pk}
    assert restored.source_hash == published_registry.source_hash
    assert restored.rollback_of_id == changed.pk


@pytest.mark.django_db
def test_backup_command_refuses_repository_output(
    published_registry: TuiMetadataRegistryORM,
) -> None:
    """Sensitive production backup payloads cannot be written under Git root."""

    with pytest.raises(CommandError, match="outside the repository"):
        call_command(
            "backup_tui_registry",
            output=str(ROOT / "forbidden-registry-backup.json"),
        )
