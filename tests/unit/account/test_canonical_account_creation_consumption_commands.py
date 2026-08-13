"""Pure CLI safety coverage for canonical creation-consumption maintenance."""

from __future__ import annotations

import json
from dataclasses import dataclass
from io import StringIO

import pytest
from django.core.management.base import CommandError

from apps.account.management.commands import (
    backfill_canonical_account_creation_consumption_v1 as backfill_command,
)
from apps.account.management.commands import (
    inventory_canonical_account_creation_consumption as inventory_command,
)


@dataclass(frozen=True)
class _Consistency:
    is_consistent: bool = True
    v1_claim_null_count: int = 0


@dataclass(frozen=True)
class _Inventory:
    snapshot_hash: str = "a" * 64
    backend: str = "postgresql"
    closed_world_validated: bool = True
    consistency: _Consistency = _Consistency()

    def canonical_payload(self) -> dict[str, object]:
        return {
            "backend": self.backend,
            "closed_world_validated": self.closed_world_validated,
            "consistency": {
                "is_consistent": self.consistency.is_consistent,
                "v1_claim_null_count": self.consistency.v1_claim_null_count,
            },
            "database_alias": "default",
            "snapshot_hash": self.snapshot_hash,
        }


@dataclass(frozen=True)
class _BackfillReport:
    scanned: int = 2
    eligible: int = 1
    created: int = 0
    already_linked: int = 1


def test_inventory_json_is_stable_redacted_and_marks_batch_reserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        inventory_command,
        "load_inventory_report",
        lambda *, using: _Inventory(),
    )
    output = StringIO()
    inventory_command.Command(stdout=output).handle(
        database="default",
        batch_size=100,
        as_json=True,
        require_0048_ready=False,
    )
    raw = output.getvalue().strip()
    payload = json.loads(raw)
    assert raw == json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert payload["batch_size"] == {
        "applied": False,
        "requested": 100,
        "semantics": "reserved_all_or_nothing",
    }
    assert payload["contract_0048_ready"] is False
    assert payload["writer_freeze"]["available"] is False
    assert "account_id" not in raw
    assert "PASSWORD" not in raw


def test_inventory_require_ready_blocks_postgresql_without_freeze(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        inventory_command,
        "load_inventory_report",
        lambda *, using: _Inventory(),
    )
    output = StringIO()
    with pytest.raises(CommandError, match="writer_freeze_proof_unavailable"):
        inventory_command.Command(stdout=output).handle(
            database="default",
            batch_size=500,
            as_json=True,
            require_0048_ready=True,
        )
    assert json.loads(output.getvalue())["outcome"] == "blocked"


def test_inventory_require_ready_checks_consistency_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _Inventory(consistency=_Consistency(is_consistent=False))
    monkeypatch.setattr(
        inventory_command,
        "load_inventory_report",
        lambda *, using: report,
    )
    with pytest.raises(CommandError, match="preconditions_not_satisfied"):
        inventory_command.Command(stdout=StringIO()).handle(
            database="default",
            batch_size=500,
            as_json=True,
            require_0048_ready=True,
        )


def test_backfill_defaults_to_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bool] = []

    class _Service:
        def run(self, *, dry_run: bool = True) -> _BackfillReport:
            calls.append(dry_run)
            return _BackfillReport()

    monkeypatch.setattr(
        backfill_command,
        "load_inventory_report",
        lambda *, using: _Inventory(),
    )
    monkeypatch.setattr(
        backfill_command,
        "build_backfill_service",
        lambda *, using: _Service(),
    )
    output = StringIO()
    backfill_command.Command(stdout=output).handle(
        database="default",
        batch_size=500,
        as_json=True,
        write=False,
        expected_inventory_sha256=None,
    )
    payload = json.loads(output.getvalue())
    assert calls == [True]
    assert payload["mode"] == "dry_run"
    assert payload["writer_freeze"]["available"] is False


def test_backfill_write_requires_hash_before_database_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        backfill_command,
        "database_vendor",
        lambda *, using: pytest.fail("database must not be read"),
    )
    with pytest.raises(CommandError, match="required with --write"):
        backfill_command.Command(stdout=StringIO()).handle(
            database="default",
            batch_size=500,
            as_json=True,
            write=True,
            expected_inventory_sha256=None,
        )


def test_backfill_write_rejects_non_postgresql_before_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(backfill_command, "database_vendor", lambda *, using: "sqlite")
    monkeypatch.setattr(
        backfill_command,
        "load_inventory_report",
        lambda *, using: pytest.fail("inventory must not run"),
    )
    with pytest.raises(CommandError, match="requires PostgreSQL"):
        backfill_command.Command(stdout=StringIO()).handle(
            database="default",
            batch_size=500,
            as_json=True,
            write=True,
            expected_inventory_sha256="a" * 64,
        )


def test_backfill_write_rejects_stale_reinventory_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(backfill_command, "database_vendor", lambda *, using: "postgresql")
    monkeypatch.setattr(
        backfill_command,
        "load_inventory_report",
        lambda *, using: _Inventory(),
    )
    with pytest.raises(CommandError, match="does not match"):
        backfill_command.Command(stdout=StringIO()).handle(
            database="default",
            batch_size=500,
            as_json=True,
            write=True,
            expected_inventory_sha256="b" * 64,
        )


def test_backfill_write_matching_hash_still_fails_closed_without_freeze(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(backfill_command, "database_vendor", lambda *, using: "postgresql")
    monkeypatch.setattr(
        backfill_command,
        "load_inventory_report",
        lambda *, using: _Inventory(),
    )
    monkeypatch.setattr(
        backfill_command,
        "build_backfill_service",
        lambda *, using: pytest.fail("write service must remain unreachable"),
    )
    output = StringIO()
    with pytest.raises(CommandError, match="writer_freeze_proof_unavailable"):
        backfill_command.Command(stdout=output).handle(
            database="default",
            batch_size=500,
            as_json=True,
            write=True,
            expected_inventory_sha256="a" * 64,
        )
    payload = json.loads(output.getvalue())
    assert payload["outcome"] == "blocked"
    assert payload["writer_freeze"] == {
        "available": False,
        "reason": "writer_freeze_proof_unavailable",
    }


@pytest.mark.parametrize("batch_size", [True, 0, 5001])
@pytest.mark.parametrize(
    "command,options",
    [
        (
            inventory_command.Command,
            {"as_json": True, "require_0048_ready": False},
        ),
        (
            backfill_command.Command,
            {
                "as_json": True,
                "write": False,
                "expected_inventory_sha256": None,
            },
        ),
    ],
)
def test_commands_reject_invalid_batch_size(
    batch_size: object,
    command: type[inventory_command.Command] | type[backfill_command.Command],
    options: dict[str, object],
) -> None:
    with pytest.raises(CommandError, match="batch-size"):
        command(stdout=StringIO()).handle(database="default", batch_size=batch_size, **options)
