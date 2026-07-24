"""First-run environment bootstrap command contracts."""

from __future__ import annotations

from io import StringIO

from apps.setup_wizard.management.commands import bootstrap_local_env


def test_bootstrap_local_environment_reports_created_and_existing_values(monkeypatch) -> None:
    """First-run command forwards generation flags and reports every outcome."""
    calls: list[dict[str, bool]] = []

    def _bootstrap(**kwargs: bool) -> dict[str, bool]:
        calls.append(kwargs)
        return {
            "env_created": len(calls) == 1,
            "secret_key_generated": len(calls) == 1,
            "encryption_key_generated": False,
        }

    monkeypatch.setattr(
        bootstrap_local_env,
        "bootstrap_local_environment",
        _bootstrap,
    )
    first = bootstrap_local_env.Command(stdout=StringIO())
    first.handle(skip_secret_key=False, skip_encryption_key=True)
    assert calls[0] == {
        "generate_secret_key": True,
        "generate_encryption_key": False,
    }
    assert "Created .env" in first.stdout.getvalue()
    assert "already configured" in first.stdout.getvalue()

    second = bootstrap_local_env.Command(stdout=StringIO())
    second.handle(skip_secret_key=True, skip_encryption_key=False)
    assert "Local .env already exists" in second.stdout.getvalue()
