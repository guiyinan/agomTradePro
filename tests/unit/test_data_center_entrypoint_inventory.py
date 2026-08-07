"""Tests for the deterministic Data Center entrypoint inventory."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "data_center_entrypoint_inventory.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("data_center_entrypoint_inventory", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("Data Center entrypoint inventory script cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def inventory_payload() -> tuple[ModuleType, dict[str, object]]:
    """Build the repository-wide AST inventory once for this test module."""

    inventory = _load_script()
    return inventory, inventory.build_inventory()


def test_inventory_covers_every_governed_invocation_category(
    inventory_payload: tuple[ModuleType, dict[str, object]],
) -> None:
    inventory, payload = inventory_payload

    assert inventory.validate_inventory(payload) == []
    assert set(payload["counts"]["by_category"]) == inventory.REQUIRED_CATEGORIES
    assert set(payload["counts"]["by_status"]) == {
        "active_public",
        "adjacent_operational",
        "compatibility",
        "candidate-review",
    }


def test_inventory_preserves_unreviewed_discovery_and_evidence(
    inventory_payload: tuple[ModuleType, dict[str, object]],
) -> None:
    _inventory, first = inventory_payload

    ids = [entry["id"] for entry in first["entries"]]
    assert len(ids) == len(set(ids))
    assert all(entry["evidence"] for entry in first["entries"])
    assert all(
        entry["target"]
        for entry in first["entries"]
        if entry["category"]
        in {
            "beat_schedule",
            "celery_dispatch_edge",
            "celery_task",
            "dynamic_import_edge",
            "management_command_edge",
            "scheduler_writer",
        }
    )


def test_inventory_includes_internal_consumers_admin_and_config_compatibility(
    inventory_payload: tuple[ModuleType, dict[str, object]],
) -> None:
    """Prevent the unified inventory from regressing to external routes only."""

    _inventory, payload = inventory_payload
    entries = payload["entries"]
    entry_keys = {
        (
            entry["category"],
            entry["path"],
            entry["symbol"],
            entry["locator"],
        )
        for entry in entries
    }

    assert any(
        category == "application_consumer"
        and path == "apps/equity/infrastructure/fundamentals_repository.py"
        for category, path, _symbol, _locator in entry_keys
    )
    assert (
        "admin_surface",
        "apps/data_center/interface/admin.py",
        "ProviderConfigAdmin",
        "ProviderConfigModel",
    ) in entry_keys
    assert (
        "runtime_config_key",
        "governance/runtime_config_contracts.json",
        "data_center.provider.failover_tolerance",
        "consumer_cutover_in_progress",
    ) in entry_keys
    assert any(
        category == "system_settings_compatibility" and path == "core/encryption_readiness.py"
        for category, path, _symbol, _locator in entry_keys
    )
    assert any(
        category == "scheduler_writer"
        and path == "apps/macro/management/commands/setup_macro_daily_sync.py"
        for category, path, _symbol, _locator in entry_keys
    )
    assert (
        "orchestration_entry",
        "scripts/setup_celery_beat.py",
        "init_scheduler_defaults",
        "line:16",
    ) in entry_keys
    assert any(
        category == "management_command" and path == "core/management/commands/warmup_cache.py"
        for category, path, _symbol, _locator in entry_keys
    )
    assert any(
        entry["category"] == "script"
        and entry["path"] == "scripts/verify_postgres_backup_restore.py"
        and entry["status"] == "active_public"
        for entry in entries
    )


def test_inventory_expands_command_edges_and_publishes_full_task_targets(
    inventory_payload: tuple[ModuleType, dict[str, object]],
) -> None:
    """Keep second-order command and scheduler dispatch machine-verifiable."""

    _inventory, payload = inventory_payload
    entries = payload["entries"]
    scheduler_commands = {
        "setup_macro_daily_sync",
        "setup_equity_valuation_sync",
        "setup_decision_quote_refresh",
        "setup_workspace_snapshot_refresh",
        "setup_account_risk_tasks",
        "setup_auto_advisor_weekly_report",
        "setup_personal_readiness_daily",
        "setup_sentiment_refresh",
    }
    expanded = {
        entry["symbol"]
        for entry in entries
        if entry["category"] == "management_command_edge"
        and entry["path"] == "apps/task_monitor/management/commands/init_scheduler_defaults.py"
    }
    assert expanded == scheduler_commands
    assert all(
        entry["symbol"] != "dynamic-command"
        for entry in entries
        if entry["category"] == "management_command_edge"
    )
    bootstrap_edges = {
        entry["symbol"]
        for entry in entries
        if entry["category"] == "management_command_edge"
        and entry["path"] == "apps/account/management/commands/bootstrap_cold_start.py"
    }
    assert {
        "init_scheduler_defaults",
        "repair_decision_data_reliability",
        "sync_macro_data",
    } <= bootstrap_edges

    cleanup_task = next(
        entry
        for entry in entries
        if entry["category"] == "celery_task"
        and entry["path"] == "apps/task_monitor/application/tasks.py"
        and entry["symbol"] == "cleanup_old_task_records"
    )
    assert cleanup_task["locator"] == (
        "apps.task_monitor.application.tasks.cleanup_old_task_records"
    )
    assert cleanup_task["target"] == cleanup_task["locator"]

    retention_schedule = next(
        entry
        for entry in entries
        if entry["category"] == "beat_schedule"
        and entry["locator"] == "data-center-retention-preview-asset-master"
    )
    assert retention_schedule["target"] == (
        "apps.data_center.application.tasks.plan_retention_task"
    )

    valuation_writer_targets = {
        entry["target"]
        for entry in entries
        if entry["category"] == "scheduler_writer"
        and entry["path"] == "apps/equity/management/commands/setup_equity_valuation_sync.py"
    }
    assert valuation_writer_targets == {
        "apps.equity.application.tasks_valuation_sync.sync_validate_scan_equity_valuation_task",
        "apps.equity.application.tasks_valuation_sync.validate_equity_valuation_quality_task",
    }
    decision_quote_schedules = {
        entry["locator"]
        for entry in entries
        if entry["category"] == "scheduler_writer"
        and entry["path"] == "apps/data_center/management/commands/setup_decision_quote_refresh.py"
    }
    assert decision_quote_schedules == {
        "decision-quote-intraday-refresh",
        "decision-quote-post-close-refresh",
        "decision-quote-pre-readiness-refresh",
        "decision-quote-freshness-check",
    }


def test_inventory_links_http_sdk_mcp_and_tui_ingress_to_runtime_targets(
    inventory_payload: tuple[ModuleType, dict[str, object]],
) -> None:
    """Keep every user-facing ingress connected to its next governed hop."""

    _inventory, payload = inventory_payload
    entries = payload["entries"]

    comprehensive = next(
        entry
        for entry in entries
        if entry["category"] == "rest_url"
        and entry["path"] == "apps/equity/interface/comprehensive_valuation_actions.py"
        and entry["symbol"].endswith("comprehensive_valuation")
    )
    assert comprehensive["locator"] == "action:comprehensive-valuation:POST"
    assert comprehensive["target"].endswith(
        "::EquityComprehensiveValuationActionsMixin.comprehensive_valuation"
    )

    sdk_property = next(
        entry
        for entry in entries
        if entry["category"] == "sdk" and entry["symbol"] == "AgomTradeProClient.data_center"
    )
    assert sdk_property["target"] == "DataCenterModule"

    core_call = next(
        entry
        for entry in entries
        if entry["category"] == "mcp_tool" and entry["symbol"] == "agom_capability_call"
    )
    assert core_call["status"] == "active_public"
    assert core_call["target"] == "CapabilityDispatcher:data_center"
    legacy_registrar = next(
        entry
        for entry in entries
        if entry["category"] == "mcp_tool"
        and entry["path"] == "sdk/agomtradepro_mcp/server.py"
        and entry["symbol"] == "register_data_center_tools"
    )
    assert legacy_registrar["status"] == "compatibility"
    assert "false" in legacy_registrar["locator"].lower()

    tui_edges = {
        (entry["symbol"], entry["locator"], entry["target"])
        for entry in entries
        if entry["category"] == "terminal_tui"
    }
    assert (
        "macro-regime.overview",
        "data_center.market_thermometer",
        "/api/data-center/market-thermometer/current/",
    ) in tui_edges
    assert (
        "command-center.overview",
        "operator.home.data_task_summary",
        "/api/tui/operator/home/data_task_summary/",
    ) in tui_edges

    data_center_capabilities = [
        entry
        for entry in entries
        if entry["category"] == "capability_runtime"
        and entry["path"].startswith("sdk/agomtradepro_mcp/registry/modules/owners/data_center_")
    ]
    assert data_center_capabilities
    assert all(entry["status"] == "active_public" for entry in data_center_capabilities)
    assert all(entry["target"] for entry in data_center_capabilities)


def test_inventory_is_sorted_and_checked_manifest_remains_structurally_valid(
    inventory_payload: tuple[ModuleType, dict[str, object]],
) -> None:
    inventory, payload = inventory_payload
    entries = payload["entries"]
    assert entries == sorted(
        entries,
        key=lambda item: (
            item["category"],
            item["path"],
            item["symbol"],
            item["locator"],
        ),
    )
    checked = json.loads(
        (ROOT / "governance" / "data_center_entrypoints.json").read_text(encoding="utf-8")
    )
    assert inventory.validate_inventory(checked) == []


def _write_source(tmp_path: Path, relative_path: str, source: str) -> Path:
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def test_typed_task_aliases_and_celery_dispatch_edges_are_discovered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory = _load_script()
    _write_source(
        tmp_path,
        "apps/demo/application/tasks.py",
        """from shared.infrastructure.celery_typing import typed_shared_task as dc_task
