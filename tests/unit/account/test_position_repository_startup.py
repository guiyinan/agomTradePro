"""Cold-start Account repository imports under the reduced Data Center settings."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_position_repository_startup_without_signal_models() -> None:
    """Use the exact slim settings module without adding or removing installed apps."""

    code = """
import sys

import django
from django.apps import apps
from django.conf import settings

configured_apps = tuple(settings.INSTALLED_APPS)
assert "apps.signal" not in configured_apps

django.setup()

from apps.account.infrastructure.position_repository import PositionRepository
from core.integration.owned_signal_asset_code import get_owned_signal_asset_code

assert tuple(settings.INSTALLED_APPS) == configured_apps
assert not apps.is_installed("apps.signal")
assert PositionRepository.__name__ == "PositionRepository"
assert get_owned_signal_asset_code(signal_id=7, user_id=11) is None
signal_orm_modules = [
    module_name
    for module_name in sys.modules
    if module_name.startswith("apps.signal.infrastructure.")
    and (module_name.endswith(".models") or module_name.endswith("_models"))
]
assert not signal_orm_modules, signal_orm_modules
"""
    environment = os.environ.copy()
    environment["DJANGO_SETTINGS_MODULE"] = "tests.settings_data_center_sync_identity"
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[3],
        env=environment,
        capture_output=True,
        check=False,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stderr
