"""Restore an existing dump and run provider-free DATA-02 historical analysis.

The runner accepts only a loopback PostgreSQL target and a controlled
disposable database name.  It never connects to production, invokes data
providers, writes restored facts/publications, creates a backup, or enables a
runtime gate.  Without ``--write`` the final content-addressed artifact is not
persisted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from psycopg import connect, sql

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.data_center.application.data02_isolated_simulation import (  # noqa: E402
    Data02IsolatedSimulationCandidate,
    Data02IsolatedSimulationRequest,
    RunData02IsolatedSimulationUseCase,
)
from apps.data_center.infrastructure.data02_isolated_snapshot import (  # noqa: E402
    PostgresData02HistoricalSnapshotAdapter,
)
from scripts.verify_postgres_backup_restore import (  # noqa: E402
    PostgresTarget,
    drop_restore_database,
    parse_postgres_target,
    recreate_restore_database,
    restore_dump,
    sha256_file,
    validate_custom_dump,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RESTORE_DATABASE_RE = re.compile(r"^agom_data02_sim_[a-z0-9]{8,32}$")
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


@dataclass(frozen=True, slots=True)
class VerifiedDumpIdentity:
    """Immutable dump identity proven by the local SHA sidecar."""

    name: str
    size: int
    sha256: str


def verify_dump_sidecar(dump_path: Path, sidecar_path: Path) -> VerifiedDumpIdentity:
    """Verify exact dump bytes against a two-field SHA-256 sidecar."""

    resolved_dump = dump_path.resolve()
    resolved_sidecar = sidecar_path.resolve()
    if not resolved_dump.is_file() or resolved_dump.stat().st_size < 1:
        raise ValueError("historical dump is missing or empty")
    if not resolved_sidecar.is_file():
        raise ValueError("historical dump SHA-256 sidecar is missing")
    fields = resolved_sidecar.read_text(encoding="ascii").strip().split()
    if len(fields) != 2 or _SHA256_RE.fullmatch(fields[0]) is None:
        raise ValueError("historical dump sidecar must contain digest and filename")
    if fields[1].lstrip("*") != resolved_dump.name:
        raise ValueError("historical dump sidecar filename does not match")
    actual = sha256_file(resolved_dump)
    if actual != fields[0]:
        raise ValueError("historical dump digest does not match sidecar")
    return VerifiedDumpIdentity(
        name=resolved_dump.name,
        size=resolved_dump.stat().st_size,
        sha256=actual,
    )


def validate_simulation_target(target: PostgresTarget) -> None:
    """Reject any target that is not an explicitly loopback PostgreSQL server."""

    if target.host not in _LOOPBACK_HOSTS:
        raise ValueError("DATA-02 simulation PostgreSQL target must use a loopback host")


def validate_restore_database(database_name: str) -> None:
    """Require the closed-world disposable database prefix before any DROP/CREATE."""

    if _RESTORE_DATABASE_RE.fullmatch(database_name) is None:
        raise ValueError("restore database must use the controlled prefix agom_data02_sim_")


def _database_absent(target: PostgresTarget, database_name: str) -> bool:
    """Return whether cleanup removed the exact disposable database."""

    validate_restore_database(database_name)
    with connect(target.url_for_database("postgres"), autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = %s)",
                (database_name,),
            )
            row = cursor.fetchone()
    return row == (True,)


def _parse_utc(value: str) -> datetime:
    """Parse an explicit UTC-Z simulation cutoff."""

    if not value.endswith("Z"):
        raise ValueError("--as-of must use ISO-8601 UTC-Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("--as-of must use ISO-8601 UTC-Z") from exc
    if parsed.utcoffset() is None:
        raise ValueError("--as-of must be timezone-aware")
    return parsed.astimezone(UTC)


def _canonical_json(value: object) -> bytes:
    """Serialize a stable UTF-8 JSON artifact."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _write_append_only(root: Path, digest: str, payload: bytes) -> tuple[Path, bool]:
    """Persist one content-addressed artifact without overwriting bytes."""

    resolved_root = root.resolve()
    artifact_dir = (resolved_root / "data02-isolated-simulation" / digest[:2]).resolve()
    if resolved_root not in artifact_dir.parents:
        raise ValueError("simulation output path escapes output root")
    artifact_path = artifact_dir / f"{digest}.json"
    digest_path = artifact_dir / f"{digest}.sha256"
    if artifact_path.exists():
        if artifact_path.read_bytes() != payload:
            raise ValueError("content-addressed simulation artifact collision")
        if digest_path.read_text(encoding="ascii") != f"{digest}\n":
            raise ValueError("content-addressed simulation sidecar collision")
        return artifact_path, False
    artifact_dir.mkdir(parents=True, exist_ok=True)
    with artifact_path.open("xb") as artifact_file:
        artifact_file.write(payload)
    with digest_path.open("xb") as digest_file:
        digest_file.write(f"{digest}\n".encode("ascii"))
    return artifact_path, True


