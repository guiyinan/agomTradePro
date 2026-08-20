"""Machine checks for the TUI metadata source boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from scripts.check_tui_metadata_source_consistency import (
    check_tui_metadata_source_consistency,
    load_json_payload,
)

ROOT = Path(__file__).resolve().parents[2]
PUBLISHED_PATH = ROOT / "config/tui/published/tui_operation_graph.published.json"
IA_PATH = ROOT / "config/tui/ia/tui_information_architecture.v1.json"


def _minimal_payload() -> dict[str, Any]:
    """Return a small source graph for violation tests."""

    screen = {
        "key": "published",
        "label": "Published",
        "summary": "Summary",
        "user_experience": {"primary_task": "Task", "primary_outcome": "Outcome"},
        "business_context": {},
        "audience": "authenticated",
        "view_type": "detail",
        "group": "daily",
        "module_key": "daily",
        "dashboard_panels": [],
    }
    return {
        "version": "test",
        "ia_version": "test",
        "groups": [],
        "modules": [],
        "screens": [screen],
        "actions": [],
    }


def test_real_tui_sources_have_consistent_published_screen_ownership() -> None:
    """The real static, IA, and normalized runtime sources agree."""

    pytest.importorskip("django")
    from apps.terminal.infrastructure.tui_metadata_repository import (
        PublishedTuiMetadataRepository,
    )

    published = load_json_payload(PUBLISHED_PATH)
    ia = load_json_payload(IA_PATH)
    runtime = PublishedTuiMetadataRepository(published_path=PUBLISHED_PATH)._load_published_file()

    report = check_tui_metadata_source_consistency(
        published_payload=published,
        ia_payload=ia,
        runtime_payload=runtime,
    )

    assert report.passed, report.as_json()
    assert report.published_screen_count == 12
    assert report.runtime_screen_count == 24
    assert report.published_action_count == 430
    assert report.runtime_action_count >= report.published_action_count


def test_retired_alias_screen_patch_is_not_registered_after_ia_cutover() -> None:
    """A legacy alias must resolve through IA, not a parallel screen patch."""

    from apps.terminal.infrastructure.tui_information_architecture import screen_aliases
    from apps.terminal.infrastructure.tui_metadata_repository import (
        RUNTIME_SCREEN_PATCHES,
        PublishedTuiMetadataRepository,
    )

    registry = load_json_payload(IA_PATH)
    aliases = screen_aliases(registry)
    runtime = PublishedTuiMetadataRepository(published_path=PUBLISHED_PATH)._load_published_file()
    runtime_screen_keys = {str(screen["key"]) for screen in runtime["screens"]}

    assert aliases["command-center.auto-advisor"] == "command-center.decision-flow"
    assert "command-center.auto-advisor" not in RUNTIME_SCREEN_PATCHES
    assert "command-center.auto-advisor" not in runtime_screen_keys


def test_execution_audit_screen_patch_is_not_registered_after_ia_cutover() -> None:
    """The canonical audit screen owns its panels in the reviewed IA graph."""

    from apps.terminal.infrastructure.tui_information_architecture import screen_aliases
    from apps.terminal.infrastructure.tui_metadata_repository import (
        RUNTIME_SCREEN_PATCHES,
        PublishedTuiMetadataRepository,
    )

    registry = load_json_payload(IA_PATH)
    aliases = screen_aliases(registry)
    runtime = PublishedTuiMetadataRepository(published_path=PUBLISHED_PATH)._load_published_file()
    runtime_screen_keys = {str(screen["key"]) for screen in runtime["screens"]}
    audit = next(screen for screen in runtime["screens"] if screen["key"] == "execution.audit")

    assert aliases["execution.events"] == "execution.audit"
    assert aliases["execution.share"] == "execution.audit"
    assert "execution.audit" not in RUNTIME_SCREEN_PATCHES
    assert "execution.events" not in RUNTIME_SCREEN_PATCHES
    assert "execution.share" not in RUNTIME_SCREEN_PATCHES
    assert "execution.events" not in runtime_screen_keys
    assert "execution.share" not in runtime_screen_keys
    assert audit["summary"] == "查看审计健康、事件指标、实盘对账与操作记录。"
    assert [
        panel["action_key"] for panel in audit["dashboard_panels"] if panel.get("action_key")
    ] == [
        "auto.api.get.api.audit.health",
        "auto.api.get.api.events.metrics",
        "broker-execution.reconciliation-list",
        "broker-execution.audit-list",
    ]


def test_execution_account_settings_alias_uses_canonical_ia_without_screen_patch() -> None:
    """Account-settings source aliases retain the canonical accounts screen."""

    from apps.terminal.infrastructure.tui_information_architecture import screen_aliases
    from apps.terminal.infrastructure.tui_metadata_repository import (
        RUNTIME_SCREEN_PATCHES,
        PublishedTuiMetadataRepository,
    )

    registry = load_json_payload(IA_PATH)
    aliases = screen_aliases(registry)
    ia_screen = next(
        screen for screen in registry["published_screens"] if screen["key"] == "execution.accounts"
    )
    runtime = PublishedTuiMetadataRepository(published_path=PUBLISHED_PATH)._load_published_file()
    runtime_screen_keys = {str(screen["key"]) for screen in runtime["screens"]}
    runtime_screen = next(
        screen for screen in runtime["screens"] if screen["key"] == "execution.accounts"
    )

    assert aliases["execution.account-settings"] == "execution.accounts"
    assert "execution.account-settings" not in RUNTIME_SCREEN_PATCHES
    assert "execution.account-settings" not in runtime_screen_keys
    assert [panel["key"] for panel in runtime_screen["dashboard_panels"]] == [
        panel["key"] for panel in ia_screen["dashboard_panels"]
    ]
    assert [
        panel.get("action_key")
        for panel in runtime_screen["dashboard_panels"]
        if panel.get("action_key")
    ] == [
        panel.get("action_key")
        for panel in ia_screen["dashboard_panels"]
        if panel.get("action_key")
    ]


def _legacy_execution_account_settings_payload() -> dict[str, Any]:
    """Return a minimal legacy account-settings payload for compatibility checks."""

    return {
        "version": "legacy-execution-account-settings",
        "default_screen": "execution.account-settings",
        "groups": [{"key": "daily", "label": "Daily"}],
        "modules": [
            {
                "key": "daily-decisions",
                "label": "Daily Decisions",
                "group": "daily",
                "summary": "Legacy daily decisions.",
            }
        ],
        "screens": [
            {
                "key": "execution.account-settings",
                "label": "Legacy Account Settings",
                "module_key": "daily-decisions",
                "group": "daily",
                "summary": "Legacy account settings.",
                "view_type": "status",
                "default_action_key": "legacy.account-settings.list",
            }
        ],
        "actions": [
            {
                "key": "legacy.account-settings.list",
                "label": "Legacy account settings list",
                "endpoint": "/api/legacy/account-settings/",
                "intent": "legacy_account_settings",
                "screen_key": "execution.account-settings",
                "module_key": "daily-decisions",
                "view_type": "status",
            }
        ],
    }


def test_legacy_execution_account_settings_payload_remains_loadable_without_screen_patch() -> None:
    """Legacy account-settings payloads retain their own contract after removal."""

    from apps.terminal.application.tui_metadata import validate_tui_metadata
    from apps.terminal.infrastructure.tui_metadata_repository import (
        PublishedTuiMetadataRepository,
    )

    normalized = PublishedTuiMetadataRepository().validate_and_normalize_runtime_payload(
        _legacy_execution_account_settings_payload()
    )
    screen = next(
        screen for screen in normalized["screens"] if screen["key"] == "execution.account-settings"
    )
    assert screen["label"] == "Legacy Account Settings"
    assert screen["dashboard_panels"] == []
    assert not normalized.get("coverage_summary", {}).get("runtime_patched_screens")
    assert "legacy.account-settings.list" in {action["key"] for action in normalized["actions"]}
    validate_tui_metadata(normalized)


def test_data_center_screen_patch_is_not_registered_after_ia_cutover() -> None:
    """The canonical IA screen owns data-center panels and row actions."""

    from apps.terminal.infrastructure.tui_metadata_repository import (
        RUNTIME_SCREEN_PATCHES,
        PublishedTuiMetadataRepository,
    )

    ia = load_json_payload(IA_PATH)
    ia_screen = next(
        screen for screen in ia["published_screens"] if screen["key"] == "api-library.data-center"
    )
    runtime = PublishedTuiMetadataRepository(published_path=PUBLISHED_PATH)._load_published_file()
    runtime_screen = next(
        screen for screen in runtime["screens"] if screen["key"] == "api-library.data-center"
    )
    assert "api-library.data-center" not in RUNTIME_SCREEN_PATCHES
    for key in ("label", "summary", "view_type", "default_action_key", "user_experience"):
        assert runtime_screen[key] == ia_screen[key]

    ia_panels = {
        str(panel["key"]): panel
        for panel in ia_screen["dashboard_panels"]
        if isinstance(panel, dict)
    }
    runtime_panels = {
        str(panel["key"]): panel
        for panel in runtime_screen["dashboard_panels"]
        if isinstance(panel, dict)
    }
    assert set(ia_panels) <= set(runtime_panels)
    ia_provider = ia_panels["data-center-providers"]
    runtime_provider = runtime_panels["data-center-providers"]
    assert [
        column["key"] for column in runtime_provider["columns"] if isinstance(column, dict)
    ] == [column["key"] for column in ia_provider["columns"] if isinstance(column, dict)]
    assert {
        action["action_key"]
        for action in runtime_provider["row_actions"]
        if isinstance(action, dict)
    } == {action["action_key"] for action in ia_provider["row_actions"] if isinstance(action, dict)}
    assert "data-center-provider-receipt" in runtime_panels


def _legacy_data_center_payload() -> dict[str, Any]:
    """Return a minimal legacy payload for screen-patch compatibility checks."""

    return {
        "version": "legacy-data-center",
        "default_screen": "api-library.data-center",
        "groups": [{"key": "system", "label": "System"}],
        "modules": [
            {
                "key": "system-governance",
                "label": "System Governance",
                "group": "system",
                "summary": "Legacy system governance.",
            }
        ],
        "screens": [
            {
                "key": "api-library.data-center",
                "label": "Legacy Data Center",
                "module_key": "system-governance",
                "group": "system",
                "summary": "Legacy data center summary.",
                "view_type": "status",
                "default_action_key": "legacy.data-center.list",
            }
        ],
        "actions": [
            {
                "key": "legacy.data-center.list",
                "label": "Legacy data center list",
                "endpoint": "/api/legacy/data-center/",
                "intent": "legacy_data_center",
                "screen_key": "api-library.data-center",
                "module_key": "system-governance",
                "view_type": "status",
            }
        ],
    }


def test_legacy_data_center_payload_remains_loadable_without_screen_patch() -> None:
    """Legacy payloads keep their own screen contract after dead-patch removal."""

    from apps.terminal.application.tui_metadata import validate_tui_metadata
    from apps.terminal.infrastructure.tui_metadata_repository import (
        PublishedTuiMetadataRepository,
    )

    normalized = PublishedTuiMetadataRepository().validate_and_normalize_runtime_payload(
        _legacy_data_center_payload()
    )
    screen = next(
        screen for screen in normalized["screens"] if screen["key"] == "api-library.data-center"
    )
    assert screen["label"] == "Legacy Data Center"
    assert screen["dashboard_panels"] == []
    assert not normalized.get("coverage_summary", {}).get("runtime_patched_screens")
    action_keys = {action["key"] for action in normalized["actions"]}
    assert "legacy.data-center.list" in action_keys
    assert "data-center.provider-update" in action_keys
    validate_tui_metadata(normalized)


def test_ai_provider_screen_patch_is_not_registered_after_ia_cutover() -> None:
    """The canonical IA screen owns AI provider governance copy and panels."""

    from apps.terminal.infrastructure.tui_metadata_repository import (
        RUNTIME_SCREEN_PATCHES,
        PublishedTuiMetadataRepository,
    )

    ia = load_json_payload(IA_PATH)
    ia_screen = next(
        screen for screen in ia["published_screens"] if screen["key"] == "ai-ops.providers"
    )
    runtime = PublishedTuiMetadataRepository(published_path=PUBLISHED_PATH)._load_published_file()
    runtime_screen = next(
        screen for screen in runtime["screens"] if screen["key"] == "ai-ops.providers"
    )

    assert "ai-ops.providers" not in RUNTIME_SCREEN_PATCHES
    for key in ("label", "summary", "view_type", "default_action_key", "user_experience"):
        assert runtime_screen[key] == ia_screen[key]
    assert [panel["key"] for panel in runtime_screen["dashboard_panels"]] == [
        panel["key"] for panel in ia_screen["dashboard_panels"]
    ]
    assert [
        panel.get("action_key")
        for panel in runtime_screen["dashboard_panels"]
        if panel.get("action_key")
    ] == [
        panel.get("action_key")
        for panel in ia_screen["dashboard_panels"]
        if panel.get("action_key")
    ]


def _legacy_ai_provider_payload() -> dict[str, Any]:
    """Return a minimal non-IA payload for the retired patch boundary."""

    return {
        "version": "legacy-ai-provider",
        "default_screen": "ai-ops.providers",
        "groups": [{"key": "research", "label": "Research"}],
        "modules": [
            {
                "key": "research-tools",
                "label": "Research Tools",
                "group": "research",
                "summary": "Legacy research tools.",
            }
        ],
        "screens": [
            {
                "key": "ai-ops.providers",
                "label": "Legacy AI Providers",
                "module_key": "research-tools",
                "group": "research",
                "summary": "Legacy AI provider summary.",
                "view_type": "datagrid",
                "default_action_key": "legacy.ai.providers",
            }
        ],
        "actions": [
            {
                "key": "legacy.ai.providers",
                "label": "Legacy AI provider list",
                "endpoint": "/api/legacy/ai/providers/",
                "intent": "legacy_ai_provider_list",
                "screen_key": "ai-ops.providers",
                "module_key": "research-tools",
                "view_type": "datagrid",
            }
        ],
    }


def test_legacy_ai_provider_payload_remains_loadable_without_screen_patch() -> None:
    """Legacy payloads keep their own contract after AI patch removal."""

    from apps.terminal.application.tui_metadata import validate_tui_metadata
    from apps.terminal.infrastructure.tui_metadata_repository import (
        PublishedTuiMetadataRepository,
    )

    normalized = PublishedTuiMetadataRepository().validate_and_normalize_runtime_payload(
        _legacy_ai_provider_payload()
    )
    screen = next(screen for screen in normalized["screens"] if screen["key"] == "ai-ops.providers")
    assert screen["label"] == "Legacy AI Providers"
    assert screen["dashboard_panels"] == []
    assert not normalized.get("coverage_summary", {}).get("runtime_patched_screens")
    assert "legacy.ai.providers" in {action["key"] for action in normalized["actions"]}
    validate_tui_metadata(normalized)


@pytest.mark.parametrize(
    ("alias", "canonical"),
    (
        ("macro-regime.beta-gate", "macro-regime.strategy"),
        ("macro-regime.hedge", "macro-regime.strategy"),
        ("macro-regime.pulse", "macro-regime.overview"),
    ),
)
def test_macro_aliases_use_canonical_ia_without_screen_patches(alias: str, canonical: str) -> None:
    """Macro aliases retain canonical IA panels after dead-patch removal."""

    from apps.terminal.infrastructure.tui_information_architecture import screen_aliases
    from apps.terminal.infrastructure.tui_metadata_repository import (
        RUNTIME_SCREEN_PATCHES,
        PublishedTuiMetadataRepository,
    )

    registry = load_json_payload(IA_PATH)
    aliases = screen_aliases(registry)
    runtime = PublishedTuiMetadataRepository(published_path=PUBLISHED_PATH)._load_published_file()
    runtime_screens = {str(screen["key"]): screen for screen in runtime["screens"]}
    ia_screens = {
        str(screen["key"]): screen
        for screen in [*registry["published_screens"], *registry["runtime_screens"]]
    }

    assert aliases[alias] == canonical
    assert alias not in RUNTIME_SCREEN_PATCHES
    assert alias not in runtime_screens
    assert [
        panel.get("action_key")
        for panel in runtime_screens[canonical]["dashboard_panels"]
        if panel.get("action_key")
    ] == [
        panel.get("action_key")
        for panel in ia_screens[canonical]["dashboard_panels"]
        if panel.get("action_key")
    ]
    assert [panel["key"] for panel in runtime_screens[canonical]["dashboard_panels"]] == [
        panel["key"] for panel in ia_screens[canonical]["dashboard_panels"]
    ]


def test_risk_center_alias_uses_canonical_ia_without_screen_patch() -> None:
    """Risk-center source semantics stay on the canonical strategy screen."""

    from apps.terminal.infrastructure.tui_information_architecture import screen_aliases
    from apps.terminal.infrastructure.tui_metadata_repository import (
        RUNTIME_SCREEN_PATCHES,
        PublishedTuiMetadataRepository,
    )

    registry = load_json_payload(IA_PATH)
    aliases = screen_aliases(registry)
    runtime = PublishedTuiMetadataRepository(published_path=PUBLISHED_PATH)._load_published_file()
    runtime_screens = {str(screen["key"]): screen for screen in runtime["screens"]}
    ia_screens = {
        str(screen["key"]): screen
        for screen in [*registry["published_screens"], *registry["runtime_screens"]]
    }

    assert aliases["risk-center.overview"] == "macro-regime.strategy"
    assert "risk-center.overview" not in RUNTIME_SCREEN_PATCHES
    assert "risk-center.overview" not in runtime_screens
    assert [
        panel.get("action_key")
        for panel in runtime_screens["macro-regime.strategy"]["dashboard_panels"]
        if panel.get("action_key")
    ] == [
        panel.get("action_key")
        for panel in ia_screens["macro-regime.strategy"]["dashboard_panels"]
        if panel.get("action_key")
    ]
    assert [
        panel["key"] for panel in runtime_screens["macro-regime.strategy"]["dashboard_panels"]
    ] == [panel["key"] for panel in ia_screens["macro-regime.strategy"]["dashboard_panels"]]


def _legacy_risk_center_payload() -> dict[str, Any]:
    """Return a minimal legacy payload for the retired risk patch boundary."""

    return {
        "version": "legacy-risk-center",
        "default_screen": "risk-center.overview",
        "groups": [{"key": "daily", "label": "Daily"}],
        "modules": [
            {
                "key": "daily-decisions",
                "label": "Daily Decisions",
                "group": "daily",
                "summary": "Legacy daily decisions.",
            }
        ],
        "screens": [
            {
                "key": "risk-center.overview",
                "label": "Legacy Risk Center",
                "module_key": "daily-decisions",
                "group": "daily",
                "summary": "Legacy risk summary.",
                "view_type": "status",
                "default_action_key": "legacy.risk.list",
            }
        ],
        "actions": [
            {
                "key": "legacy.risk.list",
                "label": "Legacy risk list",
                "endpoint": "/api/legacy/risk/",
                "intent": "legacy_risk_list",
                "screen_key": "risk-center.overview",
                "module_key": "daily-decisions",
                "view_type": "status",
            }
        ],
    }


def test_legacy_risk_center_payload_remains_loadable_without_screen_patch() -> None:
    """Legacy risk payloads retain their own contract after patch removal."""

    from apps.terminal.application.tui_metadata import validate_tui_metadata
    from apps.terminal.infrastructure.tui_metadata_repository import (
        PublishedTuiMetadataRepository,
    )

    normalized = PublishedTuiMetadataRepository().validate_and_normalize_runtime_payload(
        _legacy_risk_center_payload()
    )
    screen = next(
        screen for screen in normalized["screens"] if screen["key"] == "risk-center.overview"
    )
    assert screen["label"] == "Legacy Risk Center"
    assert screen["dashboard_panels"] == []
    assert not normalized.get("coverage_summary", {}).get("runtime_patched_screens")
    assert "legacy.risk.list" in {action["key"] for action in normalized["actions"]}
    validate_tui_metadata(normalized)


def _legacy_macro_payload(screen_key: str) -> dict[str, Any]:
    """Return a minimal legacy payload for macro screen-patch compatibility checks."""

    return {
        "version": "legacy-macro",
        "default_screen": screen_key,
        "groups": [{"key": "daily", "label": "Daily"}],
        "modules": [
            {
                "key": "daily-decisions",
                "label": "Daily",
                "group": "daily",
                "summary": "Legacy daily decisions.",
            }
        ],
        "screens": [
            {
                "key": screen_key,
                "label": f"Legacy {screen_key}",
                "module_key": "daily-decisions",
                "group": "daily",
                "summary": "Legacy macro summary.",
                "view_type": "status",
                "default_action_key": "legacy.macro.list",
                "dashboard_panels": [],
            }
        ],
        "actions": [
            {
                "key": "legacy.macro.list",
                "label": "Legacy macro list",
                "endpoint": "/api/legacy/macro/",
                "intent": "legacy_macro",
                "screen_key": screen_key,
                "module_key": "daily-decisions",
                "view_type": "status",
            }
        ],
    }


@pytest.mark.parametrize(
    "screen_key",
    ("macro-regime.beta-gate", "macro-regime.hedge", "macro-regime.pulse"),
)
def test_legacy_macro_payload_remains_loadable_without_screen_patch(screen_key: str) -> None:
    """Legacy macro payloads keep their own contract after dead-patch removal."""

    from apps.terminal.application.tui_metadata import validate_tui_metadata
    from apps.terminal.infrastructure.tui_metadata_repository import (
        PublishedTuiMetadataRepository,
    )

    normalized = PublishedTuiMetadataRepository().validate_and_normalize_runtime_payload(
        _legacy_macro_payload(screen_key)
    )
    screen = next(item for item in normalized["screens"] if item["key"] == screen_key)
    assert screen["label"] == f"Legacy {screen_key}"
    assert screen["dashboard_panels"] == []
    assert not normalized.get("coverage_summary", {}).get("runtime_patched_screens")
    assert "legacy.macro.list" in {action["key"] for action in normalized["actions"]}
    validate_tui_metadata(normalized)


def test_research_signals_screen_patch_removed_after_ia_cutover() -> None:
    """The canonical IA screen owns research.signals after patch removal."""

    from apps.terminal.infrastructure.tui_metadata_repository import (
        RUNTIME_SCREEN_PATCHES,
        PublishedTuiMetadataRepository,
    )

    ia = load_json_payload(IA_PATH)
    research_signals = next(
        screen for screen in ia["published_screens"] if screen["key"] == "research.signals"
    )

    runtime = PublishedTuiMetadataRepository(published_path=PUBLISHED_PATH)._load_published_file()
    runtime_screen = next(
        screen for screen in runtime["screens"] if screen["key"] == "research.signals"
    )

    assert "research.signals" not in RUNTIME_SCREEN_PATCHES
    assert research_signals["label"] == "Beta 态势与 Alpha 选股"
    assert (
        research_signals["summary"] == "先判断市场是否允许参与，再查看 Alpha 选股清单、理由与约束。"
    )
    assert runtime_screen["label"] == research_signals["label"]
    assert runtime_screen["summary"] == research_signals["summary"]


def test_research_alpha_triggers_alias_uses_canonical_ia_without_screen_patch() -> None:
    """The alpha-triggers alias resolves to the canonical research screen."""

    from apps.terminal.infrastructure.tui_information_architecture import screen_aliases
    from apps.terminal.infrastructure.tui_metadata_repository import (
        RUNTIME_SCREEN_PATCHES,
        PublishedTuiMetadataRepository,
    )

    registry = load_json_payload(IA_PATH)
    aliases = screen_aliases(registry)
    runtime = PublishedTuiMetadataRepository(published_path=PUBLISHED_PATH)._load_published_file()
    runtime_screen_keys = {str(screen["key"]) for screen in runtime["screens"]}
    ia_screens = {
        str(screen["key"]): screen
        for screen in [*registry["published_screens"], *registry["runtime_screens"]]
    }
    runtime_screens = {str(screen["key"]): screen for screen in runtime["screens"]}

    assert aliases["research.alpha-triggers"] == "research.signals"
    assert "research.alpha-triggers" not in RUNTIME_SCREEN_PATCHES
    assert "research.alpha-triggers" not in runtime_screen_keys
    assert [panel["key"] for panel in runtime_screens["research.signals"]["dashboard_panels"]] == [
        panel["key"] for panel in ia_screens["research.signals"]["dashboard_panels"]
    ]
    assert [
        panel.get("action_key")
        for panel in runtime_screens["research.signals"]["dashboard_panels"]
        if panel.get("action_key")
    ] == [
        panel.get("action_key")
        for panel in ia_screens["research.signals"]["dashboard_panels"]
        if panel.get("action_key")
    ]


def _legacy_alpha_triggers_payload() -> dict[str, Any]:
    """Return a minimal legacy alpha-triggers payload for compatibility checks."""

    return {
        "version": "legacy-alpha-triggers",
        "default_screen": "research.alpha-triggers",
        "groups": [{"key": "research", "label": "Research"}],
        "modules": [
            {
                "key": "research-tools",
                "label": "Research Tools",
                "group": "research",
                "summary": "Legacy research tools.",
            }
        ],
        "screens": [
            {
                "key": "research.alpha-triggers",
                "label": "Legacy Alpha Triggers",
                "module_key": "research-tools",
                "group": "research",
                "summary": "Legacy alpha trigger summary.",
                "view_type": "datagrid",
                "default_action_key": "legacy.alpha-triggers.list",
                "dashboard_panels": [],
            }
        ],
        "actions": [
            {
                "key": "legacy.alpha-triggers.list",
                "label": "Legacy alpha trigger list",
                "endpoint": "/api/legacy/alpha-triggers/",
                "intent": "legacy_alpha_triggers",
                "screen_key": "research.alpha-triggers",
                "module_key": "research-tools",
                "view_type": "datagrid",
            }
        ],
    }


def test_legacy_alpha_triggers_payload_remains_loadable_without_screen_patch() -> None:
    """Legacy alpha-triggers payloads keep their own contract after patch removal."""

    from apps.terminal.application.tui_metadata import validate_tui_metadata
    from apps.terminal.infrastructure.tui_metadata_repository import (
        PublishedTuiMetadataRepository,
    )

    normalized = PublishedTuiMetadataRepository().validate_and_normalize_runtime_payload(
        _legacy_alpha_triggers_payload()
    )
    screen = next(
        screen for screen in normalized["screens"] if screen["key"] == "research.alpha-triggers"
    )
    assert screen["label"] == "Legacy Alpha Triggers"
    assert screen["dashboard_panels"] == []
    assert not normalized.get("coverage_summary", {}).get("runtime_patched_screens")
    assert "legacy.alpha-triggers.list" in {action["key"] for action in normalized["actions"]}
    validate_tui_metadata(normalized)


def test_research_asset_lab_screen_patch_removed_after_ia_cutover() -> None:
    """The canonical asset research screen owns its panels after cutover."""

    from apps.terminal.infrastructure.tui_metadata_repository import (
        RUNTIME_SCREEN_PATCHES,
        PublishedTuiMetadataRepository,
    )

    ia = load_json_payload(IA_PATH)
    asset_lab = next(
        screen for screen in ia["published_screens"] if screen["key"] == "research.asset-lab"
    )
    runtime = PublishedTuiMetadataRepository(published_path=PUBLISHED_PATH)._load_published_file()
    runtime_screen = next(
        screen for screen in runtime["screens"] if screen["key"] == "research.asset-lab"
    )

    assert "research.asset-lab" not in RUNTIME_SCREEN_PATCHES
    for key in ("label", "summary", "view_type", "default_action_key", "user_experience"):
        assert runtime_screen[key] == asset_lab[key]
    assert [
        panel["action_key"]
        for panel in runtime_screen["dashboard_panels"]
        if panel.get("action_key")
    ] == [panel["action_key"] for panel in asset_lab["dashboard_panels"] if panel.get("action_key")]


def test_prompt_screen_injection_does_not_repeat_ia_owned_copy() -> None:
    """Prompt runtime injection keeps behavior, while IA owns screen semantics."""

    from apps.terminal.infrastructure.tui_metadata_repository import (
        PublishedTuiMetadataRepository,
    )
    from apps.terminal.infrastructure.tui_metadata_runtime_injection_prompt import (
        RUNTIME_PROMPT_SCREEN,
    )

    ia = load_json_payload(IA_PATH)
    prompt_ia = next(
        screen
        for screen in [*ia["published_screens"], *ia["runtime_screens"]]
        if screen["key"] == "prompt.workbench"
    )
    owned_keys = {
        "label",
        "module_key",
        "group",
        "audience",
        "summary",
        "view_type",
        "default_action_key",
        "user_experience",
    }

    assert owned_keys.isdisjoint(RUNTIME_PROMPT_SCREEN)

    runtime = PublishedTuiMetadataRepository(published_path=PUBLISHED_PATH)._load_published_file()
    prompt_runtime = next(
        screen for screen in runtime["screens"] if screen["key"] == "prompt.workbench"
    )
    for key in owned_keys:
        assert prompt_runtime[key] == prompt_ia[key]
    runtime_panels = {panel["key"]: panel for panel in prompt_runtime["dashboard_panels"]}
    for injected_panel in RUNTIME_PROMPT_SCREEN["dashboard_panels"]:
        normalized_panel = runtime_panels[injected_panel["key"]]
        for key, value in injected_panel.items():
            assert normalized_panel[key] == value


def test_runtime_action_replacements_keep_published_copy() -> None:
    """Runtime action behavior may be richer, but IA-owned copy stays canonical."""

    from apps.terminal.infrastructure.tui_metadata_repository import (
        PublishedTuiMetadataRepository,
    )

    published = load_json_payload(PUBLISHED_PATH)
    runtime = PublishedTuiMetadataRepository(published_path=PUBLISHED_PATH)._load_published_file()
    action_keys = {
        "auto.api.get.api.dashboard.allocation",
        "auto.api.get.api.dashboard.performance",
        "auto.api.get.api.data-center.providers",
        "auto.api.get.api.data-center.publishers",
        "regime.current",
        "regime.navigator_history",
    }
    published_actions = {
        str(action["key"]): action
        for action in published["actions"]
        if str(action.get("key") or "") in action_keys
    }
    runtime_actions = {
        str(action["key"]): action
        for action in runtime["actions"]
        if str(action.get("key") or "") in action_keys
    }

    assert set(runtime_actions) == action_keys
    for action_key in action_keys:
        for copy_key in ("label", "description"):
            assert runtime_actions[action_key][copy_key] == published_actions[action_key][copy_key]


def test_source_guard_rejects_runtime_replacement_of_ia_copy() -> None:
    """A runtime copy override must fail closed instead of being accepted."""

    ia = {
        "version": "test",
        "published_screens": [_minimal_payload()["screens"][0]],
        "runtime_screens": [],
    }
    published = _minimal_payload()
    runtime = _minimal_payload()
    runtime["screens"][0]["label"] = "Runtime override"

    report = check_tui_metadata_source_consistency(
        published_payload=published,
        ia_payload=ia,
        runtime_payload=runtime,
    )

    assert not report.passed
    assert [item.rule_id for item in report.violations] == ["runtime_screen_copy:published"]


def test_source_guard_requires_runtime_screen_default_action() -> None:
    """Runtime-only screens must expose the contract needed by the shell."""

    base = _minimal_payload()
    runtime_screen = {
        "key": "runtime",
        "label": "Runtime",
        "summary": "Runtime summary",
        "user_experience": {"primary_task": "Task", "primary_outcome": "Outcome"},
        "default_action_key": "",
    }
    ia = {
        "version": "test",
        "published_screens": [base["screens"][0]],
        "runtime_screens": [runtime_screen],
    }
    published = base
    runtime = dict(base)
    runtime["screens"] = [base["screens"][0], runtime_screen]

    report = check_tui_metadata_source_consistency(
        published_payload=published,
        ia_payload=ia,
        runtime_payload=runtime,
    )

    assert not report.passed
    assert report.violations[0].rule_id == "runtime_screen_contract:runtime"
