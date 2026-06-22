import importlib.util
import json
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def generator_module():
    root = Path(__file__).resolve().parents[2]
    path = root / "tui-metadata-compiler" / "scripts" / "generate_tui_metadata.py"
    spec = importlib.util.spec_from_file_location("tui_metadata_generator", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def promoter_module():
    root = Path(__file__).resolve().parents[2]
    path = root / "tui-metadata-compiler" / "scripts" / "promote_tui_business_screens.py"
    spec = importlib.util.spec_from_file_location("tui_metadata_promoter", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _sample_payload() -> dict:
    return {
        "actions": [
            {
                "key": "existing.safe",
                "label": "Existing Safe",
                "method": "GET",
                "endpoint": "/api/existing/safe/",
                "intent": "existing",
                "screen_key": "api-library.safe-read",
                "module_key": "api-library",
                "view_type": "detail",
                "risk": "read",
                "fields": [],
            }
        ]
    }


def test_api_evidence_default_collects_all_safe_records(generator_module, monkeypatch):
    records = [
        {
            "key": f"safe-{index}",
            "name": f"Safe {index}",
            "method": "GET",
            "endpoint": f"/api/safe/{index}/",
            "category": "safe",
            "risk_level": "low",
            "visibility": "user",
        }
        for index in range(6)
    ]
    records += [
        {
            "key": "write",
            "name": "Write",
            "method": "POST",
            "endpoint": "/api/write/",
            "category": "write",
            "risk_level": "low",
            "visibility": "user",
        },
        {
            "key": "admin",
            "name": "Admin",
            "method": "GET",
            "endpoint": "/api/admin/status/",
            "category": "admin",
            "risk_level": "low",
            "visibility": "admin",
        },
    ]

    monkeypatch.setattr(generator_module, "collect_api_capability_records", lambda: records)

    safe_records, evidence = generator_module.collect_api_evidence(limit=0)
    _, limited = generator_module.collect_api_evidence(limit=3)

    assert len(safe_records) == 6
    assert len(evidence) == 6
    assert len(limited) == 3
    assert all(item["endpoint"].startswith("/api/safe/") for item in evidence)


def test_sdk_mcp_and_template_evidence_default_is_uncapped(generator_module):
    with tempfile.TemporaryDirectory(prefix="tui-metadata-compiler-") as temp_dir:
        root = Path(temp_dir)
        _write(
            root / "sdk" / "agomtradepro" / "modules" / "alpha.py",
            '''
class AlphaModule:
    def list_alpha(self, limit=10):
        """List alpha."""
        return []

    def get_alpha(self, code):
        """Get alpha."""
        return {}
''',
        )
        _write(
            root / "sdk" / "agomtradepro" / "modules" / "beta.py",
            '''
class BetaModule:
    def list_beta(self):
        """List beta."""
        return []
''',
        )
        _write(
            root / "sdk" / "agomtradepro_mcp" / "tools" / "alpha_tools.py",
            '''
def first_tool(symbol):
    """First tool."""
    return symbol

def second_tool(limit=10):
    """Second tool."""
    return limit

def register_alpha_tools(server):
    return server
''',
        )
        _write(
            root / "core" / "templates" / "alpha.html",
            '<table><tbody></tbody></table><select></select><div class="pagination"></div>',
        )
        _write(
            root / "apps" / "demo" / "templates" / "demo" / "beta.html",
            '<button class="tab-btn"></button><div class="modal"></div>',
        )

        assert len(generator_module.collect_sdk_evidence(root)) == 3
        assert len(generator_module.collect_sdk_evidence(root, limit=2)) == 2
        assert len(generator_module.collect_mcp_evidence(root)) == 2
        assert len(generator_module.collect_mcp_evidence(root, limit=1)) == 1
        assert len(generator_module.collect_template_evidence(root)) == 2
        assert len(generator_module.collect_template_evidence(root, limit=1)) == 1


def test_safe_api_actions_are_opt_in_and_limited(generator_module):
    safe_records = [
        {
            "key": f"safe-{index}",
            "name": f"Safe {index}",
            "method": "GET",
            "endpoint": f"/api/safe/{index}/",
            "summary": "Safe endpoint.",
        }
        for index in range(4)
    ]

    payload = _sample_payload()
    assert generator_module.add_safe_api_actions(payload, safe_records, limit=0) == 0
    assert len(payload["actions"]) == 1

    added = generator_module.add_safe_api_actions(payload, safe_records, limit=2)

    assert added == 2
    assert len(payload["actions"]) == 3
    assert payload["actions"][1]["key"] == "auto.safe-0"
    assert payload["actions"][2]["endpoint"] == "/api/safe/1/"


def test_safe_api_actions_skip_parameterized_internal_and_write_like_candidates(generator_module):
    safe_records = [
        {
            "key": "account.positions",
            "name": "Get Account Positions",
            "method": "GET",
            "endpoint": "/api/account/accounts/<int:account_id>/positions/",
            "summary": "Needs account selector.",
            "category": "account",
            "risk_level": "low",
            "visibility": "user",
        },
        {
            "key": "debug.logs",
            "name": "Get Debug Logs",
            "method": "GET",
            "endpoint": "/api/debug/server-logs/",
            "summary": "Debug only.",
            "category": "debug",
            "risk_level": "low",
            "visibility": "user",
        },
        {
            "key": "alpha.refresh",
            "name": "Refresh Alpha Scores",
            "method": "GET",
            "endpoint": "/api/alpha/refresh/",
            "summary": "Heavy refresh.",
            "category": "alpha",
            "risk_level": "low",
            "visibility": "user",
        },
        {
            "key": "alpha.scores",
            "name": "Get Alpha Scores",
            "method": "GET",
            "endpoint": "/api/alpha/scores/",
            "summary": "Read alpha scores.",
            "category": "alpha",
            "risk_level": "low",
            "visibility": "user",
        },
    ]

    payload = _sample_payload()
    added = generator_module.add_safe_api_actions(payload, safe_records, limit=10)

    assert added == 1
    assert payload["actions"][1]["key"] == "auto.alpha.scores"
    assert payload["actions"][1]["label"] == "Alpha Scores"
    assert payload["actions"][1]["screen_key"] == "api-library.research"


def test_parameterized_safe_api_actions_create_required_path_fields(generator_module):
    safe_records = [
        {
            "key": "account.positions.detail",
            "name": "Get Account Position Detail",
            "method": "GET",
            "endpoint": "/api/account/accounts/<int:account_id>/positions/<int:pk>/",
            "summary": "Needs account and position selectors.",
            "category": "account",
            "risk_level": "low",
            "visibility": "user",
        },
        {
            "key": "alpha.refresh",
            "name": "Refresh Alpha Scores",
            "method": "GET",
            "endpoint": "/api/alpha/<str:code>/refresh/",
            "summary": "Heavy refresh.",
            "category": "alpha",
            "risk_level": "low",
            "visibility": "user",
        },
        {
            "key": "account.format",
            "name": "Account DRF format suffix",
            "method": "GET",
            "endpoint": "/api/account/<drf_format_suffix:format>",
            "summary": "Technical route.",
            "category": "account",
            "risk_level": "low",
            "visibility": "user",
        },
        {
            "key": "strategy.activate",
            "name": "Activate Strategy",
            "method": "GET",
            "endpoint": "/api/strategy/strategies/<pk>/activate/",
            "summary": "Operation-like route.",
            "category": "strategy",
            "risk_level": "low",
            "visibility": "user",
        },
    ]

    payload = _sample_payload()
    added = generator_module.add_parameterized_safe_api_actions(payload, safe_records, limit=10)

    assert added == 1
    action = payload["actions"][1]
    assert action["key"] == "param.account.positions.detail"
    assert action["screen_key"] == "api-library.parameterized"
    assert action["source"] == "api-collector:parameterized-candidate"
    assert [field["key"] for field in action["fields"]] == ["account_id", "pk"]
    assert [field["label"] for field in action["fields"]] == ["账户 ID", "记录 ID"]
    assert [field["placeholder"] for field in action["fields"]] == ["输入账户 ID", "输入记录 ID"]
    assert all(field["required"] is True for field in action["fields"])
    assert all(field["binding"] == "path" for field in action["fields"])


def test_parameterized_safe_api_actions_skip_get_routes_with_operation_semantics(generator_module):
    safe_records = [
        {
            "key": "strategy.rules.disable",
            "name": "Disable Strategy Rule",
            "method": "GET",
            "endpoint": "/api/strategy/rules/<pk>/disable/",
            "summary": "Operation-like route.",
            "category": "strategy",
            "risk_level": "low",
            "visibility": "user",
        },
        {
            "key": "share.links.revoke",
            "name": "Revoke Share Link",
            "method": "GET",
            "endpoint": "/api/share/links/<pk>/revoke/",
            "summary": "Operation-like route.",
            "category": "share",
            "risk_level": "low",
            "visibility": "user",
        },
        {
            "key": "rotation.account_configs.apply_template",
            "name": "Apply Template",
            "method": "GET",
            "endpoint": "/api/rotation/account-configs/<pk>/apply-template/",
            "summary": "Operation-like route.",
            "category": "rotation",
            "risk_level": "low",
            "visibility": "user",
        },
        {
            "key": "hedge.pairs.check_effectiveness",
            "name": "Check Hedge Effectiveness",
            "method": "GET",
            "endpoint": "/api/hedge/pairs/<pk>/check_effectiveness/",
            "summary": "Heavy check route.",
            "category": "hedge",
            "risk_level": "low",
            "visibility": "user",
        },
        {
            "key": "account.accounts.detail",
            "name": "Get Account Detail",
            "method": "GET",
            "endpoint": "/api/account/accounts/<int:account_id>/",
            "summary": "Read detail route.",
            "category": "account",
            "risk_level": "low",
            "visibility": "user",
        },
    ]

    payload = _sample_payload()
    added = generator_module.add_parameterized_safe_api_actions(payload, safe_records, limit=10)

    assert added == 1
    assert payload["actions"][1]["key"] == "param.account.accounts.detail"


def test_parameterized_generation_rebuilds_stale_generated_actions(generator_module):
    payload = _sample_payload()
    payload["actions"].append(
        {
            "key": "param.old.bad",
            "label": "Old Bad",
            "method": "GET",
            "endpoint": "/api/account/<drf_format_suffix:format>",
            "intent": "parameterized_safe_read",
            "screen_key": "api-library.parameterized",
            "module_key": "api-library",
            "view_type": "auto",
            "risk": "read",
            "fields": [{"key": "format", "label": "Format"}],
            "source": "api-collector:parameterized-candidate",
        }
    )
    safe_records = [
        {
            "key": "account.accounts.detail",
            "name": "Get Account Detail",
            "method": "GET",
            "endpoint": "/api/account/accounts/<int:account_id>/",
            "summary": "Needs account selector.",
            "category": "account",
            "risk_level": "low",
            "visibility": "user",
        }
    ]

    added = generator_module.add_parameterized_safe_api_actions(payload, safe_records, limit=10)

    assert added == 1
    keys = {action["key"] for action in payload["actions"]}
    assert "param.old.bad" not in keys
    assert "param.account.accounts.detail" in keys


def test_coverage_summary_counts_publishable_and_deferred_candidates(generator_module):
    safe_records = [
        {
            "endpoint": "/api/alpha/scores/",
            "method": "GET",
            "category": "alpha",
            "risk_level": "low",
        },
        {"endpoint": "/api/debug/logs/", "method": "GET", "category": "debug", "risk_level": "low"},
        {
            "endpoint": "/api/account/<pk>/",
            "method": "GET",
            "category": "account",
            "risk_level": "low",
        },
        {
            "endpoint": "/api/factor/refresh/",
            "method": "GET",
            "category": "factor",
            "risk_level": "low",
        },
    ]
    payload = _sample_payload()

    summary = generator_module.build_coverage_summary(
        safe_records=safe_records,
        added_actions=1,
        added_parameterized_actions=1,
        payload=payload,
    )

    assert summary["safe_read_evidence"] == 4
    assert summary["direct_safe_read_candidates"] == 1
    assert summary["parameterized_safe_read_candidates"] == 1
    assert summary["added_parameterized_api_actions"] == 1
    assert summary["deferred"]["path_parameters"] == 0
    assert summary["deferred"]["write_like_or_heavy"] == 1
    assert summary["deferred"]["internal_debug_or_docs"] == 1


def test_generated_metadata_is_not_using_old_evidence_caps():
    root = Path(__file__).resolve().parents[2]
    graph_path = root / "config" / "tui" / "generated" / "tui_operation_graph.generated.json"
    payload = json.loads(graph_path.read_text(encoding="utf-8"))
    evidence_path = root / payload["source_evidence_ref"]
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    counts = {key: len(value) for key, value in evidence["source_evidence"].items()}

    assert "source_evidence" not in payload
    assert counts["api_safe_read"] > 80
    assert counts["sdk_methods"] > 160
    assert counts["mcp_tools"] > 220
    assert counts["classic_templates"] > 32


def test_promoter_routes_decision_rhythm_before_generic_decision(promoter_module):
    assert (
        promoter_module._promoted_screen_for("auto.api.get.api.decision-rhythm.summary")
        == "macro-regime.risk-controls"
    )
    assert (
        promoter_module._promoted_screen_for("auto.api.get.api.decision.context.step1")
        == "command-center.decision-flow"
    )


def test_promoter_routes_classic_page_clusters_to_business_screens(promoter_module):
    assert promoter_module._promoted_screen_for("auto.api.get.api.account.positions") == "execution.trading-ledger"
    assert (
        promoter_module._promoted_screen_for("auto.api.get.api.account.trading-cost-configs")
        == "execution.account-settings"
    )
    assert promoter_module._promoted_screen_for("auto.api.get.api.fund.rank") == "research.fund-sector"
    assert (
        promoter_module._promoted_screen_for("auto.api.get.api.filter.indicators")
        == "research.screening-sentiment"
    )
    assert promoter_module._promoted_screen_for("auto.api.get.api.beta-gate") == "macro-regime.beta-gate"
    assert promoter_module._promoted_screen_for("auto.api.get.api.hedge.alerts.active") == "macro-regime.hedge"


def test_promoter_prunes_empty_toolbox_screens(promoter_module):
    payload = {
        "groups": [{"key": "system", "label": "系统工具"}],
        "modules": [{"key": "api-library", "label": "系统工具", "group": "system", "summary": ""}],
        "screens": [
            {
                "key": "command-center.overview",
                "label": "今日总览",
                "module_key": "api-library",
                "group": "system",
                "summary": "",
                "view_type": "detail",
                "status": "online",
                "dashboard_panels": [{"key": "panel", "title": "Panel", "kind": "detail", "action_key": "existing.safe"}],
            },
            {
                "key": "api-library.safe-read",
                "label": "工具库",
                "module_key": "api-library",
                "group": "system",
                "summary": "",
                "view_type": "datagrid",
                "status": "online",
            },
        ],
        "actions": [
            {
                "key": "existing.safe",
                "label": "Existing Safe",
                "method": "GET",
                "endpoint": "/api/existing/safe/",
                "intent": "existing",
                "screen_key": "command-center.overview",
                "module_key": "api-library",
                "view_type": "detail",
                "risk": "read",
                "fields": [],
            }
        ],
        "default_screen": "command-center.overview",
    }

    removed = promoter_module._prune_empty_screens(payload)

    assert removed == 1
    assert [screen["key"] for screen in payload["screens"]] == ["command-center.overview"]
