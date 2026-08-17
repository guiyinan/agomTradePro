"""Static regression tests for production Web liveness recovery."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_vps_compose_uses_self_recovering_web_healthcheck():
    compose = (REPO_ROOT / "docker" / "docker-compose.vps.yml").read_text(encoding="utf-8")

    assert "sh docker/healthcheck-web.sh" in compose
    assert "WEB_HEALTH_SELF_TERMINATE_AFTER_FAILURES" in compose


def test_healthcheck_only_terminates_daphne_after_repeated_failures():
    script = (REPO_ROOT / "docker" / "healthcheck-web.sh").read_text(encoding="utf-8")

    assert "WEB_HEALTH_SELF_TERMINATE_AFTER_FAILURES" in script
    assert "core.asgi:application" in script
    assert "kill -TERM" in script
    assert "curl -fsS" in script
