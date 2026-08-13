"""Backfill Binding-v1 consumption claims with an explicit write opt-in."""

from __future__ import annotations

import json
from typing import Any, Protocol, cast

from django.core.management.base import BaseCommand, CommandError, CommandParser

_OUTPUT_SCHEMA = "canonical-account-creation-consumption-command.v1"
_FREEZE_UNAVAILABLE = "writer_freeze_proof_unavailable"


class _InventoryReport(Protocol):
    """Minimum inventory surface consumed by the backfill command."""

    snapshot_hash: str


class _BackfillReport(Protocol):
    """Minimum service report surface consumed by the backfill command."""

    scanned: int
    eligible: int
    created: int
    already_linked: int


class _BackfillService(Protocol):
    """Patchable all-or-nothing backfill service boundary."""

    def run(self, *, dry_run: bool = True) -> _BackfillReport: ...


class Command(BaseCommand):
    """Preview by default and write only after a fresh inventory comparison."""

    help = "Preview or backfill legacy Binding-v1 consumption claims."

    def add_arguments(self, parser: CommandParser) -> None:
        """Register fail-closed backfill arguments."""

        parser.add_argument("--database", default="default")
        parser.add_argument("--batch-size", type=int, default=500)
        parser.add_argument("--json", action="store_true", dest="as_json")
        parser.add_argument("--write", action="store_true")
        parser.add_argument("--expected-inventory-sha256", default=None)

    def handle(self, *args: Any, **options: Any) -> None:
        """Run one bounded operator invocation without publishing sensitive anchors."""

        del args
        database = _database(options.get("database"))
        batch_size = _batch_size(options.get("batch_size"))
        as_json = _boolean(options.get("as_json"), "json")
        write = _boolean(options.get("write"), "write")
        expected_hash = _expected_hash(options.get("expected_inventory_sha256"), required=write)
        if write and database_vendor(using=database) != "postgresql":
            raise CommandError("consumption backfill write requires PostgreSQL")

        before = load_inventory_report(using=database)
        if write and expected_hash != before.snapshot_hash:
            raise CommandError("expected inventory hash does not match current inventory")
        if write:
            _write(
                self,
                {
                    "batch_size": {
                        "applied": False,
                        "requested": batch_size,
                        "semantics": "reserved_all_or_nothing",
                    },
                    "block_reason": _FREEZE_UNAVAILABLE,
                    "command": "backfill_v1",
                    "database_alias": database,
                    "inventory_before_sha256": before.snapshot_hash,
                    "mode": "write",
                    "outcome": "blocked",
                    "schema": _OUTPUT_SCHEMA,
                    "writer_freeze": {
                        "available": False,
                        "reason": _FREEZE_UNAVAILABLE,
                    },
                },
                as_json=as_json,
            )
            raise CommandError("consumption_backfill_write_blocked:" + _FREEZE_UNAVAILABLE)

        report = run_backfill_service(build_backfill_service(using=database), dry_run=True)
        payload: dict[str, object] = {
            "batch_size": {
                "applied": False,
                "requested": batch_size,
                "semantics": "reserved_all_or_nothing",
            },
            "command": "backfill_v1",
            "counts": {
                "already_linked": report.already_linked,
                "created": report.created,
                "eligible": report.eligible,
                "scanned": report.scanned,
            },
            "database_alias": database,
            "inventory_after_sha256": before.snapshot_hash,
            "inventory_before_sha256": before.snapshot_hash,
            "mode": "dry_run",
            "outcome": "noop" if report.eligible == 0 else "success",
            "schema": _OUTPUT_SCHEMA,
            "writer_freeze": {
                "available": False,
                "reason": _FREEZE_UNAVAILABLE,
            },
        }
        _write(self, payload, as_json=as_json)


def load_inventory_report(*, using: str) -> _InventoryReport:
    """Load one inventory behind a patchable boundary and redact failures."""

    from apps.account.infrastructure.canonical_account_creation_consumption_inventory import (
        CanonicalAccountCreationConsumptionInventoryUnavailable,
        inventory_canonical_account_creation_consumption,
    )

    try:
        return cast(
            _InventoryReport,
            inventory_canonical_account_creation_consumption(using=using),
        )
    except CanonicalAccountCreationConsumptionInventoryUnavailable as error:
        raise CommandError("consumption backfill inventory blocked") from error


def build_backfill_service(*, using: str) -> _BackfillService:
    """Construct the Django backfill behind a patchable pure-test boundary."""

    from apps.account.infrastructure.canonical_account_creation_consumption_backfill import (
        DjangoCanonicalAccountCreationConsumptionBackfill,
    )

    return cast(
        _BackfillService,
        DjangoCanonicalAccountCreationConsumptionBackfill(using=using),
    )


def run_backfill_service(service: _BackfillService, *, dry_run: bool) -> _BackfillReport:
    """Translate expected domain failures into stable operator errors."""

    from apps.account.application.canonical_account_creation import (
        CanonicalAccountCreationConflict,
        CanonicalAccountCreationCorruption,
    )

    try:
        return service.run(dry_run=dry_run)
    except CanonicalAccountCreationConflict as error:
        raise CommandError("consumption backfill blocked") from error
    except CanonicalAccountCreationCorruption as error:
        raise CommandError("consumption backfill corruption detected") from error


def database_vendor(*, using: str) -> str:
    """Resolve only the backend vendor without exposing database settings."""

    from django.db import connections
    from django.utils.connection import ConnectionDoesNotExist

    try:
        return connections[using].vendor
    except (KeyError, ConnectionDoesNotExist) as error:
        raise CommandError("unknown database alias") from error


def _database(value: object) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise CommandError("database must name one explicit alias")
    return value


def _batch_size(value: object) -> int:
    if type(value) is not int or not 1 <= value <= 5000:
        raise CommandError("batch-size must be an integer from 1 through 5000")
    return value


def _boolean(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise CommandError(f"{name} must be a boolean flag")
    return value


def _expected_hash(value: object, *, required: bool) -> str | None:
    if value is None:
        if required:
            raise CommandError("--expected-inventory-sha256 is required with --write")
        return None
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise CommandError("expected inventory hash must be a lowercase SHA-256 digest")
    return value


def _write(command: BaseCommand, payload: dict[str, object], *, as_json: bool) -> None:
    text = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if as_json:
        command.stdout.write(text)
        return
    command.stdout.write(
        "canonical creation consumption backfill "
        f"outcome={payload['outcome']} mode={payload['mode']}"
    )
