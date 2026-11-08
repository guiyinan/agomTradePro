from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
RESTORE_SCRIPT: Final[Path] = REPO_ROOT / "scripts" / "vps-restore.sh"
SH_PATH: Final[str] = shutil.which("sh") or "sh"
_SH_DIRECTORY: Final[Path] = Path(SH_PATH).resolve().parent
_BASH_CANDIDATES: Final[tuple[str | None, ...]] = (
    str(_SH_DIRECTORY / ("bash.exe" if os.name == "nt" else "bash")),
    shutil.which("bash"),
)
BASH_PATH: Final[str | None] = next(
    (candidate for candidate in _BASH_CANDIDATES if candidate and Path(candidate).exists()),
    None,
)


def _shell_path(path: Path) -> str:
    """Convert a Windows path to the Git Bash path form used by the shell harness."""
    if os.name != "nt":
        return str(path)
    cygpath = shutil.which("cygpath")
    if cygpath:
        return subprocess.check_output(
            [cygpath, "-u", str(path)], text=True, encoding="utf-8", timeout=10
        ).strip()
    drive = path.drive.rstrip(":").lower()
    return f"/{drive}/{path.as_posix().split(':', 1)[-1].lstrip('/')}"


class RestoreCliHarness:
    """Run the real restore CLI against temporary files and mocked system commands."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.target = root / "target"
        self.backup = root / "backups"
        self.mock_bin = root / "bin"
        self.call_log = root / "calls.log"
        self.list_calls = root / "list-calls.txt"
        self.archive = self.backup / "database" / "postgres-20261108-120000.dump"
        self.manifest = self.backup / "meta" / "manifest-20261108-120000.txt"
        self._prepare()

    def _prepare(self) -> None:
        (self.target / "deploy").mkdir(parents=True)
        (self.target / "docker").mkdir()
        (self.backup / "database").mkdir(parents=True)
        (self.backup / "meta").mkdir()
        self.mock_bin.mkdir()
        (self.target / "deploy" / ".env").write_text(
            "DATABASE_URL=postgresql://runtime@postgres:5432/agomtradepro\n"
            "POSTGRES_DB=agomtradepro\n"
            "POSTGRES_USER=agomtradepro\n",
            encoding="utf-8",
        )
        (self.target / "docker" / "docker-compose.vps.yml").write_text(
            "services: {}\n", encoding="utf-8"
        )
        self.archive.write_bytes(b"verified-postgres-archive\n")
        self.refresh_manifest()
        self._write_mock(
            "docker",
            """#!/bin/sh
set -eu
printf '%s\\n' "$*" >> "$CALL_LOG"
if [ "$1" = compose ] && [ "$2" = version ]; then
  exit 0
fi
case "$*" in
  *"printenv POSTGRES_DB"*)
    printf '%s\\n' "${RUNTIME_DB:-agomtradepro}"
    ;;
  *"pg_restore --list"*)
    call_count=0
    if [ -f "$LIST_CALLS" ]; then call_count=$(cat "$LIST_CALLS"); fi
    call_count=$((call_count + 1))
    printf '%s' "$call_count" > "$LIST_CALLS"
    printf '\\nlist_input:' >> "$CALL_LOG"
    cat >> "$CALL_LOG"
    printf '\\n' >> "$CALL_LOG"
    if [ "$call_count" -eq 1 ]; then
      if [ -n "${MUTATE_SOURCE_ON_INPUT_PREFLIGHT:-}" ]; then
        printf 'tampered-after-preflight\\n' > "$MUTATE_SOURCE_ON_INPUT_PREFLIGHT"
      fi
      exit "${INPUT_LIST_STATUS:-0}"
    fi
    exit "${ROLLBACK_LIST_STATUS:-0}"
    ;;
  *"pg_dump"*)
    if [ "${PG_DUMP_STATUS:-0}" -ne 0 ]; then
      printf 'mock pg_dump failure\\n' >&2
      exit "$PG_DUMP_STATUS"
    fi
    printf 'verified-current-target-dump\\n'
    ;;
  *"pg_restore"*)
    printf '\\nrestore_input:' >> "$CALL_LOG"
    cat >> "$CALL_LOG"
    printf '\\n' >> "$CALL_LOG"
    ;;
  *"stop web"*)
    if [ "${STOP_STATUS:-0}" -ne 0 ]; then
      printf 'mock stop failure\\n' >&2
      exit "$STOP_STATUS"
    fi
    ;;
  *"exec -T postgres sh -eu"*)
    cat >> "$CALL_LOG"
    ;;
esac
exit 0
""",
        )
        self._write_mock(
            "gzip",
            """#!/bin/sh
set -eu
case "$1" in
  -t) exit "${GZIP_TEST_STATUS:-0}" ;;
  -dc) cat "$2" ;;
  *) exit 2 ;;
