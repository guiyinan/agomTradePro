"""Source contract for exact Web-only target interval and manual recovery."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/evid09_web_only_image_exercise.sh"


def test_only_exact_web_service_can_be_recreated() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'MODE="${1:---dry-run}"' in source
    assert "--dry-run|--raw-observation-dry-run|--internal-exercise|--forward-recover" in source
    assert (
        "docker compose -p agomtradepro -f docker/docker-compose.vps.yml --env-file deploy/.env"
        in source
    )
    assert "up -d --no-deps --no-build --force-recreate web" in source
    assert 'compose_web "$TARGET" up' in source
    assert 'compose_web "$CURRENT" up' in source
    for forbidden in (
        "docker compose down",
        "--remove-orphans",
        "docker volume rm",
        "pg_restore",
        "DROP DATABASE",
        "publish-tui-release.sh",
        "ln -s",
        "mv -Tf",
        "up -d redis",
        "up -d postgres",
        "up -d caddy",
    ):
        assert forbidden not in source


def test_default_is_dry_run_and_live_requires_fresh_operator_gate() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    dry_run = source.split('if [[ "$MODE" == --dry-run ]]; then', 1)[1].split(
        '[[ "${EVID09_OWNER_ACTION_TOKEN:-}"', 1
    )[0]

    assert 'compose_web "$TARGET" up' not in dry_run
    assert "DRY_RUN_ONLY" in dry_run
    assert '[[ "${EVID09_INTERNAL_GATE_SHA256:-}" =~ ^[0-9a-f]{64}$ ]]' in source
    assert '[[ "${EVID09_TUI_RESET_ACCEPTED:-}" == true ]]' in source
    assert '[[ "${EVID09_DOWNTIME_ACCEPTED:-}" == true ]]' in source


def test_direct_live_shell_denies_existing_raw_tui_observation_before_switch() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    live = source.split("# The operator-side entry sets this only after it ran", 1)[1]

    assert (
        'raw_observation_empty || deny "active TUI-02 raw observation or query unavailable"' in live
    )
    assert live.index("raw_observation_empty || deny") < live.index("NEED_RECOVERY=1")
    assert live.index("raw_observation_empty || deny") < live.index('compose_web "$TARGET" up')
    assert "web_to_tui_migration_events_total" in source
    assert "https://demo.agomtrade.pro/internal/prometheus/api/v1/query?" in source
    assert "PROMETHEUS_QUERY_PASSWORD" in source


def test_raw_observation_dry_run_has_no_owner_token_or_recreate() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    before_token = source.split('[[ "${EVID09_OWNER_ACTION_TOKEN:-}"', 1)[0]
    dry = before_token.split('if [[ "$MODE" == --raw-observation-dry-run ]]; then', 1)[1]

    assert (
        'raw_observation_empty || deny "active TUI-02 raw observation or query unavailable"' in dry
    )
    assert "RAW_OBSERVATION_DRY_RUN no_container_changed=true" in dry
    assert 'compose_web "$TARGET" up' not in dry
    assert "--raw-observation-dry-run" in source


def test_isolated_direct_shell_denies_nonempty_raw_vector_without_recreate() -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("Bash runtime unavailable")
    source = _isolated_source()
    source = source.replace(
        "raw_observation_empty() { :; }",
        "raw_observation_empty() { echo RAW_NONEMPTY_MARKER; return 1; }",
    )
    result = subprocess.run(
        [bash, "-s", "--", "--internal-exercise"],
        input=source.encode("utf-8"),
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode != 0
    assert "RAW_NONEMPTY_MARKER" in result.stdout.decode("utf-8")
    assert "TARGET_READY" not in result.stdout.decode("utf-8")
    assert "active TUI-02 raw observation" in result.stderr.decode("utf-8")


def test_interactive_target_interval_always_has_forward_recovery_trap() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    before_switch = source.split('compose_web "$TARGET" up', 1)[0]

    assert "NEED_RECOVERY=1\ntrap exit_recover EXIT" in before_switch
    assert "IFS= read -r -t 180 operator_instruction" in source
    assert '[[ "$operator_instruction" == FORWARD_RECOVER ]]' in source
    assert "if forward_recover; then" in source
    assert "RECOVERY_TRAP_FAILED" in source
    assert source.rindex('forward_recover || deny "forward recovery failed"') < source.rindex(
        "NEED_RECOVERY=0"
    )


def test_manual_recovery_only_requires_current_static_identity() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert (
        'if [[ "$MODE" != --forward-recover && "$MODE" != --forward-recover-dry-run ]]; then\n'
        "  require_target_static" in source
    )
    assert 'if [[ "$MODE" == --forward-recover ]]; then' in source
    assert 'forward_recover || deny "independent forward recovery failed"' in source
    assert '[[ "$(readlink -f "$ROOT/current")" == "$CURRENT" ]]' in source
    assert (
        "CURRENT_MANIFEST_SHA=b0b58b749ef1488695bb32e158f5d2ead8d83c90d5c5050e1e69d3f5a88b6bb6"
        in source
    )
    assert (
        "TARGET_MANIFEST_SHA=b5fcfa71f5635fa95e8d24b4822894e5f4ce4bf0b4c99ee8e3fa5be5cd154167"
        in source
    )
    assert "BACKUP_SHA=0a1210ab4a5e3bd0d8cc2630ce6d3f3c421ab1c28d8b53c00fcc90ed16f7250a" in source


def test_automatic_and_manual_forward_recovery_share_one_read_only_lock() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    recovery = source.split("forward_recover()", 1)[1].split("exit_recover()", 1)[0]
    manual = source.split('if [[ "$MODE" == --forward-recover ]]; then', 1)[1].split(
        "# The operator-side entry", 1
    )[0]

    assert 'exec 9< "$CURRENT/.agom-release-manifest.json"' in recovery
    assert "flock -x -w 30 9" in recovery
    assert 'if [[ "$(web_image)" == "$CURRENT_ID"' in recovery
    assert 'forward_recover || deny "independent forward recovery failed"' in manual
    assert "already_current=true" not in manual


def test_recovery_lock_dry_run_is_available_without_live_owner_token() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "--forward-recover-dry-run" in source
    pre_token = source.split('[[ "${EVID09_OWNER_ACTION_TOKEN:-}"', 1)[0]
    assert 'if [[ "$MODE" == --forward-recover-dry-run ]]; then' in pre_token
    assert (
        'forward_recovery_lock_dry_run || deny "read-only recovery lock preflight failed"'
        in pre_token
    )
    preflight = source.split("forward_recovery_lock_dry_run()", 1)[1].split("forward_recover()", 1)[
        0
    ]
    assert 'exec 9< "$CURRENT/.agom-release-manifest.json"' in preflight
    assert "flock -x -w 30 9" in preflight
    assert 'compose_web "$CURRENT" up' not in preflight
    assert "FORWARD_RECOVERY_LOCK_DRY_RUN" in preflight


def test_isolated_recovery_lock_dry_run_never_recreates_web() -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("Bash runtime unavailable")
    source = SCRIPT.read_text(encoding="utf-8")
    marker = "\nrequire_current_static\n"
    assert source.count(marker) == 1
    mock = """
