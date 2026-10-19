"""Canonical isolated universe-config input for the real M5 owner read."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from .universe_config_guard import require_m5_universe_fixture_environment

_UNIVERSE_CONFIG_PATH = "/api/data-center/production-coverage/universe/"
_SYNTHETIC_UNIVERSE_CONFIG: dict[str, object] = {
    "universe_id": "m5-synthetic-universe",
    "asset_type": "stock",
    "exchanges": ["SZSE"],
    "include_inactive": False,
    "min_active_asset_count": 1,
    "min_star_market_count": 0,
    "min_chinext_count": 1,
    "min_bse_count": 0,
    "description": "Synthetic M5 fixture only; not production coverage authority.",
}


@pytest.fixture(scope="module")
def m5_synthetic_universe_config(request: pytest.FixtureRequest, base_url: str) -> None:
    """Seed via the typed admin PUT, verify GET, then leave the disposable value."""

    if os.environ.get("AGOM_M5_SYNTHETIC_UNIVERSE") != "1":
        return
    if base_url.rstrip("/") != os.environ.get("AGOM_M5_UNIVERSE_BASE_URL", "").strip():
        pytest.fail("M5 universe fixture base URL differs from its guarded server URL")
    from django.conf import settings

    try:
        require_m5_universe_fixture_environment(databases=settings.DATABASES)
    except ValueError as exc:
        pytest.fail(str(exc))

    request.getfixturevalue("django_db_setup")
    blocker = request.getfixturevalue("django_db_blocker")

    def write_and_verify_universe_config() -> None:
        from django.contrib.auth import get_user_model
        from django.db import close_old_connections, connections
        from rest_framework.test import APIClient

        from tests.playwright.config.test_config import config

        with blocker.unblock():
            try:
                close_old_connections()
                admin_user = get_user_model().objects.get(
                    username=config.admin_username,
                    is_active=True,
                    is_staff=True,
                    is_superuser=True,
                )
                client = APIClient()
                client.force_authenticate(user=admin_user)

                put_response = client.put(
                    _UNIVERSE_CONFIG_PATH,
                    _SYNTHETIC_UNIVERSE_CONFIG,
                    format="json",
                )
                if put_response.status_code != 200:
                    pytest.fail("canonical universe-config admin PUT did not return HTTP 200")
                if not put_response["Content-Type"].startswith("application/json"):
                    pytest.fail("canonical universe-config PUT did not return JSON")
                updated: object = put_response.json()
                if updated != _SYNTHETIC_UNIVERSE_CONFIG:
                    pytest.fail("canonical universe-config PUT did not preserve the typed fixture")

                get_response = client.get(_UNIVERSE_CONFIG_PATH)
                if get_response.status_code != 200:
                    pytest.fail("canonical universe-config GET did not return HTTP 200")
                if not get_response["Content-Type"].startswith("application/json"):
                    pytest.fail("canonical universe-config GET did not return JSON")
                read_back: object = get_response.json()
                if read_back != updated:
                    pytest.fail("canonical universe-config GET differs from its PUT response")
            finally:
                connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(write_and_verify_universe_config).result()
