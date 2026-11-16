"""
select_tests.py 单元测试
"""

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

# 获取项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
select_tests_path = PROJECT_ROOT / "scripts" / "select_tests.py"

spec = importlib.util.spec_from_file_location("select_tests", select_tests_path)
select_tests = importlib.util.module_from_spec(spec)
sys.modules["select_tests"] = select_tests
spec.loader.exec_module(select_tests)

CORE_GUARDRAIL_TESTS = select_tests.CORE_GUARDRAIL_TESTS
FULL_TEST_SUITES = select_tests.FULL_TEST_SUITES
get_changed_modules = select_tests.get_changed_modules
MODULE_TEST_MAP = select_tests.MODULE_TEST_MAP
select_tests_func = select_tests.select_tests


class TestSelectTests(unittest.TestCase):
    """测试智能测试选择逻辑"""

    def test_gov05_script_only_changes_select_their_direct_contracts(self) -> None:
        contracts = {
            "scripts/vps-restore.sh": "tests/unit/test_vps_restore_script.py",
            "scripts/record_data02_reconciliation_evidence.py": (
                "tests/unit/data_center/test_data02_reconciliation_evidence.py"
            ),
            "scripts/check_web_to_tui_cutover_readiness.py": (
                "tests/unit/test_web_to_tui_cutover_readiness.py"
            ),
            "scripts/check_decision_write_surface_freeze.py": (
                "tests/unit/test_decision_write_surface_freeze.py"
            ),
        }
        for source, test in contracts.items():
            for changed in ([source], [source.replace("/", "\\"), "shared/numeric.py"]):
                with self.subTest(changed=changed):
                    targets = select_tests_func(
                        get_changed_modules(changed), changed, "logic_guardrails"
                    )
                    self.assertIn(test, targets)

    def test_sdk_only_change_selects_sdk_and_mcp_contracts_for_pull_requests(self):
        changed = ["sdk/agomtradepro/modules/signal.py"]
        targets = select_tests_func(get_changed_modules(changed), changed, "logic_guardrails")
        self.assertIn("sdk/tests/test_sdk/", targets)
        self.assertIn("sdk/tests/test_mcp/", targets)

    def test_shared_change_does_not_hide_changed_mcp_contracts(self):
        changed = ["shared/numeric.py", "sdk/agomtradepro_mcp/registry/dispatcher.py"]
        targets = select_tests_func(get_changed_modules(changed), changed, "logic_guardrails")
        self.assertIn("sdk/tests/test_sdk/", targets)
        self.assertIn("sdk/tests/test_mcp/", targets)

    def test_core_guardrail_tests_defined(self):
        """核心 guardrail 测试必须定义"""
        self.assertIsInstance(CORE_GUARDRAIL_TESTS, list)
        self.assertGreater(len(CORE_GUARDRAIL_TESTS), 0)
        for test in CORE_GUARDRAIL_TESTS:
            self.assertTrue(
                test.startswith("tests/"), f"Test path should start with tests/: {test}"
            )

    def test_module_test_map_has_key_modules(self):
        """关键模块必须在映射表中"""
        key_modules = [
            "regime",
            "policy",
            "signal",
            "audit",
            "backtest",
            "alpha",
            "account",
            "simulated_trading",
            "strategy",
            "share",
            "data_center",
            "agent_runtime",
            "asset_analysis",
            "ai_capability",
            "ai_provider",
            "beta_gate",
            "setup_wizard",
            "task_monitor",
            "terminal",
            "hedge",
            "realtime",
            "filter",
            "prompt",
            "sentiment",
            "sector",
            "fund",
            "events",
            "factor",
            "rotation",
            "macro",
            "equity",
            "alpha_trigger",
            "broker_execution",
            "operational_readiness",
            "risk_center",
            "portfolio",
            "research",
            "valuation",
            "config_center",
        ]
        for module in key_modules:
            self.assertIn(module, MODULE_TEST_MAP, f"Module {module} should be in test map")

    def test_get_changed_modules_from_apps(self):
        """从 apps/ 目录提取模块"""
        changed_files = [
            "apps/regime/domain/entities.py",
            "apps/policy/application/use_cases.py",
            "README.md",
        ]
        modules = get_changed_modules(changed_files)
        self.assertIn("regime", modules)
        self.assertIn("policy", modules)

    def test_get_changed_modules_from_core(self):
        """core/ 目录变更识别为 core 模块"""
        changed_files = ["core/settings/base.py", "core/urls.py"]
        modules = get_changed_modules(changed_files)
        self.assertIn("core", modules)

    def test_logic_profile_keeps_runtime_gate_contracts_for_core_changes(self):
        """Runtime-gate production changes must keep their public error contracts in CI."""

        required = {
            "tests/component/test_health_checks.py",
            "tests/unit/core/test_decision_runtime_gate_middleware.py",
            "tests/unit/core/test_decision_runtime_public.py",
        }
        for source in (
            "core/decision_runtime_public.py",
            "core/middleware/decision_gate.py",
            "core/health_checks.py",
        ):
            for extra in ((), (".github/workflows/ci-fast-feedback.yml",), ("shared/numeric.py",)):
                changed = [source, *extra]
                targets = set(
                    select_tests_func(
                        get_changed_modules(changed),
                        changed,
                        profile="logic_guardrails",
                    )
                )
                self.assertTrue(required <= targets, f"missing runtime contracts for {changed}")

    def test_get_changed_modules_from_shared(self):
        """shared/ 目录变更识别为 shared 模块"""
        changed_files = ["shared/domain/interfaces.py", "shared/infrastructure/filters.py"]
        modules = get_changed_modules(changed_files)
        self.assertIn("shared", modules)

    def test_deployment_entrypoints_select_deployment_contracts(self):
        """Deployment entrypoint changes must exercise wrapper and verifier contracts."""
        required = {
            "tests/unit/test_collect_release_regression_evidence.py",
            "tests/unit/test_deploy_vps_verify.py",
            "tests/unit/test_docker_pyqlib_install.py",
            "tests/unit/test_remote_build_deploy_vps.py",
            "tests/unit/test_run_release_rehearsal.py",
            "tests/unit/test_manage_vps_migrations.py",
            "tests/unit/test_rehearsal_stage_environment.py",
            "tests/unit/test_plan_release_rehearsal_attempt.py",
            "tests/unit/test_export_s6_rehearsal_inputs.py",
            "tests/unit/test_prepare_release_rehearsal_attempt.py",
            "tests/unit/test_build_release_rehearsal_manifest.py",
            "tests/unit/test_validate_release_rehearsal.py",
            "tests/unit/test_vps_web_watchdog.py",
        }
        for changed_file in (
            "scripts/deploy-vps.ps1",
            "scripts/collect_release_regression_evidence.py",
            "scripts/deploy_vps_verify.py",
            "scripts/deploy-on-vps.sh",
            "scripts/remote_build_deploy_vps.py",
            "scripts/run_release_rehearsal.py",
            "scripts/manage_vps_migrations.py",
            "scripts/plan_release_rehearsal_attempt.py",
            "scripts/postgres_s6_exporter_role_bootstrap.sql",
            "scripts/export_s6_rehearsal_inputs.py",
            "scripts/prepare_release_rehearsal_attempt.sh",
            "scripts/rehearsal_checkpoint.py",
            "shared/release_rehearsal_stage_environment.py",
            "scripts/build_release_rehearsal_manifest.py",
            "scripts/validate_release_rehearsal.py",
            "scripts/verify-vps-bundle.ps1",
        ):
            with self.subTest(changed_file=changed_file):
                changed = [changed_file]
                modules = get_changed_modules(changed)
                self.assertIn("deployment", modules)
                selected = set(select_tests_func(modules, changed, "logic_guardrails"))
                self.assertTrue(required <= selected)

    def test_unrelated_script_does_not_select_fresh_prepare_wrapper_contract(self):
        changed = ["scripts/unrelated_local_maintenance.sh"]
        modules = get_changed_modules(changed)
        selected = set(select_tests_func(modules, changed, "logic_guardrails"))
        self.assertNotIn("deployment", modules)
        self.assertNotIn("tests/unit/test_prepare_release_rehearsal_attempt.py", selected)

    def test_select_tests_with_no_changes(self):
        """无变更时返回全量测试（保守策略）"""
        tests = select_tests_func(set(), [])
        # 空模块集合时，保守地运行全量测试
        self.assertEqual(tests, FULL_TEST_SUITES)

    def test_select_tests_with_shared_changes(self):
        """shared/ 变更时运行全量测试"""
        tests = select_tests_func({"shared"}, ["shared/domain/interfaces.py"])
        self.assertEqual(tests, FULL_TEST_SUITES)

    def test_data_center_transport_change_selects_legacy_tushare_client_contracts(self):
        """Tushare transport tests remain selected after their source moved to Data Center."""

        changed = ["apps/data_center/infrastructure/tushare_client.py"]
        tests = select_tests_func(get_changed_modules(changed), changed, "logic_guardrails")

        self.assertIn("tests/unit/shared/infrastructure/test_tushare_client.py", tests)

    def test_select_tests_with_regime_changes(self):
        """regime 模块变更选择对应测试"""
        tests = select_tests_func({"regime"}, ["apps/regime/domain/services.py"])
        # 应包含核心测试
        for core_test in CORE_GUARDRAIL_TESTS:
            self.assertIn(core_test, tests)
        # 应包含 regime 相关测试
        regime_tests = [t for t in tests if "regime" in t.lower()]
        self.assertGreater(len(regime_tests), 0)
        self.assertIn("tests/api/test_regime_api_edges.py", tests)

    def test_select_tests_with_policy_changes(self):
        """policy 模块变更选择对应测试"""
        tests = select_tests_func({"policy"}, ["apps/policy/application/use_cases.py"])
        # 应包含核心测试
        for core_test in CORE_GUARDRAIL_TESTS:
            self.assertIn(core_test, tests)
        # 应包含 policy 相关测试
        policy_tests = [t for t in tests if "policy" in t.lower()]
        self.assertGreater(len(policy_tests), 0)
        self.assertIn("tests/api/test_policy_workbench_api_edges.py", tests)

    def test_select_tests_with_multiple_modules(self):
        """多模块变更时选择所有相关测试"""
        tests = select_tests_func(
            {"regime", "policy"}, ["apps/regime/services.py", "apps/policy/use_cases.py"]
        )
        # 应包含核心测试
        for core_test in CORE_GUARDRAIL_TESTS:
            self.assertIn(core_test, tests)
        # 应包含两个模块的测试
        regime_tests = [t for t in tests if "regime" in t.lower()]
        policy_tests = [t for t in tests if "policy" in t.lower()]
        self.assertGreater(len(regime_tests), 0)
        self.assertGreater(len(policy_tests), 0)

    def test_select_tests_with_backtest_changes_include_api_tests(self):
        """backtest 变更必须带上 API 测试。"""
        tests = select_tests_func({"backtest"}, ["apps/backtest/interface/views.py"])
        self.assertIn("tests/api/test_backtest_api_edges.py", tests)

    def test_select_tests_with_share_changes_include_app_local_tests(self):
        """share 模块变更必须带上 app-local tests。"""
        tests = select_tests_func({"share"}, ["apps/share/interface/views.py"])
        self.assertIn("apps/share/tests/", tests)

    def test_select_tests_with_audit_changes_include_api_tests(self):
        """audit 变更必须带上 API 测试。"""
        tests = select_tests_func({"audit"}, ["apps/audit/interface/views.py"])
        self.assertIn("tests/api/test_audit_api_edges.py", tests)

    def test_select_tests_with_data_center_changes_include_api_and_unit_tests(self):
        """data_center 变更必须带上 API、集成、单元和 Component 测试。"""
        tests = select_tests_func({"data_center"}, ["apps/data_center/interface/api_views.py"])
        self.assertIn("tests/api/test_data_center_route_cleanup.py", tests)
        self.assertIn("tests/integration/data_center/", tests)
        self.assertIn("tests/unit/data_center/", tests)
        self.assertIn("tests/component/data_center/", tests)

    def test_data_center_production_file_changes_select_realtime_consumer_component(self):
        """Provider-only changes must exercise the realtime Data Center consumer."""
        production_files = [
            "apps/data_center/application/public.py",
            "apps/data_center/infrastructure/_provider_adapter_akshare.py",
            "apps/data_center/application/tasks.py",
        ]
        for changed_file in production_files:
            with self.subTest(changed_file=changed_file):
                changed_files = [changed_file]
                tests = select_tests_func(
                    get_changed_modules(changed_files),
                    changed_files,
                    profile="logic_guardrails",
                )
                self.assertIn("tests/component/test_realtime_data_center_provider.py", tests)

    def test_logic_profile_keeps_data_center_tests_in_mixed_ci_diff(self):
        """CI workflow edits must not discard tests selected by an app change."""
        changed = [
            "apps/data_center/infrastructure/repositories.py",
            ".github/workflows/ci-fast-feedback.yml",
        ]

        tests = select_tests_func(get_changed_modules(changed), changed, profile="logic_guardrails")

        self.assertIn("tests/component/data_center/test_repositories.py", tests)
        self.assertNotIn("tests/component/data_center/", tests)

    def test_logic_profile_keeps_data_center_tests_in_mixed_shared_diff(self):
        """Shared edits must not discard tests selected by an app change."""
        changed = [
            "apps/data_center/infrastructure/repositories.py",
            "shared/numeric.py",
        ]

        tests = select_tests_func(get_changed_modules(changed), changed, profile="logic_guardrails")

        self.assertIn("tests/component/data_center/test_repositories.py", tests)
        self.assertNotIn("tests/component/data_center/", tests)

    def test_logic_profile_selects_changed_component_test_itself(self):
        """A test-only diff must execute the changed test instead of only guardrails."""
        changed_test = "tests/component/data_center/test_repositories.py"

        tests = select_tests_func(set(), [changed_test], profile="logic_guardrails")

        self.assertIn(changed_test, tests)

    def test_logic_profile_keeps_changed_component_test_with_ci_change(self):
        """A CI edit must not discard a directly changed component test."""
        changed_test = "tests/component/data_center/test_repositories.py"
        changed = [changed_test, ".github/workflows/ci-fast-feedback.yml"]

        tests = select_tests_func(get_changed_modules(changed), changed, profile="logic_guardrails")

        self.assertIn(changed_test, tests)

    def test_logic_profile_keeps_changed_component_test_with_shared_change(self):
        """A shared edit must not discard a directly changed component test."""
        changed_test = "tests/component/data_center/test_repositories.py"
        changed = [changed_test, "shared/numeric.py"]

        tests = select_tests_func(get_changed_modules(changed), changed, profile="logic_guardrails")

        self.assertIn(changed_test, tests)

    def test_default_profile_keeps_full_suite_for_mixed_ci_diff(self):
        """Default CI selection remains conservative for any workflow change."""
        changed = [
            "apps/data_center/infrastructure/repositories.py",
            ".github/workflows/ci-fast-feedback.yml",
        ]

        tests = select_tests_func(get_changed_modules(changed), changed)

        self.assertEqual(tests, FULL_TEST_SUITES)

    def test_default_profile_keeps_full_suite_for_mixed_shared_diff(self):
        """Default selection remains conservative for any shared change."""
        changed = [
            "apps/data_center/infrastructure/repositories.py",
            "shared/numeric.py",
        ]

        tests = select_tests_func(get_changed_modules(changed), changed)

        self.assertEqual(tests, FULL_TEST_SUITES)

    def test_select_tests_with_dashboard_changes_include_api_tests(self):
        """dashboard 变更必须带上 API 测试。"""
        tests = select_tests_func({"dashboard"}, ["apps/dashboard/interface/views.py"])
        self.assertIn("tests/api/test_dashboard_api_edges.py", tests)

    def test_logic_guardrails_profile_excludes_dashboard_e2e_targets(self):
        """Logic Guardrails profile 不应选择 dashboard 的 e2e 测试。"""
        tests = select_tests_func(
            {"dashboard"},
            ["apps/dashboard/interface/views.py"],
            profile="logic_guardrails",
        )
        self.assertIn("tests/api/test_dashboard_api_edges.py", tests)
        self.assertIn("apps/dashboard/tests/", tests)
        self.assertNotIn("tests/e2e/", tests)

    def test_select_tests_with_simulated_trading_changes_include_api_tests(self):
        """simulated_trading 变更必须带上 API 测试。"""
        tests = select_tests_func(
            {"simulated_trading"}, ["apps/simulated_trading/interface/views.py"]
        )
        self.assertIn("tests/api/test_simulated_trading_api_edges.py", tests)

    def test_select_tests_with_agent_runtime_changes_include_api_and_migration_tests(self):
        """agent_runtime 变更必须带上 API 和 migration 测试。"""
        tests = select_tests_func(
            {"agent_runtime"},
            ["apps/agent_runtime/interface/views.py"],
        )
        self.assertIn("tests/api/test_agent_runtime_api.py", tests)
        self.assertIn("tests/migrations/test_agent_runtime_migrations.py", tests)

    def test_select_tests_with_macro_changes_include_api_tests(self):
        """macro 变更必须带上 API 测试。"""
        tests = select_tests_func({"macro"}, ["apps/macro/interface/views/fetch_api.py"])
        self.assertIn("tests/api/test_data_center_route_cleanup.py", tests)

    def test_select_tests_with_account_changes_include_api_tests(self):
        """account 变更必须带上 API 测试。"""
        tests = select_tests_func({"account"}, ["apps/account/interface/profile_api_views.py"])
        self.assertIn("tests/api/test_account_api_edges.py", tests)

    def test_select_tests_with_ai_provider_changes_include_api_tests(self):
        """ai_provider 变更必须带上 API 测试。"""
        tests = select_tests_func(
            {"ai_provider"}, ["apps/ai_provider/interface/views/api_views.py"]
        )
        self.assertIn("tests/api/test_ai_provider_api_edges.py", tests)

    def test_select_tests_with_beta_gate_changes_include_api_tests(self):
        """beta_gate 变更必须带上 API 测试。"""
        tests = select_tests_func({"beta_gate"}, ["apps/beta_gate/interface/views.py"])
        self.assertIn("tests/api/test_beta_gate_api_edges.py", tests)

    def test_select_tests_with_decision_rhythm_changes_include_api_tests(self):
        """decision_rhythm 变更必须带上 API 测试。"""
        tests = select_tests_func(
            {"decision_rhythm"}, ["apps/decision_rhythm/interface/command_api_views.py"]
        )
        self.assertIn("tests/api/test_decision_rhythm_api_edges.py", tests)
        self.assertIn("tests/api/test_workspace_execution_api_edges.py", tests)
        self.assertIn("tests/api/test_workspace_recommendations_api_edges.py", tests)

    def test_select_tests_with_alpha_changes_include_api_tests(self):
        """alpha 变更必须带上 API 测试。"""
        tests = select_tests_func({"alpha"}, ["apps/alpha/interface/views.py"])
        self.assertIn("tests/api/test_alpha_api_edges.py", tests)

    def test_logic_guardrails_profile_excludes_alpha_heavy_targets(self):
        """Logic Guardrails profile 不应选择 alpha 集成和 e2e 压测。"""
        tests = select_tests_func(
            {"alpha"},
            ["apps/alpha/interface/views.py"],
            profile="logic_guardrails",
        )
        self.assertIn("tests/api/test_alpha_api_edges.py", tests)
        self.assertIn("tests/component/test_alpha_providers.py", tests)
        self.assertNotIn("tests/e2e/test_alpha_dashboard_e2e.py", tests)
        self.assertNotIn("tests/integration/test_alpha_stress.py", tests)

    def test_logic_guardrails_profile_uses_core_guardrails_for_shared_changes(self):
        """Logic Guardrails profile 在 shared 变更时退回核心 guardrails。"""
        tests = select_tests_func(
            {"shared"},
            ["shared/domain/interfaces.py"],
            profile="logic_guardrails",
        )
        self.assertEqual(tests, CORE_GUARDRAIL_TESTS)

    def test_select_tests_with_alpha_trigger_changes_include_api_tests(self):
        """alpha_trigger 变更必须带上 API 测试。"""
        tests = select_tests_func({"alpha_trigger"}, ["apps/alpha_trigger/interface/views.py"])
        self.assertIn("tests/api/test_alpha_trigger_api_edges.py", tests)

    def test_select_tests_with_task_monitor_changes_include_api_tests(self):
        """task_monitor 变更必须带上 API 测试。"""
        tests = select_tests_func({"task_monitor"}, ["apps/task_monitor/interface/views.py"])
        self.assertIn("tests/api/test_task_monitor_api.py", tests)

    def test_select_tests_with_hedge_changes_include_api_tests(self):
        """hedge 变更必须带上 API 测试。"""
        tests = select_tests_func({"hedge"}, ["apps/hedge/interface/views.py"])
        self.assertIn("tests/api/test_hedge_api.py", tests)

    def test_select_tests_with_terminal_changes_include_api_tests(self):
        """terminal 变更必须带上 API 测试。"""
        tests = select_tests_func({"terminal"}, ["apps/terminal/interface/api_views.py"])
        self.assertIn("tests/api/test_terminal_api_edges.py", tests)

    def test_select_tests_with_realtime_changes_include_api_tests(self):
        """realtime 变更必须覆盖 API 与 Data Center provider guard。"""
        tests = select_tests_func({"realtime"}, ["apps/realtime/interface/views.py"])
        self.assertIn("tests/api/test_realtime_api.py", tests)
        self.assertIn("tests/component/test_realtime_data_center_provider.py", tests)

    def test_select_tests_with_filter_changes_include_api_tests(self):
        """filter 变更必须带上 API 测试。"""
        tests = select_tests_func({"filter"}, ["apps/filter/interface/api_views.py"])
        self.assertIn("tests/api/test_filter_api_edges.py", tests)

    def test_select_tests_with_prompt_changes_include_api_tests(self):
        """prompt 变更必须带上 API 测试。"""
        tests = select_tests_func({"prompt"}, ["apps/prompt/interface/views.py"])
        self.assertIn("tests/api/test_prompt_api_edges.py", tests)

    def test_select_tests_with_ai_capability_changes_include_api_tests(self):
        """ai_capability 变更必须带上 API 测试。"""
        tests = select_tests_func({"ai_capability"}, ["apps/ai_capability/interface/api_views.py"])
        self.assertIn("tests/api/test_ai_capability_api_edges.py", tests)

    def test_select_tests_with_sentiment_changes_include_api_tests(self):
        """sentiment 变更必须带上 API 测试。"""
        tests = select_tests_func({"sentiment"}, ["apps/sentiment/interface/views.py"])
        self.assertIn("tests/api/test_sentiment_api_edges.py", tests)

    def test_select_tests_with_policy_changes_include_api_tests(self):
        """policy 变更必须带上 API 测试。"""
        tests = select_tests_func({"policy"}, ["apps/policy/interface/workbench_api_views.py"])
        self.assertIn("tests/api/test_policy_api_edges.py", tests)
        self.assertIn("tests/api/test_policy_workbench_api_edges.py", tests)

    def test_select_tests_with_events_changes_include_api_tests(self):
        """events 变更必须带上 API 测试。"""
        tests = select_tests_func({"events"}, ["apps/events/interface/views.py"])
        self.assertIn("tests/api/test_events_api_edges.py", tests)

    def test_select_tests_with_factor_changes_include_api_tests(self):
        """factor 变更必须带上 API 测试。"""
        tests = select_tests_func({"factor"}, ["apps/factor/interface/views.py"])
        self.assertIn("tests/api/test_factor_api_edges.py", tests)

    def test_select_tests_with_strategy_changes_include_api_tests(self):
        """strategy 变更必须带上 API 测试。"""
        tests = select_tests_func({"strategy"}, ["apps/strategy/interface/views.py"])
        self.assertIn("tests/api/test_strategy_api_edges.py", tests)

    def test_select_tests_with_sector_changes_include_api_tests(self):
        """sector 变更必须带上 API 测试。"""
        tests = select_tests_func({"sector"}, ["apps/sector/interface/views.py"])
        self.assertIn("tests/api/test_sector_api_edges.py", tests)

    def test_select_tests_with_fund_changes_include_api_tests(self):
        """fund 变更必须带上 API 测试。"""
        tests = select_tests_func({"fund"}, ["apps/fund/interface/views.py"])
        self.assertIn("tests/api/test_fund_api_edges.py", tests)

    def test_select_tests_with_equity_changes_include_api_tests(self):
        """equity 变更必须带上 API 测试。"""
        tests = select_tests_func({"equity"}, ["apps/equity/interface/views.py"])
        self.assertIn("tests/api/test_equity_api_edges.py", tests)

    def test_select_tests_with_signal_changes_include_api_tests(self):
        """signal 变更必须带上 API 测试。"""
        tests = select_tests_func({"signal"}, ["apps/signal/interface/api_views.py"])
        self.assertIn("tests/api/test_signal_api_edges.py", tests)

    def test_select_tests_with_rotation_changes_include_api_tests(self):
        """rotation 变更必须带上 API 测试。"""
        tests = select_tests_func({"rotation"}, ["apps/rotation/interface/views.py"])
        self.assertIn("tests/api/test_rotation_api_edges.py", tests)

    def test_full_test_suites_include_app_local_tests(self):
        """全量回退策略必须覆盖 app-local tests。"""
        self.assertIn("tests/api/", FULL_TEST_SUITES)
        self.assertIn("tests/migrations/", FULL_TEST_SUITES)
        self.assertIn("tests/component/", FULL_TEST_SUITES)
        self.assertIn("tests/unit/", FULL_TEST_SUITES)
        self.assertIn("tests/critical/", FULL_TEST_SUITES)
        self.assertIn("apps/dashboard/tests/", FULL_TEST_SUITES)
        self.assertIn("apps/share/tests/", FULL_TEST_SUITES)

    @patch.dict(os.environ, {"GITHUB_ACTIONS": "true"})
    def test_module_map_coverage(self):
        """所有生产 App 必须有测试映射，禁止静默漏测。"""
        apps_path = PROJECT_ROOT / "apps"
        production_apps = {
            item.name
            for item in apps_path.iterdir()
            if item.is_dir() and (item / "__init__.py").is_file()
        }
        self.assertEqual(production_apps - set(MODULE_TEST_MAP), set())

    def test_unmapped_changed_app_falls_back_to_full_suite(self):
        """未来新增但未映射的生产 App 必须保守回退全量。"""
        tests = select_tests_func(
            {"future_reliability_app"},
            ["apps/future_reliability_app/domain/entities.py"],
        )
        self.assertEqual(tests, FULL_TEST_SUITES)

    def test_unmapped_changed_app_logic_profile_keeps_full_fast_scope(self):
        """快速档遇到未知 App 时也不能只运行通用护栏。"""
        tests = select_tests_func(
            {"future_reliability_app"},
            ["apps/future_reliability_app/domain/entities.py"],
            profile="logic_guardrails",
        )
        self.assertIn("tests/critical/", tests)
        self.assertIn("tests/unit/", tests)
        self.assertIn("tests/api/", tests)

    def test_critical_reliability_suite_is_always_selected(self):
        """任意已映射模块变更都必须带上关键可靠性集合。"""
        tests = select_tests_func({"regime"}, ["apps/regime/domain/services.py"])
        self.assertIn("tests/critical/", tests)


