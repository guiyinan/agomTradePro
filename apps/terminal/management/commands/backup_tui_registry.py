"""Export the active published TUI registry to a verified external bundle."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.terminal.infrastructure.tui_metadata_repository import (
    PublishedTuiMetadataRepository,
)
from apps.terminal.infrastructure.tui_registry_backup import (
    build_registry_backup_bundle,
    write_registry_backup_bundle,
)

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_RUNTIME_MANIFEST = ROOT / "config/tui/agomtui-runtime.manifest.json"


class Command(BaseCommand):
    """Write an atomically verified backup outside the repository."""

    help = "Back up one active published TUI metadata registry generation."

    def add_arguments(self, parser: Any) -> None:
        """Register bounded backup arguments."""

        parser.add_argument("--output", required=True, help="External JSON backup path.")
        parser.add_argument("--registry-key", default="default")
        parser.add_argument(
            "--runtime-manifest",
            default=str(DEFAULT_RUNTIME_MANIFEST),
            help="Reviewed AgomTUI runtime manifest used by the deployed release.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Export the active registry and print non-sensitive recovery metadata."""

        output_path = Path(str(options["output"])).resolve()
        if output_path == ROOT or output_path.is_relative_to(ROOT):
            raise CommandError("Registry backups must be written outside the repository")
        if output_path.exists():
            raise CommandError(f"Refusing to overwrite existing backup: {output_path}")

        runtime_manifest_path = Path(str(options["runtime_manifest"])).resolve()
        try:
            runtime_manifest = json.loads(runtime_manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"Unable to read runtime manifest: {exc}") from exc
        if not isinstance(runtime_manifest, dict):
            raise CommandError("Runtime manifest must be a JSON object")

        repository = PublishedTuiMetadataRepository()
        registry_key = str(options["registry_key"]).strip()
        model = repository.get_active_registry(registry_key)
        if model is None:
            raise CommandError(f"No active published registry found for key: {registry_key}")

        try:
            bundle = build_registry_backup_bundle(
                model=model,
                runtime_manifest=runtime_manifest,
                exported_at=timezone.now().isoformat(),
            )
            sidecar_path, bundle_sha256 = write_registry_backup_bundle(
                output_path=output_path,
                bundle=bundle,
            )
        except (OSError, TypeError, ValueError) as exc:
            raise CommandError(f"Unable to create verified registry backup: {exc}") from exc

        self.stdout.write(
            self.style.SUCCESS(
                "TUI registry backup created "
                f"generation={bundle['registry']['generation']} "
                f"registry_key={registry_key} "
                f"graph_hash={bundle['registry']['source_hash']} "
                f"schema={bundle['registry']['schema_version']} "
                f"runtime_build={bundle['runtime']['build_id']} "
                f"bundle_sha256={bundle_sha256} "
                f"path={output_path} sidecar={sidecar_path}"
            )
        )