MOCK_DIR="$(mktemp -d -p /tmp evid09-recovery-lock-dry-XXXXXX)"
trap 'rm -f -- "$MOCK_DIR/.agom-release-manifest.json" "$MOCK_DIR/current"; rmdir -- "$MOCK_DIR"' EXIT
ROOT="$MOCK_DIR"
CURRENT="$MOCK_DIR"
touch "$CURRENT/.agom-release-manifest.json"
ln -s "$CURRENT" "$ROOT/current"
require_current_static() { :; }
require_image() { :; }
require_manifest() { :; }
web_image() { echo "$CURRENT_ID"; }
web_health() { echo healthy; }
web_manifest_sha() { echo "$CURRENT_MANIFEST_SHA"; }
web_started_at() { echo 2026-09-15T19:00:00Z; }
compose_web() { echo "RECREATE_SHOULD_NOT_HAPPEN"; return 1; }
"""
    driver = source.replace(marker, "\n" + mock + marker)
    result = subprocess.run(
        [bash, "-s", "--", "--forward-recover-dry-run"],
        input=driver.encode("utf-8"),
        capture_output=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8")
    output = result.stdout.decode("utf-8")
    assert "FORWARD_RECOVERY_LOCK_DRY_RUN" in output
    assert "RECREATE_SHOULD_NOT_HAPPEN" not in output


def test_two_isolated_recovery_processes_do_not_recreate_web_twice() -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("Bash runtime unavailable")
    source = SCRIPT.read_text(encoding="utf-8")
    start = source.index("forward_recover() (")
    finish = source.index("\nexit_recover() {", start)
    recovery = source[start:finish]
    driver = (
        """
set -euo pipefail
MOCK_DIR="$(mktemp -d -p /tmp evid09-forward-lock-XXXXXX)"
ROOT="$MOCK_DIR"
CURRENT="$MOCK_DIR"
CURRENT_ID=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
TARGET_ID=sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
CURRENT_MANIFEST_SHA=cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
touch "$CURRENT/.agom-release-manifest.json"
ln -s "$CURRENT" "$ROOT/current"
printf '%s' "$TARGET_ID" > "$MOCK_DIR/image"
web_image() { cat "$MOCK_DIR/image"; }
web_health() { echo healthy; }
web_manifest_sha() { echo "$CURRENT_MANIFEST_SHA"; }
web_started_at() { echo 2026-09-15T18:00:00Z; }
compose_web() { echo recreate >> "$MOCK_DIR/compose"; sleep 1; printf '%s' "$CURRENT_ID" > "$MOCK_DIR/image"; }
wait_web() { :; }
"""
        + recovery
        + """