class TestManagedBrowserSelectionBoundary(unittest.TestCase):
    """Keep managed browser suites out of the unmanaged fast pytest command."""

    browser_target = "tests/playwright/tests/uat/test_comprehensive_regression.py"
    unit_target = "tests/unit/ci/test_select_tests.py"

    def test_ci_and_shared_only_fast_changes_filter_browser_targets(self):
        for module in ("ci", "shared"):
            with self.subTest(module=module):
                targets = select_tests_func(
                    {module}, [self.browser_target], profile="logic_guardrails"
                )
                self.assertNotIn(self.browser_target, targets)
                self.assertTrue(set(CORE_GUARDRAIL_TESTS).issubset(targets))

    def test_ci_and_shared_fast_changes_keep_changed_unit_and_core_targets(self):
        for module in ("ci", "shared"):
            with self.subTest(module=module):
                targets = select_tests_func(
                    {module},
                    [self.browser_target, self.unit_target],
                    profile="logic_guardrails",
                )
                self.assertIn(self.unit_target, targets)
                self.assertNotIn(self.browser_target, targets)
                self.assertTrue(set(CORE_GUARDRAIL_TESTS).issubset(targets))

    def test_default_changed_browser_selection_remains_unchanged(self):
        targets = select_tests_func(set(), [self.browser_target])
        self.assertIn(self.browser_target, targets)
        for module in ("ci", "shared"):
            with self.subTest(module=module):
                self.assertEqual(
                    select_tests_func({module}, [self.browser_target]), FULL_TEST_SUITES
                )

    def test_required_rc_journeys_keep_managed_full_uat_execution(self):
        workflow = (PROJECT_ROOT / ".github/workflows/rc-gate.yml").read_text(encoding="utf-8")
        self.assertIn("python scripts/run_live_server_pytest.py", workflow)
        self.assertIn("tests/playwright/tests/uat/ -v", workflow)
        self.assertIn("--require-no-skips", workflow)
        self.assertIn("--min-tests 20", workflow)