esac
""",
        )

    def _write_mock(self, name: str, content: str) -> None:
        mock = self.mock_bin / name
        mock.write_text(content, encoding="utf-8", newline="\n")
        mock.chmod(0o755)

    def refresh_manifest(self, digest: str | None = None) -> None:
        recorded_digest = digest or hashlib.sha256(self.archive.read_bytes()).hexdigest()
        self.manifest.write_text(
            f"{recorded_digest}  {self.archive.as_posix()}\n",
            encoding="utf-8",
            newline="\n",
        )

    def command(
        self,
        *,
        include_target_confirmation: bool = True,
        bash_trace: bool = False,
        extra_arguments: tuple[str, ...] = (),
    ) -> list[str]:
        if (bash_trace or os.environ.get("GOV05_BASH_TRACE") == "1") and BASH_PATH:
            shell_command = [BASH_PATH, "-x"]
        else:
            shell_command = [SH_PATH]
        args = [
            "--target-dir",
            _shell_path(self.target),
            "--backup-dir",
            _shell_path(self.backup),
            "--database-file",
            _shell_path(self.archive),
            "--no-redis",
        ]
        args.extend(extra_arguments)
        if include_target_confirmation:
            args.extend(["--confirm-target", "agomtradepro"])
        return [*shell_command, _shell_path(RESTORE_SCRIPT), *args]

    def run(
        self,
        *,
        extra_arguments: tuple[str, ...] = (),
        **environment: str,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        existing_path = env.get("PATH", "")
        env.update(
            {
                "CALL_LOG": _shell_path(self.call_log),
                "LIST_CALLS": _shell_path(self.list_calls),
                "PATH": os.pathsep.join([str(self.mock_bin), existing_path]),
            }
        )
        env.update(environment)
        return subprocess.run(
            self.command(
                include_target_confirmation=environment.get("OMIT_TARGET_CONFIRMATION") != "1",
                extra_arguments=extra_arguments,
            ),
            cwd=REPO_ROOT,
            env=env,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
            timeout=60,
        )

    def calls(self) -> str:
        return self.call_log.read_text(encoding="utf-8") if self.call_log.exists() else ""


def _harness(tmp_path: Path) -> RestoreCliHarness:
    return RestoreCliHarness(tmp_path)


def _assert_no_database_mutation(call_log: str) -> None:
    assert " dropdb " not in f" {call_log} "
    assert " createdb " not in f" {call_log} "
    assert " pg_restore -U " not in f" {call_log} "


def test_missing_target_confirmation_is_rejected_before_compose_mutation(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)

    result = harness.run(OMIT_TARGET_CONFIRMATION="1")

    assert result.returncode != 0
    assert "--confirm-target" in result.stderr
    assert " up " not in f" {harness.calls()} "
    assert " stop " not in f" {harness.calls()} "
    _assert_no_database_mutation(harness.calls())


def test_archive_digest_mismatch_is_rejected_before_compose_mutation(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    harness.refresh_manifest("0" * 64)

    result = harness.run()

    assert result.returncode != 0
    assert "digest" in result.stderr.lower()
    assert " up " not in f" {harness.calls()} "
    assert " stop " not in f" {harness.calls()} "
    _assert_no_database_mutation(harness.calls())


def test_missing_archive_digest_manifest_is_rejected_before_compose_mutation(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    harness.manifest.unlink()

    result = harness.run()

    assert result.returncode != 0
    assert "sha-256" in result.stderr.lower()
    assert " up " not in f" {harness.calls()} "
    assert " stop " not in f" {harness.calls()} "
    _assert_no_database_mutation(harness.calls())


def test_malformed_explicit_digest_is_rejected_before_compose_mutation(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)

    result = harness.run(extra_arguments=("--database-sha256", "bad-digest"))

    assert result.returncode != 0
    assert "malformed" in result.stderr.lower()
    assert " up " not in f" {harness.calls()} "
    assert " stop " not in f" {harness.calls()} "
    _assert_no_database_mutation(harness.calls())


def test_explicit_independent_digest_accepts_archive_without_local_manifest(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    harness.manifest.unlink()
    digest = hashlib.sha256(harness.archive.read_bytes()).hexdigest()

    result = harness.run(extra_arguments=("--database-sha256", digest))

    assert result.returncode == 0, result.stderr
    assert "Restore completed" in result.stdout


def test_confirmed_target_must_match_configured_database_before_compose_mutation(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    command = harness.command()
    command[-1] = "other-database"

    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "CALL_LOG": _shell_path(harness.call_log),
            "LIST_CALLS": _shell_path(harness.list_calls),
            "PATH": os.pathsep.join([str(harness.mock_bin), os.environ.get("PATH", "")]),
        },
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=60,
    )

    assert result.returncode != 0
    assert "mismatch" in result.stderr.lower() or "does not match" in result.stderr.lower()
    assert " up " not in f" {harness.calls()} "
    assert " stop " not in f" {harness.calls()} "
    _assert_no_database_mutation(harness.calls())


def test_database_url_must_identify_the_confirmed_postgres_database(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    env_file = harness.target / "deploy" / ".env"
    env_file.write_text(
        "DATABASE_URL=postgresql://runtime@postgres:5432/other_db\n"
        "POSTGRES_DB=agomtradepro\n"
        "POSTGRES_USER=agomtradepro\n",
        encoding="utf-8",
    )

    result = harness.run()

    assert result.returncode != 0
    assert "does not match" in result.stderr.lower()
    assert harness.calls() == ""


def test_external_postgres_authority_is_rejected_without_echoing_credentials(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    env_file = harness.target / "deploy" / ".env"
    env_file.write_text(
        "DATABASE_URL=postgresql://runtime:dummy-password@external.example:5432/agomtradepro\n"
        "POSTGRES_DB=agomtradepro\n"
        "POSTGRES_USER=agomtradepro\n",
        encoding="utf-8",
    )

    result = harness.run()

    assert result.returncode != 0
    assert "Compose PostgreSQL service" in result.stderr
    assert "dummy-password" not in result.stderr
    assert harness.calls() == ""


def test_runtime_database_mismatch_is_rejected_before_stopping_writers(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)

    result = harness.run(RUNTIME_DB="wrong-runtime-database")

    assert result.returncode != 0
    assert "runtime" in result.stderr.lower()
    assert " stop " not in f" {harness.calls()} "
    _assert_no_database_mutation(harness.calls())


def test_failed_rollback_snapshot_preflight_preserves_database_for_manual_recovery(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)

    result = harness.run(ROLLBACK_LIST_STATUS="17")
    call_log = harness.calls()

    assert result.returncode != 0
    assert "rollback" in result.stderr.lower()
    assert " stop web " in f" {call_log} "
    assert " pg_dump " in f" {call_log} "
    assert " start web " not in f" {call_log} "
    assert "may remain stopped" in result.stderr.lower()
    _assert_no_database_mutation(call_log)


def test_pg_dump_failure_prevents_database_deletion_and_leaves_service_recovery_manual(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)

    result = harness.run(PG_DUMP_STATUS="17")
    call_log = harness.calls()

    assert result.returncode != 0
    assert "rollback" in result.stderr.lower()
    assert " stop web " in f" {call_log} "
    assert " pg_dump " in f" {call_log} "
    assert " start web " not in f" {call_log} "
    assert "may remain stopped" in result.stderr.lower()
    _assert_no_database_mutation(call_log)


def test_failed_writer_stop_prevents_rollback_dump_and_database_deletion(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)

    result = harness.run(STOP_STATUS="17")
    call_log = harness.calls()

    assert result.returncode != 0
    assert "stop may be partial" in result.stderr.lower()
    assert " stop web " in f" {call_log} "
    assert " pg_dump " not in f" {call_log} "
    assert " start web " not in f" {call_log} "
    _assert_no_database_mutation(call_log)


def test_unreadable_input_archive_is_rejected_before_stopping_writers(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)

    result = harness.run(INPUT_LIST_STATUS="17")
    call_log = harness.calls()

    assert result.returncode != 0
    assert "pg_restore --list" in result.stderr
    assert " up " not in f" {call_log} "
    assert " stop web " not in f" {call_log} "
    assert " pg_dump " not in f" {call_log} "
    _assert_no_database_mutation(call_log)


def test_verified_rollback_snapshot_precedes_drop_and_restore_uses_staged_archive(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    original_archive = b"verified-postgres-archive\n"

    result = harness.run(MUTATE_SOURCE_ON_INPUT_PREFLIGHT=_shell_path(harness.archive))
    call_log = harness.calls()

    assert result.returncode == 0, result.stderr
    assert "Restore completed" in result.stdout
    assert "list_input:verified-postgres-archive" in call_log
    assert "pre-restore" in result.stdout
    assert "list_input:verified-current-target-dump" in call_log
    assert "dropdb" in call_log
    assert "createdb" in call_log
    assert "pg_restore -U" in call_log
    assert call_log.index(" stop web ") < call_log.index(" pg_dump ")
    assert call_log.index(" pg_dump ") < call_log.index("list_input:verified-current-target-dump")
    assert call_log.index("list_input:verified-current-target-dump") < call_log.rindex(" dropdb ")
    assert call_log.rindex(" dropdb ") < call_log.index(" createdb ")
    assert call_log.index(" createdb ") < call_log.index("pg_restore -U")
    assert harness.archive.read_bytes() != original_archive
    rollback_archives = list((harness.backup / "database").glob("pre-restore-*.dump"))
    assert len(rollback_archives) == 1
    assert rollback_archives[0].stat().st_size > 0
    assert rollback_archives[0].with_suffix(".dump.sha256").is_file()


@pytest.mark.skipif(BASH_PATH is None, reason="Bash is unavailable for line-numbered xtrace")
def test_harness_can_run_with_bash_line_numbered_xtrace(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    env = os.environ.copy()
    env["GOV05_BASH_TRACE"] = "1"
    env["PS4"] = "+${BASH_SOURCE[0]}:${LINENO}: "

    result = subprocess.run(
        harness.command(bash_trace=True),
        cwd=REPO_ROOT,
        env={
            **env,
            "CALL_LOG": _shell_path(harness.call_log),
            "LIST_CALLS": _shell_path(harness.list_calls),
            "PATH": os.pathsep.join([str(harness.mock_bin), os.environ.get("PATH", "")]),
        },
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert ":" in result.stderr
    assert "Restore completed" in result.stdout
