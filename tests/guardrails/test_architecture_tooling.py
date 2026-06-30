import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_script_module(script_name: str, module_name: str):
    script_path = REPO_ROOT / "scripts" / script_name
    sys.path.insert(0, str(script_path.parent))
    try:
        spec = importlib.util.spec_from_file_location(module_name, script_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.modules.pop(module_name, None)
        sys.path.pop(0)


def test_check_architecture_delta_parse_added_lines_tracks_only_added_lines():
    module = _load_script_module(
        "check_architecture_delta.py",
        "test_check_architecture_delta",
    )
    diff_text = """diff --git a/apps/prompt/interface/views.py b/apps/prompt/interface/views.py
+++ b/apps/prompt/interface/views.py
@@ -10,2 +10,4 @@
 keep_one
+from apps.ai_provider.infrastructure.client_factory import AIClientFactory
 keep_two
+from ..infrastructure.repositories import DjangoPromptRepository
@@ -40,0 +43,2 @@
+queryset = PromptTemplateORM._default_manager.all()
+serializer_class = PromptTemplateSerializer
"""

    added_lines = module.parse_added_lines(diff_text)

    assert added_lines == {
        "apps/prompt/interface/views.py": {11, 13, 43, 44},
    }


def test_check_architecture_delta_filters_violations_to_added_lines():
    module = _load_script_module(
        "check_architecture_delta.py",
        "test_check_architecture_delta_filter",
    )
    violations = [
        {"source_path": "apps/prompt/interface/views.py", "lineno": 11, "rule_id": "a"},
        {"source_path": "apps/prompt/interface/views.py", "lineno": 12, "rule_id": "b"},
        {"source_path": "apps/equity/interface/views.py", "lineno": 5, "rule_id": "c"},
    ]
    added_lines = {
        "apps/prompt/interface/views.py": {11},
        "apps/equity/interface/views.py": {8},
    }

    filtered = module.filter_violations_to_added_lines(violations, added_lines)

    assert filtered == [
        {"source_path": "apps/prompt/interface/views.py", "lineno": 11, "rule_id": "a"},
    ]


def test_verify_architecture_cross_app_infrastructure_rule_allows_owning_app_provider():
    module = _load_script_module(
        "verify_architecture.py",
        "test_verify_architecture_cross_app_allow",
    )
    rule = {
        "id": "apps_application_no_cross_app_infrastructure_imports",
        "description": "Application layers must use other apps' application facades.",
        "source_roots": ["apps"],
        "source_layers": ["application"],
        "forbid_cross_app_infrastructure_imports": True,
    }
    records = [
        module.ImportRecord(
            source_path="apps/prompt/application/runtime_provider.py",
            source_root="apps",
            source_module="prompt",
            source_layer="application",
            import_path="apps.prompt.infrastructure.repositories",
            target_module="prompt",
            lineno=1,
        ),
        module.ImportRecord(
            source_path="apps/terminal/application/services.py",
            source_root="apps",
            source_module="terminal",
            source_layer="application",
            import_path="apps.prompt.infrastructure.repositories",
            target_module="prompt",
            lineno=2,
        ),
    ]

    violations = module.find_import_violations(records, [rule])

    assert len(violations) == 1
    assert violations[0]["source_path"] == "apps/terminal/application/services.py"
    assert violations[0]["matched_pattern"] == "apps.<other>.infrastructure"


def test_verify_architecture_tracks_literal_dynamic_imports():
    module = _load_script_module(
        "verify_architecture.py",
        "test_verify_architecture_dynamic_imports",
    )
    source_file = module.SourceFile(
        path=REPO_ROOT / "apps" / "terminal" / "application" / "services.py",
        source_path="apps/terminal/application/services.py",
        source_root="apps",
        source_module="terminal",
        source_layer="application",
        module_path="apps.terminal.application.services",
        package="apps.terminal.application",
        text=(
            "import importlib\n"
            "def load_provider():\n"
            "    return importlib.import_module("
            "'apps.prompt.infrastructure.repositories'"
            ")\n"
        ),
    )
    rule = {
        "id": "apps_application_no_cross_app_infrastructure_imports",
        "description": "Application layers must use other apps' application facades.",
        "source_roots": ["apps"],
        "source_layers": ["application"],
        "forbid_cross_app_infrastructure_imports": True,
    }

    records = module.extract_import_records(source_file)
    violations = module.find_import_violations(records, [rule])

    assert any(
        violation["import_path"] == "apps.prompt.infrastructure.repositories"
        for violation in violations
    )


def test_verify_architecture_same_app_infrastructure_rule_excludes_repository_provider():
    module = _load_script_module(
        "verify_architecture.py",
        "test_verify_architecture_same_app_allow",
    )
    rule = {
        "id": "apps_application_no_same_app_infrastructure_imports_except_repository_provider",
        "description": "Application layers should route same-app concrete access through repository_provider.py.",
        "source_roots": ["apps"],
        "source_layers": ["application"],
        "exclude_path_patterns": [r"^apps/[^/]+/application/repository_provider\.py$"],
        "forbid_same_app_infrastructure_imports": True,
    }
    records = [
        module.ImportRecord(
            source_path="apps/prompt/application/repository_provider.py",
            source_root="apps",
            source_module="prompt",
            source_layer="application",
            import_path="apps.prompt.infrastructure.repositories",
            target_module="prompt",
            lineno=1,
        ),
        module.ImportRecord(
            source_path="apps/prompt/application/use_cases.py",
            source_root="apps",
            source_module="prompt",
            source_layer="application",
            import_path="apps.prompt.infrastructure.repositories",
            target_module="prompt",
            lineno=2,
        ),
    ]

    violations = module.find_import_violations(records, [rule])

    assert len(violations) == 1
    assert violations[0]["source_path"] == "apps/prompt/application/use_cases.py"
    assert violations[0]["matched_pattern"] == "apps.<same>.infrastructure"


def test_verify_architecture_domain_rule_blocks_application_and_infrastructure_imports():
    module = _load_script_module(
        "verify_architecture.py",
        "test_verify_architecture_domain_layers",
    )
    rule = {
        "id": "apps_domain_no_application_or_infrastructure_imports",
        "description": "Domain layers must not import application or infrastructure packages.",
        "source_roots": ["apps"],
        "source_layers": ["domain"],
        "forbidden_import_patterns": [
            r"^apps\..*\.application(?:\.|$)",
            r"^apps\..*\.infrastructure(?:\.|$)",
        ],
    }
    records = [
        module.ImportRecord(
            source_path="apps/backtest/domain/alpha_backtest.py",
            source_root="apps",
            source_module="backtest",
            source_layer="domain",
            import_path="apps.alpha.application.services",
            target_module="alpha",
            lineno=1,
        ),
        module.ImportRecord(
            source_path="apps/simulated_trading/domain/__init__.py",
            source_root="apps",
            source_module="simulated_trading",
            source_layer="domain",
            import_path="apps.equity.infrastructure.adapters",
            target_module="equity",
            lineno=2,
        ),
    ]

    violations = module.find_import_violations(records, [rule])

    assert len(violations) == 2
    assert violations[0]["rule_id"] == "apps_domain_no_application_or_infrastructure_imports"

    external_rule = {
        "id": "apps_domain_no_external_runtime_imports",
        "description": "Domain layers must not import runtime frameworks.",
        "source_roots": ["apps"],
        "source_layers": ["domain"],
        "forbidden_import_patterns": [
            r"^(django|pandas|numpy|requests|akshare|tushare)(?:\.|$)"
        ],
        "forbidden_line_patterns": [
            r"importlib\.import_module\([\"'](?:django|pandas|numpy|requests|akshare|tushare)(?:\.|[\"'])"
        ],
    }
    external_records = [
        module.ImportRecord(
            source_path="apps/regime/domain/services.py",
            source_root="apps",
            source_module="regime",
            source_layer="domain",
            import_path="django.utils.timezone",
            target_module=None,
            lineno=3,
        ),
        module.ImportRecord(
            source_path="apps/regime/domain/services.py",
            source_root="apps",
            source_module="regime",
            source_layer="domain",
            import_path="pandas",
            target_module=None,
            lineno=4,
        ),
    ]
    external_lines = [
        module.LineRecord(
            source_path="apps/regime/domain/services.py",
            source_root="apps",
            source_module="regime",
            source_layer="domain",
            lineno=5,
            line_text='        importlib.import_module("requests")',
        )
    ]

    external_import_violations = module.find_import_violations(
        external_records, [external_rule]
    )
    external_line_violations = module.find_line_violations(
        external_lines, [external_rule]
    )

    assert len(external_import_violations) == 2
    assert len(external_line_violations) == 1
    assert all(
        violation["rule_id"] == "apps_domain_no_external_runtime_imports"
        for violation in [*external_import_violations, *external_line_violations]
    )


def test_verify_architecture_application_line_rule_blocks_transaction_and_get_model():
    module = _load_script_module(
        "verify_architecture.py",
        "test_verify_architecture_application_line_rule",
    )
    rule = {
        "id": "apps_application_no_transaction_or_get_model",
        "description": "Application layers must not own transaction scopes or dynamic model resolution.",
        "source_roots": ["apps"],
        "source_layers": ["application"],
        "forbidden_line_patterns": [
            r"with\s+transaction\.atomic\(",
            r"@\s*transaction\.atomic\b",
            r"transaction\.atomic\(",
            r"django_apps\.get_model\(",
            r"\bapps\.get_model\(",
        ],
    }
    records = [
        module.LineRecord(
            source_path="apps/share/application/use_cases.py",
            source_root="apps",
            source_module="share",
            source_layer="application",
            lineno=10,
            line_text="        with transaction.atomic():",
        ),
        module.LineRecord(
            source_path="apps/share/application/use_cases.py",
            source_root="apps",
            source_module="share",
            source_layer="application",
            lineno=11,
            line_text='        model = django_apps.get_model("share", "ShareLinkModel")',
        ),
    ]

    violations = module.find_line_violations(records, [rule])

    assert len(violations) == 2
    assert violations[0]["rule_id"] == "apps_application_no_transaction_or_get_model"
    assert violations[1]["rule_id"] == "apps_application_no_transaction_or_get_model"


def test_verify_architecture_application_call_command_rule_respects_whitelist():
    module = _load_script_module(
        "verify_architecture.py",
        "test_verify_architecture_application_call_command_rule",
    )
    rule = {
        "id": "apps_application_no_call_command_except_whitelisted_entrypoints",
        "description": "Application layers must not invoke Django management commands directly outside whitelisted composition entrypoints.",
        "source_roots": ["apps"],
        "source_layers": ["application"],
        "exclude_path_patterns": [r"^apps/data_center/application/interface_services\.py$"],
        "forbidden_line_patterns": [r"\bcall_command\("],
    }
    records = [
        module.LineRecord(
            source_path="apps/data_center/application/interface_services.py",
            source_root="apps",
            source_module="data_center",
            source_layer="application",
            lineno=10,
            line_text='        call_command("build_qlib_data", verbosity=0)',
        ),
        module.LineRecord(
            source_path="apps/data_center/application/use_cases.py",
            source_root="apps",
            source_module="data_center",
            source_layer="application",
            lineno=22,
            line_text='        call_command("sync_macro_data", "--source", "akshare")',
        ),
    ]

    violations = module.find_line_violations(records, [rule])

    assert len(violations) == 1
    assert violations[0]["source_path"] == "apps/data_center/application/use_cases.py"
    assert violations[0]["rule_id"] == "apps_application_no_call_command_except_whitelisted_entrypoints"


def test_verify_architecture_app_root_model_shim_rule_exempts_admin_only():
    module = _load_script_module(
        "verify_architecture.py",
        "test_verify_architecture_model_shim_rule",
    )
    rule = {
        "id": "apps_no_app_root_model_shim_imports_outside_admin",
        "description": "Only admin entrypoints may import app-root models.py shims.",
        "source_roots": ["apps"],
        "exclude_path_patterns": [
            r"(^|/)admin\.py$",
            r"^apps/[^/]+/models\.py$",
            r"/migrations/",
        ],
        "forbidden_import_patterns": [r"^apps\.[^.]+\.models$"],
    }
    records = [
        module.ImportRecord(
            source_path="apps/alpha/interface/admin.py",
            source_root="apps",
            source_module="alpha",
            source_layer="interface",
            import_path="apps.alpha.models",
            target_module="alpha",
            lineno=3,
        ),
        module.ImportRecord(
            source_path="apps/alpha/interface/views.py",
            source_root="apps",
            source_module="alpha",
            source_layer="interface",
            import_path="apps.alpha.models",
            target_module="alpha",
            lineno=5,
        ),
    ]

    violations = module.find_import_violations(records, [rule])

    assert len(violations) == 1
    assert violations[0]["source_path"] == "apps/alpha/interface/views.py"
    assert violations[0]["rule_id"] == "apps_no_app_root_model_shim_imports_outside_admin"


def test_check_module_cycles_reports_unexpected_strong_components():
    module = _load_script_module(
        "check_module_cycles.py",
        "test_check_module_cycles_components",
    )
    graph = {
        "account": {"backtest"},
        "backtest": {"decision_rhythm"},
        "decision_rhythm": {"account"},
    }

    cycle_components = module.find_cycle_components(graph, list(graph))
    report = module.build_report(
        graph=graph,
        modules=list(graph),
        import_records=[],
        bidirectional_pairs=[],
        cycle_components=cycle_components,
        allowed_pairs=set(),
        allowed_components=set(),
        allowlist_path=REPO_ROOT / "governance" / "module_cycle_allowlist.json",
        allowlist_payload={"version": "test"},
    )

    assert cycle_components == [["account", "backtest", "decision_rhythm"]]
    assert report["unexpected_pairs"] == []
    assert report["unexpected_cycle_components"] == [
        ["account", "backtest", "decision_rhythm"]
    ]


def test_check_module_cycles_honors_allowed_strong_components():
    module = _load_script_module(
        "check_module_cycles.py",
        "test_check_module_cycles_allowed_components",
    )
    graph = {
        "alpha": {"beta_gate"},
        "beta_gate": {"alpha"},
    }
    cycle_components = module.find_cycle_components(graph, list(graph))

    report = module.build_report(
        graph=graph,
        modules=list(graph),
        import_records=[],
        bidirectional_pairs=[("alpha", "beta_gate")],
        cycle_components=cycle_components,
        allowed_pairs={("alpha", "beta_gate")},
        allowed_components={("alpha", "beta_gate")},
        allowlist_path=REPO_ROOT / "governance" / "module_cycle_allowlist.json",
        allowlist_payload={"version": "test"},
    )

    assert report["unexpected_pairs"] == []
    assert report["unexpected_cycle_components"] == []
    assert report["allowed_cycle_components_found"] == [["alpha", "beta_gate"]]


def test_check_module_cycles_reports_dependency_budget_regressions():
    module = _load_script_module(
        "check_module_cycles.py",
        "test_check_module_cycles_dependency_budget",
    )
    graph = {
        "dashboard": {"account", "alpha", "data_center"},
        "account": {"data_center"},
        "alpha": set(),
        "data_center": set(),
    }

    report = module.build_report(
        graph=graph,
        modules=list(graph),
        import_records=[],
        bidirectional_pairs=[],
        cycle_components=[],
        allowed_pairs=set(),
        allowed_components=set(),
        allowlist_path=REPO_ROOT / "governance" / "module_cycle_allowlist.json",
        allowlist_payload={
            "version": "test",
            "max_app_import_edges": 3,
            "max_outbound_modules_per_app": 2,
            "max_inbound_modules_per_app": 1,
            "max_outbound_modules_by_app": {
                "dashboard": 2,
                "account": 1,
                "alpha": 0,
            },
            "max_inbound_modules_by_app": {
                "dashboard": 0,
                "account": 1,
                "data_center": 1,
            },
        },
    )

    assert report["edge_count"] == 4
    assert report["edge_budget_exceeded"] is True
    assert report["outbound_budget_exceeded"] == [
        {
            "module": "dashboard",
            "outbound_count": 3,
            "targets": ["account", "alpha", "data_center"],
        }
    ]
    assert report["outbound_app_budget_exceeded"] == [
        {
            "module": "dashboard",
            "outbound_count": 3,
            "budget": 2,
            "targets": ["account", "alpha", "data_center"],
        }
    ]
    assert report["outbound_app_budget_missing"] == [
        {
            "module": "data_center",
            "outbound_count": 0,
            "targets": [],
        }
    ]
    assert report["inbound_budget_exceeded"] == [
        {
            "module": "data_center",
            "inbound_count": 2,
            "sources": ["account", "dashboard"],
        }
    ]
    assert report["inbound_app_budget_exceeded"] == [
        {
            "module": "data_center",
            "inbound_count": 2,
            "budget": 1,
            "sources": ["account", "dashboard"],
        }
    ]
    assert report["inbound_app_budget_missing"] == [
        {
            "module": "alpha",
            "inbound_count": 1,
            "sources": ["dashboard"],
        }
    ]


def test_check_module_cycles_reports_stale_dependency_budgets_and_allowlists():
    module = _load_script_module(
        "check_module_cycles.py",
        "test_check_module_cycles_stale_budget",
    )
    graph = {
        "dashboard": {"account", "alpha"},
        "account": set(),
        "alpha": set(),
        "resolved": set(),
    }

    report = module.build_report(
        graph=graph,
        modules=list(graph),
        import_records=[],
        bidirectional_pairs=[],
        cycle_components=[],
        allowed_pairs={("account", "resolved")},
        allowed_components={("account", "alpha", "resolved")},
        allowlist_path=REPO_ROOT / "governance" / "module_cycle_allowlist.json",
        allowlist_payload={
            "version": "test",
            "max_app_import_edges": 3,
            "max_outbound_modules_per_app": 3,
            "max_inbound_modules_per_app": 2,
            "max_outbound_modules_by_app": {
                "dashboard": 3,
                "account": 0,
                "alpha": 0,
                "removed": 2,
                "resolved": 0,
            },
            "max_inbound_modules_by_app": {
                "dashboard": 0,
                "account": 2,
                "alpha": 1,
                "removed": 1,
                "resolved": 0,
            },
        },
    )

    assert report["edge_count"] == 2
    assert report["edge_budget_stale"] is True
    assert report["observed_max_outbound_modules"] == 2
    assert report["outbound_budget_stale"] is True
    assert report["outbound_app_budget_stale"] == [
        {
            "module": "dashboard",
            "outbound_count": 2,
            "budget": 3,
            "targets": ["account", "alpha"],
        },
        {
            "module": "removed",
            "outbound_count": 0,
            "budget": 2,
            "targets": [],
        },
    ]
    assert report["observed_max_inbound_modules"] == 1
    assert report["inbound_budget_stale"] is True
    assert report["inbound_app_budget_stale"] == [
        {
            "module": "account",
            "inbound_count": 1,
            "budget": 2,
            "sources": ["dashboard"],
        },
        {
            "module": "removed",
            "inbound_count": 0,
            "budget": 1,
            "sources": [],
        },
    ]
    assert report["stale_allowlist_pairs"] == [["account", "resolved"]]
    assert report["stale_allowed_cycle_components"] == [["account", "alpha", "resolved"]]


def test_scaffold_application_providers_renders_grouped_imports():
    module = _load_script_module(
        "scaffold_application_providers.py",
        "test_scaffold_application_providers",
    )
    specs = [
        module.ProviderSpec(
            function_name="get_prompt_repository",
            module_path="apps.prompt.infrastructure.repositories",
            symbol_name="DjangoPromptRepository",
        ),
        module.ProviderSpec(
            function_name="get_execution_log_repository",
            module_path="apps.prompt.infrastructure.repositories",
            symbol_name="DjangoExecutionLogRepository",
        ),
        module.ProviderSpec(
            function_name="get_ai_client_factory",
            module_path="apps.ai_provider.infrastructure.client_factory",
            symbol_name="AIClientFactory",
        ),
    ]

    content = module.render_provider_module("prompt", specs)

    assert '"""Provider helpers for prompt application consumers."""' in content
    assert "from apps.ai_provider.infrastructure.client_factory import AIClientFactory" in content
    assert "from apps.prompt.infrastructure.repositories import (" in content
    assert "DjangoExecutionLogRepository" in content
    assert "DjangoPromptRepository" in content
    assert "def get_prompt_repository() -> DjangoPromptRepository:" in content
    assert "return DjangoPromptRepository()" in content