class TestNativePostgresCalendarSelection(unittest.TestCase):
    """Keep the calendar browser journey on its isolated PostgreSQL runner."""

    browser_target = "tests/component/data_center/test_institutional_calendar_browser.py"
    history_target = (
        "tests/component/data_center/test_formal_exchange_calendar_publication_history_pg.py"
    )
    catalog_admin_target = "tests/component/data_center/test_calendar_catalog_admin_pg.py"
    generic_catalog_target = "tests/component/data_center/test_generic_calendar_catalog_pg.py"
    native_targets = (browser_target, history_target, catalog_admin_target, generic_catalog_target)

    @staticmethod
    def _data_center_component_test_files() -> set[str]:
        component_root = PROJECT_ROOT / "tests/component/data_center"
        return {
            path.relative_to(PROJECT_ROOT).as_posix()
            for path in component_root.rglob("*.py")
            if path.is_file() and (path.name.startswith("test_") or path.name.endswith("_test.py"))
        }

    def test_data_center_fast_feedback_keeps_every_other_component_test(self):
        targets = set(
            select_tests_func(
                {"data_center"},
                ["apps/data_center/domain/entities.py"],
                profile="logic_guardrails",
            )
        )
        selected_component_tests = {
            target for target in targets if target.startswith("tests/component/data_center/")
        }
        expected_component_tests = self._data_center_component_test_files() - set(
            self.native_targets
        )

        self.assertEqual(selected_component_tests, expected_component_tests)
        self.assertNotIn("tests/component/data_center/", targets)
        self.assertTrue(set(self.native_targets).isdisjoint(targets))

    def test_browser_test_only_change_routes_out_of_sqlite_selector(self):
        for target in self.native_targets:
            with self.subTest(target=target):
                targets = set(select_tests_func(set(), [target], profile="logic_guardrails"))

                self.assertTrue(set(self.native_targets).isdisjoint(targets))
                self.assertNotIn("tests/component/data_center/", targets)
                self.assertTrue(set(CORE_GUARDRAIL_TESTS).issubset(targets))

    def test_raw_scope_detector_and_postgres_job_cover_test_only_changes(self):
        workflow_path = PROJECT_ROOT / ".github/workflows/ci-fast-feedback.yml"
        workflow = yaml.load(workflow_path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

        reusable_input = workflow["on"]["workflow_call"]["inputs"]["full_validation"]
        self.assertEqual(reusable_input["default"], "true")
        detect_job = workflow["jobs"]["detect-tests"]
        self.assertEqual(
            detect_job["outputs"]["calendar-postgres-required"],
            "${{ steps.calendar-postgres.outputs.required }}",
        )
        detector = next(
            step
            for step in detect_job["steps"]
            if step.get("name") == "Detect native calendar PostgreSQL scope"
        )
        self.assertIn("git diff --name-only", detector["run"])
        self.assertIn("workflow_call", detector["run"])
        self.assertIn("workflow_dispatch", detector["run"])
        self.assertEqual(detector["env"]["FULL_VALIDATION"], "${{ inputs.full_validation }}")
        self.assertIn('"${FULL_VALIDATION}" == "true"', detector["run"])
        self.assertIn('-z "${BASE_REF}"', detector["run"])
        self.assertIn('-z "${HEAD_REF}"', detector["run"])
        self.assertIn("! changed_paths=", detector["run"])
        self.assertIn("tests/component/data_center/", detector["run"])
        self.assertIn("tests/support/", detector["run"])
        self.assertIn("scripts/select_tests.py", detector["run"])
        self.assertIn(".github/workflows/nightly-tests.yml", detector["run"])
        native_path_case = (
            detector["run"].split('case "${changed_path}" in', 1)[1].split("esac", 1)[0]
        )
        self.assertIn("tests/component/data_center/*", native_path_case)
        self.assertIn("required=true", native_path_case)

        job = workflow["jobs"]["institutional-calendar-postgres"]
        self.assertEqual(job["needs"], "detect-tests")
        self.assertEqual(
            job["if"],
            "needs.detect-tests.outputs.calendar-postgres-required == 'true'",
        )
        self.assertEqual(
            job["services"]["postgres"]["env"]["POSTGRES_DB"],
            "cal02_institutional_calendar_source_ci",
        )
        self.assertEqual(
            job["env"]["DJANGO_SETTINGS_MODULE"], "core.settings.critical_postgres_test"
        )
        self.assertEqual(
            job["env"]["AGOM_CRITICAL_TEST_DB_NAME"],
            "cal02_institutional_calendar_qa",
        )
        install_index = next(
            index
            for index, step in enumerate(job["steps"])
            if step.get("name") == "Install Python browser runtime"
        )
        browser_index = next(
            index
            for index, step in enumerate(job["steps"])
            if step.get("name") == "Run native calendar PostgreSQL safety and browser journeys"
        )
        self.assertLess(install_index, browser_index)
        browser_run = job["steps"][browser_index]["run"]
        for target in self.native_targets:
            self.assertIn(target, browser_run)
        self.assertIn("--create-db", browser_run)
        self.assertIn("--migrations", browser_run)
        self.assertNotIn("--no-migrations", browser_run)

    def test_nightly_sqlite_component_and_postgres_job_route_browser_as_a_pair(self):
        workflow_path = PROJECT_ROOT / ".github/workflows/nightly-tests.yml"
        workflow = yaml.load(workflow_path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

        nightly_steps = workflow["jobs"]["nightly"]["steps"]
        sqlite_component = next(
            step for step in nightly_steps if step.get("name") == "Run Component Tests"
        )
        for target in self.native_targets:
            self.assertIn(f"--ignore={target}", sqlite_component["run"])

        postgres_steps = workflow["jobs"]["critical-postgres"]["steps"]
        browser_install_index = next(
            index
            for index, step in enumerate(postgres_steps)
            if step.get("name") == "Install Python browser runtime for current-data contracts"
        )
        calendar_index = next(
            index
            for index, step in enumerate(postgres_steps)
            if step.get("name") == "Run native calendar PostgreSQL safety and browser journeys"
        )
        self.assertLess(browser_install_index, calendar_index)
        calendar_step = postgres_steps[calendar_index]
        self.assertEqual(
            calendar_step["env"]["DJANGO_SETTINGS_MODULE"],
            "core.settings.critical_postgres_test",
        )
        self.assertEqual(
            calendar_step["env"]["AGOM_CRITICAL_TEST_DB_NAME"],
            "cal02_institutional_calendar_qa",
        )
        for target in self.native_targets:
            self.assertIn(target, calendar_step["run"])
        self.assertIn("--create-db", calendar_step["run"])
        self.assertIn("--migrations", calendar_step["run"])
        self.assertNotIn("--no-migrations", calendar_step["run"])


if __name__ == "__main__":
    unittest.main()
