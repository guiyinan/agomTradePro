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


@pytest.fixture
def smoke_module():
    root = Path(__file__).resolve().parents[2]
    path = root / "tui-metadata-compiler" / "scripts" / "smoke_tui_actions.py"
    spec = importlib.util.spec_from_file_location("tui_metadata_smoke", path)
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


def test_parameterized_safe_api_actions_use_curated_uuid_path_field_rules(generator_module):
    safe_records = [
        {
            "key": "account.observer-grants.detail",
            "name": "Get Observer Grant Detail",
            "method": "GET",
            "endpoint": "/api/account/observer-grants/<pk>/",
            "summary": "Observer grant detail.",
            "category": "account",
            "risk_level": "low",
            "visibility": "user",
        }
    ]

    payload = _sample_payload()
    added = generator_module.add_parameterized_safe_api_actions(payload, safe_records, limit=10)

    assert added == 1
    action = payload["actions"][1]
    assert action["fields"] == [
        {
            "key": "pk",
            "label": "授权 ID",
            "input_type": "text",
            "required": True,
            "default": "",
            "placeholder": "输入授权 ID（UUID）",
            "binding": "path",
            "value_type": "string",
        }
    ]


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
            "key": "share.public.access",
            "name": "Public Share Access",
            "method": "GET",
            "endpoint": "/api/share/public/<str:short_code>/access/",
            "summary": "Public access route.",
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


def test_parameterized_safe_api_actions_merge_curated_query_fields(generator_module):
    safe_records = [
        {
            "key": "account.accounts.performance-report",
            "name": "Get Account Performance Report",
            "method": "GET",
            "endpoint": "/api/account/accounts/<int:account_id>/performance-report/",
            "summary": "Thin summary.",
            "category": "account",
            "risk_level": "low",
            "visibility": "user",
            "input_schema": {"type": "object", "properties": {}},
        }
    ]

    payload = _sample_payload()
    added = generator_module.add_parameterized_safe_api_actions(payload, safe_records, limit=10)

    assert added == 1
    action = payload["actions"][1]
    assert action["key"] == "param.account.accounts.performance-report"
    assert [field["key"] for field in action["fields"]] == [
        "account_id",
        "start_date",
        "end_date",
    ]
    assert action["fields"][0]["binding"] == "path"
    assert all(field["binding"] == "query" for field in action["fields"][1:])
    assert all(field["required"] is True for field in action["fields"][1:])


def test_existing_actions_receive_inferred_query_fields(generator_module):
    payload = _sample_payload()
    payload["actions"].append(
        {
            "key": "approved.account.performance-report",
            "label": "账户 / 绩效报告",
            "method": "GET",
            "endpoint": "/api/account/accounts/<int:account_id>/performance-report/",
            "intent": "parameterized_safe_read",
            "screen_key": "execution.portfolio-performance",
            "module_key": "execution",
            "view_type": "datagrid",
            "risk": "read",
            "fields": [
                {
                    "key": "account_id",
                    "label": "账户 ID",
                    "input_type": "number",
                    "required": True,
                    "binding": "path",
                }
            ],
            "source": "approved:parameterized-promoted",
        }
    )

    safe_records = [
        {
            "key": "account.accounts.performance-report",
            "name": "Get Account Performance Report",
            "method": "GET",
            "endpoint": "/api/account/accounts/<int:account_id>/performance-report/",
            "summary": "Thin summary.",
            "category": "account",
            "risk_level": "low",
            "visibility": "user",
            "input_schema": {"type": "object", "properties": {}},
        }
    ]

    updated = generator_module.merge_inferred_query_fields_into_existing_actions(
        payload, safe_records
    )

    assert updated == 1
    action = payload["actions"][1]
    assert [field["key"] for field in action["fields"]] == [
        "account_id",
        "start_date",
        "end_date",
    ]


