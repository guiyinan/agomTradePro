"""Repair one historical personal readiness evidence file with archive provenance."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, NotRequired, TypedDict

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.operational_readiness.management.commands.collect_personal_readiness_evidence import (
    DEFAULT_OUTPUT_DIR,
    collect_personal_readiness_evidence,
    write_personal_readiness_evidence_files,
)
from apps.operational_readiness.management.commands.inspect_personal_readiness_evidence import (
    inspect_personal_readiness_evidence,
)

REPAIR_TRIGGER_SOURCE = "repair"
REPAIR_TRIGGER_NAME = "apps.task_monitor.management.commands.repair_personal_readiness_evidence"
REPAIR_ARCHIVE_DIRNAME = "_repair_archive"


class _ArchivePaths(TypedDict):
    """Canonical paths created while preserving historical evidence."""

    json: str
    markdown: str | None
    manifest: NotRequired[str]


class Command(BaseCommand):
    help = "Archive and rebuild one historical personal readiness evidence file."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--target-date",
            required=True,
            help="Historical evidence target date in YYYY-MM-DD format.",
        )
        parser.add_argument(
            "--output-dir",
            default=DEFAULT_OUTPUT_DIR,
            help=f"Evidence directory. Default: {DEFAULT_OUTPUT_DIR}",
        )
        parser.add_argument(
            "--reason",
            default="historical_evidence_repair",
            help="Audit reason attached to the repaired evidence.",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Exit with CommandError when the repaired evidence is still blocked.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            dest="print_json",
            help="Print full JSON result.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        payload = repair_personal_readiness_evidence(
            output_dir=Path(str(options["output_dir"])),
            target_date=_parse_date(options.get("target_date")),
            reason=str(options.get("reason") or "historical_evidence_repair"),
        )
        if options.get("print_json"):
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "Personal readiness evidence repair: "
                    f"target={payload['target_date']}, status={payload['status']}"
                )
            )
            self.stdout.write(f"  archived json: {payload['archive']['json']}")
            if payload["archive"].get("markdown"):
                self.stdout.write(f"  archived md: {payload['archive']['markdown']}")
            self.stdout.write(f"  repaired json: {payload['output_paths']['json']}")
            self.stdout.write(f"  repaired md: {payload['output_paths']['markdown']}")
            self.stdout.write(
                "  acceptance: "
                f"{payload['original_acceptance']['reason']} -> "
                f"{payload['repaired_acceptance']['reason']}"
            )

        if options.get("strict") and payload["repaired_acceptance"]["accepted"] is not True:
            raise CommandError(
                "Repaired personal readiness evidence is not accepted: "
                f"{payload['repaired_acceptance']['reason']}"
            )


def repair_personal_readiness_evidence(
    *,
    output_dir: Path,
    target_date: date,
    reason: str,
) -> dict[str, Any]:
    """Archive the canonical evidence pair and rebuild it with repair provenance."""

    root = _resolve_output_root(output_dir=output_dir)
    json_path, markdown_path = _build_canonical_paths(root=root, target_date=target_date)
    if not json_path.exists():
        raise CommandError(f"evidence file does not exist: {json_path}")

    original_payload = _load_payload(json_path)
    original_inspection = inspect_personal_readiness_evidence(
        output_dir=root,
        target_date=target_date,
    )
    original_fingerprint = _build_file_fingerprint(json_path)
    repair_started_at = datetime.now(UTC)
    archive_paths = _archive_existing_files(
        json_path=json_path,
        markdown_path=markdown_path,
        repair_started_at=repair_started_at,
    )
    original_inputs = dict(original_payload.get("inputs") or {})
    repaired_payload = collect_personal_readiness_evidence(
        target_date=target_date,
        user_id=_parse_optional_int(original_inputs.get("user_id")),
        account_id=_parse_optional_int(original_inputs.get("account_id")),
        max_qlib_staleness_days=int(original_inputs.get("max_qlib_staleness_days") or 5),
        run_workspace_refresh=bool(original_inputs.get("run_workspace_refresh")),
        include_weekly_advisor=bool(original_inputs.get("include_weekly_advisor")),
        persist_risk_report=bool(original_inputs.get("persist_risk_report")),
        allow_unclosed_target_date=False,
        trigger_source=REPAIR_TRIGGER_SOURCE,
        trigger_task_id=None,
        trigger_task_name=REPAIR_TRIGGER_NAME,
    )
    repaired_payload["repair_context"] = {
        "reason": reason,
        "repaired_at": repair_started_at.isoformat(),
        "archive_dir": str(Path(archive_paths["json"]).parent),
        "original_file": original_fingerprint,
        "original_generated_at": original_payload.get("generated_at"),
        "original_status": original_payload.get("status"),
        "original_acceptance": dict(original_inspection.get("acceptance") or {}),
        "original_operation_context": dict(original_payload.get("operation_context") or {}),
    }
    output_paths = write_personal_readiness_evidence_files(
        payload=repaired_payload,
        output_dir=root,
    )
    repaired_inspection = inspect_personal_readiness_evidence(
        output_dir=root,
        target_date=target_date,
    )
    repaired_fingerprint = _build_file_fingerprint(Path(output_paths["json"]))
    manifest_path = _write_archive_manifest(
        archive_dir=Path(archive_paths["json"]).parent,
        payload={
            "schema_version": "personal-readiness-evidence-repair.v1",
            "target_date": target_date.isoformat(),
            "reason": reason,
            "repair_started_at": repair_started_at.isoformat(),
            "source_trigger": REPAIR_TRIGGER_SOURCE,
            "source_command": REPAIR_TRIGGER_NAME,
            "original_file": original_fingerprint,
            "archived_paths": archive_paths,
            "original_acceptance": dict(original_inspection.get("acceptance") or {}),
            "repaired_file": repaired_fingerprint,
            "repaired_paths": output_paths,
            "repaired_acceptance": dict(repaired_inspection.get("acceptance") or {}),
        },
    )
    archive_paths["manifest"] = str(manifest_path)
    return {
        "status": repaired_inspection["status"],
        "target_date": target_date.isoformat(),
        "reason": reason,
        "archive": archive_paths,
        "output_paths": output_paths,
        "original_acceptance": dict(original_inspection.get("acceptance") or {}),
        "repaired_acceptance": dict(repaired_inspection.get("acceptance") or {}),
        "original_file": original_fingerprint,
        "repaired_file": repaired_fingerprint,
    }


def _resolve_output_root(*, output_dir: Path) -> Path:
    return Path(settings.BASE_DIR) / output_dir if not output_dir.is_absolute() else output_dir


def _build_canonical_paths(*, root: Path, target_date: date) -> tuple[Path, Path]:
    stem = f"{target_date.isoformat()}-personal-readiness"
    return root / f"{stem}.json", root / f"{stem}.md"


def _archive_existing_files(
    *,
    json_path: Path,
    markdown_path: Path,
    repair_started_at: datetime,
) -> _ArchivePaths:
    archive_dir = (
        json_path.parent
        / REPAIR_ARCHIVE_DIRNAME
        / json_path.stem.replace("-personal-readiness", "")
        / repair_started_at.strftime("%Y%m%dT%H%M%SZ")
    )
    archive_dir.mkdir(parents=True, exist_ok=True)
    archived_json = archive_dir / json_path.name
    archived_json.write_bytes(json_path.read_bytes())
    archived_markdown: Path | None = None
    if markdown_path.exists():
        archived_markdown = archive_dir / markdown_path.name
        archived_markdown.write_text(markdown_path.read_text(encoding="utf-8"), encoding="utf-8")
    return {
        "json": str(archived_json),
        "markdown": str(archived_markdown) if archived_markdown is not None else None,
    }


def _write_archive_manifest(*, archive_dir: Path, payload: dict[str, Any]) -> Path:
    manifest_path = archive_dir / "repair-manifest.json"
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest_path


def _build_file_fingerprint(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    return {
        "path": str(path),
        "size_bytes": len(raw),
        "sha256": sha256(raw).hexdigest(),
    }


def _load_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CommandError(f"cannot read evidence file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CommandError(f"evidence file is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise CommandError(f"evidence JSON root must be an object: {path}")
    return payload


def _parse_optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise CommandError("target-date must be YYYY-MM-DD") from exc
