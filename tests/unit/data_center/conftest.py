"""Test-isolation guards for the data_center unit suite.

Several tests in this suite monkeypatch
``apps.data_center.infrastructure.legacy_sdk_bridge.get_akshare_module``.
The gateway modules below bind that name at import time via
``from ...legacy_sdk_bridge import get_akshare_module`` and are themselves
imported lazily inside application code and test bodies. If such a module is
imported for the first time while the monkeypatch is active, it captures the
fake callable permanently (the module stays in ``sys.modules``), and every
later test that needs the real binding fails in an order-dependent way.

Importing the modules once, before any test runs, pins the real binding and
keeps the suite order-independent.
"""

import pytest

_PATCHABLE_AKSHARE_SEAM_MODULES = (
    "apps.data_center.infrastructure.gateways.akshare_eastmoney_gateway",
    "apps.data_center.infrastructure.gateways.akshare_general_gateway",
)


@pytest.fixture(autouse=True, scope="session")
def _pin_akshare_seam_modules_before_patching() -> None:
    """Eagerly import modules that bind the patchable akshare seam."""
    import importlib

    for module_name in _PATCHABLE_AKSHARE_SEAM_MODULES:
        importlib.import_module(module_name)
