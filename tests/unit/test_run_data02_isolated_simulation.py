"""CLI safety contracts for the isolated DATA-02 simulation runner."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts import run_data02_isolated_simulation as module
from scripts.verify_postgres_backup_restore import parse_postgres_target


def test_verify_dump_sidecar_requires_exact_hash_and_filename(tmp_path: Path) -> None:
    dump = tmp_path / "postgres-20260829T171523Z.dump"
    dump.write_bytes(b"immutable-history")
    digest = hashlib.sha256(dump.read_bytes()).hexdigest()
    sidecar = Path(f"{dump}.sha256")
    sidecar.write_text(f"{digest}  {dump.name}\n", encoding="ascii")

    identity = module.verify_dump_sidecar(dump, sidecar)

    assert identity.sha256 == digest
    assert identity.size == len(b"immutable-history")
    sidecar.write_text(f"{'0' * 64}  {dump.name}\n", encoding="ascii")
    with pytest.raises(ValueError, match="digest"):
        module.verify_dump_sidecar(dump, sidecar)


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://agom:secret@db.internal/agom",
        "postgresql://agom:secret@10.0.0.5/agom",
    ],
)
def test_validate_simulation_target_rejects_non_loopback_hosts(database_url: str) -> None:
    with pytest.raises(ValueError, match="loopback"):
        module.validate_simulation_target(parse_postgres_target(database_url))


def test_validate_restore_database_requires_controlled_prefix() -> None:
    module.validate_restore_database("agom_data02_sim_deadbeef")

    with pytest.raises(ValueError, match="controlled prefix"):
        module.validate_restore_database("agomtradepro")
