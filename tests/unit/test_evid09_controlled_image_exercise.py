"""Fail-closed source contract for the exact EVID-09 manual image entry."""

from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "evid09-controlled-image-exercise.sh"


def test_default_mode_has_no_mutation_and_missing_prerequisites_deny() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'MODE="${1:---dry-run}"' in source
    dry_run = source.split('if [[ "$MODE" == --dry-run ]]; then', 1)[1].split(
        '[[ "${EVID09_OWNER_ACTION_TOKEN:-}"', 1
    )[0]
    assert "docker tag" not in dry_run
    assert "install -m 600" not in dry_run
    assert "docker compose" not in dry_run
    assert '[[ "$READY" == 1 ]] || exit 1' in dry_run
    assert 'echo "DENY: target original tag missing"' in dry_run
    assert 'echo "DENY: target protected-query env missing"' in dry_run


def test_repair_verifies_exact_alias_and_approved_secret_safe_source() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "ALIAS_TAG=agomtradepro-evid09-compatible-rollback:20260914021633" in source
    assert (
        "TARGET_ID=sha256:f5647b6d4a17c81963a41dd4d66dee70ccfc4b18e881b368db4b89dda7bf86fd"
        in source
    )
    assert 'require_image "$ALIAS_TAG" "$TARGET_ID" "$TARGET_COMMIT"' in source
    assert source.index('require_image "$ALIAS_TAG"') < source.index(
        'docker tag "$ALIAS_TAG" "$TARGET_TAG"'
    )
    assert 'require_image "$TARGET_TAG" "$TARGET_ID" "$TARGET_COMMIT"' in source
    assert 'install -m 600 "$CURRENT/deploy/prometheus-query.env"' in source
    assert (
        'cmp -s "$CURRENT/deploy/prometheus-query.env" "$TARGET/deploy/prometheus-query.env"'
        in source
    )
    assert 'cat "$CURRENT/deploy/prometheus-query.env"' not in source


def test_manual_entry_cannot_switch_web_or_touch_database() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert (
        'deny "live web switch disabled until independently captured fresh preservation' in source
    )
    for forbidden in (
        "docker compose down",
        "--remove-orphans",
        "docker volume rm",
        "pg_restore",
        "DROP DATABASE",
        "publish-tui-release.sh",
    ):
        assert forbidden not in source


def test_exact_current_target_forward_and_retained_backup_are_checked() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert '[[ "$(readlink -f "$ROOT/current")" == "$CURRENT" ]]' in source
    assert 'require_manifest "$CURRENT/.agom-release-manifest.json"' in source
    assert 'require_manifest "$TARGET/.agom-release-manifest.json"' in source
    assert 'require_image "$CURRENT_TAG" "$CURRENT_ID" "$CURRENT_COMMIT"' in source
    assert '[[ -f "$BACKUP" && "$(sha256sum "$BACKUP"' in source
    assert '[[ "$(docker inspect agomtradepro-web-1 --format' in source
