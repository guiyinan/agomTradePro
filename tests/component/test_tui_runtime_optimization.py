"""Focused regression tests for the optimized TUI runtime path."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.terminal.application.tui_metadata import _tui_metadata_schema_validator
from apps.terminal.application.tui_operator_services import _navigation_badges
from apps.terminal.application.tui_workbench import TuiWorkbenchService
from apps.terminal.infrastructure.tui_metadata_repository import (
    PublishedTuiMetadataRepository,
    get_tui_metadata_repository,
)


@pytest.mark.django_db
def test_tui_bootstrap_returns_catalog_and_screen_with_server_timing(client) -> None:
    user = get_user_model().objects.create_user(
        username="tui-bootstrap-user",
        password="bootstrap-pass",
    )
    client.force_login(user)

    response = client.get("/api/tui/bootstrap/?screen_key=command-center.overview")

    assert response.status_code == 200
    assert response.json()["contract"] == "tui-bootstrap.v1"
    assert response.json()["catalog"]["default_screen"]
    assert response.json()["screen"]["screen"]["key"] == "command-center.overview"
    assert response["Server-Timing"].startswith("tui_bootstrap;dur=")


@pytest.mark.django_db
def test_tui_bootstrap_falls_back_for_stale_screen(client) -> None:
    user = get_user_model().objects.create_user(
        username="tui-bootstrap-fallback-user",
        password="bootstrap-pass",
    )
    client.force_login(user)

    response = client.get("/api/tui/bootstrap/?screen_key=removed.screen")

    assert response.status_code == 200
    payload = response.json()
    assert payload["requested_screen"] == "removed.screen"
    assert payload["resolved_screen"] == payload["catalog"]["default_screen"]
    assert payload["restored"] is False


@pytest.mark.django_db
def test_runtime_metadata_cache_is_scoped_by_source_path(tmp_path: Path) -> None:
    cache.clear()
    source = (
        Path(settings.BASE_DIR)
        / "config"
        / "tui"
        / "published"
        / "tui_operation_graph.published.json"
    )
    copied = tmp_path / "published.json"
    copied.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    repository = PublishedTuiMetadataRepository(published_path=copied)

    with patch.object(
        repository,
        "_load_published_file",
        wraps=repository._load_published_file,
    ) as loader:
        first = repository.load_published("isolated-source")
        second = repository.load_published("isolated-source")

    assert first["version"] == second["version"]
    assert loader.call_count == 1


def test_json_schema_validator_is_compiled_once() -> None:
    _tui_metadata_schema_validator.cache_clear()
    assert _tui_metadata_schema_validator() is _tui_metadata_schema_validator()


def test_operator_navigation_badges_are_compact_and_screen_scoped() -> None:
    badges = _navigation_badges(
        [
            {"severity": "blocked", "target_screen": "runtime"},
            {"severity": "warning", "target_screen": "runtime"},
            {"severity": "ok", "target_screen": "ignored"},
        ]
    )

    assert badges == {
        "counts_by_screen": {
            "runtime": {"blocked_count": 1, "warning_count": 1},
        }
    }


@pytest.mark.django_db
def test_warm_catalog_stays_within_three_query_budget() -> None:
    user = get_user_model().objects.create_user(username="tui-query-budget")
    service = TuiWorkbenchService(metadata_repository=get_tui_metadata_repository())
    service.get_catalog(user=user)

    with CaptureQueriesContext(connection) as queries:
        payload = TuiWorkbenchService(
            metadata_repository=get_tui_metadata_repository()
        ).get_catalog(user=user)

    assert payload["default_screen"]
    assert len(queries) <= 3