(forward_recover > "$MOCK_DIR/a" 2>&1) & first=$!
(forward_recover > "$MOCK_DIR/b" 2>&1) & second=$!
if wait "$first"; then first_status=0; else first_status=$?; fi
if wait "$second"; then second_status=0; else second_status=$?; fi
trap 'rm -f -- "$MOCK_DIR/.agom-release-manifest.json" "$MOCK_DIR/current" "$MOCK_DIR/image" "$MOCK_DIR/compose" "$MOCK_DIR/a" "$MOCK_DIR/b"; rmdir -- "$MOCK_DIR"' EXIT
[[ "$first_status" == 0 && "$second_status" == 0 ]] || exit 1
printf 'recreates=%s\\n' "$(wc -l < "$MOCK_DIR/compose")"
cat "$MOCK_DIR/a" "$MOCK_DIR/b"
"""
    )

    result = subprocess.run(
        [bash, "-s"], input=driver.encode("utf-8"), capture_output=True, timeout=45, check=False
    )
    assert result.returncode == 0, result.stderr.decode("utf-8")
    assert "recreates=1" in result.stdout.decode("utf-8")
    assert result.stdout.decode("utf-8").count("FORWARD_RECOVERED ") == 2
    assert "already_current=true" in result.stdout.decode("utf-8")


def _isolated_source() -> str:
    """Override every Docker/filesystem helper before action, only in memory."""

    source = SCRIPT.read_text(encoding="utf-8")
    marker = "\nrequire_current_static\n"
    assert source.count(marker) == 1
    mock = """
EVID09_OWNER_ACTION_TOKEN=EVID09-891c40c57-6760c9aa-20260915
EVID09_INTERNAL_GATE_SHA256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
EVID09_TUI_RESET_ACCEPTED=true
EVID09_DOWNTIME_ACCEPTED=true
MOCK_IMAGE="$CURRENT_ID"
require_current_static() { :; }
require_target_static() { :; }
compose_web() { if [[ "$1" == "$TARGET" ]]; then MOCK_IMAGE="$TARGET_ID"; else MOCK_IMAGE="$CURRENT_ID"; fi; }
web_image() { echo "$MOCK_IMAGE"; }
web_health() { echo healthy; }
web_manifest_sha() { echo "$CURRENT_MANIFEST_SHA"; }
web_started_at() { echo 2026-09-15T17:00:00Z; }
wait_web() { :; }
forward_recover() { MOCK_IMAGE="$CURRENT_ID"; echo "FORWARD_RECOVERED image=$CURRENT_ID started_at=2026-09-15T17:00:01Z health=healthy"; }
raw_observation_empty() { :; }
"""
    return source.replace(marker, "\n" + mock + marker).replace(
        "read -r -t 180 operator_instruction", "read -r -t 10 operator_instruction"
    )


@pytest.mark.parametrize(("instruction", "expected_exit"), [(True, 0), (False, 1)])
def test_isolated_bash_fifo_control_or_timeout_always_recovers(
    instruction: bool, expected_exit: int
) -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("Bash runtime unavailable")
    process = subprocess.Popen(
        [bash, "-s", "--", "--internal-exercise"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(_isolated_source().encode("utf-8"))
    process.stdin.flush()
    process.stdin.close()
    first = process.stdout.readline().decode("utf-8")
    if not first:
        assert process.stderr is not None
        pytest.fail(
            f"mock Bash exited before target ready: {process.stderr.read().decode('utf-8')}"
        )
    assert first.startswith("TARGET_READY image=sha256:f5647b6d")
    if instruction:
        fifo = first.split(" fifo=", 1)[1].strip()
        assert re.fullmatch(r"/tmp/evid09-web-recovery-[A-Za-z0-9]{6}/recovery\.fifo", fifo)
        writer = subprocess.run(
            [bash, "-c", f'printf "%s\\n" FORWARD_RECOVER > "{fifo}"'],
            capture_output=True,
            timeout=15,
            check=False,
        )
        assert writer.returncode == 0, writer.stderr.decode("utf-8")
    rest = process.stdout.read().decode("utf-8")
    status = process.wait(timeout=30)
    assert process.stderr is not None
    assert (
        status == expected_exit
    ), f"mock Bash rest={rest} stderr={process.stderr.read().decode('utf-8')}"
    assert "FORWARD_RECOVERED image=sha256:554f816b" in rest
    assert "RECOVERY_TRAP_FAILED" not in rest
