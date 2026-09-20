"""Apply a reviewed, bounded correction plan to legacy price facts."""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.db.models import F, QuerySet

from apps.data_center.infrastructure.models import AssetMasterModel, PriceBarModel


@dataclass(frozen=True)
class RepairRule:
    """One source/asset-type cohort with reviewed source-unit evidence."""

    source: str
    asset_type: str
    expected: int
    volume_factor: Decimal
    amount_factor: Decimal
    adjustment: str
    amount_presence: str


def _read_rule(value: object) -> RepairRule:
    if not isinstance(value, dict):
        raise CommandError("Each rule must be an object")
    try:
        rule = RepairRule(
            source=str(value["source"]),
            asset_type=str(value["asset_type"]),
            expected=int(value["expected"]),
            volume_factor=Decimal(str(value["volume_factor"])),
            amount_factor=Decimal(str(value["amount_factor"])),
            adjustment=str(value["adjustment"]),
            amount_presence=str(value.get("amount_presence", "any")),
        )
    except (KeyError, ValueError, TypeError, InvalidOperation) as exc:
        raise CommandError("Invalid correction rule") from exc
    if (
        rule.expected <= 0
        or not value.get("evidence")
        or rule.adjustment not in {"none", "forward", "backward"}
        or not rule.source
        or not rule.asset_type
        or rule.amount_presence not in {"any", "present", "missing"}
        or not rule.volume_factor.is_finite()
        or not rule.amount_factor.is_finite()
        or rule.volume_factor <= 0
        or rule.amount_factor <= 0
    ):
        raise CommandError("Rules require positive counts/factors and source evidence")
    return rule


class Command(BaseCommand):
    help = "Dry-run a reviewed legacy price correction plan; --apply writes with a row rollback archive."

    def add_arguments(self, parser: CommandParser) -> None:
        """Require an explicit plan and an archive location for writes."""
        parser.add_argument("--plan", required=True)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--audit-dir")

    def handle(self, *args: Any, **options: Any) -> None:
        """Correct only the declared pre-cutoff legacy cohort, preserving observation times."""
        plan = json.loads(Path(str(options["plan"])).read_text(encoding="utf-8"))
        if not isinstance(plan, dict):
            raise CommandError("Plan must be an object")
        marker = str(plan.get("marker") or "")
        cutoff = datetime.fromisoformat(str(plan.get("fetched_before") or ""))
        if not marker or len(marker) > 40 or marker == "1.0" or cutoff.tzinfo is None:
            raise CommandError("Plan needs a unique schema marker and timezone-aware cutoff")
        values = plan.get("rules")
        if not isinstance(values, list) or not values:
            raise CommandError("Plan needs rules")
        rules = [_read_rule(value) for value in values]
        keys = [(rule.source, rule.asset_type, rule.amount_presence) for rule in rules]
        if len(keys) != len(set(keys)):
            raise CommandError("Overlapping source/type rules")
        for source, asset_type, presence in keys:
            if presence == "any" and sum(key[:2] == (source, asset_type) for key in keys) > 1:
                raise CommandError("Overlapping amount selectors")
        apply = bool(options["apply"])
        audit_dir = Path(str(options.get("audit_dir") or ""))
        if apply and not options.get("audit_dir"):
            raise CommandError("--apply requires --audit-dir")
        if apply:
            audit_dir.mkdir(parents=True, exist_ok=True)
        # Validate every cohort before starting any write.
        for rule in rules:
            self._validate_cohort(rule, cutoff, marker)
        for index, rule in enumerate(rules):
            if not apply:
                continue
            with transaction.atomic():
                pending = self._cohort(rule, cutoff).filter(schema_version="1.0")
                self._validate_cohort(rule, cutoff, marker)
                if not pending.exists():
                    continue
                archive = (
                    audit_dir / f"{marker}-{index}-{datetime.now(UTC).timestamp():.6f}.jsonl.gz"
                )
                # Row locks prevent concurrent edits between the rollback archive and update.
                with gzip.open(archive, "xt", encoding="utf-8") as stream:
                    for row in (
                        pending.select_for_update()
                        .order_by("pk")
                        .values(
                            "id",
                            "asset_code",
                            "bar_date",
                            "source",
                            "freq",
                            "volume",
                            "amount",
                            "adjustment",
                            "schema_version",
                            "revision_number",
                            "fetched_at",
                        )
                        .iterator(chunk_size=4000)
                    ):
                        stream.write(json.dumps(row, default=str) + "\n")
                updated = pending.update(
                    volume=F("volume") * rule.volume_factor,
                    amount=F("amount") * rule.amount_factor,
                    adjustment=rule.adjustment,
                    schema_version=marker,
                    revision_number=F("revision_number") + 1,
                )
                if updated != rule.expected:
                    raise CommandError("Concurrent cohort change: rolled back")
                self.stdout.write(
                    json.dumps(
                        {
                            "source": rule.source,
                            "asset_type": rule.asset_type,
                            "updated": updated,
                            "archive": str(archive),
                        }
                    )
                )
        self.stdout.write(json.dumps({"outcome": "success", "applied": apply, "marker": marker}))

    @staticmethod
    def _cohort(rule: RepairRule, cutoff: datetime) -> QuerySet[PriceBarModel]:
        cohort = PriceBarModel.objects.filter(
            source=rule.source,
            fetched_at__lt=cutoff,
            freq="1d",
            raw_payload_hash="",
            source_record_id="",
            ingested_run_id__isnull=True,
        )
        if rule.amount_presence != "any":
            cohort = cohort.filter(amount__isnull=rule.amount_presence == "missing")
        if rule.asset_type == "unregistered":
            return cohort.exclude(asset_code__in=AssetMasterModel.objects.values("code"))
        return cohort.filter(
            asset_code__in=AssetMasterModel.objects.filter(asset_type=rule.asset_type).values(
                "code"
            )
        )

    def _validate_cohort(self, rule: RepairRule, cutoff: datetime, marker: str) -> None:
        cohort = self._cohort(rule, cutoff)
        remaining = cohort.filter(
            schema_version="1.0", adjustment="none", revision_number=1
        ).count()
        repaired = cohort.filter(
            schema_version=marker, adjustment=rule.adjustment, revision_number=2
        ).count()
        if remaining + repaired != rule.expected or (remaining and repaired):
            raise CommandError(
                f"Cohort changed: {rule.source}/{rule.asset_type}: {remaining}+{repaired} != {rule.expected}"
            )
        if (
            rule.adjustment != "none"
            and remaining
            and cohort.filter(adjustment=rule.adjustment).exists()
        ):
            raise CommandError(
                "Target adjustment already exists; review collisions before applying"
            )
        self.stdout.write(
            json.dumps(
                {
                    "source": rule.source,
                    "asset_type": rule.asset_type,
                    "pending": remaining,
                    "already_repaired": repaired,
                }
            )
        )
