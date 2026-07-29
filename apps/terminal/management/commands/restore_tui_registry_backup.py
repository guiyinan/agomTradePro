"""Validate or restore a verified TUI registry backup bundle."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.terminal.infrastructure.tui_metadata_repository import (
    PublishedTuiMetadataRepository,
)
from apps.terminal.infrastructure.tui_registry_backup import (
    load_verified_registry_backup,
)


class Command(BaseCommand):
    """Dry-run by default and publish a restore only after explicit approval."""

    help = "Validate or restore one verified TUI registry backup."

    def add_arguments(self, parser: Any) -> None:
        """Register fail-closed restore arguments."""

        parser.add_argument("--input", required=True, help="Backup JSON path.")
        parser.add_argument(
            "--sha256-file",
            help="SHA-256 sidecar path; defaults to <input>.sha256.",
        )
        parser.add_argument("--approve", action="store_true")
        parser.add_argument(
            "--expected-active-source-hash",
            help="Required with --approve to prevent restoring over an unexpected generation.",
        )
        parser.add_argument("--approved-by-user-id", type=int)

    def handle(self, *args: Any, **options: Any) -> None:
        """Verify integrity and optionally publish the recovered payload."""

        input_path = Path(str(options["input"])).resolve()
        sidecar_option = options.get("sha256_file")
        sidecar_path = (
            Path(str(sidecar_option)).resolve()
            if sidecar_option
            else input_path.with_suffix(f"{input_path.suffix}.sha256")
        )
        try:
            bundle = load_verified_registry_backup(
                input_path=input_path,
                sidecar_path=sidecar_path,
            )
        except (OSError, TypeError, ValueError) as exc:
            raise CommandError(f"Registry backup verification failed: {exc}") from exc

        record = bundle["registry"]
        repository = PublishedTuiMetadataRepository()
        payload = dict(record["payload"])
        try:
            _compacted, prepared_hash = repository.prepare_payload_for_publish(payload)
        except (TypeError, ValueError) as exc:
            raise CommandError(f"Registry payload validation failed: {exc}") from exc
        if prepared_hash != record["source_hash"]:
            raise CommandError("Validated restore payload hash differs from backup source_hash")

        active = repository.get_active_registry(record["registry_key"])
        active_hash = str(active.source_hash or "") if active is not None else "none"
        if not bool(options["approve"]):
            self.stdout.write(
                self.style.SUCCESS(
                    "TUI registry backup verified (dry-run) "
                    f"generation={record['generation']} "
                    f"registry_key={record['registry_key']} "
                    f"graph_hash={record['source_hash']} "
                    f"schema={record['schema_version']} "
                    f"runtime_build={bundle['runtime']['build_id']} "
                    f"active_source_hash={active_hash}"
                )
            )
            return

        expected_active_hash = str(options.get("expected_active_source_hash") or "").strip()
        if not expected_active_hash:
            raise CommandError("--expected-active-source-hash is required with --approve")
        if expected_active_hash != active_hash:
            raise CommandError(
                "Active registry changed since approval: "
                f"expected={expected_active_hash} actual={active_hash}"
            )

        approved_by = None
        approved_by_user_id = options.get("approved_by_user_id")
        if approved_by_user_id is not None:
            user_model = get_user_model()
            try:
                approved_by = user_model._default_manager.get(pk=approved_by_user_id)
            except user_model.DoesNotExist as exc:
                raise CommandError(
                    f"Approved-by user does not exist: {approved_by_user_id}"
                ) from exc

        restored = repository.publish_payload(
            payload=payload,
            registry_key=record["registry_key"],
            approved_by=approved_by,
            review_note=(
                "Verified registry restore from "
                f"generation {record['generation']} ({input_path.name})"
            ),
            generation_source="manual",
            backend_version=record["backend_version"],
            source_evidence_hash=record["source_evidence_hash"],
            changed_fields=list(record["changed_fields"]),
            rollback_of=active,
        )
        self.stdout.write(
            self.style.SUCCESS(
                "TUI registry restore published "
                f"generation={restored.pk} "
                f"rollback_of={getattr(active, 'pk', None)} "
                f"graph_hash={restored.source_hash}"
            )
        )