from celery import current_app, signature

TASK_NAME = "apps.demo.application.tasks.refresh"

@dc_task(name=TASK_NAME)
def refresh() -> None:
    return None

def enqueue() -> None:
    refresh.delay()
    refresh.apply_async()
    signature(TASK_NAME)
    current_app.send_task(TASK_NAME)
""",
    )
    monkeypatch.setattr(inventory, "ROOT", tmp_path)
    inventory._tree.cache_clear()
    celery = {"tasks": [{"task_path": "apps.demo.application.tasks.refresh"}]}

    task_entries = inventory._discover_celery_tasks(celery)
    dispatch_entries = inventory._discover_celery_dispatch_edges(celery)

    assert [(entry["symbol"], entry["target"]) for entry in task_entries] == [
        ("refresh", "apps.demo.application.tasks.refresh")
    ]
    assert {(entry["symbol"], entry["target"]) for entry in dispatch_entries} == {
        ("delay", "apps.demo.application.tasks.refresh"),
        ("apply_async", "apps.demo.application.tasks.refresh"),
        ("signature", "apps.demo.application.tasks.refresh"),
        ("send_task", "apps.demo.application.tasks.refresh"),
    }


def test_periodic_task_annassign_and_alias_preserve_each_schedule_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory = _load_script()
    _write_source(
        tmp_path,
        "apps/data_center/management/commands/setup_demo.py",
        """from typing import Any