def _parser() -> argparse.ArgumentParser:
    """Build the fail-closed simulation CLI parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATA02_SIMULATION_DATABASE_URL", ""),
        help="Loopback PostgreSQL maintenance URL; prefer DATA02_SIMULATION_DATABASE_URL.",
    )
    parser.add_argument("--dump-path", required=True, type=Path)
    parser.add_argument("--sidecar-path", type=Path)
    parser.add_argument("--restore-database")
    parser.add_argument(
        "--pg-restore-container",
        default=os.environ.get("PG_RESTORE_CONTAINER"),
    )
    parser.add_argument("--candidate-commit", required=True)
    parser.add_argument("--candidate-version", required=True)
    parser.add_argument("--source-tree-sha256", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--write", action="store_true")
    return parser


def _redact_error(error: BaseException, *, password: str) -> str:
    """Return a bounded error without leaking a local database password."""

    message = f"{type(error).__name__}: {error}"
    if password:
        message = message.replace(password, "[redacted]")
    return message[-4000:]


def main(argv: list[str] | None = None) -> int:
    """Restore, analyze, clean up and optionally persist one simulation artifact."""

    args = _parser().parse_args(argv)
    if not str(args.database_url).strip():
        raise SystemExit("DATA02_SIMULATION_DATABASE_URL or --database-url is required")
    target = parse_postgres_target(str(args.database_url))
    validate_simulation_target(target)
    dump_path = Path(args.dump_path).resolve()
    sidecar_path = (
        Path(args.sidecar_path).resolve()
        if args.sidecar_path is not None
        else Path(f"{dump_path}.sha256")
    )
    dump_identity = verify_dump_sidecar(dump_path, sidecar_path)
    restore_database = str(args.restore_database or f"agom_data02_sim_{uuid4().hex[:12]}")
    validate_restore_database(restore_database)
    if restore_database == target.database:
        raise ValueError("restore database must differ from the maintenance database")
    if args.write and args.output_root is None:
        raise ValueError("--output-root is required with --write")

    restore_entries = 0
    created = False
    report_payload: dict[str, object] | None = None
    failure: BaseException | None = None
    cleanup_error: BaseException | None = None
    cleanup_verified = False
    try:
        restore_entries = validate_custom_dump(
            dump_path,
            target,
            container_image=args.pg_restore_container,
        )
        recreate_restore_database(target, restore_database)
        created = True
        restore_dump(
            dump_path,
            target,
            restore_database,
            container_image=args.pg_restore_container,
        )
        if sha256_file(dump_path) != dump_identity.sha256:
            raise RuntimeError("historical dump changed during restore")
        request = Data02IsolatedSimulationRequest(
            candidate=Data02IsolatedSimulationCandidate(
                commit=str(args.candidate_commit),
                version=str(args.candidate_version),
                source_tree_sha256=str(args.source_tree_sha256),
            ),
            dump_sha256=dump_identity.sha256,
            dump_size=dump_identity.size,
            dump_name=dump_identity.name,
            restored_database=restore_database,
            as_of=_parse_utc(str(args.as_of)),
        )
        report = RunData02IsolatedSimulationUseCase(
            snapshot_port=PostgresData02HistoricalSnapshotAdapter(
                database_url=target.url_for_database(restore_database)
            )
        ).execute(request)
        report_payload = report.to_dict()
    except BaseException as exc:  # noqa: BLE001 - normalized after mandatory cleanup
        failure = exc
    finally:
        if created:
            try:
                drop_restore_database(target, restore_database)
                cleanup_verified = _database_absent(target, restore_database)
            except BaseException as exc:  # noqa: BLE001 - cleanup failure is the gate
                cleanup_error = exc

    if failure is not None or cleanup_error is not None or not cleanup_verified:
        error = (
            cleanup_error or failure or RuntimeError("disposable database cleanup was not verified")
        )
        failure_output = {
            "cleanup_database_absent": cleanup_verified,
            "error": _redact_error(error, password=target.password),
            "production_claim": False,
            "production_ready": False,
            "runtime_enablement": "not_authorized",
            "schema_version": "data02-isolated-simulation-run.v1",
            "simulation_outcome": "failed",
            "written": False,
        }
        print(json.dumps(failure_output, ensure_ascii=True, sort_keys=True))
        return 1
    if report_payload is None:
        raise RuntimeError("simulation report is unavailable after successful cleanup")
    envelope = {
        **report_payload,
        "cleanup_database_absent": True,
        "dump_sha256_after": sha256_file(dump_path),
        "restore_entries": restore_entries,
        "run_schema_version": "data02-isolated-simulation-run.v1",
    }
    payload = _canonical_json(envelope)
    artifact_sha256 = hashlib.sha256(payload).hexdigest()
    artifact_path: Path | None = None
    written = False
    if args.write:
        artifact_path, written = _write_append_only(
            Path(args.output_root),
            artifact_sha256,
            payload,
        )
    success_output: dict[str, object] = {
        "analysis_sha256": report_payload["analysis_sha256"],
        "artifact_sha256": artifact_sha256,
        "cleanup_database_absent": True,
        "historical_data_gate": report_payload["historical_data_gate"],
        "production_claim": False,
        "production_ready": False,
        "runtime_enablement": "not_authorized",
        "simulation_outcome": "completed",
        "written": written,
    }
    if artifact_path is not None:
        success_output["path"] = str(artifact_path)
    print(json.dumps(success_output, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
