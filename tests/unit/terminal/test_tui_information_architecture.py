from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from apps.terminal.application.tui_metadata import validate_tui_metadata
from apps.terminal.application.tui_workbench import TuiWorkbenchService
from apps.terminal.infrastructure.tui_information_architecture import (
    load_tui_information_architecture,
    screen_aliases,
)
from apps.terminal.infrastructure.tui_metadata_repository import (
    PublishedTuiMetadataRepository,
)

ROOT = Path(__file__).resolve().parents[3]
PUBLISHED_PATH = ROOT / "config" / "tui" / "published" / "tui_operation_graph.published.json"


class _StaticMetadataRepository:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def load_published(self, registry_key: str = "default") -> dict:
        del registry_key
        return self.payload


def _runtime_payload() -> dict:
    raw = json.loads(PUBLISHED_PATH.read_text(encoding="utf-8"))
    repository = PublishedTuiMetadataRepository(published_path=PUBLISHED_PATH)
    return repository._normalize_runtime_payload(validate_tui_metadata(raw))


def _catalog_screen_keys(catalog: dict) -> list[str]:
    return [
        screen["key"]
        for group in catalog["groups"]
        for module in group["modules"]
        for screen in module["screens"]
    ]


def test_tui_ia_registry_is_the_complete_screen_routing_source() -> None:
    registry = load_tui_information_architecture()
    aliases = screen_aliases(registry)

    assert [group["key"] for group in registry["groups"]] == ["daily", "research", "system"]
    assert len(registry["published_screens"]) == 12
    assert len(registry["runtime_screens"]) == 4
    assert len(registry["workflow"]) == 8
    assert sum(len(screen["sources"]) for screen in registry["published_screens"]) == 37
    assert (
        sum(len(screen.get("runtime_sources", [])) for screen in registry["published_screens"])
        + sum(len(screen["sources"]) for screen in registry["runtime_screens"])
        == 13
    )
    assert aliases["macro-regime.pulse"] == "macro-regime.overview"
    assert aliases["command-center.auto-advisor"] == "command-center.decision-flow"
    assert aliases["risk-center.overview"] == "macro-regime.strategy"
    assert aliases["realtime-monitor.alerts"] == "execution.audit"
    assert aliases["broker-execution.overview"] == "execution.accounts"
    assert aliases["broker-execution.audit"] == "execution.audit"
    assert aliases["ai-ops.user-quotas"] == "ai-ops.system-providers"
    assert aliases["capability-router.gateway"] == "capability-router.mcp-center"
    assert aliases["capability-router.admin-access"] == "capability-router.mcp-center"


def test_runtime_catalog_has_13_user_screens_and_16_admin_screens() -> None:
    payload = _runtime_payload()
    service = TuiWorkbenchService(metadata_repository=_StaticMetadataRepository(payload))
    user = SimpleNamespace(
        id=1,
        is_authenticated=True,
        is_staff=False,
        is_superuser=False,
        role="user",
    )
    admin = SimpleNamespace(
        id=2,
        is_authenticated=True,
        is_staff=True,
        is_superuser=True,
        role="admin",
    )

    user_screens = _catalog_screen_keys(service.get_catalog(user=user))
    admin_screens = _catalog_screen_keys(service.get_catalog(user=admin))

    assert len(user_screens) == 13
    assert len(admin_screens) == 16
    assert "api-library.data-center" not in user_screens
    assert "ai-ops.system-providers" not in user_screens
    assert "capability-router.mcp-center" not in user_screens
    assert admin_screens[-3:] == [
        "api-library.data-center",
        "capability-router.mcp-center",
        "ai-ops.system-providers",
    ]


def test_runtime_ia_is_idempotent_and_has_no_dangling_screen_references() -> None:
    raw = json.loads(PUBLISHED_PATH.read_text(encoding="utf-8"))
    repository = PublishedTuiMetadataRepository(published_path=PUBLISHED_PATH)
    normalized_once = repository._normalize_runtime_payload(validate_tui_metadata(raw))
    normalized_twice = repository._normalize_runtime_payload(validate_tui_metadata(normalized_once))

    assert normalized_twice == normalized_once
    screen_keys = {screen["key"] for screen in normalized_once["screens"]}
    action_keys = {action["key"] for action in normalized_once["actions"]}
    assert len(screen_keys) == 16
    assert all(action["screen_key"] in screen_keys for action in normalized_once["actions"])
    assert all(
        not panel.get("action_key") or panel["action_key"] in action_keys
        for screen in normalized_once["screens"]
        for panel in screen.get("dashboard_panels", [])
    )


def test_legacy_screen_keys_resolve_to_canonical_screens() -> None:
    payload = _runtime_payload()
    service = TuiWorkbenchService(metadata_repository=_StaticMetadataRepository(payload))
    user = SimpleNamespace(
        id=1,
        is_authenticated=True,
        is_staff=False,
        is_superuser=False,
        role="user",
    )
    admin = SimpleNamespace(
        id=2,
        is_authenticated=True,
        is_staff=True,
        is_superuser=True,
        role="admin",
    )

    assert service.get_screen("macro-regime.pulse", user=user)["screen"]["key"] == (
        "macro-regime.overview"
    )
    assert service.get_screen("capability-router.gateway", user=admin)["screen"]["key"] == (
        "capability-router.mcp-center"
    )


def test_published_screens_define_panel_and_action_density_contracts() -> None:
    payload = validate_tui_metadata(json.loads(PUBLISHED_PATH.read_text(encoding="utf-8")))

    for screen in payload["screens"]:
        p0_panels = [
            panel
            for panel in screen.get("dashboard_panels", [])
            if panel.get("user_priority") == "p0"
        ]
        if screen["key"] != "command-center.overview":
            assert len(p0_panels) <= 2
        assert screen["action_density"]["primary_operation_limit"] <= 12
        assert screen["action_density"]["task_group_limit"] == 6
        assert screen["user_experience"]["primary_task"]
        assert screen["user_experience"]["primary_outcome"]