import importlib

beat_models = importlib.import_module("django_celery_beat.models")
PeriodicTask: Any = beat_models.PeriodicTask
periodic_task_model = beat_models.PeriodicTask
TASK = "apps.data_center.application.tasks.refresh"

PeriodicTask.objects.update_or_create(name="morning", defaults={"task": TASK})
PeriodicTask.objects.update_or_create(name="close", defaults={"task": TASK})
periodic_task_model.objects.update_or_create(name="intraday", defaults={"task": TASK})
""",
    )
    monkeypatch.setattr(inventory, "ROOT", tmp_path)
    inventory._tree.cache_clear()

    entries = inventory._discover_scheduler_writers()

    assert [entry["locator"] for entry in entries] == ["morning", "close", "intraday"]
    assert {entry["target"] for entry in entries} == {"apps.data_center.application.tasks.refresh"}
    assert all(entry["status"] == "active_public" for entry in entries)


def test_management_dispatch_resolves_execute_argv_and_call_command_constants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory = _load_script()
    _write_source(
        tmp_path,
        "apps/data_center/management/commands/sync_demo.py",
        "from django.core.management.base import BaseCommand\n",
    )
    _write_source(
        tmp_path,
        "scripts/wrapper.py",
        """from django.core.management import call_command as cc
