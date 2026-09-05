"""Production ASGI database connection policy contracts."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path


def test_production_asgi_disables_persistent_database_connections(monkeypatch) -> None:
    """An environment override cannot retain request-scoped ASGI connections."""

    monkeypatch.setenv(
        "SECRET_KEY",
        "A7mQ2vN9kR4sT8uW3yZ6bC1dE5fG0hJ7pL2nS9xV4qK8rM6tY3",
    )
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://agomtradepro:test@localhost:5432/agomtradepro",
    )
    monkeypatch.setenv("DB_CONN_MAX_AGE", "600")
    sys.modules.pop("core.settings.production", None)

    try:
        production = importlib.import_module("core.settings.production")
        assert production.DATABASES["default"]["CONN_MAX_AGE"] == 0
    finally:
        sys.modules.pop("core.settings.production", None)


def test_environment_example_does_not_advertise_persistent_asgi_connections() -> None:
    """Operators must not be invited to restore the unsafe production setting."""

    env_example = Path(__file__).resolve().parents[2] / ".env.example"
    content = env_example.read_text(encoding="utf-8")

    assert "DB_CONN_MAX_AGE=" not in content
    assert "Daphne/ASGI" in content
