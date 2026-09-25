"""Deployment contract for the scheduled System Audit authority renewal."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
COMPOSE_PATH = ROOT / "docker" / "docker-compose.vps.yml"
DEFAULT_REQUEST_PATH = "/app/var/system-audit-authority-renewal.json"


def test_web_and_default_worker_receive_the_persistent_renewal_request_path() -> None:
    """The guard must be able to read its bounded request after every image update."""

    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    services = compose["services"]

    for service_name in ("web", "celery_worker"):
        service = services[service_name]
        environment = service["environment"]
        configured = environment["AGOM_SYSTEM_AUDIT_RENEWAL_REQUEST_PATH"]
        assert configured == (
            "${AGOM_SYSTEM_AUDIT_RENEWAL_REQUEST_PATH:-" f"{DEFAULT_REQUEST_PATH}" + "}"
        )
        assert any(volume == "var_data:/app/var" for volume in service["volumes"])
