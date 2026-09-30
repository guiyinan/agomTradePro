#!/usr/bin/env python3
"""Create or reuse PostgreSQL admin, runtime, and migrator credentials."""

from __future__ import annotations

import argparse
import os
import re
import secrets
import tempfile
from pathlib import Path
from urllib.parse import quote

_RUNTIME_PASSWORD_KEY = "AGOMTRADEPRO_RUNTIME_PASSWORD"
_MIGRATOR_PASSWORD_KEY = "AGOMTRADEPRO_MIGRATOR_PASSWORD"
_ADMIN_PASSWORD_KEY = "POSTGRES_PASSWORD"
_PLACEHOLDER_PREFIXES = (
    "replace-with",
    "change-this",
    "your-password",
    "password",
    "secret",
)


def _read_env_file(path: Path) -> dict[str, str]:
    """Read simple KEY=VALUE entries without evaluating shell syntax."""

    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _is_valid_password(value: str) -> bool:
    """Return whether a role password meets the URL-safe bootstrap contract."""

    if len(value) < 32 or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        return False
    return not _is_placeholder(value)


def _is_placeholder(value: str) -> bool:
    """Return whether a configured password is a known example value."""

    normalized = value.casefold()
    return normalized.startswith(_PLACEHOLDER_PREFIXES) or normalized in {
        "changeme",
        "example",
        "placeholder",
    }


def _existing_password(key: str, *value_sets: dict[str, str]) -> str | None:
    """Select the first valid saved password from newest to oldest settings."""

    for values in value_sets:
        candidate = values.get(key, "")
        if _is_valid_password(candidate):
            return candidate
    return None


def _generate_password() -> str:
    """Generate a bootstrap-compatible URL-safe password."""

    candidate = secrets.token_urlsafe(36)
    if not _is_valid_password(candidate):
        raise RuntimeError("generated role password did not meet the safety contract")
    return candidate


def _upsert_env_file(path: Path, updates: dict[str, str]) -> None:
    """Write selected environment keys while preserving unrelated settings."""

    path.parent.mkdir(parents=True, exist_ok=True)
    original_lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = set(updates)
    result: list[str] = []
    for line in original_lines:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key not in updates:
            result.append(line)
        elif key in remaining:
            result.append(f"{key}={updates[key]}")
            remaining.remove(key)
    result.extend(f"{key}={updates[key]}" for key in updates if key in remaining)
    content = "\n".join(result) + "\n"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def ensure_vps_postgres_role_env(env_path: Path, secrets_path: Path) -> None:
    """Persist admin and distinct split-role credentials in both env files."""

    env_values = _read_env_file(env_path)
    secrets_values = _read_env_file(secrets_path)
    database_name = env_values.get("POSTGRES_DB", "").strip()
    if not database_name:
        raise ValueError("POSTGRES_DB must be configured before preparing role URLs")

    admin_password = (
        _existing_password(_ADMIN_PASSWORD_KEY, env_values, secrets_values) or _generate_password()
    )
    runtime_password = _existing_password(_RUNTIME_PASSWORD_KEY, env_values, secrets_values)
    if runtime_password is None or runtime_password == admin_password:
        runtime_password = _generate_password()
        while runtime_password == admin_password:
            runtime_password = _generate_password()
    migrator_password = _existing_password(_MIGRATOR_PASSWORD_KEY, env_values, secrets_values)
    if migrator_password is None or migrator_password in {
        admin_password,
        runtime_password,
    }:
        migrator_password = _generate_password()
        while migrator_password in {admin_password, runtime_password}:
            migrator_password = _generate_password()

    encoded_database_name = quote(database_name, safe="")
    runtime_url = (
        f"postgresql://agomtradepro_runtime:{runtime_password}"
        f"@postgres:5432/{encoded_database_name}"
    )
    migrator_url = (
        f"postgresql://agomtradepro_migrator:{migrator_password}"
        f"@postgres:5432/{encoded_database_name}"
    )
    updates = {
        _ADMIN_PASSWORD_KEY: admin_password,
        _RUNTIME_PASSWORD_KEY: runtime_password,
        _MIGRATOR_PASSWORD_KEY: migrator_password,
        "DATABASE_URL": runtime_url,
        "MIGRATOR_DATABASE_URL": migrator_url,
    }
    _upsert_env_file(env_path, updates)
    _upsert_env_file(secrets_path, updates)


def main(argv: list[str] | None = None) -> int:
    """Prepare role credentials and URLs for VPS Compose deployments."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--secrets-file", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        ensure_vps_postgres_role_env(arguments.env_file, arguments.secrets_file)
    except (OSError, ValueError, RuntimeError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
