"""Protect pytest's explicit early import of the authority-clock plugin."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_explicit_plugin_startup_captures_source_without_database_connection(
    tmp_path: Path,
) -> None:
    """Protect early -p loading and source-name capture without a DB connection."""

    candidate_root = Path(__file__).resolve().parents[2]
    probe_root = tmp_path / "pytest-startup-probe"
    probe_root.mkdir()
    source_name = str(probe_root / "missing-parent" / "source_only.sqlite3")
    (probe_root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    database_settings: dict[str, object] = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": source_name,
            "TEST": {"NAME": "test_only.sqlite3"},
        }
    }
    settings_source = (
        "SECRET_KEY = 'startup-only'\n"
        "INSTALLED_APPS = []\n"
        f"DATABASES = {database_settings!r}\n"
    )
    (probe_root / "pg_startup_settings.py").write_text(settings_source, encoding="utf-8")
    (probe_root / "startup_deny_database_plugin.py").write_text(
        "import pytest\n"
        "@pytest.hookimpl(trylast=True)\n"
        "def pytest_sessionstart(session):\n"
        "    del session\n"
        "    from django.db.backends.base.base import BaseDatabaseWrapper\n"
        "    def deny_connection(self):\n"
        "        raise AssertionError('database connection is forbidden in startup probe')\n"
        "    BaseDatabaseWrapper.ensure_connection = deny_connection\n",
        encoding="utf-8",
    )
    probe_test = probe_root / "test_startup_probe.py"
    probe_test.write_text(
        "from django.apps import apps\n"
        "from django.conf import settings\n"
        "from django.db import connection\n"
        "from tests.support import account_authority_generation_flush as clock_plugin\n"
        "from tests.support import native_postgres_database as native_database\n"
        "def test_real_plugin_startup_and_source_name_capture():\n"
        "    assert apps.ready\n"
        f"    assert clock_plugin._SOURCE_DATABASE_NAME == {source_name!r}\n"
        f"    assert native_database._DEFAULT_SOURCE_DATABASE_NAME == {source_name!r}\n"
        "    settings.DATABASES['default']['NAME'] = 'test_only.sqlite3'\n"
        f"    assert clock_plugin._SOURCE_DATABASE_NAME == {source_name!r}\n"
        f"    assert native_database._DEFAULT_SOURCE_DATABASE_NAME == {source_name!r}\n"
        "    assert connection.connection is None\n"
        "    print('STARTUP_IMPORT_AND_SOURCE_PIN_OK')\n",
        encoding="utf-8",
    )

    def run_probe(package_root: Path) -> subprocess.CompletedProcess[str]:
        """Run real pytest with the CI -p order and plugin autoload disabled."""

        env = os.environ.copy()
        python_paths = [str(probe_root), str(package_root)]
        existing_pythonpath = env.get("PYTHONPATH")
        if existing_pythonpath:
            python_paths.append(existing_pythonpath)
        env.update(
            {
                "DJANGO_SETTINGS_MODULE": "pg_startup_settings",
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                "PYTHONPATH": os.pathsep.join(python_paths),
            }
        )
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "pytest_django.plugin",
            "-p",
            "tests.support.account_authority_generation_flush",
            "-p",
            "startup_deny_database_plugin",
            "-c",
            str(probe_root / "pytest.ini"),
            "--confcutdir",
            str(probe_root),
            "-q",
            "-s",
            str(probe_test),
        ]
        return subprocess.run(
            command,
            cwd=probe_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    corrected = run_probe(candidate_root)
    assert corrected.returncode == 0, (
        f"Corrected plugin startup failed. stdout={corrected.stdout}\n" f"stderr={corrected.stderr}"
    )
    assert "STARTUP_IMPORT_AND_SOURCE_PIN_OK" in corrected.stdout
    assert not (probe_root / "missing-parent").exists()
    assert not (probe_root / "test_only.sqlite3").exists()
