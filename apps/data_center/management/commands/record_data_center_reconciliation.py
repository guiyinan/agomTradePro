"""Persist a deterministic legacy/canonical shadow comparison from JSON snapshots."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.data_center.application.public import record_reconciliation_evidence
from apps.data_center.application.reconciliation import build_reconciliation_report


def _read_snapshot(path: Path) -> dict[str, object]:
    """Load one natural-keyed snapshot and reject non-object JSON."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CommandError(f"cannot read reconciliation snapshot {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CommandError(f"reconciliation snapshot {path} must contain a JSON object")
    return {str(key): value for key, value in payload.items()}


def _snapshot_hash(snapshot: dict[str, object]) -> str:
    """Return a stable hash for an exported snapshot."""

    canonical = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _observed_at(raw: object) -> datetime:
    """Parse an explicit aware observation timestamp."""

    if raw is None:
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(str(raw))
    except ValueError as exc:
        raise CommandError("--observed-at must be an ISO-8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CommandError("--observed-at must include a timezone offset")
    return parsed


class Command(BaseCommand):
    """Record one maintenance-only reconciliation evidence snapshot."""

    help = "Persist a Data Center legacy/canonical reconciliation report."

    def add_arguments(self, parser: CommandParser) -> None:
        """Register snapshot and observation arguments."""

        parser.add_argument("dataset_key", help="Dataset Contract key being reconciled")
        parser.add_argument("legacy_snapshot", type=str, help="JSON object of legacy rows")
        parser.add_argument("canonical_snapshot", type=str, help="JSON object of canonical rows")
        parser.add_argument("--evidence-id", default=None)
        parser.add_argument("--observed-at", default=None)

    def handle(self, *args: Any, **options: Any) -> None:
        """Load, compare and persist one deterministic evidence record."""

        dataset_key = str(options["dataset_key"]).strip()
        if not dataset_key:
            raise CommandError("dataset_key cannot be empty")
        legacy = _read_snapshot(Path(str(options["legacy_snapshot"])).resolve())
        canonical = _read_snapshot(Path(str(options["canonical_snapshot"])).resolve())
        report = build_reconciliation_report(dataset_key, legacy, canonical)
        evidence = record_reconciliation_evidence(
            report,
            evidence_id=(str(options["evidence_id"]) if options.get("evidence_id") else None),
            legacy_snapshot_hash=_snapshot_hash(legacy),
            canonical_snapshot_hash=_snapshot_hash(canonical),
            observed_at=_observed_at(options.get("observed_at")),
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Data Center reconciliation recorded: "
                f"evidence_id={evidence.evidence_id}, dataset={dataset_key}, "
                f"clean={evidence.report.is_clean}, counts={evidence.report.counts}"
            )
        )