from django.core.management import execute_from_command_line as run

COMMAND = "sync_demo"
cc(COMMAND)
run(["manage.py", COMMAND])
""",
    )
    monkeypatch.setattr(inventory, "ROOT", tmp_path)
    inventory._tree.cache_clear()

    entries = inventory._discover_management_command_edges()

    assert [(entry["symbol"], entry["target"]) for entry in entries] == [
        ("sync_demo", "apps/data_center/management/commands/sync_demo.py"),
        ("sync_demo", "apps/data_center/management/commands/sync_demo.py"),
    ]


def test_unresolved_dynamic_import_is_retained_for_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory = _load_script()
    _write_source(
        tmp_path,
        "apps/data_center/infrastructure/plugins.py",
        """from importlib import import_module

def load(module_path: str) -> object:
    return import_module(module_path)
""",
    )
    monkeypatch.setattr(inventory, "ROOT", tmp_path)
    inventory._tree.cache_clear()

    entries = inventory._discover_dynamic_import_edges()

    assert len(entries) == 1
    assert entries[0]["status"] == "candidate-review"
    assert entries[0]["target"] == "dynamic-import"


def test_duplicate_ids_are_reported_without_prevalidation_deduplication() -> None:
    inventory = _load_script()
    entry = inventory._entry(
        category="celery_dispatch_edge",
        path="apps/demo.py",
        symbol="delay",
        locator="line:10",
        target="apps.demo.task",
        status="active_public",
        evidence="test edge",
    )
    payload: dict[str, object] = {"entries": [entry, dict(entry)]}

    violations = inventory.validate_inventory(payload)

    assert f"entry_id_duplicate:{entry['id']}" in violations
    assert len(payload["entries"]) == 2


def test_admin_multiple_model_and_custom_site_registrations_are_all_preserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory = _load_script()
    _write_source(
        tmp_path,
        "apps/data_center/interface/admin.py",
        """from django.contrib import admin

@admin.register(ModelA, ModelB)
class MultiAdmin:
    pass

custom_site.register([ModelC, ModelD])
""",
    )
    monkeypatch.setattr(inventory, "ROOT", tmp_path)
    inventory._tree.cache_clear()

    entries = inventory._discover_admin_surfaces()

    assert {entry["target"] for entry in entries} == {
        "ModelA",
        "ModelB",
        "ModelC",
        "ModelD",
    }


def test_repository_pytest_temp_directories_never_enter_governance_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory = _load_script()
    _write_source(
        tmp_path,
        "apps/data_center/management/commands/real_command.py",
        "from django.core.management.base import BaseCommand\n",
    )
    _write_source(
        tmp_path,
        "pytest-tmp/test_fixture/apps/data_center/management/commands/ghost.py",
        "from django.core.management.base import BaseCommand\n",
    )
    monkeypatch.setattr(inventory, "ROOT", tmp_path)
    inventory._tree.cache_clear()

    entries = inventory._discover_management_commands()

    assert [entry["symbol"] for entry in entries] == ["real_command"]
