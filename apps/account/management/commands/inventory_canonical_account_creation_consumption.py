"""Inventory canonical Account-creation consumption evidence for one database."""

from __future__ import annotations

import json
from typing import Any, Protocol, cast

from django.core.management.base import BaseCommand, CommandError, CommandParser

_OUTPUT_SCHEMA = "canonical-account-creation-consumption-command.v1"
_FREEZE_UNAVAILABLE = "writer_freeze_proof_unavailable"
_PRECONDITIONS_FAILED = "contract_preconditions_not_satisfied"
_POSTGRESQL_REQUIRED = "production_postgresql_required"


class _ConsistencyReport(Protocol):
    """Minimum consistency surface consumed by the command."""

    is_consistent: bool
    v1_claim_null_count: int


class _InventoryReport(Protocol):
    """Minimum inventory surface consumed by the command."""

    backend: str
    closed_world_validated: bool
    consistency: _ConsistencyReport

    def canonical_payload(self) -> dict[str, object]: ...


class Command(BaseCommand):
    """Publish a read-only inventory without exposing Account-level identifiers."""

    help = "Inventory canonical Account-creation consumption ledgers for one database."

    def add_arguments(self, parser: CommandParser) -> None:
        """Register the explicit single-database inventory boundary."""

        parser.add_argument("--database", default="default")
        parser.add_argument("--batch-size", type=int, default=500)
        parser.add_argument("--json", action="store_true", dest="as_json")
        parser.add_argument(
            "--require-contract-ready",
            "--require-0048-ready",
            action="store_true",
            dest="require_contract_ready",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Inspect one alias and fail closed when production readiness is requested."""

        del args
        database = _database(options.get("database"))
        batch_size = _batch_size(options.get("batch_size"))
        as_json = _boolean(options.get("as_json"), "json")
        require_ready = _boolean(
            options.get("require_contract_ready", options.get("require_0048_ready")),
            "require-contract-ready",
        )
        report = load_inventory_report(using=database)
        consistency = report.consistency
        preconditions_satisfied = (
            report.closed_world_validated
            and consistency.is_consistent
            and consistency.v1_claim_null_count == 0
        )
        block_reason = _readiness_block_reason(
            require_ready=require_ready,
            preconditions_satisfied=preconditions_satisfied,
            backend=report.backend,
        )
        payload: dict[str, object] = {
            "batch_size": {
                "applied": False,
                "requested": batch_size,
                "semantics": "reserved_all_or_nothing",
            },
            "command": "inventory",
            "contract_preconditions_satisfied": preconditions_satisfied,
            "contract_ready": False,
            "inventory": report.canonical_payload(),
            "outcome": "blocked" if block_reason is not None else "success",
            "schema": _OUTPUT_SCHEMA,
            "writer_freeze": {
                "available": False,
                "reason": _FREEZE_UNAVAILABLE,
            },
        }
        if block_reason is not None:
            payload["block_reason"] = block_reason
        _write(self, payload, as_json=as_json)
        if block_reason is not None:
            raise CommandError(
                "canonical_account_creation_consumption_contract_ready_blocked:" + block_reason
            )


def load_inventory_report(*, using: str) -> _InventoryReport:
    """Load one report behind a patchable boundary and redact service failures."""

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
        raise CommandError("canonical_account_creation_consumption_inventory_blocked") from error


def _readiness_block_reason(
    *, require_ready: bool, preconditions_satisfied: bool, backend: str
) -> str | None:
    if not require_ready:
        return None
    if not preconditions_satisfied:
        return _PRECONDITIONS_FAILED
    if backend != "postgresql":
        return _POSTGRESQL_REQUIRED
    return _FREEZE_UNAVAILABLE


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
        "canonical creation consumption inventory "
        f"outcome={payload['outcome']} ready={payload['contract_ready']}"
    )