def test_safe_api_actions_attach_required_query_fields_from_summary(generator_module):
    safe_records = [
        {
            "key": "decision.workspace.recommendations",
            "name": "Get Decision Workspace Recommendations",
            "method": "GET",
            "endpoint": "/api/decision/workspace/recommendations/",
            "summary": (
                "获取推荐列表\n\n"
                "Query params:\n"
                "    account_id: 账户 ID（必填）\n"
                "    status: 状态过滤（可选）\n"
                "    page: 页码（默认 1）\n"
                "    page_size: 每页大小（默认 20）"
            ),
            "category": "decision",
            "risk_level": "low",
            "visibility": "user",
        }
    ]

    payload = _sample_payload()
    added = generator_module.add_safe_api_actions(payload, safe_records, limit=10)

    assert added == 1
    action = payload["actions"][1]
    assert action["key"] == "auto.decision.workspace.recommendations"
    assert [field["key"] for field in action["fields"]] == [
        "account_id",
        "status",
        "page",
        "page_size",
    ]
    assert action["fields"][0]["required"] is True
    assert all(field["binding"] == "query" for field in action["fields"])


def test_safe_api_actions_attach_curated_query_fields_when_summary_is_too_thin(generator_module):
    safe_records = [
        {
            "key": "strategy.execution-logs.by_portfolio",
            "name": "Get Strategy Execution Logs By_Portfolio",
            "method": "GET",
            "endpoint": "/api/strategy/execution-logs/by_portfolio/",
            "summary": "策略执行日志 API（只读）",
            "category": "strategy",
            "risk_level": "low",
            "visibility": "user",
        }
    ]

    payload = _sample_payload()
    added = generator_module.add_safe_api_actions(payload, safe_records, limit=10)

    assert added == 1
    action = payload["actions"][1]
    assert [field["key"] for field in action["fields"]] == ["portfolio_id"]
    assert action["fields"][0]["required"] is True
    assert action["fields"][0]["value_type"] == "integer"


def test_safe_api_actions_attach_curated_query_fields_for_audit_summary(generator_module):
    safe_records = [
        {
            "key": "audit.summary",
            "name": "Get Audit Summary",
            "method": "GET",
            "endpoint": "/api/audit/summary/",
            "summary": "审计摘要 API",
            "category": "audit",
            "risk_level": "low",
            "visibility": "user",
        }
    ]

    payload = _sample_payload()
    added = generator_module.add_safe_api_actions(payload, safe_records, limit=10)

    assert added == 1
    action = payload["actions"][1]
    assert action["key"] == "auto.audit.summary"
    assert [field["key"] for field in action["fields"]] == ["start_date", "end_date"]
    assert all(field["required"] is True for field in action["fields"])
    assert all(field["binding"] == "query" for field in action["fields"])


def test_write_like_candidate_detection_ignores_resource_nouns_but_blocks_operation_segments(
    generator_module,
):
    agent_runtime_read = {
        "key": "api.get.api.agent-runtime.tasks",
        "name": "Get Agent Runtime Tasks",
        "method": "GET",
        "endpoint": "/api/agent-runtime/tasks/",
        "summary": "List tasks.",
        "category": "agent-runtime",
        "risk_level": "low",
        "visibility": "user",
    }
    alpha_trigger_read = {
        "key": "api.get.api.alpha-triggers.triggers",
        "name": "Get Alpha Triggers Triggers",
        "method": "GET",
        "endpoint": "/api/alpha-triggers/triggers/",
        "summary": "List triggers.",
        "category": "alpha-triggers",
        "risk_level": "low",
        "visibility": "user",
    }
    agent_runtime_cancel = {
        "key": "api.get.api.agent-runtime.tasks.pk.cancel",
        "name": "Get Agent Runtime Task Cancel",
        "method": "GET",
        "endpoint": "/api/agent-runtime/tasks/<pk>/cancel/",
        "summary": "Cancel task.",
        "category": "agent-runtime",
        "risk_level": "low",
        "visibility": "user",
    }
    alpha_trigger_update = {
        "key": "api.get.api.alpha-triggers.candidates.pk.update-status",
        "name": "Get Candidate Update Status",
        "method": "GET",
        "endpoint": "/api/alpha-triggers/candidates/<pk>/update-status/",
        "summary": "Update candidate.",
        "category": "alpha-triggers",
        "risk_level": "low",
        "visibility": "user",
    }

    assert generator_module._is_write_like_candidate(agent_runtime_read) is False
    assert generator_module._is_write_like_candidate(alpha_trigger_read) is False
    assert generator_module._is_write_like_candidate(agent_runtime_cancel) is True
    assert generator_module._is_write_like_candidate(alpha_trigger_update) is True
    assert generator_module._is_write_like_candidate(
        {
            "endpoint": "/api/rotation/generate-signal/",
        }
    ) is True


