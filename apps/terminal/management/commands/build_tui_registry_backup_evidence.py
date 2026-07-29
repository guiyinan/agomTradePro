"""Build payload-free M5 evidence from a verified production registry backup."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from django.core.management.base import BaseCommand, CommandError

from apps.terminal.infrastructure.tui_metadata_repository import (
    PublishedTuiMetadataRepository,
)
from apps.terminal.infrastructure.tui_registry_backup import (
    load_verified_registry_backup,
)

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CUTOVER_EVIDENCE = ROOT / "config/tui/migration/web_to_tui_cutover_evidence.v1.json"
ATTESTATION_VERSION = "web-to-tui-production-registry-backup-attestation.v1"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
APPROVED_LOCATION_SCHEMES = frozenset({"artifact", "s3", "sftp", "https"})


def _load_object(path: Path) -> dict[str, Any]:
    """Load one JSON object from disk."""

    payload = cast(Any, json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(payload, dict):
        raise CommandError(f"Expected a JSON object: {path}")
    return cast(dict[str, Any], payload)


def _parse_date(value: object, *, field: str) -> date:
    """Parse one required ISO date."""

    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        raise CommandError(f"Missing date field: {field}")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise CommandError(f"Invalid date field: {field}") from exc


def _parse_aware_datetime(value: object, *, field: str) -> datetime:
    """Parse one required timezone-aware ISO datetime."""

    if not isinstance(value, str) or not value.strip():
        raise CommandError(f"Missing datetime field: {field}")
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError as exc:
        raise CommandError(f"Invalid datetime field: {field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CommandError(f"Datetime field must be timezone-aware: {field}")
    return parsed


def _valid_external_location(value: str) -> bool:
    """Return whether a secret-free external artifact locator is approved."""

    parsed = urlparse(value)
    return bool(
        parsed.scheme in APPROVED_LOCATION_SCHEMES
        and (parsed.netloc or parsed.path)
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    )


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Atomically replace one JSON object on disk."""

    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(
            (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
                "utf-8"
            )
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class Command(BaseCommand):
    """Validate a production backup and emit a payload-free M5 attestation."""

    help = "Build candidate-bound M5 evidence from a verified TUI registry backup."

    def add_arguments(self, parser: Any) -> None:
        """Register fail-closed attestation arguments."""

        parser.add_argument("--input", required=True, help="External registry backup JSON.")
        parser.add_argument(
            "--sha256-file",
            help="Backup SHA-256 sidecar; defaults to <input>.sha256.",
        )
        parser.add_argument("--location", required=True, help="Protected external locator.")
        parser.add_argument("--verified-by", required=True)
        parser.add_argument("--retention-until", required=True, type=date.fromisoformat)
        parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
        parser.add_argument("--attestation-output", required=True)
        parser.add_argument(
            "--cutover-evidence",
            default=str(DEFAULT_CUTOVER_EVIDENCE),
        )
        parser.add_argument("--replace", action="store_true")
        parser.add_argument(
            "--write-evidence",
            action="store_true",
            help="Write both the attestation and its cutover-evidence projection.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Verify bundle integrity, active state, restoreability and candidate binding."""

        input_path = Path(str(options["input"])).resolve()
        sidecar_value = options.get("sha256_file")
        sidecar_path = (
            Path(str(sidecar_value)).resolve()
            if sidecar_value
            else input_path.with_suffix(f"{input_path.suffix}.sha256")
        )
        root = ROOT.resolve()
        if input_path.is_relative_to(root) or sidecar_path.is_relative_to(root):
            raise CommandError(
                "Registry backup payload and sidecar must remain outside the repository"
            )

        output_path = Path(str(options["attestation_output"])).resolve()
        if not output_path.is_relative_to(root):
            raise CommandError("Registry backup attestation must be written inside the repository")
        if output_path.exists() and not bool(options["replace"]):
            raise CommandError(f"Refusing to overwrite existing attestation: {output_path}")

        location = str(options["location"] or "").strip()
        if not _valid_external_location(location):
            raise CommandError(
                "Backup location must be a credential-free approved external locator"
            )
        verified_by = str(options["verified_by"] or "").strip()
        if not verified_by:
            raise CommandError("verified-by is required")

        evidence_path = Path(str(options["cutover_evidence"])).resolve()
        evidence = _load_object(evidence_path)
        source_sha256 = str(evidence.get("source_sha256") or "").strip()
        if not SHA256_PATTERN.fullmatch(source_sha256):
            raise CommandError("Cutover evidence source_sha256 is invalid")
        candidate_value = evidence.get("candidate")
        candidate = (
            cast(dict[str, Any], candidate_value) if isinstance(candidate_value, dict) else {}
        )
        candidate_version = str(candidate.get("stable_version") or "").strip()
        candidate_commit = str(candidate.get("candidate_commit") or "").strip()
        observation_end = _parse_date(
            candidate.get("observation_end"), field="candidate.observation_end"
        )
        if not candidate_version or not COMMIT_PATTERN.fullmatch(candidate_commit):
            raise CommandError("Cutover evidence does not contain a complete candidate")

        as_of = _parse_date(options["as_of"], field="as_of")
        retention_until = _parse_date(options["retention_until"], field="retention_until")
        if observation_end > as_of:
            raise CommandError("Production registry backup cannot precede observation end")
        if retention_until <= as_of:
            raise CommandError("Registry backup retention must extend beyond the attestation date")

        try:
            bundle = load_verified_registry_backup(
                input_path=input_path,
                sidecar_path=sidecar_path,
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CommandError(f"Registry backup verification failed: {exc}") from exc

        exported_at = _parse_aware_datetime(bundle.get("exported_at"), field="bundle.exported_at")
        if not observation_end <= exported_at.date() <= as_of:
            raise CommandError(
                "Registry backup export is outside the post-observation review window"
            )

        record = bundle["registry"]
        runtime = bundle["runtime"]
        integrity = bundle["integrity"]
        repository = PublishedTuiMetadataRepository()
        payload = dict(record["payload"])
        try:
            _compacted, prepared_hash = repository.prepare_payload_for_publish(payload)
        except (TypeError, ValueError) as exc:
            raise CommandError(f"Registry backup restore validation failed: {exc}") from exc
        if prepared_hash != record["source_hash"]:
            raise CommandError("Restore validation changed the registry graph hash")

        active = repository.get_active_registry(record["registry_key"])
        if (
            active is None
            or active.pk != record["generation"]
            or str(active.source_hash or "") != record["source_hash"]
        ):
            raise CommandError("Current active registry does not match the production backup")

        runtime_version = str(runtime.get("version") or "").strip()
        runtime_build_id = str(runtime.get("build_id") or "").strip()
        schema_version = str(record.get("schema_version") or "").strip()
        if not runtime_version or not runtime_build_id or not schema_version:
            raise CommandError("Registry backup lacks schema/runtime identity")

        bundle_sha256 = hashlib.sha256(input_path.read_bytes()).hexdigest()
        attestation: dict[str, Any] = {
            "version": ATTESTATION_VERSION,
            "candidate_version": candidate_version,
            "candidate_commit": candidate_commit,
            "source_sha256": source_sha256,
            "location": location,
            "bundle_sha256": bundle_sha256,
            "payload_sha256": str(integrity["payload_sha256"]),
            "registry_generation": int(record["generation"]),
            "graph_hash": str(record["source_hash"]),
            "schema_version": schema_version,
            "runtime_version": runtime_version,
            "runtime_build_id": runtime_build_id,
            "created_at": exported_at.date().isoformat(),
            "restore_dry_run_passed": True,
            "restore_verified_at": as_of.isoformat(),
            "verified_by": verified_by,
            "retention_until": retention_until.isoformat(),
        }
        serialized = (
            json.dumps(attestation, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        evidence_reference = output_path.relative_to(root).as_posix()
        projection = dict(attestation)
        projection.pop("version")
        projection["evidence"] = evidence_reference
        projection["evidence_sha256"] = hashlib.sha256(serialized).hexdigest()

        prepared_evidence = copy.deepcopy(evidence)
        rollback_value = prepared_evidence.get("rollback")
        if not isinstance(rollback_value, dict):
            raise CommandError("Cutover evidence is missing rollback")
        rollback_value["production_registry_backup"] = projection

        if bool(options["write_evidence"]):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            _write_json_atomic(output_path, attestation)
            _write_json_atomic(evidence_path, prepared_evidence)

        mode = "WRITTEN" if bool(options["write_evidence"]) else "READY (dry-run)"
        self.stdout.write(
            self.style.SUCCESS(
                f"TUI registry backup evidence {mode} "
                f"generation={record['generation']} graph_hash={record['source_hash']} "
                f"bundle_sha256={bundle_sha256} attestation={evidence_reference}"
            )
        )