def test_safe_api_actions_include_agent_runtime_and_alpha_trigger_reads(generator_module):
    safe_records = [
        {
            "key": "agent-runtime.tasks",
            "name": "Get Agent Runtime Tasks",
            "method": "GET",
            "endpoint": "/api/agent-runtime/tasks/",
            "summary": "List tasks.",
            "category": "agent-runtime",
            "risk_level": "low",
            "visibility": "user",
        },
        {
            "key": "alpha-triggers.candidates",
            "name": "Get Alpha Trigger Candidates",
            "method": "GET",
            "endpoint": "/api/alpha-triggers/candidates/",
            "summary": "List candidates.",
            "category": "alpha-triggers",
            "risk_level": "low",
            "visibility": "user",
        },
    ]

    payload = _sample_payload()
    added = generator_module.add_safe_api_actions(payload, safe_records, limit=10)

    assert added == 2
    keys = {action["key"] for action in payload["actions"]}
    assert "auto.agent-runtime.tasks" in keys
    assert "auto.alpha-triggers.candidates" in keys


def test_safe_api_actions_skip_curated_non_runtime_fragment_and_collection_routes(generator_module):
    safe_records = [
        {
            "key": "dashboard.positions",
            "name": "Get Dashboard Positions",
            "method": "GET",
            "endpoint": "/api/dashboard/positions/",
            "summary": "HTMX partial.",
            "category": "dashboard",
            "risk_level": "low",
            "visibility": "user",
        },
        {
            "key": "dashboard.alpha.stocks",
            "name": "Get Dashboard Alpha Stocks",
            "method": "GET",
            "endpoint": "/api/dashboard/alpha/stocks/",
            "summary": "Requires format=json or HX-Request.",
            "category": "dashboard",
            "risk_level": "low",
            "visibility": "user",
        },
        {
            "key": "signal.unified",
            "name": "Get Unified Signals",
            "method": "GET",
            "endpoint": "/api/signal/unified/",
            "summary": "Redundant unstable collection route.",
            "category": "signal",
            "risk_level": "low",
            "visibility": "user",
        },
        {
            "key": "agent-runtime.proposals",
            "name": "Get Agent Runtime Proposals",
            "method": "GET",
            "endpoint": "/api/agent-runtime/proposals/",
            "summary": "Collection route is not a stable read surface.",
            "category": "agent-runtime",
            "risk_level": "low",
            "visibility": "user",
        },
    ]

    payload = _sample_payload()
    added = generator_module.add_safe_api_actions(payload, safe_records, limit=10)

    assert added == 0
    assert len(payload["actions"]) == 1


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


def test_parameterized_generation_removes_stale_promoted_actions(generator_module):
    payload = _sample_payload()
    payload["actions"].append(
        {
            "key": "param.strategy.evaluate-position-management",
            "label": "策略 / Evaluate Position Management",
            "method": "GET",
            "endpoint": "/api/strategy/strategies/<pk>/evaluate_position_management/",
            "intent": "parameterized_safe_read",
            "screen_key": "macro-regime.strategy",
            "module_key": "strategy",
            "view_type": "datagrid",
            "risk": "read",
            "fields": [{"key": "pk", "label": "记录 ID"}],
            "source": "approved:parameterized-promoted",
        }
    )
    safe_records = [
        {
            "key": "strategy.detail",
            "name": "Get Strategy Detail",
            "method": "GET",
            "endpoint": "/api/strategy/strategies/<pk>/",
            "summary": "Read detail route.",
            "category": "strategy",
            "risk_level": "low",
            "visibility": "user",
        }
    ]

    removed = generator_module.remove_stale_parameterized_safe_actions(payload, safe_records)

    assert removed == 1
    keys = {action["key"] for action in payload["actions"]}
    assert "param.strategy.evaluate-position-management" not in keys


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
            "endpoint": "/api/decision/workspace/conflicts/",
            "method": "GET",
            "summary": "Query params:\n    account_id: 账户 ID（必填）",
            "category": "decision",
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

    assert summary["safe_read_evidence"] == 5
    assert summary["direct_safe_read_candidates"] == 1
    assert summary["parameterized_safe_read_candidates"] == 2
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


def test_promoter_routes_portfolio_pk_and_valuation_snapshot_to_row_compatible_screens(promoter_module):
    assert (
        promoter_module._promoted_screen_for("param.api.get.api.account.portfolios.pk")
        == "execution.portfolio-performance"
    )
    assert (
        promoter_module._promoted_screen_for("param.api.get.api.account.portfolios.pk.statistics")
        == "execution.portfolio-performance"
    )
    assert (
        promoter_module._promoted_screen_for("param.api.get.api.account.portfolios.pk.positions")
        == "execution.portfolio-performance"
    )
    assert (
        promoter_module._promoted_screen_for("param.api.get.api.valuation.snapshot.str.snapshot_id")
        == "command-center.decision-flow"
    )


def test_promoter_routes_alpha_trigger_and_agent_runtime_to_operator_screens(promoter_module):
    assert (
        promoter_module._promoted_screen_for("auto.api.get.api.alpha-triggers.candidates.actionable")
        == "research.alpha-triggers"
    )
    assert (
        promoter_module._promoted_screen_for("auto.api.get.api.agent-runtime.tasks.needs_attention")
        == "ai-ops.agent-runtime"
    )


def test_promoter_overrides_list_view_types_for_row_selection_workflows(promoter_module):
    aggregated_action = {
        "key": "auto.api.get.api.decision.workspace.aggregated",
        "view_type": "detail",
        "fields": [],
    }
    promoter_module._normalize_special_action(aggregated_action)
    assert aggregated_action["view_type"] == "datagrid"

    recommendations_action = {
        "key": "auto.api.get.api.decision.workspace.recommendations",
        "view_type": "detail",
        "fields": [{"key": "account_id", "default": "", "placeholder": "输入账户ID"}],
    }
    promoter_module._normalize_special_action(recommendations_action)
    assert recommendations_action["view_type"] == "datagrid"
    assert recommendations_action["view_model"]["rows_path"] == "recommendations"
    assert recommendations_action["view_model"]["total_path"] == "total_count"
    assert recommendations_action["fields"][0]["default"] == "default"
    assert recommendations_action["fields"][0]["input_type"] == "text"
    assert recommendations_action["fields"][0]["value_type"] == "string"

    requests_action = {
        "key": "auto.api.get.api.decision-rhythm.requests",
        "view_type": "status",
        "fields": [],
    }
    promoter_module._normalize_special_action(requests_action)
    assert requests_action["view_type"] == "datagrid"

    hedge_snapshots_action = {
        "key": "auto.api.get.api.hedge.snapshots.latest",
        "view_type": "status",
        "fields": [],
    }
    promoter_module._normalize_special_action(hedge_snapshots_action)
    assert hedge_snapshots_action["view_type"] == "datagrid"
    assert hedge_snapshots_action["view_model"]["rows_path"] == "results"
    assert hedge_snapshots_action["view_model"]["total_path"] == "count"


def test_promoter_merges_share_public_access_operation(promoter_module):
    payload = {
        "screens": [
            {
                "key": "execution.share",
                "module_key": "execution",
            }
        ],
        "actions": [],
    }

    merged = promoter_module._merge_approved_operation_actions(payload)

    assert merged >= 1
    action = next(action for action in payload["actions"] if action["key"] == "share.public.access")
    assert action["method"] == "POST"
    assert action["endpoint"] == "/api/share/public/<str:short_code>/access/"
    assert action["risk"] == "read"
    assert action["screen_key"] == "execution.share"
    assert action["fields"][0]["key"] == "short_code"
    assert action["fields"][1]["key"] == "password"
    assert action["module_key"] == "execution"


def test_promoter_merges_data_center_selector_reads(promoter_module):
    payload = {
        "screens": [
            {
                "key": "api-library.data-center",
                "module_key": "api-library",
            }
        ],
        "actions": [],
    }

    merged = promoter_module._merge_approved_operation_actions(payload)

    assert merged >= 3
    actions = {action["key"]: action for action in payload["actions"]}
    assert actions["auto.api.get.api.data-center.indicators"]["endpoint"] == "/api/data-center/indicators/"
    assert actions["auto.api.get.api.data-center.indicators"]["risk"] == "read"
    assert actions["auto.api.get.api.data-center.indicators"]["task_group"] == "02 指标目录"
    assert actions["auto.api.get.api.data-center.providers"]["endpoint"] == "/api/data-center/providers/"
    assert actions["auto.api.get.api.data-center.providers"]["task_group"] == "04 服务商"
    assert actions["auto.api.get.api.data-center.publishers"]["endpoint"] == "/api/data-center/publishers/"
    assert actions["auto.api.get.api.data-center.publishers"]["task_group"] == "05 发布机构"
    assert actions["auto.api.get.api.data-center.indicators"]["module_key"] == "api-library"


def test_promoter_merges_trading_ledger_account_selector(promoter_module):
    payload = {
        "screens": [
            {
                "key": "execution.trading-ledger",
                "module_key": "execution",
            }
        ],
        "actions": [],
    }

    merged = promoter_module._merge_approved_operation_actions(payload)

    assert merged >= 1
    actions = {action["key"]: action for action in payload["actions"]}
    selector = actions["execution.trading-ledger.account-selector"]
    assert selector["endpoint"] == "/api/account/accounts/"
    assert selector["risk"] == "read"
    assert selector["task_group"] == "02 账户选择"
    assert selector["module_key"] == "execution"


def test_smoke_prune_marks_auto_promoted_failures_as_prunable(smoke_module):
    assert smoke_module._should_prune_failed_action({"source": "api-collector:candidate"}) is True
    assert smoke_module._should_prune_failed_action({"source": "approved:smoke-promoted"}) is True
    assert smoke_module._should_prune_failed_action({"source": "approved:parameterized-promoted"}) is True
    assert smoke_module._should_prune_failed_action({"source": "approved:operation"}) is False
    assert smoke_module._should_prune_failed_action({"source": "approved:admin"}) is False


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


def test_promoter_prunes_redundant_capability_pk_detail_action(promoter_module):
    payload = {
        "actions": [
            {
                "key": "param.api.get.api.ai-capability.capabilities.str.capability_key",
                "screen_key": "ai-ops.capabilities",
            },
            {
                "key": "param.api.get.api.ai-capability.capabilities.pk",
                "screen_key": "ai-ops.capabilities",
            },
            {
                "key": "param.api.get.api.ai.me.providers.pk",
                "screen_key": "ai-ops.providers",
            },
        ]
    }

    removed = promoter_module._prune_redundant_screen_actions(payload)

    assert removed == 1
    keys = {action["key"] for action in payload["actions"]}
    assert "param.api.get.api.ai-capability.capabilities.str.capability_key" in keys
    assert "param.api.get.api.ai-capability.capabilities.pk" not in keys
    assert "param.api.get.api.ai.me.providers.pk" in keys
